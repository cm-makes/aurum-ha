"""
Startup detection under Manual override (audit 2026-11-05 #7, override
half).

While the override is on AURUM sends no switch command, but the state
machine keeps watching the power: a program the user runs meanwhile is
adopted as RUNNING and its finish is detected. Before the fix the state
machine froze, so on release

(a) WAITING switched the plug off ('sd_waiting_enforce_off') and cut the
    program the user had resumed by hand,
(b) STANDBY read a program started under override as a new start and
    paused it mid-cycle,
(c) a program that had ended under override kept the plug off until the
    next surplus, then produced phantom 'running' / 'finished' pushes.
"""

from datetime import datetime, timedelta

from custom_components.aurum.const import (
    MODE_NORMAL,
    SD_STATE_RUNNING,
    SD_STATE_STANDBY,
    SD_STATE_WAITING,
    SCHED_REASON_EXCESS_SUFFICIENT,
    muss_heute_entity_id,
    override_entity_id,
)
from custom_components.aurum.modules.advisor import AdvisorManager
from custom_components.aurum.modules.persistence import PersistenceManager

SW = "switch.washer"
PW = "sensor.washer_power"
OV = override_entity_id("washer")
MH = muss_heute_entity_id("washer")
T0 = datetime(2026, 11, 15, 9, 0, 0)
TICK = 30


def shared(t, excess=0, soc=80):
    return {
        "now": t,
        "excess_for_devices": excess,
        "excess_raw_for_devices": excess,
        "grid_power_ema_asym": -excess,
        "battery_soc": soc,
        "battery_mode": MODE_NORMAL,
        "device_budget_w": None,
    }


def washer(make_manager, make_device, **kw):
    cfg = dict(name="Washer", switch_entity=SW, power_entity=PW,
               nominal_power=2000, startup_detection=True)
    cfg.update(kw)
    mgr = make_manager([make_device(**cfg)])
    return mgr, mgr.devices[0]


def run(mgr, hass, t, seconds, watts, excess=0):
    """Drive update() every TICK for `seconds` at a measured `watts`
    (the plug reads 0 W while it is off). Returns the next time and the
    last shared dict."""
    end = t + timedelta(seconds=seconds)
    sh = None
    while t < end:
        hass.states[PW] = str(watts)
        sh = shared(t, excess)
        mgr.update(sh)
        t += timedelta(seconds=TICK)
    return t, sh


def switch_cmds(hass):
    return [a for a in hass.actions if a[1] == SW]


def pushes(hass, needle):
    return [kw["message"] for svc, kw in hass.services
            if svc == "persistent_notification/create"
            and needle in kw.get("message", "")]


def to_waiting(mgr, hass, dev, t):
    """Plug on in standby, the user presses Start, AURUM pauses it."""
    t, _ = run(mgr, hass, t, 60, 1)
    t, _ = run(mgr, hass, t, 60, 2000)
    assert dev["sd_state"] == SD_STATE_WAITING
    assert hass.states[SW] == "off"
    return t


