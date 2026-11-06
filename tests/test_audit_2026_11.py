"""
Regression tests for the 2026-11-05 audit fixes (v1.15.4).

- Deadline force-start honours the runtime already done today and ends
  once the daily target is met (muss_heute auto-resets).
- Startup detection does not re-detect and pause a program that is still
  running after a max_runtime / premature smart finish.
- battery_priority: battery discharge counts as a deficit.
- _scheduling_reason survives the daily reset and an HA restart while
  the device is running.
- Power / energy / price sensors are converted by unit_of_measurement.
"""

import json
from datetime import datetime, timedelta

from custom_components.aurum.const import (
    MODE_NORMAL,
    SD_STATE_RUNNING,
    SD_STATE_STANDBY,
    SD_STATE_WAITING,
    muss_heute_entity_id,
)
from custom_components.aurum.modules.energy import EnergyManager
from custom_components.aurum.modules.helpers import (
    get_energy_kwh,
    get_power_w,
    get_price_ct,
)
from custom_components.aurum.modules.persistence import PersistenceManager

SW = "switch.test_device"
MH = muss_heute_entity_id("test_device")
TICK = 30


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


def deadline_device(make_device, **kw):
    base = dict(deadline="18:00", estimated_runtime=60, debounce_on=0)
    base.update(kw)
    return make_device(**base)


# ══════════════════════════════════════════════════════════════════
#  Deadline force-start
# ══════════════════════════════════════════════════════════════════


