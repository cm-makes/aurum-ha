"""
Time-of-use tariffs via a Schedule helper as the cheap-period source.

Households with a day/night tariff (HT/NT, Economy 7, the German grid-fee
module 3) have no price sensor. Up to 1.16.4 the cheap-period field only
accepted a binary_sensor, so marking the night hours in an HA Schedule
helper needed a template binary sensor around it. Now:

- the setup and options flows accept schedule and input_boolean for the
  cheap-period field; every other domain is still rejected,
- PricingManager reads their on/off like a binary sensor (data
  availability, 30-min outage hold),
- with a schedule and no countdown sensor, the countdown comes from the
  schedule's next_event attribute,
- Advisor and the field texts / README cover the setup.
"""

import asyncio
import json
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from custom_components.aurum.const import MODE_NORMAL
from custom_components.aurum.modules.pricing import (
    PRICE_OUTAGE_HOLD_S,
    PricingManager,
)

REPO = Path(__file__).resolve().parent.parent
COMPONENT = REPO / "custom_components" / "aurum"

SCHED = "schedule.night_tariff"
TOGGLE = "input_boolean.cheap_hours"
BINARY = "binary_sensor.best_price"
SW = "switch.test_device"
T0 = datetime(2026, 11, 15, 20, 30, 0)

CHEAP_DEV = {"price_mode": "cheap_grid", "max_price": 0}


# ══════════════════════════════════════════════════════════════════
#  Config flow: which domains the cheap-period field accepts
# ══════════════════════════════════════════════════════════════════


def _install_flow_stubs():
    """Just enough voluptuous / selector / config_entries to import
    config_flow.py and build its forms without Home Assistant.

    The entity selector validates the way HA's does: an entity outside
    the configured domain(s) raises vol.Invalid.
    """
    try:
        import voluptuous as vol
    except ImportError:
        vol = types.ModuleType("voluptuous")

        class _Marker:
            def __init__(self, schema, default=None, description=None):
                self.schema = schema
                self.default = default
                self.description = description

            def __hash__(self):
                return hash(self.schema)

            def __eq__(self, other):
                return getattr(other, "schema", other) == self.schema

        class Schema:
            def __init__(self, schema):
                self.schema = schema

        vol.Required = type("Required", (_Marker,), {})
        vol.Optional = type("Optional", (_Marker,), {})
        vol.Schema = Schema
        vol.Invalid = type("Invalid", (Exception,), {})
        vol.UNDEFINED = object()
        sys.modules["voluptuous"] = vol

    sel = sys.modules["homeassistant.helpers.selector"]
    if not hasattr(sel, "EntitySelector"):
        class _Selector:
            def __init__(self, config=None):
                self.config = config or {}

            def __call__(self, value):
                return value

        class EntitySelector(_Selector):
            def __call__(self, value):
                allowed = self.config.get("domain") or []
                if isinstance(allowed, str):
                    allowed = [allowed]
                domain = value.split(".", 1)[0]
                if allowed and domain not in allowed:
                    raise vol.Invalid(
                        f"Entity {value} belongs to domain {domain}, "
                        f"expected {allowed}")
                return value

        sel.EntitySelector = EntitySelector
        for name in ("NumberSelector", "BooleanSelector", "TextSelector",
                     "SelectSelector", "TimeSelector"):
            setattr(sel, name, type(name, (_Selector,), {}))
        for name in ("EntitySelectorConfig", "NumberSelectorConfig",
                     "TextSelectorConfig", "SelectSelectorConfig",
                     "SelectOptionDict"):
            setattr(sel, name, dict)
        sel.NumberSelectorMode = types.SimpleNamespace(
            BOX="box", SLIDER="slider")
        sel.TextSelectorType = types.SimpleNamespace(TEXT="text")
        sel.SelectSelectorMode = types.SimpleNamespace(
            DROPDOWN="dropdown", LIST="list")

    ce = sys.modules["homeassistant.config_entries"]
    if not hasattr(ce, "ConfigFlow"):
        class _Flow:
            def async_show_form(self, **kwargs):
                return {"type": "form", **kwargs}

        class ConfigFlow(_Flow):
            def __init_subclass__(cls, domain=None, **kwargs):
                super().__init_subclass__(**kwargs)

        ce.ConfigFlow = ConfigFlow
        ce.OptionsFlow = type("OptionsFlow", (_Flow,), {})


