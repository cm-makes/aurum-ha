"""
Regression tests for the repair issue about configured entities that no
longer exist.

After an entity rename (HA 2026.11 "Recreate entity IDs" included), a
removed plug or a removed integration, a configured entity stopped
working silently: startup detection never fired without its
power sensor, a run condition failed open, a price or forecast sensor was
ignored. On the maintainer's HA the configured Tibber price sensors no
longer existed and nobody noticed.

- configured_entities: hub fields and each device's switch, power
  measurement and run condition sensor; empty fields skipped; the field
  lists and labels match the settings forms (EN/DE).
- MissingEntityCheck: two-pass (still missing 10 minutes later), an
  entity created late or a reload blip is not reported, self-clearing,
  a clock that goes back keeps the report.
- Coordinator: checks only once HA is running (or after an hour), one
  repair issue listing the missing entities with their role, updated and
  deleted as they come back, no second "unavailable" issue for a missing
  hub sensor, an unavailable entity is not missing, logged once.
- End to end: real update cycles raise the issue about 10 minutes after
  startup and clear it when the entity exists again.
"""

import asyncio
import json
import logging
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from custom_components.aurum.modules.entity_check import (
    DEVICE_FIELDS,
    FIELD_LABELS,
    HUB_FIELDS,
    MissingEntityCheck,
    configured_entities,
    format_missing,
)

TRANSLATIONS = (Path(__file__).resolve().parents[1]
                / "custom_components" / "aurum" / "translations")

GRID = "sensor.grid"
SOC = "sensor.soc"
PRICE = "sensor.tibber_price"
WASHER_SW = "switch.washer"
WASHER_PW = "sensor.washer_power"

T0 = datetime(2026, 11, 15, 12, 0)
MIN = timedelta(minutes=1)

CONFIG = {
    "grid_power_entity": GRID,
    "battery_soc_entity": SOC,
    "price_entity": PRICE,
    "devices": [{"name": "Washer", "switch_entity": WASHER_SW,
                 "power_entity": WASHER_PW}],
}

PRICE_LINE = "- Electricity price sensor: `sensor.tibber_price`"
WASHER_LINE = "- Washer – Power measurement: `sensor.washer_power`"


def _exists(present):
    return lambda entity_id: entity_id in present


def _entities(check):
    return [ref["entity"] for ref in check.missing]


# ══════════════════════════════════════════════════════════════════
#  Configured entities
# ══════════════════════════════════════════════════════════════════


class TestConfiguredEntities:
    def test_hub_and_device_fields_without_empty_ones(self):
        refs = configured_entities({
            "grid_power_entity": GRID,
            "pv_power_entity": "",
            "battery_soc_entity": None,
            "weather_entity": "weather.home",
            "price_entity": PRICE,
            "update_interval": 15,
            "devices": [
                {"name": "Washer", "switch_entity": WASHER_SW,
                 "power_entity": WASHER_PW, "condition_entity": None},
                {"name": "Boiler", "switch_entity": "switch.boiler",
                 "power_entity": "", "condition_entity": "sensor.boiler_t"},
            ],
        })
        assert [(r["entity"], r["device"], r["field"]) for r in refs] == [
            (GRID, None, "grid_power_entity"),
            ("weather.home", None, "weather_entity"),
            (PRICE, None, "price_entity"),
            (WASHER_SW, "Washer", "switch_entity"),
            (WASHER_PW, "Washer", "power_entity"),
            ("switch.boiler", "Boiler", "switch_entity"),
            ("sensor.boiler_t", "Boiler", "condition_entity"),
        ]

    @pytest.mark.parametrize("lang", ["en", "de"])
    def test_fields_and_labels_match_the_settings_forms(self, lang):
        # Every entity field of the forms is checked, and the issue names
        # it with the label the user sees in Configure.
        steps = json.loads((TRANSLATIONS / f"{lang}.json").read_text(
            encoding="utf-8"))["options"]["step"]
        forms = {"hub": steps["settings"]["data"],
                 "device": steps["edit_device"]["data"]}
        assert tuple(k for k in forms["hub"]
                     if k.endswith("_entity")) == HUB_FIELDS
        assert tuple(k for k in forms["device"]
                     if k.endswith("_entity")) == DEVICE_FIELDS
        for kind, fields in (("hub", HUB_FIELDS), ("device", DEVICE_FIELDS)):
            for field in fields:
                label = forms[kind][field].removesuffix(" (optional)")
                assert FIELD_LABELS[lang][field] == label

    def test_issue_lines_name_device_role_and_entity(self):
        refs = configured_entities(CONFIG)
        missing = [r for r in refs if r["entity"] in (PRICE, WASHER_PW)]
        assert format_missing(missing, "en") == (
            PRICE_LINE + "\n" + WASHER_LINE)
        assert format_missing(missing, "de") == (
            "- Strompreis-Sensor: `sensor.tibber_price`\n"
            "- Washer – Verbrauchsmessung: `sensor.washer_power`")
        # Regional variants and unknown languages.
        assert format_missing(missing, "de-CH").startswith(
            "- Strompreis-Sensor")
        assert format_missing(missing, "fr") == format_missing(missing, "en")