class TestDeadlineRemainingRuntime:
    def test_no_force_start_when_target_already_met_on_pv(
            self, hass, make_manager, make_device):
        mgr = make_manager([deadline_device(make_device)])
        dev = mgr.devices[0]
        dev["runtime_today_s"] = 185 * 60      # ran 3x the target on PV
        hass.states[SW] = "off"
        hass.states[MH] = "on"

        mgr.update(shared(datetime(2026, 11, 5, 16, 55), -500))

        assert ("ON", SW) not in hass.actions
        assert hass.states[MH] == "off"        # auto-reset, target met

    def test_window_uses_remaining_runtime(
            self, hass, make_manager, make_device):
        mgr = make_manager([deadline_device(make_device)])
        dev = mgr.devices[0]
        dev["runtime_today_s"] = 30 * 60       # 30 of 60 min done
        hass.states[MH] = "on"

        # 40 min left > 30 min missing + 5 min buffer → not yet.
        assert mgr._deadline_urgent(dev, datetime(2026, 11, 5, 17, 20)) is False
        # 34 min left ≤ 35 → start now.
        assert mgr._deadline_urgent(dev, datetime(2026, 11, 5, 17, 26)) is True

    def test_forced_run_ends_when_target_reached(
            self, hass, make_manager, make_device):
        mgr = make_manager([deadline_device(make_device)])
        dev = mgr.devices[0]
        hass.states[SW] = "off"
        hass.states[MH] = "on"

        t = datetime(2026, 11, 5, 16, 50)
        end = datetime(2026, 11, 5, 19, 30)
        while t < end:
            mgr.update(shared(t, -1000))        # importing all evening
            t += timedelta(seconds=TICK)

        assert ("ON", SW) in hass.actions
        assert hass.states[SW] == "off"        # not held until midnight
        assert dev["force_started"] is False
        assert hass.states[MH] == "off"
        # Ran its 60 min target (plus at most the debounce_off tail).
        assert 60 * 60 <= dev["runtime_today_s"] <= 75 * 60

    def test_second_load_armed_later_gets_a_full_run(
            self, hass, make_manager, make_device):
        # Regular (unmetered) washer: plug was on 188 min on PV this
        # morning. Switching muss_heute on at 13:00 for a second load asks
        # for a full run; it must not be cancelled by the morning runtime.
        mgr = make_manager([deadline_device(make_device, estimated_runtime=120)])
        dev = mgr.devices[0]
        dev["runtime_today_s"] = 188 * 60
        hass.states[SW] = "off"
        hass.states[MH] = "off"
        mgr.update(shared(datetime(2026, 11, 5, 12, 59), -500))
        hass.states[MH] = "on"

        t = datetime(2026, 11, 5, 13, 0)
        started = None
        while t < datetime(2026, 11, 5, 17, 0):
            mgr.update(shared(t, -500))
            if started is None and hass.states[SW] == "on":
                started = t
            t += timedelta(seconds=TICK)

        assert started is not None
        assert datetime(2026, 11, 5, 15, 50) <= started <= datetime(2026, 11, 5, 16, 0)

    def test_armed_before_day_start_hour_counts_next_cycle(
            self, hass, make_manager, make_device):
        # day_start_hour=9: at 07:30 the 90 min still belong to yesterday's
        # cycle. Arming muss_heute then must not reset it at once.
        mgr = make_manager([deadline_device(make_device, day_start_hour=9)])
        dev = mgr.devices[0]
        hass.states[SW] = "off"
        hass.states[MH] = "off"
        t = datetime(2026, 11, 5, 7, 29)
        mgr.daily_reset(t)
        dev["runtime_today_s"] = 90 * 60
        mgr.update(shared(t, -500))
        hass.states[MH] = "on"

        t = datetime(2026, 11, 5, 7, 30)
        started = None
        while t < datetime(2026, 11, 5, 17, 30):
            mgr.daily_reset(t)
            mgr.update(shared(t, -500))
            if started is None and hass.states[SW] == "on":
                started = t
            t += timedelta(seconds=TICK)

        assert started is not None
        assert datetime(2026, 11, 5, 16, 50) <= started <= datetime(2026, 11, 5, 17, 0)

    def test_switching_muss_heute_off_ends_force_start_immunity(
            self, hass, make_manager, make_device):
        mgr = make_manager([deadline_device(make_device)])
        dev = mgr.devices[0]
        hass.states[SW] = "off"
        hass.states[MH] = "on"
        mgr.update(shared(datetime(2026, 11, 5, 16, 56), -1000))
        assert dev["force_started"] is True

        hass.states[MH] = "off"                # user cancels the job
        mgr.update(shared(datetime(2026, 11, 5, 16, 57), -1000))
        assert dev["force_started"] is False

    def test_arm_after_last_save_survives_restart(
            self, hass, make_manager, make_device, tmp_path):
        # Saved with muss_heute off; the user arms it, HA restarts before
        # the next save. The restored OFF state makes the arm an edge.
        sf = str(tmp_path / "state.json")
        cfg = deadline_device(make_device)
        mgr = make_manager([cfg])
        dev = mgr.devices[0]
        hass.states[SW] = "off"
        hass.states[MH] = "off"
        dev["runtime_today_s"] = 245 * 60       # earlier PV runs today
        mgr.update(shared(datetime.now().replace(hour=15, minute=0), -500))
        PersistenceManager(hass, {"state_file": sf}).save(mgr)

        hass.states[MH] = "on"                  # armed, then restart
        mgr2 = make_manager([cfg])
        PersistenceManager(hass, {"state_file": sf}).restore(mgr2)
        mgr2.update(shared(datetime.now().replace(hour=15, minute=5), -500))

        assert hass.states[MH] == "on"          # job not cancelled
        assert mgr2._muss_heute_job_runtime_s(mgr2.devices[0]) == 0

    def test_rearm_right_after_auto_reset_is_a_new_job(
            self, hass, make_manager, make_device):
        mgr = make_manager([deadline_device(make_device)])
        dev = mgr.devices[0]
        hass.states[SW] = "off"
        hass.states[MH] = "on"
        dev["runtime_today_s"] = 61 * 60
        mgr.update(shared(datetime(2026, 11, 5, 11, 5), 2000))
        assert hass.states[MH] == "off"         # job done → auto-reset

        hass.states[MH] = "on"                  # re-armed within one cycle
        mgr.update(shared(datetime(2026, 11, 5, 11, 5, 30), 2000))
        assert hass.states[MH] == "on"
        assert dev["_mh_runtime_base"] == dev["runtime_today_s"]

    def test_daily_reset_carries_open_job(
            self, hass, make_manager, make_device):
        mgr = make_manager([deadline_device(make_device)])
        dev = mgr.devices[0]
        hass.states[MH] = "on"
        hass.states[SW] = "off"
        dev["runtime_today_s"] = 100 * 60
        dev["_mh_runtime_base"] = 60 * 60        # 40 min of the job done
        mgr.daily_reset()
        assert dev["runtime_today_s"] == 0
        assert mgr._muss_heute_job_runtime_s(dev) == 40 * 60

    def test_stop_after_runtime_window_uses_daily_remainder(
            self, hass, make_manager, make_device):
        # Pool pump: daily target 400 min, 214 min ran on PV before the
        # arm. The cap stops it after 186 more min, so the window opens
        # for 186 (+5) min, not for the full 400-min job.
        mgr = make_manager([deadline_device(
            make_device, estimated_runtime=400, stop_after_runtime=True)])
        dev = mgr.devices[0]
        dev["runtime_today_s"] = 214 * 60
        dev["_mh_runtime_base"] = 214 * 60
        dev["_mh_prev"] = True
        hass.states[MH] = "on"
        assert mgr._deadline_urgent(dev, datetime(2026, 11, 5, 12, 0)) is False
        assert mgr._deadline_urgent(dev, datetime(2026, 11, 5, 14, 55)) is True

    def test_sd_deadline_ignores_runtime_done(
            self, hass, make_manager, make_device):
        mgr = make_manager([deadline_device(
            make_device, startup_detection=True)])
        dev = mgr.devices[0]
        dev["runtime_today_s"] = 120 * 60      # earlier program today
        hass.states[MH] = "on"                 # re-armed for a 2nd program

        assert mgr._deadline_urgent(dev, datetime(2026, 11, 5, 17, 0)) is True


