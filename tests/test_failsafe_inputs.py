"""
Regression tests for the fail-safe input handling (v1.16.0).

- Hub inputs: NaN/inf readings, short dropouts, unavailable and stale
  (frozen) grid/PV sensors, battery power sensors, unknown SOC.
- Devices while the surplus is unknown: no surplus starts, surplus runs
  released after debounce_off; price, deadline and user runs continue.
- Unknown SOC: no min_soc emergency, no SOC-based shedding.
- Unavailable switches: no commands, no allocation, frozen SD machine.
- Unavailable SD power sensor: no phantom detection, no false finish.
- Restore with a switch that has not loaded yet.
- Price outage hold is bounded.
- Advisor, coordinator startup guard, repair issues, restart helpers.
"""

import math
import sys
import types
from datetime import datetime, timedelta

import pytest

from custom_components.aurum.const import (
    INPUT_OK,
    INPUT_STALE,
    INPUT_UNAVAILABLE,
    MODE_CHARGING,
    MODE_LOW_SOC,
    MODE_NORMAL,
    SD_STATE_RUNNING,
    SD_STATE_STANDBY,
    SD_STATE_WAITING,
    muss_heute_entity_id,
)
from custom_components.aurum.modules.battery import BatteryManager
from custom_components.aurum.modules.energy import EnergyManager
from custom_components.aurum.modules.helpers import (
    ema_update,
    ema_update_asymmetric,
    get_float,
)
from custom_components.aurum.modules.persistence import PersistenceManager
from custom_components.aurum.modules.pricing import (
    PRICE_OUTAGE_HOLD_S,
    PricingManager,
)

from conftest import FakePricing

SW = "switch.test_device"
MH = muss_heute_entity_id("test_device")
GRID = "sensor.grid"
T0 = datetime(2026, 11, 7, 12, 0, 0)


def dev_shared(now, excess, soc=80, blind=False, mode=MODE_NORMAL):
    return {
        "now": now,
        "excess_for_devices": excess,
        "excess_raw_for_devices": excess,
        "grid_power_ema_asym": -excess,
        "battery_soc": soc,
        "battery_mode": mode,
        "device_budget_w": None,
        "surplus_blind": blind,
    }


def run(mgr, start, minutes, shared_fn, step=30):
    """Run device cycles every `step` s for `minutes`."""
    t = start
    end = start + timedelta(minutes=minutes)
    while t <= end:
        mgr.update(shared_fn(t))
        t += timedelta(seconds=step)
    return t


def energy(hass, **cfg):
    base = {"grid_power_entity": GRID, "update_interval": 15}
    base.update(cfg)
    return EnergyManager(hass, base)


def tick(em, now):
    sh = {"now": now}
    em.update(sh)
    return sh


def running(dev, now, reason="surplus_available"):
    dev["managed_on"] = True
    dev["on_since"] = now - timedelta(hours=1)
    dev["_runtime_tick"] = now
    dev["_scheduling_reason"] = reason


# ══════════════════════════════════════════════════════════════════
#  Readings: NaN / inf
# ══════════════════════════════════════════════════════════════════


class TestNonFinite:
    @pytest.mark.parametrize("raw", ["nan", "NaN", "inf", "-inf", "1e999"])
    def test_get_float_rejects(self, hass, raw):
        hass.states["sensor.x"] = raw
        assert get_float(hass, "sensor.x", default=None) is None

    def test_ema_recovers_from_a_non_finite_value(self):
        assert ema_update(float("nan"), 400.0) == 400.0
        assert ema_update_asymmetric(float("inf"), 400.0) == 400.0

    def test_one_nan_grid_sample_does_not_poison_the_surplus(self, hass):
        em = energy(hass)
        hass.states[GRID] = "400"
        tick(em, T0)
        hass.states[GRID] = "nan"
        tick(em, T0 + timedelta(seconds=15))
        hass.states[GRID] = "400"
        sh = tick(em, T0 + timedelta(seconds=30))
        assert math.isfinite(sh["excess"])
        assert sh["excess"] == -400.0


# ══════════════════════════════════════════════════════════════════
#  Grid meter: dropout, unavailable, stale, recovery
# ══════════════════════════════════════════════════════════════════


