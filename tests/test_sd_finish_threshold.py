"""
Startup detection: the program-finished threshold.

Up to 1.16.3 the finish threshold defaulted to the standby power (3 W = 3 W)
and the help text said "Usually same as standby". The finish check is strict
(power < threshold), so a machine idling at its standby never finished
smartly: only Max runtime (3 h) ended the program, the finished push and the
Must-run-today reset came hours late. The config flow stores every SD field,
so existing devices keep the old 3 W and need the runtime correction.

Only values that were not chosen on purpose are raised: finish == standby
for a standby of 3 W or more, or a stored default (the old 3 W, the new
4 W) left alone below a raised standby. Any other value at or below standby
is a deliberate edit (a machine that really idles lower) and is used as set.

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
        (3.0, 3.0, 5.0, 4.0),   # as the number selector stores it
        (4, 4, 50, 5),      # = standby, raised together
        (10, 10, 50, 11),   # = standby, as the old help text said
        (3, 3, 50, 4),      # washer with 50 W start: not raised further
        (2, 2, 5, 2),       # equal pair lowered below the old default:
        (1, 1, 5, 1),       # ... both lowered on purpose, used as set
        (2.0, 2.0, 5.0, 2.0),
        (0, 0, 5, 0),       # ... 0 W is never undercut: left to Max runtime
        (5, 3, 10, 6),      # old 3 W default left below a raised standby
        (5, 3, 5, 5),       # ... raised, then capped at the start threshold
        (5, 4, 10, 6),      # new 4 W default left below a raised standby
        (5, 4, 50, 6),
        (6, 4, 50, 7),
        (5.0, 4.0, 50.0, 6.0),
        (5, 4, 5, 5),       # ... raised, then capped at the start threshold
        (3, 2, 5, 2),       # deliberately below standby: used as set
        (3, 1, 5, 1),
        (3, 0, 5, 0),
        (5, 2, 10, 2),      # below a raised standby, not a default
        (6, 5, 50, 5),
        (1, 3, 5, 3),       # old default above a lowered standby: usable
        (2, 4, 5, 4),       # new default above a lowered standby: usable
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

    def test_old_default_below_a_raised_standby_is_raised(
            self, hass, make_manager, make_device):
        # Standby raised to 5 W for a machine that idles there, Finish left
        # at the stored 3 W: the idle machine never dropped below it.
        mgr = make_manager([flow_device(
            make_device, sd_standby_power=5, sd_power_threshold=10)])
        start = datetime(2026, 11, 15, 9, 0)
        dev = running_since(hass, mgr, start)
        t = run(hass, mgr, start, start + timedelta(minutes=60), 1900)
        run(hass, mgr, t, t + timedelta(minutes=11), 5.3)

        assert dev["sd_finish_power"] == 6
        assert dev["sd_state"] == SD_STATE_STANDBY
        pushes = finished_pushes(hass)
        assert len(pushes) == 1 and "smart_finish" in pushes[0]
        assert ("OFF", SW) not in hass.actions
        assert any("using 6 W" in m for m in hass.logs)

    @pytest.mark.parametrize("standby, start, idle, used", [
        (5, 50, 5.2, 6),    # washer with the recommended 50 W start
        (6, 50, 6.3, 7),
        (5, 10, 5.3, 6),
    ])
    def test_new_default_below_a_raised_standby_is_raised(
            self, hass, make_manager, make_device, standby, start, idle,
            used):
        # A device added from this release on: Standby raised for a machine
        # that idles there, Finish left at the 4 W the add-device form
        # stores. Kept as set, the idle machine never dropped below it.
        mgr = make_manager([flow_device(
            make_device, sd_standby_power=standby,
            sd_finish_power=const.DEFAULT_DEV_SD_FINISH_POWER,
            sd_power_threshold=start)])
        begin = datetime(2026, 11, 15, 9, 0)
        dev = running_since(hass, mgr, begin)
        t = run(hass, mgr, begin, begin + timedelta(minutes=60), 400)
        run(hass, mgr, t, t + timedelta(minutes=11), idle)

        assert dev["sd_finish_power"] == used
        assert dev["sd_state"] == SD_STATE_STANDBY
        pushes = finished_pushes(hass)
        assert len(pushes) == 1 and "smart_finish" in pushes[0]
        assert hass.states[MH] == "off"          # job done, not 3 h later
        assert ("OFF", SW) not in hass.actions
        assert any(f"using {used} W" in m for m in hass.logs)


# ══════════════════════════════════════════════════════════════════
#  A finish threshold deliberately set below standby
# ══════════════════════════════════════════════════════════════════


class TestBelowStandbyKeptAsSet:
    """A finish threshold below standby only comes from a deliberate edit,
    typically for a machine that really idles lower than the entered 3 W
    standby (a plug that does not count its own draw idles at ~0.5 W) and
    whose drying phase ended the program too early. Raising it to
    standby + 1 W brought that back, and the pump-out after the drying
    phase was detected as a new program and its plug cut. The same holds
    for an equal pair lowered below the old 3 W / 3 W default (2 W / 2 W):
    a user who followed the old "Usually same as standby" lowered both."""

    @pytest.mark.parametrize("standby, finish, drying", [
        (3, 1, 2.0),
        (3, 2, 2.5),
        (2, 2, 2.5),        # equal pair lowered on purpose
        (1, 1, 1.5),
    ])
    def test_drying_phase_does_not_end_the_program(
            self, hass, make_manager, make_device, standby, finish, drying):
        mgr = make_manager([flow_device(
            make_device, sd_standby_power=standby, sd_finish_power=finish)])
        start = datetime(2026, 11, 15, 9, 0)
        dev = running_since(hass, mgr, start)
        t = run(hass, mgr, start, start + timedelta(minutes=60), 1900)
        t = run(hass, mgr, t, t + timedelta(minutes=30), drying)
        t = run(hass, mgr, t, t + timedelta(minutes=2), 80)   # pump-out

        assert ("OFF", SW) not in hass.actions   # pump-out not cut
        assert finished_pushes(hass) == []
        assert dev["sd_state"] == SD_STATE_RUNNING
        assert hass.states[MH] == "on"           # job not reset early

        run(hass, mgr, t, t + timedelta(minutes=11), 0.5)   # real idle
        assert dev["sd_state"] == SD_STATE_STANDBY
        pushes = finished_pushes(hass)
        assert len(pushes) == 1 and "smart_finish" in pushes[0]
        assert hass.states[MH] == "off"
        assert ("OFF", SW) not in hass.actions
        assert dev["sd_finish_power"] == finish

    def test_finish_zero_is_left_to_max_runtime(
            self, hass, make_manager, make_device):
        # 0 W is never undercut: the user left the end to Max runtime.
        mgr = make_manager([flow_device(make_device, sd_finish_power=0)])
        start = datetime(2026, 11, 15, 9, 0)
        dev = running_since(hass, mgr, start)
        t = run(hass, mgr, start, start + timedelta(minutes=60), 1900)
        t = run(hass, mgr, t, t + timedelta(minutes=30), 2.0)
        run(hass, mgr, t, t + timedelta(minutes=30), 0.5)

        assert ("OFF", SW) not in hass.actions
        assert finished_pushes(hass) == []
        assert dev["sd_state"] == SD_STATE_RUNNING
        assert dev["sd_finish_power"] == 0

    @pytest.mark.parametrize("standby, finish, relation", [
        (3, 2, "is below standby 3 W"),
        (2, 2, "equals standby 2 W"),
    ])
    def test_hint_is_logged_once_per_setup(
            self, hass, make_manager, make_device, standby, finish,
            relation):
        mgr = make_manager([flow_device(
            make_device, sd_standby_power=standby, sd_finish_power=finish)])
        start = datetime(2026, 11, 15, 9, 0)
        running_since(hass, mgr, start)
        run(hass, mgr, start, start + timedelta(minutes=10), 1900)

        notes = [m for m in hass.logs if "AURUM SD [Test Device]: " in m
                 and "finish threshold" in m]
        assert len(notes) == 1
        assert f"finish threshold {finish} W {relation}, kept as set" \
            in notes[0]
        assert "using" not in notes[0]


# ══════════════════════════════════════════════════════════════════
#  The setup log line
# ══════════════════════════════════════════════════════════════════


class TestThresholdLog:
    @staticmethod
    def sd_notes(hass):
        return [m for m in hass.logs if m.startswith("AURUM SD [Test Device]")]

    @pytest.mark.parametrize("standby, finish, start, expected", [
        (3, 3, 5, "finish threshold 3 W is not above standby 3 W"),
        (5, 3, 10, "finish threshold 3 W is not above standby 5 W"),
        (5, 4, 50, "finish threshold 4 W is not above standby 5 W, so a "
                   "machine idling at its standby never finishes: using 6 W"),
        (3, 10, 5, "finish threshold 10 W must not be above the start "
                   "threshold 5 W, using 5 W"),
        (3, 2, 5, "finish threshold 2 W is below standby 3 W, kept as set"),
        (2, 2, 5, "finish threshold 2 W equals standby 2 W, kept as set"),
    ])
    def test_one_line_names_the_problem(self, hass, make_manager, make_device,
                                        standby, finish, start, expected):
        make_manager([flow_device(
            make_device, sd_standby_power=standby, sd_finish_power=finish,
            sd_power_threshold=start)])
        notes = self.sd_notes(hass)
        assert len(notes) == 1
        assert expected in notes[0]

    @pytest.mark.parametrize("standby, finish, start, using", [
        (6, 6, 5, ", using finish threshold 5 W instead of 6 W"),
        (5, 5, 5, ""),      # raised to 6, capped back to 5: unchanged
        (6, 2, 5, ""),      # below standby: kept
    ])
    def test_standby_at_or_above_start_names_the_standby(
            self, hass, make_manager, make_device, standby, finish, start,
            using):
        # The finish threshold cannot be both above standby and not above
        # the start threshold here: the standby power is what to fix.
        make_manager([flow_device(
            make_device, sd_standby_power=standby, sd_finish_power=finish,
            sd_power_threshold=start)])
        notes = self.sd_notes(hass)
        assert notes == [
            f"AURUM SD [Test Device]: standby {standby} W must be below "
            f"the start threshold {start} W{using}"]

    def test_consistent_config_logs_nothing(self, hass, make_manager,
                                            make_device):
        make_manager([flow_device(make_device, sd_finish_power=4)])
        assert self.sd_notes(hass) == []


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
            assert "Meist gleich dem Standby" not in text

    @pytest.mark.parametrize("path, gone, kept", [
        ("strings.json", "never draws less than its own standby",
         "Other values are used as set."),
        ("translations/en.json", "never draws less than its own standby",
         "Other values are used as set."),
        ("translations/de.json", "nie weniger als seinen Standby",
         "Andere Werte gelten wie eingestellt."),
    ])
    def test_finish_help_allows_a_value_below_standby(self, path, gone, kept):
        # A finish threshold below standby is used as set (a machine that
        # really idles lower): the help must not say it is pointless. Both
        # forms say so: existing users see only the edit form.
        data = json.loads((COMPONENT / path).read_text(encoding="utf-8"))
        steps = data["options"]["step"]
        for step in ("add_device", "edit_device"):
            text = steps[step]["data_description"]["sd_finish_power"]
            assert kept in text
            assert gone not in text
            assert "corrects other values" not in text
            assert "andere Werte korrigiert" not in text

    @pytest.mark.parametrize("path, rules", [
        ("strings.json", ("3W or more",
                          "a default (3W or 4W) below a higher standby")),
        ("translations/en.json", ("3W or more",
                                  "a default (3W or 4W) below a higher "
                                  "standby")),
        ("translations/de.json", ("ab 3W",
                                  "ein Standardwert (3W oder 4W) unter "
                                  "einem höheren Standby")),
    ])
    def test_finish_help_describes_which_values_are_raised(self, path, rules):
        # Equal to a standby of 3 W or more, or a stored default (old 3 W,
        # new 4 W) below a higher standby: the edit form shows the stored
        # value while standby + 1 W is used, so both forms must say so.
        data = json.loads((COMPONENT / path).read_text(encoding="utf-8"))
        steps = data["options"]["step"]
        for step in ("add_device", "edit_device"):
            text = steps[step]["data_description"]["sd_finish_power"]
            for rule in rules:
                assert rule in text, (step, rule)
            assert "standby + 1W" in text.replace("Standby", "standby")