# ══════════════════════════════════════════════════════════════════
#  Startup detection: no re-detection of a still-running program
# ══════════════════════════════════════════════════════════════════


class TestSdRearm:
    def _finished_by_max_runtime(self, hass, make_manager, make_device, now):
        mgr = make_manager([make_device(
            startup_detection=True, power_entity="sensor.washer_power")])
        dev = mgr.devices[0]
        dev["sd_state"] = SD_STATE_RUNNING
        dev["sd_running_since"] = now - timedelta(hours=3)
        dev["sd_lockout_until"] = now - timedelta(seconds=1)
        hass.states[SW] = "on"
        mgr._handle_startup_detection(
            dev, 0, 80, actual_power=800, now=now, excess=0)
        assert dev["sd_state"] == SD_STATE_STANDBY
        assert dev["sd_rearm_pending"] is True
        return mgr, dev

    def test_still_running_program_is_not_paused(
            self, hass, make_manager, make_device, now):
        mgr, dev = self._finished_by_max_runtime(
            hass, make_manager, make_device, now)
        hass.actions.clear()

        for s in range(1, 1800, 15):           # 30 more min at 800 W
            mgr._handle_startup_detection(
                dev, 0, 80, actual_power=800,
                now=now + timedelta(seconds=s), excess=0)

        assert dev["sd_state"] == SD_STATE_STANDBY
        assert ("OFF", SW) not in hass.actions

    def test_rearms_after_power_stays_at_standby(
            self, hass, make_manager, make_device, now):
        mgr, dev = self._finished_by_max_runtime(
            hass, make_manager, make_device, now)

        t = now + timedelta(seconds=60)
        mgr._handle_startup_detection(dev, 0, 80, actual_power=1, now=t, excess=0)
        t += timedelta(seconds=dev["sd_finish_time"])
        mgr._handle_startup_detection(dev, 0, 80, actual_power=1, now=t, excess=0)
        assert dev["sd_rearm_pending"] is False

        # Next program is detected and paused as usual.
        t += timedelta(seconds=60)
        mgr._handle_startup_detection(dev, 0, 80, actual_power=800, now=t, excess=0)
        t += timedelta(seconds=dev["sd_detection_time"] + 1)
        mgr._handle_startup_detection(dev, 0, 80, actual_power=800, now=t, excess=0)
        assert dev["sd_state"] == SD_STATE_WAITING

    def test_max_runtime_finish_during_a_pause_still_holds(
            self, hass, make_manager, make_device, now):
        mgr = make_manager([make_device(
            startup_detection=True, power_entity="sensor.washer_power")])
        dev = mgr.devices[0]
        dev["sd_state"] = SD_STATE_RUNNING
        dev["sd_running_since"] = now - timedelta(hours=3)
        dev["sd_lockout_until"] = now - timedelta(seconds=1)
        hass.states[SW] = "on"
        # The finish tick lands in a drum pause (2 W) ...
        mgr._handle_startup_detection(dev, 0, 80, actual_power=2, now=now, excess=0)
        assert dev["sd_rearm_pending"] is True
        hass.actions.clear()
        # ... and the program goes on drawing power.
        for sec in range(30, 600, 30):
            mgr._handle_startup_detection(
                dev, 0, 80, actual_power=2000,
                now=now + timedelta(seconds=sec), excess=0)
        assert ("OFF", SW) not in hass.actions
        assert dev["sd_state"] == SD_STATE_STANDBY

    def test_skipped_cycles_do_not_count_as_quiet_time(
            self, hass, make_manager, make_device, now):
        mgr, dev = self._finished_by_max_runtime(
            hass, make_manager, make_device, now)
        mgr._handle_startup_detection(
            dev, 0, 80, actual_power=2, now=now + timedelta(seconds=30), excess=0)
        assert dev["_sd_rearm_below_since"] is not None
        # 20 min of battery-charging emergency: the SD machine is skipped.
        sh = shared(now + timedelta(minutes=20), 0)
        sh["battery_mode"] = "charging"
        mgr.update(sh)
        assert dev["_sd_rearm_below_since"] is None

    def test_plug_off_drops_the_hold(
            self, hass, make_manager, make_device, now):
        mgr, dev = self._finished_by_max_runtime(
            hass, make_manager, make_device, now)
        hass.states[SW] = "off"                 # e.g. disabled overnight
        mgr._handle_startup_detection(
            dev, 0, 80, actual_power=0, now=now + timedelta(hours=8), excess=0)
        assert dev["sd_rearm_pending"] is False

    def test_program_started_right_after_smart_finish_is_detected(
            self, hass, make_manager, make_device, now):
        # Back-to-back loads: a smart finish has already seen standby for
        # sd_finish_time, so the next program must be detected at once.
        mgr = make_manager([make_device(
            startup_detection=True, power_entity="sensor.washer_power")])
        dev = mgr.devices[0]
        dev["sd_state"] = SD_STATE_RUNNING
        dev["sd_running_since"] = now - timedelta(hours=1)
        dev["sd_lockout_until"] = now + timedelta(hours=2)
        dev["sd_power_below_since"] = now - timedelta(
            seconds=dev["sd_finish_time"] + 1)
        hass.states[SW] = "on"
        mgr._handle_startup_detection(dev, 0, 80, actual_power=1, now=now, excess=0)
        assert dev["sd_state"] == SD_STATE_STANDBY
        assert dev["sd_rearm_pending"] is False

        t = now + timedelta(minutes=5)          # user starts load 2
        mgr._handle_startup_detection(dev, 0, 80, actual_power=2000, now=t, excess=0)
        t += timedelta(seconds=dev["sd_detection_time"] + 1)
        mgr._handle_startup_detection(dev, 0, 80, actual_power=2000, now=t, excess=0)
        assert dev["sd_state"] == SD_STATE_WAITING

    def test_no_hold_without_power_sensor(
            self, hass, make_manager, make_device, now):
        # Without a power sensor the reading is the nominal fallback and can
        # never drop to standby: a hold would latch the plug on for good.
        mgr = make_manager([make_device(startup_detection=True)])
        dev = mgr.devices[0]
        dev["sd_state"] = SD_STATE_RUNNING
        dev["sd_running_since"] = now - timedelta(hours=3)
        dev["sd_lockout_until"] = now - timedelta(seconds=1)
        hass.states[SW] = "on"
        mgr._handle_startup_detection(
            dev, 0, 80, actual_power=1000, now=now, excess=0)
        assert dev["sd_rearm_pending"] is False