class TestGridHealth:
    def test_short_dropout_is_bridged(self, hass):
        em = energy(hass)
        hass.states[GRID] = "-2000"
        tick(em, T0)
        hass.states[GRID] = "unavailable"
        sh = tick(em, T0 + timedelta(seconds=45))
        assert sh["surplus_blind"] is False
        assert sh["grid_power_raw"] == -2000
        assert sh["input_health"]["grid"] == INPUT_OK

    def test_outage_beyond_the_hold_makes_the_surplus_unknown(self, hass):
        em = energy(hass)
        hass.states[GRID] = "-2000"
        tick(em, T0)
        hass.states[GRID] = "unavailable"
        tick(em, T0 + timedelta(seconds=15))
        sh = tick(em, T0 + timedelta(seconds=90))
        assert sh["surplus_blind"] is True
        assert sh["excess"] == 0.0 and sh["excess_raw"] == 0.0
        assert sh["input_health"]["grid"] == INPUT_UNAVAILABLE
        fault = sh["input_faults"][0]
        assert fault["input"] == "grid" and fault["entity"] == GRID
        assert fault["since"] == T0 + timedelta(seconds=90)

    def test_never_seen_grid_is_unavailable_at_once(self, hass):
        sh = tick(energy(hass), T0)
        assert sh["surplus_blind"] is True

    def test_frozen_grid_value_is_stale(self, hass):
        em = energy(hass, sensor_timeout=10)
        hass.states[GRID] = "-2000"
        hass.ages[GRID] = 30
        assert tick(em, T0)["surplus_blind"] is False
        hass.ages[GRID] = 601
        sh = tick(em, T0 + timedelta(minutes=10))
        assert sh["surplus_blind"] is True
        assert sh["input_health"]["grid"] == INPUT_STALE

    def test_zero_reading_is_not_age_checked(self, hass):
        # Zero-export inverter: the meter may sit at 0 W for hours.
        em = energy(hass, sensor_timeout=10)
        hass.states[GRID] = "0"
        hass.ages[GRID] = 7200
        assert tick(em, T0)["surplus_blind"] is False

    def test_timeout_zero_turns_the_age_check_off(self, hass):
        em = energy(hass, sensor_timeout=0)
        hass.states[GRID] = "-2000"
        hass.ages[GRID] = 7200
        assert tick(em, T0)["surplus_blind"] is False

    def test_stale_value_is_not_used_to_bridge_a_later_dropout(self, hass):
        em = energy(hass, sensor_timeout=10)
        hass.states[GRID] = "-2000"
        hass.ages[GRID] = 601
        tick(em, T0)
        hass.states[GRID] = "unavailable"
        sh = tick(em, T0 + timedelta(seconds=15))
        assert sh["surplus_blind"] is True

    def test_recovery_restarts_the_emas(self, hass):
        em = energy(hass)
        hass.states[GRID] = "-2000"
        for s in range(0, 300, 15):
            tick(em, T0 + timedelta(seconds=s))
        hass.states[GRID] = "unavailable"
        tick(em, T0 + timedelta(seconds=300))
        tick(em, T0 + timedelta(seconds=400))
        hass.states[GRID] = "3000"
        sh = tick(em, T0 + timedelta(seconds=415))
        # Fresh start, not 0.2 * 3000 + 0.8 * -2000 = -1000 W import.
        assert sh["excess"] == -3000.0
        assert sh["input_health"]["grid"] == INPUT_OK

    def test_grid_outage_while_battery_charges_from_grid(self, hass):
        # Audit #40: legacy formula turned the charge power into surplus.
        em = energy(hass, battery_charge_power_entity="sensor.bc",
                    battery_discharge_power_entity="sensor.bd")
        hass.states["sensor.bc"] = "3000"
        hass.states["sensor.bd"] = "0"
        hass.states[GRID] = "3500"
        tick(em, T0)
        hass.states[GRID] = "unavailable"
        tick(em, T0 + timedelta(seconds=15))
        sh = tick(em, T0 + timedelta(seconds=120))
        assert sh["surplus_blind"] is True
        assert sh["excess"] == 0.0

    def test_battery_power_sensor_outage_makes_the_surplus_unknown(
            self, hass):
        em = energy(hass, battery_charge_power_entity="sensor.bc")
        hass.states[GRID] = "-500"
        hass.states["sensor.bc"] = "1500"
        tick(em, T0)
        hass.states["sensor.bc"] = "unavailable"
        tick(em, T0 + timedelta(seconds=15))
        sh = tick(em, T0 + timedelta(seconds=120))
        assert sh["surplus_blind"] is True
        assert sh["input_health"]["battery_charge"] == INPUT_UNAVAILABLE


class TestPvHealth:
    def test_frozen_daytime_pv_counts_as_zero(self, hass):
        em = energy(hass, pv_power_entity="sensor.pv", sensor_timeout=10)
        hass.states[GRID] = "0"
        hass.states["sensor.pv"] = "3000"
        hass.ages["sensor.pv"] = 700
        sh = tick(em, T0)
        assert sh["pv_power"] == 0
        assert sh["input_health"]["pv"] == INPUT_STALE
        assert sh["surplus_blind"] is False   # PV is not a surplus term

    def test_pv_at_zero_overnight_is_healthy(self, hass):
        em = energy(hass, pv_power_entity="sensor.pv", sensor_timeout=10)
        hass.states[GRID] = "300"
        hass.states["sensor.pv"] = "0"
        hass.ages["sensor.pv"] = 36000
        assert tick(em, T0)["input_health"]["pv"] == INPUT_OK


# ══════════════════════════════════════════════════════════════════
#  SOC unknown
# ══════════════════════════════════════════════════════════════════


