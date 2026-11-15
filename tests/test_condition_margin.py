"""
Restart margin for the run condition (thermostat band).

'below 55' with margin 3: the condition is unmet from 55 on and met again
only below 52, so a tank that dips to 54.9 no longer restarts the water
heater ('above' mirrored). The latch follows the readings, so every path
that uses the condition sees the same answer: surplus start, cheap grid,
deadline start, the startup-detection WAITING state and the stop of a
running device. Margin 0 (the default) keeps the strict compare.
"""

import ast
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from custom_components.aurum import const
from custom_components.aurum.const import (
    MODE_NORMAL,
    SD_STATE_RUNNING,
    SD_STATE_WAITING,
    muss_heute_entity_id,
    override_entity_id,
)
from custom_components.aurum.modules.persistence import PersistenceManager
from tests.conftest import FakePricing

SW = "switch.test_device"
MH = muss_heute_entity_id("test_device")
OVR = override_entity_id("test_device")
TEMP = "sensor.tank_temp"
T0 = datetime(2026, 7, 1, 12, 0)

ROOT = Path(__file__).resolve().parent.parent / "custom_components" / "aurum"
TRANSLATION_FILES = [
    ROOT / "strings.json",
    ROOT / "translations" / "en.json",
    ROOT / "translations" / "de.json",
]


def heater(make_device, **kw):
    """Water heater: run while the tank is below 55, restart below 52."""
    base = dict(condition_entity=TEMP, condition_op="below",
                condition_value=55, condition_margin=3,
                debounce_on=0, min_on_time=0, min_off_time=0)
    base.update(kw)
    return make_device(**base)


def shared(now, excess, soc=80):
    return {
        "now": now,
        "excess_for_devices": excess,
        "excess_raw_for_devices": excess,
        "grid_power_ema_asym": -excess,
        "battery_soc": soc,
        "battery_mode": MODE_NORMAL,
        "device_budget_w": None,
    }


class Clock:
    """Runs DeviceManager cycles 30 s apart."""

    def __init__(self, mgr, start=T0):
        self.mgr = mgr
        self.now = start

    def cycle(self, excess, n=1, soc=80):
        data = None
        for _ in range(n):
            data = shared(self.now, excess, soc)
            self.mgr.update(data)
            self.now += timedelta(seconds=30)
        return data


# ══════════════════════════════════════════════════════════════════
#  The band itself
# ══════════════════════════════════════════════════════════════════


class TestBand:
    def test_below(self, hass, make_manager, make_device):
        mgr = make_manager([heater(make_device)])
        dev = mgr.devices[0]
        for value, expected in [
            ("50", True),       # cold tank
            ("55", False),      # limit reached → latched
            ("54.9", False),    # the dip that used to restart the heater
            ("52", False),      # the restart level itself is still inside
            ("51.9", True),     # back past the limit by the margin
            ("54", True),       # heating up again: free until the limit
            ("55", False),
        ]:
            hass.states[TEMP] = value
            assert mgr._condition_met(dev) is expected, value

    def test_above_is_mirrored(self, hass, make_manager, make_device):
        mgr = make_manager([make_device(
            condition_entity="sensor.pool_ph", condition_op="above",
            condition_value=7, condition_margin=0.5)])
        dev = mgr.devices[0]
        for value, expected in [("7.4", True), ("7.0", False),
                                ("7.2", False), ("7.5", False),
                                ("7.6", True), ("7.1", True),
                                ("6.9", False)]:
            hass.states["sensor.pool_ph"] = value
            assert mgr._condition_met(dev) is expected, value

    def test_repeated_calls_in_one_cycle_agree(
            self, hass, make_manager, make_device):
        # Block 1d, the start path and the published flag all ask.
        mgr = make_manager([heater(make_device)])
        dev = mgr.devices[0]
        hass.states[TEMP] = "56"
        mgr._condition_met(dev)
        hass.states[TEMP] = "53"
        assert [mgr._condition_met(dev) for _ in range(3)] == [False] * 3

    def test_default_margin_is_the_strict_compare(
            self, hass, make_manager, make_device):
        mgr = make_manager([make_device(
            condition_entity=TEMP, condition_op="below",
            condition_value=55)])
        dev = mgr.devices[0]
        assert dev["condition_margin"] == 0
        hass.states[TEMP] = "55"
        assert mgr._condition_met(dev) is False
        hass.states[TEMP] = "54.9"
        assert mgr._condition_met(dev) is True

    def test_unavailable_sensor_fails_open_and_keeps_the_latch(
            self, hass, make_manager, make_device):
        mgr = make_manager([heater(make_device)])
        dev = mgr.devices[0]
        hass.states[TEMP] = "55"
        assert mgr._condition_met(dev) is False
        hass.states[TEMP] = "unavailable"
        assert mgr._condition_met(dev) is True     # fail-open, as before
        # Back with a reading inside the band: a short dropout must not
        # reopen the band.
        hass.states[TEMP] = "54"
        assert mgr._condition_met(dev) is False