# ══════════════════════════════════════════════════════════════════
#  battery_priority: discharge is a deficit
# ══════════════════════════════════════════════════════════════════


def _energy(hass, **cfg):
    base = {
        "grid_power_entity": "sensor.grid",
        "battery_charge_power_entity": "sensor.bat_charge",
        "battery_discharge_power_entity": "sensor.bat_discharge",
        "battery_priority": True,
    }
    base.update(cfg)
    return EnergyManager(hass, base)


class TestBatteryPriorityDischarge:
    def test_discharge_counts_as_deficit(self, hass):
        hass.states.update({"sensor.grid": "0", "sensor.bat_charge": "0",
                            "sensor.bat_discharge": "2000"})
        sh = {}
        _energy(hass).update(sh)
        assert sh["excess_raw"] == -2000
        assert sh["excess"] == -2000

    def test_charge_still_not_surplus(self, hass):
        hass.states.update({"sensor.grid": "-500", "sensor.bat_charge": "3000",
                            "sensor.bat_discharge": "0"})
        sh = {}
        _energy(hass).update(sh)
        assert sh["excess_raw"] == 500           # only real export

    def test_legacy_mode_unchanged(self, hass):
        hass.states.update({"sensor.grid": "-500", "sensor.bat_charge": "3000",
                            "sensor.bat_discharge": "0"})
        sh = {}
        _energy(hass, battery_priority=False).update(sh)
        assert sh["excess_raw"] == 3500