class TestSocUnknown:
    def _em(self, hass):
        hass.states[GRID] = "0"
        return energy(hass, battery_soc_entity="sensor.soc")

    def test_never_seen_soc_is_unknown_not_zero(self, hass):
        sh = tick(self._em(hass), T0)
        assert sh["battery_soc"] is None
        BatteryManager(hass, {"min_soc": 10, "target_soc": 80}).update(sh)
        assert sh["battery_mode"] == MODE_LOW_SOC   # not charging

    def test_dropout_holds_the_last_soc_for_30_min(self, hass):
        em = self._em(hass)
        hass.states["sensor.soc"] = "55"
        tick(em, T0)
        hass.states["sensor.soc"] = "unavailable"
        assert tick(em, T0 + timedelta(minutes=29))["battery_soc"] == 55.0
        assert tick(em, T0 + timedelta(minutes=31))["battery_soc"] is None

    def test_unknown_soc_does_not_kill_running_devices(
            self, hass, make_manager, make_device):
        # Audit #16: restart at 03:00, cloud SOC still unavailable. A
        # non-interruptible dishwasher and a cheap-grid boiler are ON.
        mgr = make_manager([
            make_device(name="Dishwasher", switch_entity="switch.dw",
                        interruptible=False, priority=80),
            make_device(name="Boiler", switch_entity="switch.boiler",
                        price_mode="cheap_grid", priority=60),
        ])
        mgr.pricing = FakePricing(price_ok=True)
        night = T0.replace(hour=3)
        for d in mgr.devices:
            hass.states[d["switch_entity"]] = "on"
        running(mgr.devices[0], night)
        running(mgr.devices[1], night, reason="cheap_grid")
        bm = BatteryManager(hass, {"min_soc": 10, "target_soc": 80})

        def sh(t):
            s = dev_shared(t, -2500, soc=None)
            bm.update(s)
            return s
        run(mgr, night, 30, sh)
        assert hass.states["switch.dw"] == "on"
        assert hass.states["switch.boiler"] == "on"
        assert not any(a == "OFF" for a, _ in hass.actions)

    def test_unknown_soc_starts_only_on_genuine_export(
            self, hass, make_manager, make_device):
        mgr = make_manager([make_device(debounce_on=0)])
        # Surplus only from battery charging, grid at 0 W: no start.
        run(mgr, T0, 5, lambda t: {
            **dev_shared(t, 3000, soc=None, mode=MODE_LOW_SOC),
            "grid_power_ema_asym": 0})
        assert hass.states[SW] == "off"
        # Genuine export: start.
        run(mgr, T0 + timedelta(minutes=10), 2, lambda t: dev_shared(
            t, 3000, soc=None, mode=MODE_LOW_SOC))
        assert hass.states[SW] == "on"


# ══════════════════════════════════════════════════════════════════
#  Devices while the surplus is unknown
# ══════════════════════════════════════════════════════════════════


class TestSurplusBlind:
    def test_surplus_run_is_released_after_debounce_off(
            self, hass, make_manager, make_device):
        mgr = make_manager([make_device()])
        dev = mgr.devices[0]
        hass.states[SW] = "on"
        running(dev, T0)
        mgr.update(dev_shared(T0, 1500, blind=True))
        mgr.update(dev_shared(T0 + timedelta(seconds=590), 1500, blind=True))
        assert hass.states[SW] == "on"
        mgr.update(dev_shared(T0 + timedelta(seconds=610), 1500, blind=True))
        assert hass.states[SW] == "off"

    def test_same_run_stays_on_with_a_working_meter(
            self, hass, make_manager, make_device):
        mgr = make_manager([make_device()])
        hass.states[SW] = "on"
        running(mgr.devices[0], T0)
        run(mgr, T0, 30, lambda t: dev_shared(t, 1500))
        assert hass.states[SW] == "on"

    def test_nothing_starts_on_surplus(self, hass, make_manager, make_device):
        mgr = make_manager([make_device(debounce_on=0)])
        run(mgr, T0, 30, lambda t: dev_shared(t, 5000, blind=True))
        assert hass.states[SW] == "off"

    def test_cheap_grid_run_continues(self, hass, make_manager, make_device):
        mgr = make_manager([make_device(price_mode="cheap_grid")])
        mgr.pricing = FakePricing(price_ok=True)
        hass.states[SW] = "on"
        running(mgr.devices[0], T0, reason="cheap_grid")
        run(mgr, T0, 30, lambda t: dev_shared(t, -2000, blind=True))
        assert hass.states[SW] == "on"

    def test_cheap_grid_start_is_still_granted(
            self, hass, make_manager, make_device):
        mgr = make_manager([make_device(price_mode="cheap_grid")])
        mgr.pricing = FakePricing(price_ok=True)
        mgr.update(dev_shared(T0, 0, blind=True))
        assert hass.states[SW] == "on"

    def test_user_started_device_is_left_alone(
            self, hass, make_manager, make_device):
        mgr = make_manager([make_device()])
        hass.states[SW] = "on"                  # switched on by the user
        run(mgr, T0, 30, lambda t: dev_shared(t, 0, blind=True))
        assert hass.states[SW] == "on"

    def test_deadline_force_start_still_fires(
            self, hass, make_manager, make_device):
        mgr = make_manager([make_device(
            deadline="13:00", estimated_runtime=60)])
        hass.states[MH] = "on"
        mgr.update(dev_shared(T0, 0, blind=True))
        assert hass.states[SW] == "on"
        assert mgr.devices[0]["force_started"] is True

    def test_sd_device_does_not_preempt(
            self, hass, make_manager, make_device):
        mgr = make_manager([
            make_device(name="Washer", switch_entity="switch.washer",
                        startup_detection=True, priority=90,
                        power_entity="sensor.washer_power"),
            make_device(name="Heater", switch_entity="switch.heater",
                        priority=10, min_on_time=0),
        ])
        washer, heater = mgr.devices
        washer["sd_state"] = SD_STATE_WAITING
        washer["sd_waiting_since"] = T0 - timedelta(minutes=5)
        hass.states["switch.heater"] = "on"
        running(heater, T0)
        # Two cycles: the heater is a preemption candidate from the second
        # one on (its on-state is cached after the washer's turn).
        mgr.update(dev_shared(T0, 0, blind=True))
        mgr.update(dev_shared(T0 + timedelta(seconds=30), 0, blind=True))
        assert hass.states["switch.heater"] == "on"
        assert not any("PREEMPT" in m for m in hass.logs)