# ══════════════════════════════════════════════════════════════════
#  Two-pass check
# ══════════════════════════════════════════════════════════════════


class TestTwoPass:
    def test_reported_when_still_missing_10_minutes_later(self):
        check = MissingEntityCheck(CONFIG)
        exists = _exists({GRID, SOC, WASHER_SW, WASHER_PW})
        assert check.check(exists, T0) is False and check.missing == []
        assert check.check(exists, T0 + 5 * MIN) is False
        assert check.check(exists, T0 + 10 * MIN) is True
        assert _entities(check) == [PRICE]
        assert check.check(exists, T0 + 15 * MIN) is False   # unchanged

    def test_entity_created_late_by_its_integration_is_not_reported(self):
        # A cloud integration creates the plug's power sensor minutes
        # after Home Assistant has started.
        check = MissingEntityCheck(CONFIG)
        present = {GRID, SOC, PRICE, WASHER_SW}
        check.check(_exists(present), T0)
        present.add(WASHER_PW)
        for minutes in (5, 10, 15):
            check.check(_exists(present), T0 + minutes * MIN)
        assert check.missing == []

    def test_a_check_that_finds_the_entity_restarts_the_wait(self):
        # An integration reload removes its entities for a moment.
        check = MissingEntityCheck(CONFIG)
        gone = _exists({GRID, SOC, WASHER_SW, WASHER_PW})
        back = _exists({GRID, SOC, WASHER_SW, WASHER_PW, PRICE})
        check.check(gone, T0)
        check.check(back, T0 + 5 * MIN)
        check.check(gone, T0 + 10 * MIN)
        check.check(gone, T0 + 15 * MIN)
        assert check.missing == []
        check.check(gone, T0 + 20 * MIN)
        assert _entities(check) == [PRICE]

    def test_clears_when_the_entity_exists_again(self):
        check = MissingEntityCheck(CONFIG)
        exists = _exists({GRID, SOC, WASHER_SW})
        for minutes in (0, 5, 10):
            check.check(exists, T0 + minutes * MIN)
        assert _entities(check) == [PRICE, WASHER_PW]
        assert check.check(_exists({GRID, SOC, WASHER_SW, PRICE}),
                           T0 + 15 * MIN) is True
        assert _entities(check) == [WASHER_PW]
        assert check.check(
            _exists({GRID, SOC, WASHER_SW, PRICE, WASHER_PW}),
            T0 + 20 * MIN) is True
        assert check.missing == []

    def test_due_every_5_minutes(self):
        check = MissingEntityCheck(CONFIG)
        assert check.due(T0)
        check.check(_exists(set()), T0)
        assert not check.due(T0 + 4 * MIN)
        assert check.due(T0 + 5 * MIN)
        assert check.due(T0 - 60 * MIN)       # clock went back

    def test_clock_going_back_keeps_the_report(self):
        # Naive local time repeats an hour when DST ends.
        check = MissingEntityCheck(CONFIG)
        exists = _exists({GRID, SOC, WASHER_SW, WASHER_PW})
        for minutes in (0, 5, 10):
            check.check(exists, T0 + minutes * MIN)
        assert check.check(exists, T0 - 45 * MIN) is False
        assert _entities(check) == [PRICE]


# ══════════════════════════════════════════════════════════════════
#  Coordinator: timing, repair issue, dedupe, log
# ══════════════════════════════════════════════════════════════════


def _coordinator(hass, **config):
    from custom_components.aurum.coordinator import AurumCoordinator
    c = AurumCoordinator.__new__(AurumCoordinator)
    c.config = config
    c.bridge = hass
    c.hass = hass
    c.cycle = 30
    c._first_cycle_at = T0
    c._in_startup = False
    c._issues = {}
    c.entity_check = MissingEntityCheck(config)
    return c


def _tick(c, t, faults=()):
    shared = {"now": t, "input_faults": list(faults)}
    c._check_missing_entities(shared)
    c._update_repair_issues(shared)
    return shared


def _run(c, start, end, step=timedelta(seconds=15), faults=()):
    t = start
    while t <= end:
        _tick(c, t, faults)
        t += step


def _running():
    # HA's CoreState enum: the value is "RUNNING".
    return SimpleNamespace(value="RUNNING")