# ══════════════════════════════════════════════════════════════════
#  _scheduling_reason across daily reset and restart
# ══════════════════════════════════════════════════════════════════


class TestSchedulingReasonKept:
    def test_daily_reset_keeps_reason_of_running_device(
            self, hass, make_manager, make_device):
        mgr = make_manager([
            make_device(name="Pump", switch_entity="switch.pump"),
            make_device(name="Heater", switch_entity="switch.heater"),
        ])
        pump, heater = mgr.devices
        hass.states["switch.pump"] = "on"
        hass.states["switch.heater"] = "off"
        pump["_scheduling_reason"] = "cheap_grid"
        heater["_scheduling_reason"] = "cheap_grid"

        mgr.daily_reset()

        assert pump["_scheduling_reason"] == "cheap_grid"
        assert heater["_scheduling_reason"] is None

    def test_restart_restores_reason_only_when_switch_on(
            self, hass, make_manager, make_device, tmp_path):
        sf = str(tmp_path / "state.json")
        cfgs = [make_device(name="Pump", switch_entity="switch.pump"),
                make_device(name="Heater", switch_entity="switch.heater")]
        mgr = make_manager(cfgs)
        for d in mgr.devices:
            d["_scheduling_reason"] = "cheap_grid"
        hass.states["switch.pump"] = "on"
        hass.states["switch.heater"] = "on"
        PersistenceManager(hass, {"state_file": sf}).save(mgr)

        hass.states["switch.heater"] = "off"   # turned off during restart
        mgr2 = make_manager(cfgs)
        PersistenceManager(hass, {"state_file": sf}).restore(mgr2)

        assert mgr2.devices[0]["_scheduling_reason"] == "cheap_grid"
        assert mgr2.devices[1]["_scheduling_reason"] is None

    def test_force_started_does_not_survive_rollover(
            self, hass, make_manager, make_device, tmp_path):
        sf = str(tmp_path / "state.json")
        yesterday = datetime.now() - timedelta(days=1, hours=1)
        with open(sf, "w") as f:
            json.dump({
                "_meta": {"saved_at": yesterday.isoformat()},
                "Test Device": {"force_started": True, "runtime_today_s": 99},
            }, f)
        hass.states[SW] = "on"
        mgr = make_manager([make_device()])
        PersistenceManager(hass, {"state_file": sf}).restore(mgr)
        assert mgr.devices[0]["force_started"] is False
        assert mgr.devices[0]["runtime_today_s"] == 0


# ══════════════════════════════════════════════════════════════════
#  Units
# ══════════════════════════════════════════════════════════════════