# ══════════════════════════════════════════════════════════════════
#  Unavailable switch
# ══════════════════════════════════════════════════════════════════


class TestSwitchUnavailable:
    def test_no_commands_no_pushes_in_the_deadline_window(
            self, hass, make_manager, make_device):
        # Audit #35/#42: ON command and push every cycle.
        mgr = make_manager([make_device(
            deadline="13:00", estimated_runtime=60)])
        hass.states[MH] = "on"
        hass.states[SW] = "unavailable"
        run(mgr, T0, 20, lambda t: dev_shared(t, 0))
        assert hass.actions == []
        assert hass.services == []
        assert mgr.devices[0]["total_switches"] == 0

    def test_published_as_unavailable(self, hass, make_manager, make_device):
        mgr = make_manager([make_device()])
        hass.states[SW] = "unavailable"
        sh = dev_shared(T0, 3000)
        mgr.update(sh)
        assert sh["device_states"][0]["state"] == "unavailable"

    def test_missing_entity_counts_as_unavailable(
            self, hass, make_manager, make_device):
        mgr = make_manager([make_device(debounce_on=0)])
        del hass.states[SW]
        run(mgr, T0, 2, lambda t: dev_shared(t, 3000))
        assert hass.actions == []

    def test_no_phantom_allocation_for_lower_priority_devices(
            self, hass, make_manager, make_device):
        # Audit #38: the offline plug's ON hid the surplus from others.
        mgr = make_manager([
            make_device(name="Offline", switch_entity="switch.offline",
                        nominal_power=1500, priority=90, debounce_on=0),
            make_device(name="Pool", switch_entity="switch.pool",
                        nominal_power=800, priority=10, debounce_on=0),
        ])
        hass.states["switch.offline"] = "unavailable"
        # 2000 W would start the offline plug (1500 + hysteresis), which
        # then hid the surplus from the pool (800 W) in every cycle.
        run(mgr, T0, 5, lambda t: dev_shared(t, 2000))
        assert hass.states["switch.pool"] == "on"
        assert ("ON", "switch.offline") not in hass.actions

    def test_sd_program_is_not_finished_while_the_plug_is_offline(
            self, hass, make_manager, make_device):
        # Audit #36: unavailable plug read as 0 W → false 'finished'.
        mgr = make_manager([make_device(
            startup_detection=True, power_entity="sensor.washer_power")])
        dev = mgr.devices[0]
        dev["sd_state"] = SD_STATE_RUNNING
        dev["sd_running_since"] = T0 - timedelta(hours=1)
        dev["sd_lockout_until"] = T0 + timedelta(hours=2)
        dev["managed_on"] = True
        hass.states[MH] = "on"
        hass.states[SW] = "unavailable"
        run(mgr, T0, 30, lambda t: dev_shared(t, 0))
        assert dev["sd_state"] == SD_STATE_RUNNING
        assert hass.states[MH] == "on"
        assert hass.actions == [] and hass.services == []


# ══════════════════════════════════════════════════════════════════
#  Startup detection with an unavailable power sensor
# ══════════════════════════════════════════════════════════════════