# ══════════════════════════════════════════════════════════════════
#  Every path that uses the condition
# ══════════════════════════════════════════════════════════════════


class TestPaths:
    def test_surplus_does_not_restart_inside_the_band(
            self, hass, make_manager, make_device):
        mgr = make_manager([heater(make_device)])
        clock = Clock(mgr)
        hass.states[TEMP] = "50"
        clock.cycle(3000, n=2)
        assert hass.states[SW] == "on"

        hass.states[TEMP] = "55"                  # tank hot → off
        clock.cycle(3000)
        assert hass.states[SW] == "off"

        for value in ("54.9", "53", "52"):
            hass.states[TEMP] = value
            data = clock.cycle(3000, n=3)
            assert hass.states[SW] == "off", value
            # The Advisor reads this flag: "run condition not met".
            assert data["device_states"][0]["condition_met"] is False

        hass.states[TEMP] = "51.9"
        clock.cycle(3000, n=2)
        assert hass.states[SW] == "on"

    def test_cheap_grid_start_waits_for_the_restart_level(
            self, hass, make_manager, make_device):
        mgr = make_manager([heater(make_device, price_mode="cheap_grid")])
        mgr.pricing = FakePricing(price_ok=True)
        clock = Clock(mgr, datetime(2026, 7, 1, 2, 0))   # night, no PV
        hass.states[TEMP] = "55"
        clock.cycle(-300)
        hass.states[TEMP] = "53"
        clock.cycle(-300, n=3)
        assert ("ON", SW) not in hass.actions

        hass.states[TEMP] = "51"
        clock.cycle(-300)
        assert hass.states[SW] == "on"
        assert mgr.devices[0]["_scheduling_reason"] == "cheap_grid"

    def test_deadline_start_waits_for_the_restart_level(
            self, hass, make_manager, make_device):
        mgr = make_manager([heater(
            make_device, deadline="18:00", estimated_runtime=60)])
        hass.states[MH] = "on"
        # 60 min + 5 min buffer before 18:00: the deadline window is open.
        clock = Clock(mgr, datetime(2026, 11, 5, 16, 55))
        hass.states[TEMP] = "55"
        clock.cycle(-500)
        hass.states[TEMP] = "53"
        clock.cycle(-500, n=4)
        assert ("ON", SW) not in hass.actions

        hass.states[TEMP] = "51"
        clock.cycle(-500)
        assert hass.states[SW] == "on"
        assert mgr.devices[0]["force_started"] is True

    def test_paused_program_waits_for_the_restart_level(
            self, hass, make_manager, make_device):
        mgr = make_manager([heater(make_device, startup_detection=True)])
        dev = mgr.devices[0]
        dev["sd_state"] = SD_STATE_WAITING
        dev["sd_waiting_since"] = T0
        clock = Clock(mgr)
        hass.states[TEMP] = "55"
        clock.cycle(3000)
        hass.states[TEMP] = "54"
        clock.cycle(3000, n=3)
        assert dev["sd_state"] == SD_STATE_WAITING
        assert ("ON", SW) not in hass.actions

        hass.states[TEMP] = "51.9"
        clock.cycle(3000, n=2)
        assert dev["sd_state"] == SD_STATE_RUNNING
        assert hass.states[SW] == "on"

    def test_running_program_is_not_cut_by_the_band(
            self, hass, make_manager, make_device):
        # README promise: a running startup-detection program is never
        # cut by AURUM, the run condition included.
        mgr = make_manager([heater(make_device, startup_detection=True,
                                   power_entity="sensor.heater_power")])
        dev = mgr.devices[0]
        dev["sd_state"] = SD_STATE_RUNNING
        dev["sd_running_since"] = T0
        dev["sd_lockout_until"] = T0 + timedelta(hours=3)
        dev["managed_on"] = True
        hass.states[SW] = "on"
        hass.states["sensor.heater_power"] = "1500"
        clock = Clock(mgr)
        for value in ("56", "54"):
            hass.states[TEMP] = value
            clock.cycle(-2000, n=3)
        assert ("OFF", SW) not in hass.actions
        assert dev["sd_state"] == SD_STATE_RUNNING

    def test_device_switched_on_by_hand_inside_the_band_is_stopped(
            self, hass, make_manager, make_device):
        # Inside the band the condition counts as unmet, like above the
        # limit: block 1d stops the device once min_on_time is honoured.
        mgr = make_manager([heater(make_device, min_on_time=600)])
        clock = Clock(mgr)
        hass.states[TEMP] = "55"
        clock.cycle(3000)
        hass.states[TEMP] = "53"
        hass.states[SW] = "on"                    # by hand, no override
        clock.cycle(3000)
        assert hass.states[SW] == "on"            # min_on_time first
        clock.now += timedelta(seconds=600)
        clock.cycle(3000)
        assert hass.states[SW] == "off"

    def test_latch_follows_the_sensor_under_manual_override(
            self, hass, make_manager, make_device):
        # The user heats the tank to 60 under override (anti-legionella);
        # AURUM switches nothing then. Released at 54, it is not restarted
        # until the tank is below 52.
        mgr = make_manager([heater(make_device)])
        clock = Clock(mgr)
        hass.states[OVR] = "on"
        hass.states[SW] = "on"
        for value in ("50", "60"):
            hass.states[TEMP] = value
            clock.cycle(3000, n=2)
        assert hass.actions == []                 # override: hands off

        hass.states[SW] = "off"                   # user switches off
        hass.states[TEMP] = "54"
        hass.states[OVR] = "off"
        clock.cycle(3000, n=3)
        assert ("ON", SW) not in hass.actions

        hass.states[TEMP] = "51"
        clock.cycle(3000, n=2)
        assert hass.states[SW] == "on"