class TestReleaseDoesNotCutTheProgram:
    def test_a_resumed_waiting_program_runs_on_after_release(
            self, hass, make_manager, make_device):
        mgr, dev = washer(make_manager, make_device)
        t = to_waiting(mgr, hass, dev, T0)
        hass.actions.clear()

        # Manual: the user switches the plug on, the program resumes.
        hass.states[OV] = "on"
        hass.states[SW] = "on"
        t, _ = run(mgr, hass, t, 600, 2000)

        # Back to PV with no surplus: the program is not cut.
        hass.states[OV] = "off"
        t, _ = run(mgr, hass, t, 1800, 2000)
        assert ("OFF", SW) not in hass.actions
        assert hass.states[SW] == "on"
        assert dev["sd_state"] == SD_STATE_RUNNING

        # It ends as usual and the plug stays on for the next load.
        t, _ = run(mgr, hass, t, dev["sd_finish_time"] + 60, 1)
        assert dev["sd_state"] == SD_STATE_STANDBY
        assert switch_cmds(hass) == []
        assert len(pushes(hass, "finished")) == 1

    def test_b_program_started_under_override_is_not_paused(
            self, hass, make_manager, make_device):
        mgr, dev = washer(make_manager, make_device)
        t, _ = run(mgr, hass, T0, 7200, 1)      # standby, plug on
        assert dev["sd_state"] == SD_STATE_STANDBY
        hass.actions.clear()
        hass.services.clear()

        hass.states[OV] = "on"
        t, _ = run(mgr, hass, t, 900, 2000)     # started at the machine

        hass.states[OV] = "off"
        t, _ = run(mgr, hass, t, 900, 2000)
        assert switch_cmds(hass) == []
        assert pushes(hass, "detected") == []
        assert dev["sd_state"] == SD_STATE_RUNNING
        # Runtime counts the program (~30 min), not the standby before it.
        assert 25 * 60 <= dev["runtime_today_s"] <= 31 * 60

    def test_c_program_that_ended_under_override_leaves_plug_on(
            self, hass, make_manager, make_device):
        mgr, dev = washer(make_manager, make_device)
        t = to_waiting(mgr, hass, dev, T0)
        hass.actions.clear()
        hass.services.clear()

        hass.states[OV] = "on"
        hass.states[SW] = "on"
        t, _ = run(mgr, hass, t, 3600, 2000)    # the whole program ...
        t, _ = run(mgr, hass, t, 900, 1)        # ... and its end

        # Released at full surplus: no plug-off, no phantom program.
        hass.states[OV] = "off"
        t, _ = run(mgr, hass, t, 3600, 1, excess=5000)
        assert switch_cmds(hass) == []
        assert hass.states[SW] == "on"
        assert pushes(hass, "running now") == []
        assert len(pushes(hass, "finished")) == 1
        assert dev["sd_state"] == SD_STATE_STANDBY

        # The next load is detected and paused as usual.
        t, _ = run(mgr, hass, t, 60, 2000)
        assert dev["sd_state"] == SD_STATE_WAITING
        assert ("OFF", SW) in hass.actions