class TestSdPowerUnavailable:
    def _sd(self, make_manager, make_device):
        return make_manager([make_device(
            startup_detection=True, power_entity="sensor.washer_power")])

    def test_standby_detects_nothing(self, hass, make_manager, make_device):
        # Audit #10: the nominal fallback looked like a program start.
        mgr = self._sd(make_manager, make_device)
        dev = mgr.devices[0]
        dev["sd_state"] = SD_STATE_STANDBY
        hass.states[SW] = "on"
        hass.states["sensor.washer_power"] = "unavailable"
        run(mgr, T0, 10, lambda t: dev_shared(t, 0))
        assert dev["sd_state"] == SD_STATE_STANDBY
        assert ("OFF", SW) not in hass.actions

    def test_running_program_is_not_finished_without_a_reading(
            self, hass, make_manager, make_device):
        mgr = self._sd(make_manager, make_device)
        dev = mgr.devices[0]
        dev["sd_state"] = SD_STATE_RUNNING
        dev["sd_running_since"] = T0 - timedelta(hours=1)
        dev["sd_lockout_until"] = T0 + timedelta(hours=2)
        hass.states[SW] = "on"
        hass.states["sensor.washer_power"] = "unavailable"
        run(mgr, T0, 20, lambda t: dev_shared(t, 0))
        assert dev["sd_state"] == SD_STATE_RUNNING
        # Reading back at standby: the normal smart finish follows.
        hass.states["sensor.washer_power"] = "1"
        run(mgr, T0 + timedelta(minutes=21), 11, lambda t: dev_shared(t, 0))
        assert dev["sd_state"] == SD_STATE_STANDBY


# ══════════════════════════════════════════════════════════════════
#  Restore while the switch has not loaded yet
# ══════════════════════════════════════════════════════════════════


class TestRestoreUnavailableSwitch:
    def _saved(self, hass, make_manager, make_device, tmp_path):
        sf = str(tmp_path / "state.json")
        cfg = make_device(price_mode="cheap_grid")
        mgr = make_manager([cfg])
        dev = mgr.devices[0]
        hass.states[SW] = "on"
        running(dev, datetime.now(), reason="cheap_grid")
        PersistenceManager(hass, {"state_file": sf}).save(mgr)
        mgr2 = make_manager([cfg])
        hass.states[SW] = "unavailable"          # boot: not loaded yet
        PersistenceManager(hass, {"state_file": sf}).restore(mgr2)
        return mgr2

    def test_saved_state_is_kept(self, hass, make_manager, make_device,
                                 tmp_path):
        mgr = self._saved(hass, make_manager, make_device, tmp_path)
        dev = mgr.devices[0]
        assert dev["managed_on"] is True
        assert dev["_scheduling_reason"] == "cheap_grid"
        assert dev["_switch_recheck"] is True

    def test_reports_on_later_stays_managed(
            self, hass, make_manager, make_device, tmp_path):
        # Audit #71: was published as manual_override.
        mgr = self._saved(hass, make_manager, make_device, tmp_path)
        mgr.pricing = FakePricing(price_ok=True)
        hass.states[SW] = "on"
        sh = dev_shared(datetime.now(), -2000)
        mgr.update(sh)
        assert sh["device_states"][0]["state"] == "on"
        assert mgr.devices[0]["_scheduling_reason"] == "cheap_grid"
        assert mgr.devices[0]["_switch_recheck"] is False

    def test_reports_off_later_is_cleared(
            self, hass, make_manager, make_device, tmp_path):
        mgr = self._saved(hass, make_manager, make_device, tmp_path)
        hass.states[SW] = "off"
        mgr.pricing = FakePricing(price_ok=False)
        mgr.update(dev_shared(datetime.now(), 0))
        dev = mgr.devices[0]
        assert dev["managed_on"] is False
        assert dev["on_since"] is None
        assert dev["_scheduling_reason"] is None

    def test_saved_at_is_exposed(self, hass, make_manager, make_device,
                                 tmp_path):
        sf = str(tmp_path / "state.json")
        mgr = make_manager([make_device()])
        PersistenceManager(hass, {"state_file": sf}).save(mgr)
        pm = PersistenceManager(hass, {"state_file": sf})
        pm.restore(make_manager([make_device()]))
        assert pm.last_saved_at is not None


# ══════════════════════════════════════════════════════════════════
#  Price outage
# ══════════════════════════════════════════════════════════════════


class TestPriceOutage:
    def _pm(self):
        return PricingManager(None, {"price_entity": "sensor.price"})

    def test_hold_then_release(self):
        pm = self._pm()
        dev = {"price_mode": "cheap_grid", "max_price": 25}
        pm.snapshot({"now": T0, "price_data_available": False})
        assert pm.should_run_on_grid(dev) is None
        later = T0 + timedelta(seconds=PRICE_OUTAGE_HOLD_S + 30)
        pm.snapshot({"now": later, "price_data_available": False})
        assert pm.should_run_on_grid(dev) is False

    def test_data_back_resets_the_outage(self):
        pm = self._pm()
        dev = {"price_mode": "cheap_grid", "max_price": 25}
        pm.snapshot({"now": T0, "price_data_available": False})
        pm.snapshot({"now": T0 + timedelta(hours=1),
                     "price_data_available": False})
        pm.snapshot({"now": T0 + timedelta(hours=2),
                     "price_data_available": True, "current_price": 20})
        assert pm.should_run_on_grid(dev) is True
        pm.snapshot({"now": T0 + timedelta(hours=3),
                     "price_data_available": False})
        assert pm.should_run_on_grid(dev) is None

    def test_cheap_grid_run_is_released_after_the_hold(
            self, hass, make_manager, make_device):
        mgr = make_manager([make_device(price_mode="cheap_grid")])
        pm = self._pm()
        mgr.pricing = pm
        hass.states[SW] = "on"
        running(mgr.devices[0], T0, reason="cheap_grid")

        def sh(t):
            pm.snapshot({"now": t, "price_data_available": False})
            return dev_shared(t, -2000)
        run(mgr, T0, 25, sh)
        assert hass.states[SW] == "on"
        run(mgr, T0 + timedelta(minutes=31), 1, sh)
        assert hass.states[SW] == "off"


