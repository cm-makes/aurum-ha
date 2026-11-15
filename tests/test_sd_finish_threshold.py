"""
Startup detection: the program-finished threshold.

Up to 1.16.3 the finish threshold defaulted to the standby power (3 W = 3 W)
and the help text said "Usually same as standby". The finish check is strict
(power < threshold), so a machine idling at its standby never finished
smartly: only Max runtime (3 h) ended the program, the finished push and the
Must-run-today reset came hours late. The config flow stores every SD field,
so existing devices keep the old 3 W and need the runtime correction.

The threshold must also stay at or below the start threshold, or a finished
machine idling between the two is detected as a new program and its plug cut.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from custom_components.aurum import const
from custom_components.aurum.const import (
    MODE_NORMAL,
    SD_STATE_RUNNING,
    SD_STATE_STANDBY,
    muss_heute_entity_id,
)

SW ="switch.test_device"
PW = "sensor.test_device_power"
MH = muss_heute_entity_id("test_device")
TICK = 30
COMPONENT = Path(__file__).resolve().parent.parent / "custom_components" / "aurum"


def shared(now, excess=0):
    return {
        "now": now,
        "excess_for_devices": excess,
        "excess_raw_for_devices": excess,
        "grid_power_ema_asym": -excess,
        "battery_soc": 80,
        "battery_mode": MODE_NORMAL,
        "device_budget_w": None,
    }


def flow_device(make_device, **kw):
    """An SD device as the config flow stored it up to 1.16.3: every field
    explicit, finish threshold equal to the standby power."""
    base = dict(
        power_entity=PW, nominal_power=2000, startup_detection=True,
        sd_power_threshold=5, sd_standby_power=3, sd_finish_power=3,
        sd_finish_time=600, sd_detection_time=5, sd_max_runtime=10800)
    base.update(kw)
    return make_device(**base)


def running_since(hass, mgr, start):
    """Put the device into RUNNING as a PV start at `start` leaves it."""
    dev = mgr.devices[0]
    dev["sd_state"] = SD_STATE_RUNNING
    dev["sd_running_since"] = start
    dev["sd_lockout_until"] = start + timedelta(seconds=dev["sd_max_runtime"])
    dev["on_since"] = start
    dev["_runtime_tick"] = start
    dev["managed_on"] = True
    hass.states[SW] = "on"
    hass.states[MH] = "on"
    return dev


def run(hass, mgr, start, end, power):
    """Control cycles every TICK s from start (incl.) to end (excl.)."""
    t = start
    while t < end:
        hass.states[PW] = str(power(t) if callable(power) else power)
        mgr.update(shared(t))
        t += timedelta(seconds=TICK)
    return t


def finished_pushes(hass):
    return [kw["message"] for svc, kw in hass.services
            if svc == "persistent_notification/create"
            and "finished" in kw["message"]]


# ══════════════════════════════════════════════════════════════════
#  The rule
# ══════════════════════════════════════════════════════════════════


class TestRule:
    @pytest.mark.parametrize("standby, finish, start, expected", [
        (3, 3, 5, 4),       # old default: at standby, never reached
        (3, 2, 5, 4),       # below standby
        (0, 0, 5, 1),       # a device that idles at 0 W
        (10, 10, 50, 11),   # high idle, high start threshold
        (3, 3, 50, 4),      # washer with 50 W start: not raised further
        (3, 4, 5, 4),       # a usable value is kept
        (3, 4, 50, 4),
        (3, 10, 5, 5),      # above the start threshold: capped
        (5, 5, 5, 5),       # standby at the start threshold: capped
    ])
    def test_effective_threshold(self, standby, finish, start, expected):
        from custom_components.aurum.modules.devices import (
            sd_finish_threshold)
        assert sd_finish_threshold(standby, finish, start) == expected

    def test_config_without_sd_fields(self, make_manager, make_device):
        # Devices set up before the SD fields were in the config flow.
        mgr = make_manager([make_device(startup_detection=True)])
        assert mgr.devices[0]["sd_finish_power"] == 4

    def test_new_default_lies_between_standby_and_start(self):
        assert (const.DEFAULT_DEV_SD_STANDBY_POWER
                < const.DEFAULT_DEV_SD_FINISH_POWER
                <= const.DEFAULT_DEV_SD_POWER_THRESHOLD)

    def test_default_config_is_used_unchanged(self, hass, make_manager,
                                              make_device):
        mgr = make_manager([flow_device(
            make_device,
            sd_standby_power=const.DEFAULT_DEV_SD_STANDBY_POWER,
            sd_finish_power=const.DEFAULT_DEV_SD_FINISH_POWER,
            sd_power_threshold=const.DEFAULT_DEV_SD_POWER_THRESHOLD)])
        assert (mgr.devices[0]["sd_finish_power"]
                == const.DEFAULT_DEV_SD_FINISH_POWER)
        assert not any("finish threshold" in m for m in hass.logs)


# ══════════════════════════════════════════════════════════════════
#  Existing devices with the old stored default
# ══════════════════════════════════════════════════════════════════


class TestStoredOldDefault:
    def test_program_idling_at_standby_finishes_smartly(
            self, hass, make_manager, make_device):
        # Dishwasher, PV start at 09:00, program ends at 10:13, then the
        # machine idles at 3.2-3.4 W (meter reads a little above the
        # entered 3 W standby).
        mgr = make_manager([flow_device(make_device)])
        start = datetime(2026, 11, 15, 9, 0)
        end = datetime(2026, 11, 15, 10, 13)
        dev = running_since(hass, mgr, start)

        run(hass, mgr, start, end, 1900)
        run(hass, mgr, end, end + timedelta(minutes=11),
            lambda t: 3.2 if t.minute % 2 else 3.4)

        assert dev["sd_state"] == SD_STATE_STANDBY
        pushes = finished_pushes(hass)
        assert len(pushes) == 1 and "smart_finish" in pushes[0]
        assert hass.states[MH] == "off"         # job done, not 3 h later
        assert dev["sd_rearm_pending"] is False  # next load detected at once
        assert ("OFF", SW) not in hass.actions   # plug stays on for it

    def test_correction_is_logged_for_startup_detection_only(
            self, hass, make_manager, make_device):
        make_manager([
            flow_device(make_device),
            flow_device(make_device, name="Pump", switch_entity="switch.pump",
                        startup_detection=False),
        ])
        notes = [m for m in hass.logs if "finish threshold" in m]
        assert len(notes) == 1
        assert "Test Device" in notes[0] and "using 4 W" in notes[0]

    def test_quiet_phase_above_the_new_threshold_does_not_finish(
            self, hass, make_manager, make_device):
        # Audit #1 (premature finish in a long quiet phase) is not widened
        # to the start threshold: a 40-min drying phase at 4.5 W, between
        # the corrected 4 W and the 5 W start threshold, keeps the program
        # running, as it did before.
        mgr = make_manager([flow_device(make_device)])
        start = datetime(2026, 11, 15, 9, 0)
        dev = running_since(hass, mgr, start)
        t = run(hass, mgr, start, start + timedelta(minutes=60), 1900)
        t = run(hass, mgr, t, t + timedelta(minutes=40), 4.5)
        run(hass, mgr, t, t + timedelta(minutes=2), 80)   # pump-out

        assert dev["sd_state"] == SD_STATE_RUNNING
        assert finished_pushes(hass) == []
        assert ("OFF", SW) not in hass.actions

    def test_high_start_threshold_raises_only_above_standby(
            self, hass, make_manager, make_device):
        # Washer with the recommended 50 W start threshold: a 20-min soak at
        # 6 W is a program phase, not the end.
        mgr = make_manager([flow_device(make_device, sd_power_threshold=50)])
        start = datetime(2026, 11, 15, 9, 0)
        dev = running_since(hass, mgr, start)
        t = run(hass, mgr, start, start + timedelta(minutes=30), 400)
        run(hass, mgr, t, t + timedelta(minutes=20), 6)

        assert dev["sd_finish_power"] == 4
        assert dev["sd_state"] == SD_STATE_RUNNING
        assert finished_pushes(hass) == []


# ══════════════════════════════════════════════════════════════════
#  Finish threshold above the start threshold
# ══════════════════════════════════════════════════════════════════


class TestAboveStartThreshold:
    def test_finished_machine_is_not_detected_again_and_cut(
            self, hass, make_manager, make_device):
        # Finish 10 W, start 5 W, the machine idles at 7 W after the
        # program. 7 W < 10 W used to finish it, and 7 W > 5 W then
        # detected a new program at once: the plug was switched off and a
        # phantom program waited for PV.
        mgr = make_manager([flow_device(make_device, sd_finish_power=10)])
        start = datetime(2026, 11, 15, 9, 0)
        dev = running_since(hass, mgr, start)
        t = run(hass, mgr, start, start + timedelta(minutes=60), 1900)
        t = run(hass, mgr, t, t + timedelta(minutes=30), 7)

        assert ("OFF", SW) not in hass.actions
        assert finished_pushes(hass) == []
        assert dev["sd_state"] == SD_STATE_RUNNING

        # Max runtime ends it; the re-arm hold keeps the idling machine
        # from being detected again.
        run(hass, mgr, t, start + timedelta(hours=3, minutes=30), 7)
        assert dev["sd_state"] == SD_STATE_STANDBY
        pushes = finished_pushes(hass)
        assert len(pushes) == 1 and "max_runtime" in pushes[0]
        assert ("OFF", SW) not in hass.actions

    def test_still_finishes_below_the_start_threshold(
            self, hass, make_manager, make_device):
        mgr = make_manager([flow_device(make_device, sd_finish_power=10)])
        start = datetime(2026, 11, 15, 9, 0)
        dev = running_since(hass, mgr, start)
        t = run(hass, mgr, start, start + timedelta(minutes=60), 1900)
        run(hass, mgr, t, t + timedelta(minutes=11), 1.5)

        assert dev["sd_state"] == SD_STATE_STANDBY
        assert len(finished_pushes(hass)) == 1
        assert ("OFF", SW) not in hass.actions


# ══════════════════════════════════════════════════════════════════
#  Help texts
# ══════════════════════════════════════════════════════════════════


class TestHelpTexts:
    @pytest.mark.parametrize("path, default", [
        ("strings.json", "Default: {}W."),
        ("translations/en.json", "Default: {}W."),
        ("translations/de.json", "Standard: {}W."),
    ])
    def test_finish_help_matches_default_and_not_standby(self, path, default):
        data = json.loads((COMPONENT / path).read_text(encoding="utf-8"))
        for step in ("add_device", "edit_device"):
            text = data["options"]["step"][step]["data_description"][
                "sd_finish_power"]
            assert default.format(const.DEFAULT_DEV_SD_FINISH_POWER) in text
            assert "same as standby" not in text
            assert "gleich dem Standby" not in text