def _config_flow():
    _install_flow_stubs()
    from custom_components.aurum import config_flow
    return config_flow


def _setup_form():
    """Setup wizard, step 2 (battery + price sources)."""
    flow = _config_flow().AurumConfigFlow()
    return asyncio.run(flow.async_step_battery())


def _options_form(**configured):
    """Options flow, Energy & Battery settings."""
    entry = types.SimpleNamespace(
        data={"grid_power_entity": "sensor.grid", "devices": [],
              **configured},
        options={})
    handler = _config_flow().AurumOptionsFlowHandler(entry)
    return asyncio.run(handler.async_step_settings())


def _field(form, key):
    """(marker, validator) of a field in a shown form."""
    for marker, validator in form["data_schema"].schema.items():
        if getattr(marker, "schema", marker) == key:
            return marker, validator
    raise AssertionError(f"{key} is not in step {form['step_id']}")


FORMS = {"setup": _setup_form, "options": _options_form}


class TestCheapPeriodSelector:
    @pytest.mark.parametrize("flow", sorted(FORMS))
    @pytest.mark.parametrize("entity", [SCHED, TOGGLE, BINARY])
    def test_accepts_schedule_toggle_and_binary_sensor(self, flow, entity):
        _, validator = _field(FORMS[flow](), "cheap_period_entity")
        assert validator(entity) == entity

    @pytest.mark.parametrize("flow", sorted(FORMS))
    @pytest.mark.parametrize("entity", [
        "sensor.tibber_price", "switch.boiler", "input_number.cheap",
        "calendar.tariff", "light.kitchen", "input_select.tariff",
    ])
    def test_rejects_other_domains(self, flow, entity):
        _, validator = _field(FORMS[flow](), "cheap_period_entity")
        vol = sys.modules["voluptuous"]
        with pytest.raises(vol.Invalid):
            validator(entity)

    @pytest.mark.parametrize("flow", sorted(FORMS))
    def test_countdown_field_stays_a_sensor(self, flow):
        _, validator = _field(FORMS[flow](), "cheap_period_starts_in_entity")
        assert validator("sensor.best_price_starts_in")
        with pytest.raises(sys.modules["voluptuous"].Invalid):
            validator(SCHED)

    def test_options_form_keeps_a_configured_schedule(self):
        marker, _ = _field(
            _options_form(cheap_period_entity=SCHED), "cheap_period_entity")
        default = marker.default
        assert (default() if callable(default) else default) == SCHED


# ══════════════════════════════════════════════════════════════════
#  PricingManager: on/off of a schedule or toggle = binary sensor
# ══════════════════════════════════════════════════════════════════


def _pm(hass, entity=SCHED, **config):
    return PricingManager(hass, {"cheap_period_entity": entity, **config})


def _cycle(pm, now):
    shared = {"now": now}
    pm.update(shared)
    pm.snapshot(shared)
    return shared


SOURCES = [SCHED, TOGGLE, BINARY]


class TestOnOffSource:
    """PricingManager already read any on/off state; these keep the
    schedule and toggle on exactly the binary-sensor path."""

    @pytest.mark.parametrize("entity", SOURCES)
    def test_on_is_cheap(self, hass, entity):
        hass.states[entity] = "on"
        pm = _pm(hass, entity)
        assert pm.active
        shared = _cycle(pm, T0)
        assert shared["cheap_period"] is True
        assert shared["price_data_available"] is True
        assert pm.should_run_on_grid(CHEAP_DEV) is True
        assert pm.should_run_on_grid({"price_mode": "solar_only"}) is False

    @pytest.mark.parametrize("entity", SOURCES)
    def test_off_is_a_valid_not_cheap_reading(self, hass, entity):
        hass.states[entity] = "off"
        pm = _pm(hass, entity)
        shared = _cycle(pm, T0)
        assert shared["cheap_period"] is False
        assert shared["price_data_available"] is True
        # False (not cheap), not None (hold): a cheap-grid run ends.
        assert pm.should_run_on_grid(CHEAP_DEV) is False

    @pytest.mark.parametrize("entity", SOURCES)
    @pytest.mark.parametrize("raw", ["unavailable", "unknown", None])
    def test_outage_holds_then_releases(self, hass, entity, raw):
        hass.states[entity] = "on"
        pm = _pm(hass, entity)
        _cycle(pm, T0)
        if raw is None:
            del hass.states[entity]     # helper deleted
        else:
            hass.states[entity] = raw
        shared = _cycle(pm, T0 + timedelta(minutes=1))
        assert shared["price_data_available"] is False
        assert pm.should_run_on_grid(CHEAP_DEV) is None
        _cycle(pm, T0 + timedelta(seconds=60 + PRICE_OUTAGE_HOLD_S))
        assert pm.should_run_on_grid(CHEAP_DEV) is False
        hass.states[entity] = "on"
        _cycle(pm, T0 + timedelta(hours=1))
        assert pm.should_run_on_grid(CHEAP_DEV) is True