# ══════════════════════════════════════════════════════════════════
#  Advisor
# ══════════════════════════════════════════════════════════════════


class TestAdvisor:
    def _adv(self):
        from custom_components.aurum.modules.advisor import AdvisorManager
        return AdvisorManager(None, {})

    def test_input_fault_headline_and_reason(self):
        data = self._adv().update({
            "battery_mode": MODE_NORMAL,
            "battery_soc": 80,
            "surplus_blind": True,
            "input_faults": [{"input": "grid", "status": "stale",
                              "entity": GRID, "since": T0}],
            "device_states": [{"name": "Heater", "slug": "heater",
                               "state": "off", "soc_threshold": 20}],
        })
        assert data["decision"] == "input_fault"
        assert data["devices"][0]["reason"] == "input_fault"
        assert data["input_faults"] == [
            {"input": "grid", "status": "stale", "entity": GRID}]

    def test_unknown_soc_is_an_input_fault(self):
        data = self._adv().update({
            "battery_mode": MODE_LOW_SOC, "battery_soc": None,
            "device_states": []})
        assert data["decision"] == "input_fault"

    def test_switch_unavailable_reason(self):
        data = self._adv().update({
            "battery_mode": MODE_NORMAL, "battery_soc": 80,
            "device_states": [{"name": "Plug", "slug": "plug",
                               "state": "unavailable"}],
        })
        assert data["devices"][0]["reason"] == "switch_unavailable"
        assert data["decision"] != "input_fault"

    def test_pv_fault_alone_is_not_a_headline(self):
        data = self._adv().update({
            "battery_mode": MODE_NORMAL, "battery_soc": 80,
            "input_faults": [{"input": "pv", "status": "stale",
                              "entity": "sensor.pv", "since": T0}],
            "device_states": [],
        })
        assert data["decision"] == "idle"
        assert data["input_faults"][0]["input"] == "pv"


# ══════════════════════════════════════════════════════════════════
#  Coordinator: startup guard, repair issues, restart helpers
# ══════════════════════════════════════════════════════════════════


def _coordinator(hass, **config):
    from custom_components.aurum.coordinator import AurumCoordinator
    c = AurumCoordinator.__new__(AurumCoordinator)
    c.config = config
    c.bridge = hass
    c.hass = hass
    c.cycle = 0
    c._first_cycle_at = None
    c._in_startup = True
    c._issues = {}
    return c


class TestStartupGuard:
    def test_waits_for_the_soc_sensor_then_gives_up(self, hass):
        c = _coordinator(hass, grid_power_entity=GRID,
                         battery_soc_entity="sensor.soc")
        hass.states[GRID] = "100"
        hass.states["sensor.soc"] = "unavailable"
        c.cycle = 1
        assert c._is_startup(T0) == (True, False)
        c.cycle = 7
        assert c._is_startup(T0 + timedelta(seconds=120))[0] is True
        c.cycle = 21
        assert c._is_startup(T0 + timedelta(seconds=301))[0] is False
        # Latched: a later sensor failure is not a new startup.
        hass.states[GRID] = "unavailable"
        c.cycle = 22
        assert c._is_startup(T0 + timedelta(seconds=316))[0] is False

    def test_ends_after_the_grace_when_ready(self, hass):
        c = _coordinator(hass, grid_power_entity=GRID,
                         battery_soc_entity="sensor.soc")
        hass.states[GRID] = "100"
        hass.states["sensor.soc"] = "60"
        c.cycle = 6
        assert c._is_startup(T0)[0] is True
        c.cycle = 7
        assert c._is_startup(T0 + timedelta(seconds=15))[0] is False