# ══════════════════════════════════════════════════════════════════
#  Restart / reload
# ══════════════════════════════════════════════════════════════════


class TestPersistence:
    def _latched_state_file(self, hass, make_manager, make_device, tmp_path):
        sf = str(tmp_path / "state.json")
        mgr = make_manager([heater(make_device)])
        hass.states[TEMP] = "55"
        Clock(mgr, datetime.now()).cycle(0)
        PersistenceManager(hass, {"state_file": sf}).save(mgr)
        return sf

    def test_band_survives_a_restart(
            self, hass, make_manager, make_device, tmp_path):
        sf = self._latched_state_file(
            hass, make_manager, make_device, tmp_path)
        hass.states[TEMP] = "53"
        mgr2 = make_manager([heater(make_device)])
        PersistenceManager(hass, {"state_file": sf}).restore(mgr2)
        assert mgr2._condition_met(mgr2.devices[0]) is False

    @pytest.mark.parametrize("edit", [
        {"condition_value": 56},
        {"condition_op": "above", "condition_value": 50},
        {"condition_entity": "sensor.other_temp"},
    ], ids=["limit", "operator", "sensor"])
    def test_edited_condition_starts_without_a_latch(
            self, hass, make_manager, make_device, tmp_path, edit):
        sf = self._latched_state_file(
            hass, make_manager, make_device, tmp_path)
        hass.states[TEMP] = "53"
        hass.states["sensor.other_temp"] = "53"
        mgr2 = make_manager([heater(make_device, **edit)])
        PersistenceManager(hass, {"state_file": sf}).restore(mgr2)
        assert mgr2._condition_met(mgr2.devices[0]) is True

    def test_edited_margin_keeps_the_latch(
            self, hass, make_manager, make_device, tmp_path):
        # The latch means "the limit was reached"; the margin only says
        # where it ends.
        sf = self._latched_state_file(
            hass, make_manager, make_device, tmp_path)
        hass.states[TEMP] = "51"
        mgr2 = make_manager([heater(make_device, condition_margin=5)])
        PersistenceManager(hass, {"state_file": sf}).restore(mgr2)
        assert mgr2._condition_met(mgr2.devices[0]) is False

    def test_state_file_without_the_field(
            self, hass, make_manager, make_device, tmp_path):
        sf = tmp_path / "state.json"
        sf.write_text(json.dumps({
            "_meta": {"saved_at": datetime.now().isoformat()},
            "Test Device": {"runtime_today_s": 0, "managed_on": False},
        }))
        mgr = make_manager([heater(make_device)])
        PersistenceManager(hass, {"state_file": str(sf)}).restore(mgr)
        hass.states[TEMP] = "53"
        assert mgr._condition_met(mgr.devices[0]) is True