class TestUnits:
    def _set(self, hass, entity, value, unit):
        hass.states[entity] = value
        hass.attributes = getattr(hass, "attributes", {})
        hass.attributes[entity] = {"unit_of_measurement": unit}

    def test_power(self, hass):
        self._set(hass, "sensor.p", "1.5", "kW")
        assert get_power_w(hass, "sensor.p") == 1500
        self._set(hass, "sensor.p", "1500", "W")
        assert get_power_w(hass, "sensor.p") == 1500
        self._set(hass, "sensor.p", "1500", None)      # unknown → as-is
        assert get_power_w(hass, "sensor.p") == 1500
        self._set(hass, "sensor.p", "unavailable", "kW")
        assert get_power_w(hass, "sensor.p", 7) == 7    # default unscaled

    def test_energy(self, hass):
        self._set(hass, "sensor.e", "12500", "Wh")
        assert get_energy_kwh(hass, "sensor.e") == 12.5
        self._set(hass, "sensor.e", "12.5", "kWh")
        assert get_energy_kwh(hass, "sensor.e") == 12.5

    def test_price(self, hass):
        self._set(hass, "sensor.price", "0.2512", "EUR/kWh")
        assert abs(get_price_ct(hass, "sensor.price") - 25.12) < 1e-9
        self._set(hass, "sensor.price", "25.12", "ct/kWh")
        assert get_price_ct(hass, "sensor.price") == 25.12

    def test_device_power_sensor_in_kw(self, hass, make_manager, make_device):
        mgr = make_manager([make_device(power_entity="sensor.dev_power")])
        self._set(hass, "sensor.dev_power", "0.8", "kW")
        assert mgr._get_device_power(mgr.devices[0]) == 800

    def test_eur_price_meets_ct_max_price(self, hass):
        from custom_components.aurum.modules.pricing import PricingManager
        self._set(hass, "sensor.price", "0.28", "EUR/kWh")
        pm = PricingManager(hass, {"price_entity": "sensor.price"})
        sh = {}
        pm.update(sh)
        pm.snapshot(sh)
        assert sh["current_price"] == 28
        dev = {"price_mode": "cheap_grid", "max_price": 28}
        assert pm.is_price_ok(dev) is True
        dev["max_price"] = 27
        assert pm.is_price_ok(dev) is False

    def test_pv_actual_today_in_mwh(self, hass):
        from custom_components.aurum.modules.budget import BudgetManager
        bm = BudgetManager(hass, {"pv_actual_today_entity": "sensor.pv_total"})
        self._set(hass, "sensor.pv_total", "25.312", "MWh")   # lifetime
        assert bm._get_pv_today_kwh() == 0.0                  # snapshot taken
        self._set(hass, "sensor.pv_total", "25.320", "MWh")
        assert abs(bm._get_pv_today_kwh() - 8.0) < 1e-6

    def test_old_mwh_snapshot_is_replaced(self, hass):
        from custom_components.aurum.modules.budget import BudgetManager
        bm = BudgetManager(hass, {"pv_actual_today_entity": "sensor.pv_total"})
        bm._pv_total_midnight = 150.2           # saved by 1.15.3 in MWh
        self._set(hass, "sensor.pv_total", "150.215", "MWh")
        assert bm._get_pv_today_kwh() == 0.0     # re-snapshot, not 150 MWh
        self._set(hass, "sensor.pv_total", "150.223", "MWh")
        assert abs(bm._get_pv_today_kwh() - 8.0) < 1e-6

    def test_pv_forecast_in_wh(self, hass):
        from custom_components.aurum.modules.budget import BudgetManager
        bm = BudgetManager(hass, {"pv_forecast_entity": "sensor.fc",
                                  "target_soc": 90,
                                  "battery_capacity_wh": 10000})
        self._set(hass, "sensor.fc", "12500", "Wh")
        sh = {"now": datetime(2026, 11, 5, 10, 0), "battery_soc": 50}
        bm.update(sh)
        assert sh["pv_forecast_remaining_kwh"] == 12.5

    def test_grid_sensor_in_kw_drives_surplus_in_w(self, hass):
        self._set(hass, "sensor.grid", "-2.0", "kW")
        sh = {}
        EnergyManager(hass, {"grid_power_entity": "sensor.grid"}).update(sh)
        assert sh["excess_raw"] == 2000