# ══════════════════════════════════════════════════════════════════
#  Countdown from the schedule's next_event
# ══════════════════════════════════════════════════════════════════


def _schedule(hass, state, next_event=None, entity=SCHED):
    hass.states[entity] = state
    hass.attributes = getattr(hass, "attributes", {})
    hass.attributes[entity] = {"next_event": next_event}


def _local(now):
    """now as an aware datetime, like HA's schedule reports it."""
    return now.astimezone()


class TestScheduleCountdown:
    def test_minutes_until_the_next_block_while_off(self, hass):
        _schedule(hass, "off", _local(T0) + timedelta(minutes=90))
        shared = _cycle(_pm(hass), T0)
        assert shared["cheap_period_starts_in_min"] == 90

    def test_zero_while_the_block_runs(self, hass):
        # next_event is then the END of the block: not a start.
        _schedule(hass, "on", _local(T0) + timedelta(hours=8))
        shared = _cycle(_pm(hass), T0)
        assert shared["cheap_period_starts_in_min"] == 0

    def test_rounds_up_so_zero_means_started(self, hass):
        _schedule(hass, "off", _local(T0) + timedelta(seconds=30))
        shared = _cycle(_pm(hass), T0)
        assert shared["cheap_period_starts_in_min"] == 1

    def test_next_event_in_another_time_zone(self, hass):
        event = (_local(T0) + timedelta(minutes=45)).astimezone(
            timezone(timedelta(hours=-5)))
        _schedule(hass, "off", event)
        shared = _cycle(_pm(hass), T0)
        assert shared["cheap_period_starts_in_min"] == 45

    def test_next_event_as_iso_string(self, hass):
        _schedule(hass, "off",
                  (_local(T0) + timedelta(minutes=150)).isoformat())
        shared = _cycle(_pm(hass), T0)
        assert shared["cheap_period_starts_in_min"] == 150

    @pytest.mark.parametrize("event", [None, "", "soon", 42])
    def test_no_usable_next_event(self, hass, event):
        # An empty schedule has next_event None.
        _schedule(hass, "off", event)
        shared = _cycle(_pm(hass), T0)
        assert shared["cheap_period_starts_in_min"] is None

    def test_unavailable_schedule_has_no_countdown(self, hass):
        _schedule(hass, "unavailable", _local(T0) + timedelta(minutes=90))
        shared = _cycle(_pm(hass), T0)
        assert shared["cheap_period_starts_in_min"] is None

    def test_a_countdown_sensor_wins(self, hass):
        _schedule(hass, "off", _local(T0) + timedelta(minutes=90))
        hass.states["sensor.starts_in"] = "12"
        shared = _cycle(
            _pm(hass, cheap_period_starts_in_entity="sensor.starts_in"), T0)
        assert shared["cheap_period_starts_in_min"] == 12

    @pytest.mark.parametrize("entity", [TOGGLE, BINARY])
    def test_only_a_schedule_is_read(self, hass, entity):
        _schedule(hass, "off", _local(T0) + timedelta(minutes=90), entity)
        shared = _cycle(_pm(hass, entity), T0)
        assert shared["cheap_period_starts_in_min"] is None


# ══════════════════════════════════════════════════════════════════
#  End to end: a cheap-grid device on a night-tariff schedule
# ══════════════════════════════════════════════════════════════════


def _night_shared(now):
    """No surplus (importing 500 W), battery fine, no PV budget."""
    return {
        "now": now,
        "excess_for_devices": -500,
        "excess_raw_for_devices": -500,
        "grid_power_ema_asym": 500,
        "battery_soc": 80,
        "battery_mode": MODE_NORMAL,
        "device_budget_w": None,
        "surplus_blind": False,
    }