class TestOverrideNeverSwitches:
    def test_no_switch_command_while_override_is_on(
            self, hass, make_manager, make_device):
        mgr, dev = washer(make_manager, make_device,
                          deadline="10:00", estimated_runtime=120)
        t = to_waiting(mgr, hass, dev, T0)
        hass.actions.clear()
        hass.states[OV] = "on"
        hass.states[MH] = "on"                  # deadline is due

        # WAITING, plug off, surplus and deadline: nothing is started.
        t, _ = run(mgr, hass, t, 600, 0, excess=5000)
        assert dev["sd_state"] == SD_STATE_WAITING
        # Plug on, program not resumed yet: not switched off.
        hass.states[SW] = "on"
        t, _ = run(mgr, hass, t, 300, 1, excess=0)
        assert dev["sd_state"] == SD_STATE_WAITING
        # Resumed, runs past max_runtime, then a smart-finished program.
        t, _ = run(mgr, hass, t, dev["sd_max_runtime"] + 120, 2000)
        assert dev["sd_state"] == SD_STATE_STANDBY
        t, _ = run(mgr, hass, t, 1200, 1)
        t, _ = run(mgr, hass, t, 1800, 2000)
        t, _ = run(mgr, hass, t, 900, 1)
        assert dev["sd_state"] == SD_STATE_STANDBY
        # Plug switched off by the user in standby: not switched back on.
        hass.states[SW] = "off"
        t, _ = run(mgr, hass, t, 600, 0, excess=5000)

        assert switch_cmds(hass) == []

    def test_max_runtime_finish_keeps_the_rearm_hold(
            self, hass, make_manager, make_device):
        mgr, dev = washer(make_manager, make_device)
        t, _ = run(mgr, hass, T0, 60, 1)
        hass.states[OV] = "on"
        t, _ = run(mgr, hass, t, dev["sd_max_runtime"] + 120, 2000)
        # Finished by max_runtime while still drawing power: held, the
        # still-running program is not adopted as a second run.
        assert dev["sd_state"] == SD_STATE_STANDBY
        assert dev["sd_rearm_pending"] is True
        t, _ = run(mgr, hass, t, 1200, 2000)
        assert dev["sd_state"] == SD_STATE_STANDBY
        assert len(pushes(hass, "finished")) == 1

        # Released while the eco programme is still going: not paused.
        hass.actions.clear()
        hass.states[OV] = "off"
        t, _ = run(mgr, hass, t, 900, 2000)
        assert switch_cmds(hass) == []

    def test_unknown_power_is_not_a_program_start(
            self, hass, make_manager, make_device):
        mgr, dev = washer(make_manager, make_device)
        t, _ = run(mgr, hass, T0, 60, 1)
        hass.states[OV] = "on"
        t, _ = run(mgr, hass, t, 600, "unavailable")
        assert dev["sd_state"] == SD_STATE_STANDBY

    def test_waiting_program_that_never_resumed_stays_paused(
            self, hass, make_manager, make_device):
        # The plug was on under override but the program did not run:
        # it is still pending, so the release pauses it as before.
        mgr, dev = washer(make_manager, make_device)
        t = to_waiting(mgr, hass, dev, T0)
        hass.states[OV] = "on"
        hass.states[SW] = "on"
        t, _ = run(mgr, hass, t, 600, 1)
        assert dev["sd_state"] == SD_STATE_WAITING
        hass.states[OV] = "off"
        t, _ = run(mgr, hass, t, 60, 1)
        assert dev["sd_state"] == SD_STATE_WAITING
        assert hass.states[SW] == "off"


class TestAdoptedRun:
    def test_advisor_shows_plain_running(
            self, hass, make_manager, make_device):
        mgr, dev = washer(make_manager, make_device)
        t, _ = run(mgr, hass, T0, 60, 1)
        # Left over from an earlier PV run (a finish keeps the reason).
        dev["_scheduling_reason"] = SCHED_REASON_EXCESS_SUFFICIENT
        hass.states[OV] = "on"
        t, sh = run(mgr, hass, t, 300, 2000)

        ds = sh["device_states"][0]
        assert ds["state"] == SD_STATE_RUNNING
        assert ds["force_started"] is False
        assert ds["scheduling_reason"] is None
        view = AdvisorManager(hass, {}).update(sh)
        assert view["devices"][0]["reason"] == "running"
        assert view["decision"] == "running"

    def test_adopted_run_survives_a_restart(
            self, hass, make_manager, make_device, tmp_path):
        sf = str(tmp_path / "state.json")
        mgr, dev = washer(make_manager, make_device)
        t = datetime.now().replace(microsecond=0) - timedelta(minutes=30)
        t, _ = run(mgr, hass, t, 60, 1)
        hass.states[OV] = "on"
        t, _ = run(mgr, hass, t, 600, 2000)
        assert dev["sd_state"] == SD_STATE_RUNNING
        PersistenceManager(hass, {"state_file": sf}).save(mgr)

        mgr2, dev2 = washer(make_manager, make_device)
        PersistenceManager(hass, {"state_file": sf}).restore(mgr2)
        assert dev2["sd_state"] == SD_STATE_RUNNING
        hass.actions.clear()
        hass.states[OV] = "off"
        t, _ = run(mgr2, hass, t, 600, 2000)
        assert dev2["sd_state"] == SD_STATE_RUNNING
        t, _ = run(mgr2, hass, t, dev2["sd_finish_time"] + 60, 1)
        assert dev2["sd_state"] == SD_STATE_STANDBY
        assert switch_cmds(hass) == []