class TestRepairIssues:
    @pytest.fixture
    def ir(self, monkeypatch):
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

    def _fault(self, since, status="unavailable"):
        return {"now": T0, "input_faults": [
            {"input": "grid", "status": status, "entity": GRID,
             "since": since}]}

    def test_raised_after_15_min_and_cleared(self, hass, ir):
        c = _coordinator(hass)
        c._update_repair_issues(self._fault(T0 - timedelta(minutes=5)))
        assert ir == []
        c._update_repair_issues(self._fault(T0 - timedelta(minutes=16)))
        assert ir[0][0] == "create" and ir[0][1] == "input_grid"
        assert ir[0][2]["translation_key"] == "input_unavailable"
        assert ir[0][2]["translation_placeholders"] == {"entity": GRID}
        c._update_repair_issues(self._fault(T0 - timedelta(minutes=17)))
        assert len(ir) == 1                      # not re-created
        c._update_repair_issues({"now": T0, "input_faults": []})
        assert ir[-1] == ("delete", "input_grid")

    def test_status_change_updates_the_issue(self, hass, ir):
        c = _coordinator(hass)
        c._update_repair_issues(self._fault(T0 - timedelta(minutes=16)))
        c._update_repair_issues(
            self._fault(T0 - timedelta(minutes=16), status="stale"))
        assert ir[-1][2]["translation_key"] == "input_stale"


class TestRestartHelpers:
    def test_budget_day_state_from_yesterday_is_stale(self):
        from custom_components.aurum.coordinator import (
            budget_day_state_is_stale)
        now = datetime(2026, 11, 7, 0, 5)
        assert budget_day_state_is_stale(datetime(2026, 11, 6, 23, 59), now)
        assert not budget_day_state_is_stale(datetime(2026, 11, 7, 0, 1), now)
        assert budget_day_state_is_stale(None, now)

    def test_placeholders_carry_the_restored_counters(
            self, make_manager, make_device):
        # Audit #21/#25: energy sensors published 0 until the first cycle.
        from custom_components.aurum.coordinator import initial_device_states
        mgr = make_manager([make_device()])
        mgr.devices[0]["energy_today_wh"] = 3500.04
        mgr.devices[0]["runtime_today_s"] = 5400.4
        ds = initial_device_states(mgr.devices)[0]
        assert ds["energy_today_wh"] == 3500.0
        assert ds["runtime_today_s"] == 5400


# ══════════════════════════════════════════════════════════════════
#  Review round 1 (adversarial review of the 1.16.0 diff)
# ══════════════════════════════════════════════════════════════════