@pytest.fixture
def ir(monkeypatch):
    calls = []
    mod = types.ModuleType("homeassistant.helpers.issue_registry")
    mod.IssueSeverity = types.SimpleNamespace(WARNING="warning")
    mod.async_create_issue = (
        lambda hass, domain, issue_id, **kw:
        calls.append(("create", issue_id, kw)))
    mod.async_delete_issue = (
        lambda hass, domain, issue_id: calls.append(("delete", issue_id)))
    monkeypatch.setitem(
        sys.modules, "homeassistant.helpers.issue_registry", mod)
    monkeypatch.setattr(
        sys.modules["homeassistant.helpers"], "issue_registry", mod,
        raising=False)
    return calls


@pytest.fixture
def renamed(hass):
    """The Tibber price sensor and the washer's power sensor are gone;
    grid, SOC and the washer's plug exist."""
    hass.states.update({GRID: "100", SOC: "60", WASHER_SW: "off"})
    hass.state = _running()
    return hass


class TestCoordinatorTiming:
    def test_waits_until_home_assistant_is_running(self, hass, ir):
        hass.states.update({GRID: "100", SOC: "60", WASHER_SW: "off"})
        hass.state = SimpleNamespace(value="STARTING")
        c = _coordinator(hass, **CONFIG)
        _run(c, T0, T0 + 30 * MIN)
        assert c.entity_check.missing == [] and ir == []
        hass.state = _running()
        _run(c, T0 + 31 * MIN, T0 + 40 * MIN)
        assert ir == []                       # first pass only
        _run(c, T0 + 41 * MIN, T0 + 42 * MIN)
        assert [call[1] for call in ir] == ["missing_entities"]

    def test_checks_after_an_hour_if_never_running(self, hass, ir):
        hass.states.update({GRID: "100", SOC: "60", WASHER_SW: "off"})
        c = _coordinator(hass, **CONFIG)       # MockHass has no state
        _run(c, T0, T0 + 59 * MIN, step=MIN)
        assert ir == []
        _run(c, T0 + 60 * MIN, T0 + 70 * MIN, step=MIN)
        assert [call[1] for call in ir] == ["missing_entities"]

    def test_unavailable_entity_is_not_missing(self, renamed, ir):
        # An outage is handled where the entity is read; only an entity
        # Home Assistant does not have at all is reported.
        renamed.states.update({PRICE: "unavailable", WASHER_PW: "unknown"})
        c = _coordinator(renamed, **CONFIG)
        _run(c, T0, T0 + 30 * MIN)
        assert c.entity_check.missing == [] and ir == []


class TestCoordinatorIssue:
    def test_one_issue_listing_entities_with_their_role(self, renamed, ir):
        c = _coordinator(renamed, **CONFIG)
        _run(c, T0, T0 + 9 * MIN)
        assert ir == []
        _run(c, T0 + 9 * MIN + timedelta(seconds=15), T0 + 14 * MIN)
        assert len(ir) == 1                    # one issue, not re-created
        kind, issue_id, kw = ir[0]
        assert (kind, issue_id) == ("create", "missing_entities")
        assert kw["translation_key"] == "missing_entities"
        assert kw["is_fixable"] is False
        assert kw["translation_placeholders"] == {
            "entities": PRICE_LINE + "\n" + WASHER_LINE}

    def test_updated_then_cleared_when_entities_exist_again(
            self, renamed, ir):
        c = _coordinator(renamed, **CONFIG)
        _run(c, T0, T0 + 10 * MIN)
        renamed.states[PRICE] = "0.25"
        _run(c, T0 + 10 * MIN + timedelta(seconds=15), T0 + 15 * MIN)
        assert ir[-1][1] == "missing_entities"
        assert ir[-1][2]["translation_placeholders"] == {
            "entities": WASHER_LINE}
        renamed.states[WASHER_PW] = "0"
        _run(c, T0 + 15 * MIN + timedelta(seconds=15), T0 + 20 * MIN)
        assert ir[-1] == ("delete", "missing_entities")
        assert c._issues == {}

    def test_german_role_labels(self, renamed, ir):
        renamed.language = "de"
        c = _coordinator(renamed, **CONFIG)
        _run(c, T0, T0 + 10 * MIN)
        assert ir[0][2]["translation_placeholders"]["entities"] == (
            "- Strompreis-Sensor: `sensor.tibber_price`\n"
            "- Washer – Verbrauchsmessung: `sensor.washer_power`")

    def test_missing_grid_meter_gets_no_second_unavailable_issue(
            self, renamed, ir):
        # A missing grid meter is also an input fault. Reported once,
        # as "not found", not again as "unavailable".
        renamed.states.update({PRICE: "0.25", WASHER_PW: "0"})
        del renamed.states[GRID]
        fault = {"input": "grid", "status": "unavailable", "entity": GRID,
                 "since": T0 - 30 * MIN}
        c = _coordinator(renamed, **CONFIG)
        _run(c, T0, T0 + 20 * MIN, faults=[fault])
        assert list(c._issues) == ["missing_entities"]
        assert c._issues["missing_entities"][1] == {
            "entities": "- Grid meter: `sensor.grid`"}
        assert ("delete", "input_grid") in ir

    def test_unavailable_grid_meter_keeps_its_issue(self, renamed, ir):
        renamed.states.update({PRICE: "0.25", WASHER_PW: "0",
                               GRID: "unavailable"})
        fault = {"input": "grid", "status": "unavailable", "entity": GRID,
                 "since": T0 - 30 * MIN}
        c = _coordinator(renamed, **CONFIG)
        _run(c, T0, T0 + 20 * MIN, faults=[fault])
        assert list(c._issues) == ["input_grid"]

    def test_logged_once(self, renamed, ir, caplog):
        c = _coordinator(renamed, **CONFIG)
        with caplog.at_level(logging.WARNING):
            _run(c, T0, T0 + 40 * MIN)
        warnings = [r.getMessage() for r in caplog.records
                    if "not found" in r.getMessage()]
        assert len(warnings) == 1
        assert ("Electricity price sensor: sensor.tibber_price; "
                "Washer – Power measurement: sensor.washer_power"
                in warnings[0])

    def test_shutdown_deletes_the_issue(self, renamed, ir):
        c = _coordinator(renamed, **CONFIG)
        _run(c, T0, T0 + 10 * MIN)
        c._clear_repair_issues()
        assert ir[-1] == ("delete", "missing_entities")