# ══════════════════════════════════════════════════════════════════
#  Device form
# ══════════════════════════════════════════════════════════════════


def _device_form_fields():
    """{const value: vol.Optional/Required call} of _schema_add_device,
    read from config_flow.py's source (no HA install needed)."""
    tree = ast.parse((ROOT / "config_flow.py").read_text(encoding="utf-8"))
    func = next(f for f in ast.walk(tree)
                if isinstance(f, ast.FunctionDef)
                and f.name == "_schema_add_device")
    fields = {}
    for call in ast.walk(func):
        if (isinstance(call, ast.Call)
                and getattr(call.func, "attr", None) in ("Optional",
                                                         "Required")
                and call.args and isinstance(call.args[0], ast.Name)):
            fields[getattr(const, call.args[0].id)] = call
    return fields, func


class TestDeviceForm:
    def test_margin_field_defaults_to_zero(self):
        fields, func = _device_form_fields()
        call = fields["condition_margin"]
        default = next(k.value for k in call.keywords if k.arg == "default")
        assert isinstance(default, ast.Call)         # d.get(KEY, 0)
        assert default.args[1].value == 0
        # The selector that belongs to this field: min 0 (no negative
        # band), a positive max and step.
        parent = next(n for n in ast.walk(func)
                      if isinstance(n, ast.Dict)
                      and any(k is call for k in n.keys))
        selector = parent.values[parent.keys.index(call)]
        cfg = next(n for n in ast.walk(selector)
                   if isinstance(n, ast.Call)
                   and getattr(n.func, "attr", None)
                   == "NumberSelectorConfig")
        kw = {k.arg: k.value.value for k in cfg.keywords
              if isinstance(k.value, ast.Constant)}
        assert kw["min"] == 0 and kw["max"] > 0 and kw["step"] > 0

    @pytest.mark.parametrize("path", TRANSLATION_FILES, ids=lambda p: p.name)
    @pytest.mark.parametrize("step", ["add_device", "edit_device"])
    def test_every_field_has_a_label(self, path, step):
        fields, _ = _device_form_fields()
        data = json.loads(path.read_text(encoding="utf-8"))
        labels = data["options"]["step"][step]["data"]
        assert set(fields) <= set(labels)

    @pytest.mark.parametrize("path", TRANSLATION_FILES, ids=lambda p: p.name)
    @pytest.mark.parametrize("step", ["add_device", "edit_device"])
    def test_margin_is_labelled_and_explained(self, path, step):
        data = json.loads(path.read_text(encoding="utf-8"))
        texts = data["options"]["step"][step]
        assert texts["data"]["condition_margin"]
        assert "52" in texts["data_description"]["condition_margin"]

    def test_strings_json_matches_english(self):
        assert ((ROOT / "strings.json").read_bytes()
                == (ROOT / "translations" / "en.json").read_bytes())