class TestReviewRound1:
    def _sd_running(self, hass, make_manager, make_device):
        mgr = make_manager([make_device(
            startup_detection=True, power_entity="sensor.washer_power",
            switch_entity="switch.dw", name="Dishwasher")])
        dev = mgr.devices[0]
        dev["sd_state"] = SD_STATE_RUNNING
        dev["sd_running_since"] = T0 - timedelta(hours=1)
        dev["sd_lockout_until"] = T0 + timedelta(hours=3)
        dev["managed_on"] = True
        hass.states["switch.dw"] = "on"
        hass.states[muss_heute_entity_id("dishwasher")] = "on"
        return mgr, dev

    @pytest.mark.parametrize("outage", ["power", "plug"])
    def test_quiet_time_before_an_outage_does_not_finish_the_program(
            self, hass, make_manager, make_device, outage):
        mgr, dev = self._sd_running(hass, make_manager, make_device)
        hass.states["sensor.washer_power"] = "1"     # short pause
        run(mgr, T0, 1, lambda t: dev_shared(t, 0))
        assert dev["sd_power_below_since"] is not None
        if outage == "power":
            hass.states["sensor.washer_power"] = "unavailable"
        else:
            hass.states["switch.dw"] = "unavailable"
        run(mgr, T0 + timedelta(minutes=2), 15, lambda t: dev_shared(t, 0))
        hass.states["switch.dw"] = "on"
        hass.states["sensor.washer_power"] = "1"     # back in a pause
        mgr.update(dev_shared(T0 + timedelta(minutes=18), 0))
        assert dev["sd_state"] == SD_STATE_RUNNING
        assert hass.states[muss_heute_entity_id("dishwasher")] == "on"
        # A real finish still needs finish_time of observed quiet.
        run(mgr, T0 + timedelta(minutes=19), 11, lambda t: dev_shared(t, 0))
        assert dev["sd_state"] == SD_STATE_STANDBY

    def test_switch_outage_is_not_counted_as_runtime(
            self, hass, make_manager, make_device):
        mgr = make_manager([make_device(power_entity="sensor.p")])
        dev = mgr.devices[0]
        hass.states[SW] = "on"
        hass.states["sensor.p"] = "800"
        running(dev, T0)
        dev["runtime_today_s"] = 3600
        mgr.update(dev_shared(T0, 2000))
        hass.states[SW] = "unavailable"
        run(mgr, T0 + timedelta(seconds=30), 180, lambda t: dev_shared(t, 2000))
        hass.states[SW] = "on"
        mgr.update(dev_shared(T0 + timedelta(hours=3, minutes=1), 2000))
        assert dev["runtime_today_s"] < 3600 + 120
        assert dev["energy_today_wh"] < 800 * 2 / 60 + 1

    def test_switch_back_off_after_an_outage_clears_the_run(
            self, hass, make_manager, make_device):
        mgr = make_manager([make_device()])
        dev = mgr.devices[0]
        hass.states[SW] = "on"
        running(dev, T0, reason="cheap_grid")
        hass.states[SW] = "unavailable"
        mgr.update(dev_shared(T0, 0))
        hass.states[SW] = "off"
        mgr.update(dev_shared(T0 + timedelta(minutes=30), 0))
        assert dev["managed_on"] is False
        assert dev["on_since"] is None
        assert dev["_scheduling_reason"] is None

    def test_unknown_switch_is_still_commanded(
            self, hass, make_manager, make_device):
        # MQTT switch without retained state: 'unknown' until commanded.
        mgr = make_manager([make_device(debounce_on=0)])
        hass.states[SW] = "unknown"
        run(mgr, T0, 2, lambda t: dev_shared(t, 3000))
        assert ("ON", SW) in hass.actions

    def test_restore_defers_an_unknown_switch(
            self, hass, make_manager, make_device, tmp_path):
        sf = str(tmp_path / "state.json")
        cfg = make_device()
        mgr = make_manager([cfg])
        hass.states[SW] = "on"
        running(mgr.devices[0], datetime.now())
        PersistenceManager(hass, {"state_file": sf}).save(mgr)
        mgr2 = make_manager([cfg])
        hass.states[SW] = "unknown"
        PersistenceManager(hass, {"state_file": sf}).restore(mgr2)
        assert mgr2.devices[0]["managed_on"] is True
        assert mgr2.devices[0]["_switch_recheck"] is True

    def test_user_started_device_stays_the_users_after_a_restart(
            self, hass, make_manager, make_device, tmp_path):
        sf = str(tmp_path / "state.json")
        cfg = make_device()
        mgr = make_manager([cfg])
        hass.states[SW] = "on"                       # switched on by hand
        sh = dev_shared(datetime.now(), 0)
        mgr.update(sh)
        assert sh["device_states"][0]["state"] == "manual_override"
        PersistenceManager(hass, {"state_file": sf}).save(mgr)
        mgr2 = make_manager([cfg])
        PersistenceManager(hass, {"state_file": sf}).restore(mgr2)
        assert mgr2.devices[0]["managed_on"] is False
        start = datetime.now()
        run(mgr2, start, 30, lambda t: dev_shared(t, 0, blind=True))
        assert hass.states[SW] == "on"

    def test_restore_without_a_saved_record_keeps_the_old_rule(
            self, hass, make_manager, make_device, tmp_path):
        sf = str(tmp_path / "state.json")
        PersistenceManager(hass, {"state_file": sf}).save(
            make_manager([]))
        mgr = make_manager([make_device()])
        hass.states[SW] = "on"
        PersistenceManager(hass, {"state_file": sf}).restore(mgr)
        assert mgr.devices[0]["managed_on"] is True

    def test_pv_gate_starts_although_the_surplus_is_short(
            self, hass, make_manager, make_device):
        mgr = make_manager([make_device(
            nominal_power=800, pv_power_threshold=2500, debounce_on=60)])
        def sh(t):
            s = dev_shared(t, 300)
            s["pv_power"] = 4000
            return s
        run(mgr, T0, 2, sh)
        assert hass.states[SW] == "on"
        assert mgr.devices[0]["_scheduling_reason"] == "solar_pv"

    def test_cached_summary_ignores_unavailable_devices(self):
        from custom_components.aurum.coordinator import (
            summarize_cached_states)
        on, power, cheap = summarize_cached_states([
            {"state": "unavailable", "scheduling_reason": "cheap_grid",
             "power": 0},
            {"state": "on", "scheduling_reason": "surplus_available",
             "power": 500},
        ])
        assert (on, power, cheap) == (1, 500, False)


class TestRepairIssueInputs:
    @pytest.fixture
    def ir(self, monkeypatch):
        calls = []
        mod = types.ModuleType("homeassistant.helpers.issue_registry")
        mod.IssueSeverity = types.SimpleNamespace(WARNING="warning")
        mod.async_create_issue = (
            lambda hass, domain, issue_id, **kw:
            calls.append(("create", issue_id)))
        mod.async_delete_issue = (
            lambda hass, domain, issue_id: calls.append(("delete", issue_id)))
        monkeypatch.setitem(
            sys.modules, "homeassistant.helpers.issue_registry", mod)
        monkeypatch.setattr(
            sys.modules["homeassistant.helpers"], "issue_registry", mod,
            raising=False)
        return calls

    def test_pv_outage_raises_no_issue(self, hass, ir):
        # Inverters take their PV sensor offline every night.
        c = _coordinator(hass)
        c._update_repair_issues({"now": T0, "input_faults": [
            {"input": "pv", "status": "unavailable", "entity": "sensor.pv",
             "since": T0 - timedelta(hours=8)}]})
        assert ir == []

    def test_soc_outage_raises_an_issue(self, hass, ir):
        c = _coordinator(hass)
        c._update_repair_issues({"now": T0, "input_faults": [
            {"input": "soc", "status": "unavailable", "entity": "sensor.soc",
             "since": T0 - timedelta(hours=1)}]})
        assert ir == [("create", "input_soc")]