# ══════════════════════════════════════════════════════════════════
#  End to end: real update cycles
# ══════════════════════════════════════════════════════════════════


class _Clock(datetime):
    current = T0

    @classmethod
    def now(cls, tz=None):
        return cls.current


def _real_coordinator(monkeypatch, hass, tmp_path, config):
    from custom_components.aurum import coordinator as coord_mod

    monkeypatch.setattr(
        coord_mod.DataUpdateCoordinator, "__init__",
        lambda self, hass, *a, **k: setattr(self, "hass", hass))
    monkeypatch.setattr(coord_mod, "HassAccess", lambda h: h)
    monkeypatch.setattr(coord_mod, "datetime", _Clock)

    async def _executor(func, *args):
        return func(*args)

    hass.async_add_executor_job = _executor
    hass.config = SimpleNamespace(path=lambda name: str(tmp_path / name))
    entry = SimpleNamespace(data=config, options={}, entry_id="test")
    coord = coord_mod.AurumCoordinator(hass, entry)
    asyncio.run(coord.async_setup())
    return coord


def _cycles(coord, start, end, step_s=15):
    async def _go():
        t = start
        while t <= end:
            _Clock.current = t
            await coord._async_update_data()
            t += timedelta(seconds=step_s)
    asyncio.run(_go())


class TestEndToEnd:
    def test_issue_after_startup_and_cleared_when_entity_returns(
            self, monkeypatch, hass, tmp_path, make_device, ir):
        config = {
            "grid_power_entity": GRID,
            "battery_soc_entity": SOC,
            "price_entity": PRICE,
            "update_interval": 15,
            "state_file": str(tmp_path / "aurum_state.json"),
            "devices": [make_device(name="Washer", switch_entity=WASHER_SW,
                                    power_entity=WASHER_PW)],
        }
        hass.states.update({GRID: "100", SOC: "60", WASHER_SW: "off"})
        hass.state = _running()
        coord = _real_coordinator(monkeypatch, hass, tmp_path, config)

        # The plug's integration creates the power sensor 8 min after start.
        _cycles(coord, T0, T0 + 8 * MIN)
        hass.states[WASHER_PW] = "0"
        _cycles(coord, T0 + 8 * MIN + timedelta(seconds=15),
                T0 + 11 * MIN)
        assert ir == []                      # still waiting for pass two
        _cycles(coord, T0 + 11 * MIN + timedelta(seconds=15),
                T0 + 13 * MIN)
        assert len(ir) == 1
        assert ir[0][1] == "missing_entities"
        assert ir[0][2]["translation_placeholders"] == {
            "entities": PRICE_LINE}

        # The user selects the renamed price sensor: it exists again.
        hass.states[PRICE] = "0.25"
        _cycles(coord, T0 + 13 * MIN + timedelta(seconds=15),
                T0 + 19 * MIN)
        assert ir[-1] == ("delete", "missing_entities")