def _run(mgr, pm, start, minutes, step=30):
    t = start
    end = start + timedelta(minutes=minutes)
    shared = None
    while t <= end:
        shared = _night_shared(t)
        pm.update(shared)
        pm.snapshot(shared)
        mgr.update(shared)
        t += timedelta(seconds=step)
    return t, shared


class TestNightTariffDevice:
    def test_runs_in_the_cheap_hours_only(
            self, hass, make_manager, make_device):
        mgr = make_manager([make_device(price_mode="cheap_grid")])
        pm = _pm(hass)
        mgr.pricing = pm

        _schedule(hass, "off", _local(T0) + timedelta(minutes=90))
        t, shared = _run(mgr, pm, T0, 30)
        assert hass.states[SW] == "off"
        assert shared["cheap_period_starts_in_min"] == 60

        _schedule(hass, "on", _local(T0) + timedelta(hours=9))
        t, shared = _run(mgr, pm, t, 15)
        assert hass.states[SW] == "on"
        assert shared["cheap_period_starts_in_min"] == 0
        dev = next(d for d in shared["device_states"]
                   if d["slug"] == "test_device")
        assert dev["scheduling_reason"] == "cheap_grid"

        # 06:00, the block ends: the run ends after the usual delays.
        _schedule(hass, "off", _local(t) + timedelta(hours=16))
        _run(mgr, pm, t, 30)
        assert hass.states[SW] == "off"


# ══════════════════════════════════════════════════════════════════
#  Advisor with only a schedule (no price, no level)
# ══════════════════════════════════════════════════════════════════


class TestAdvisorScheduleOnly:
    def test_cheap_grid_run_without_a_price(self, hass):
        from custom_components.aurum.modules.advisor import AdvisorManager
        hass.states[SCHED] = "on"
        shared = _cycle(_pm(hass), T0)
        shared.update({
            "battery_mode": MODE_NORMAL, "battery_soc": 80,
            "device_states": [{
                "name": "Boiler", "slug": "boiler", "state": "on",
                "scheduling_reason": "cheap_grid"}],
        })
        data = AdvisorManager(None, {}).update(shared)
        assert data["decision"] == "running_cheap_grid"
        assert data["devices"][0]["reason"] == "cheap_grid"
        # No price figure to show: the panel prints no "ct/kWh".
        assert "current_price_ct" not in data


# ══════════════════════════════════════════════════════════════════
#  Field texts and README
# ══════════════════════════════════════════════════════════════════


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


TEXTS = {
    "strings.json": (COMPONENT / "strings.json",
                     ("Schedule helper", "22:00–06:00", "input_boolean"),
                     "Not needed with a Schedule helper"),
    "en.json": (COMPONENT / "translations" / "en.json",
                ("Schedule helper", "22:00–06:00", "input_boolean"),
                "Not needed with a Schedule helper"),
    "de.json": (COMPONENT / "translations" / "de.json",
                ("Zeitplan-Helfer", "22:00–06:00", "input_boolean"),
                "Mit einem Zeitplan-Helfer nicht nötig"),
}
STEPS = [("config", "battery"), ("options", "settings")]


class TestTexts:
    def test_strings_json_is_en_json(self):
        assert (COMPONENT / "strings.json").read_bytes() == (
            COMPONENT / "translations" / "en.json").read_bytes()

    @pytest.mark.parametrize("name", sorted(TEXTS))
    @pytest.mark.parametrize("section, step", STEPS)
    def test_field_texts_in_setup_and_options(self, name, section, step):
        path, phrases, countdown = TEXTS[name]
        form = _load(path)[section]["step"][step]
        assert form["data"]["cheap_period_entity"]
        assert form["data"]["cheap_period_starts_in_entity"]
        text = form["data_description"]["cheap_period_entity"]
        for phrase in phrases:
            assert phrase in text
        assert countdown in form["data_description"][
            "cheap_period_starts_in_entity"]

    def test_readme_example(self):
        readme = " ".join(
            (REPO / "README.md").read_text(encoding="utf-8").split())
        assert "**Day/night tariff without a price sensor**" in readme
        assert "`schedule.night_tariff`" in readme
        assert ("add two blocks on every day, 00:00–06:00 and "
                "22:00–24:00") in readme
        assert ("AURUM reads the countdown to the next cheap block from "
                "the schedule") in readme
