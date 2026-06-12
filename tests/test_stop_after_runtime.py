"""
Tests for the stop_after_runtime feature (daily runtime target).

Covers the unit-level decision logic plus tick-by-tick full-day
simulations for every device type: solar-only loads, cheap-grid loads,
startup-detection appliances, non-interruptible devices, manual
override, multi-day operation and cloudy-sky interruptions.
"""

from datetime import datetime, timedelta

import pytest

from custom_components.aurum.const import (
    MODE_NORMAL,
    SD_STATE_RUNNING,
    SD_STATE_STANDBY,
    SD_STATE_WAITING,
    muss_heute_entity_id,
    override_entity_id,
)

TICK = 15  # seconds, default AURUM update interval


def make_shared(now, excess, soc=80, raw=None, grid=None):
    return {
        "now": now,
        "excess_for_devices": excess,
        "excess_raw_for_devices": raw if raw is not None else excess,
        "grid_power_ema_asym": -(grid if grid is not None else excess),
        "battery_soc": soc,
        "battery_mode": MODE_NORMAL,
        "device_budget_w": None,
    }


def simulate(mgr, hass, start, duration_s, pv_fn, soc=80, tick=TICK):
    """Tick-by-tick simulation.

    ``pv_fn(t_s)`` returns the raw PV surplus in W at second ``t_s``
    (before subtracting AURUM-controlled loads). The effective excess
    fed to the manager is pv minus the nominal power of all devices
    currently ON — mirroring how a real grid sensor would see it.
    """
    t = 0
    while t < duration_s:
        now = start + timedelta(seconds=t)
        on_power = sum(
            d["nominal_power"] for d in mgr.devices
            if hass.get_state(d["switch_entity"]) == "on")
        excess = pv_fn(t) - on_power
        mgr.update(make_shared(now, excess, soc=soc))
        t += tick
    return start + timedelta(seconds=duration_s)


def on_actions(hass, entity):
    return [a for a in hass.actions if a == ("ON", entity)]


def off_actions(hass, entity):
    return [a for a in hass.actions if a == ("OFF", entity)]


# ══════════════════════════════════════════════════════════════════
#  _runtime_target_reached
# ══════════════════════════════════════════════════════════════════


class TestRuntimeTargetReached:
    def test_false_when_flag_off(self, make_manager, make_device):
        mgr = make_manager([make_device(estimated_runtime=100)])
        dev = mgr.devices[0]
        dev["runtime_today_s"] = 999999
        assert mgr._runtime_target_reached(dev) is False

    def test_false_when_no_target_configured(self, make_manager, make_device):
        mgr = make_manager([make_device(stop_after_runtime=True)])
        dev = mgr.devices[0]
        dev["runtime_today_s"] = 999999
        assert mgr._runtime_target_reached(dev) is False

    def test_false_below_target(self, make_manager, make_device):
        mgr = make_manager([make_device(
            stop_after_runtime=True, estimated_runtime=100)])
        dev = mgr.devices[0]
        dev["runtime_today_s"] = 99 * 60
        assert mgr._runtime_target_reached(dev) is False

    def test_true_at_target(self, make_manager, make_device):
        mgr = make_manager([make_device(
            stop_after_runtime=True, estimated_runtime=100)])
        dev = mgr.devices[0]
        dev["runtime_today_s"] = 100 * 60
        assert mgr._runtime_target_reached(dev) is True


# ══════════════════════════════════════════════════════════════════
#  Turn-on block once target is reached
# ══════════════════════════════════════════════════════════════════


class TestTurnOnBlocked:
    def test_should_turn_on_false_when_target_reached(
            self, make_manager, make_device, now):
        mgr = make_manager([make_device(
            stop_after_runtime=True, estimated_runtime=100, debounce_on=0)])
        dev = mgr.devices[0]
        dev["runtime_today_s"] = 100 * 60
        dev["excess_since"] = now - timedelta(seconds=600)
        assert mgr._should_turn_on(dev, 9999, 9999, 80, 20, now) is False

    def test_should_turn_on_unaffected_below_target(
            self, make_manager, make_device, now):
        mgr = make_manager([make_device(
            stop_after_runtime=True, estimated_runtime=100, debounce_on=0)])
        dev = mgr.devices[0]
        dev["runtime_today_s"] = 50 * 60
        dev["excess_since"] = now - timedelta(seconds=600)
        assert mgr._should_turn_on(dev, 9999, 9999, 80, 20, now) is True

    def test_cheap_grid_turn_on_also_blocked(
            self, make_manager, make_device, now):
        from tests.conftest import FakePricing

        mgr = make_manager([make_device(
            stop_after_runtime=True, estimated_runtime=100,
            price_mode="cheap_grid")])
        mgr.pricing = FakePricing(price_ok=True)
        dev = mgr.devices[0]
        dev["runtime_today_s"] = 100 * 60
        assert mgr._should_turn_on(dev, 0, 0, 80, 20, now) is False


# ══════════════════════════════════════════════════════════════════
#  Enforce stop via update() — the critical path from issue #2:
#  device must turn OFF at full PV surplus, not only on deficit.
# ══════════════════════════════════════════════════════════════════


class TestEnforceStopInUpdate:
    def _running_device(self, mgr, hass, now, runtime_min, on_for_s=3600):
        dev = mgr.devices[0]
        hass.set_state(dev["switch_entity"], "on")
        dev["managed_on"] = True
        dev["on_since"] = now - timedelta(seconds=on_for_s)
        dev["_runtime_tick"] = now  # no extra accumulation this tick
        dev["runtime_today_s"] = runtime_min * 60
        return dev

    def test_turns_off_at_full_surplus(
            self, make_manager, make_device, hass, now):
        mgr = make_manager([make_device(
            stop_after_runtime=True, estimated_runtime=400)])
        dev = self._running_device(mgr, hass, now, runtime_min=400)
        mgr.update(make_shared(now, 5000))
        assert ("OFF", dev["switch_entity"]) in hass.actions
        assert hass.get_state(dev["switch_entity"]) == "off"

    def test_off_reason_logged(self, make_manager, make_device, hass, now):
        mgr = make_manager([make_device(
            stop_after_runtime=True, estimated_runtime=400)])
        self._running_device(mgr, hass, now, runtime_min=400)
        mgr.update(make_shared(now, 5000))
        # Notification sent via persistent_notification
        assert any(s == "persistent_notification/create"
                   for s, _ in hass.services)

    def test_min_on_time_respected_then_stopped(
            self, make_manager, make_device, hass, now):
        mgr = make_manager([make_device(
            stop_after_runtime=True, estimated_runtime=400, min_on_time=600)])
        dev = self._running_device(
            mgr, hass, now, runtime_min=400, on_for_s=60)
        mgr.update(make_shared(now, 5000))
        # Only 60s into the session: held by min_on_time
        assert hass.get_state(dev["switch_entity"]) == "on"
        # 10 minutes later: stop fires
        later = now + timedelta(seconds=600)
        dev["_runtime_tick"] = later
        mgr.update(make_shared(later, 5000))
        assert hass.get_state(dev["switch_entity"]) == "off"

    def test_no_restart_after_stop(self, make_manager, make_device, hass, now):
        mgr = make_manager([make_device(
            stop_after_runtime=True, estimated_runtime=400,
            debounce_on=0, min_off_time=0)])
        dev = self._running_device(mgr, hass, now, runtime_min=400)
        mgr.update(make_shared(now, 5000))
        assert hass.get_state(dev["switch_entity"]) == "off"
        # Massive surplus for an hour: must stay off
        for i in range(1, 240):
            mgr.update(make_shared(now + timedelta(seconds=i * TICK), 9000))
        assert len(on_actions(hass, dev["switch_entity"])) == 0

    def test_flag_off_keeps_old_behavior(
            self, make_manager, make_device, hass, now):
        mgr = make_manager([make_device(estimated_runtime=400)])
        dev = self._running_device(mgr, hass, now, runtime_min=500)
        mgr.update(make_shared(now, 5000))
        assert hass.get_state(dev["switch_entity"]) == "on"
        assert len(off_actions(hass, dev["switch_entity"])) == 0

    def test_manual_override_wins(self, make_manager, make_device, hass, now):
        mgr = make_manager([make_device(
            stop_after_runtime=True, estimated_runtime=400)])
        dev = self._running_device(mgr, hass, now, runtime_min=500)
        hass.set_state(override_entity_id(dev["slug"]), "on")
        mgr.update(make_shared(now, 5000))
        assert hass.get_state(dev["switch_entity"]) == "on"

    def test_manually_started_device_is_stopped(
            self, make_manager, make_device, hass, now):
        """Device turned on at the wall switch (managed_on=False) is still
        stopped once the daily target is reached (same semantics as the
        existing shed logic for unmanaged devices)."""
        mgr = make_manager([make_device(
            stop_after_runtime=True, estimated_runtime=400, min_on_time=600)])
        dev = mgr.devices[0]
        hass.set_state(dev["switch_entity"], "on")
        dev["runtime_today_s"] = 400 * 60
        dev["_runtime_tick"] = now
        # on_since unknown → first tick adopts it, min_on_time holds,
        # then the stop fires.
        t = now
        for i in range(int(600 / TICK) + 2):
            t = now + timedelta(seconds=i * TICK)
            dev["_runtime_tick"] = t
            mgr.update(make_shared(t, 5000))
        assert hass.get_state(dev["switch_entity"]) == "off"

    def test_cheap_grid_device_stopped_despite_cheap_price(
            self, make_manager, make_device, hass, now):
        from tests.conftest import FakePricing

        mgr = make_manager([make_device(
            stop_after_runtime=True, estimated_runtime=400,
            price_mode="cheap_grid")])
        mgr.pricing = FakePricing(price_ok=True)
        dev = self._running_device(mgr, hass, now, runtime_min=400)
        dev["_scheduling_reason"] = "cheap_grid"
        mgr.update(make_shared(now, -2000))  # night, grid power
        assert hass.get_state(dev["switch_entity"]) == "off"

    def test_non_interruptible_device_stopped(
            self, make_manager, make_device, hass, now):
        """stop_after_runtime is an explicit user instruction and
        overrides the interruptible=False protection."""
        mgr = make_manager([make_device(
            stop_after_runtime=True, estimated_runtime=400,
            interruptible=False)])
        dev = self._running_device(mgr, hass, now, runtime_min=400)
        mgr.update(make_shared(now, 5000))
        assert hass.get_state(dev["switch_entity"]) == "off"

    def test_low_soc_grid_export_device_stopped(
            self, make_manager, make_device, hass, now):
        mgr = make_manager([make_device(
            stop_after_runtime=True, estimated_runtime=400,
            soc_threshold=50)])
        dev = self._running_device(mgr, hass, now, runtime_min=400)
        mgr.update(make_shared(now, 3000, soc=30))
        assert hass.get_state(dev["switch_entity"]) == "off"


# ══════════════════════════════════════════════════════════════════
#  Startup-detection devices (washing machine, dishwasher, …)
# ══════════════════════════════════════════════════════════════════


class TestSDDevices:
    def _sd_device(self, make_device, **overrides):
        base = dict(
            startup_detection=True, stop_after_runtime=True,
            estimated_runtime=120, nominal_power=2000)
        base.update(overrides)
        return make_device(**base)

    def test_waiting_blocks_excess_start_when_target_reached(
            self, make_manager, make_device, hass, now):
        mgr = make_manager([self._sd_device(make_device, debounce_on=0)])
        dev = mgr.devices[0]
        dev["sd_state"] = SD_STATE_WAITING
        dev["runtime_today_s"] = 120 * 60
        dev["excess_since"] = now - timedelta(seconds=600)
        mgr.update(make_shared(now, 9000))
        assert dev["sd_state"] == SD_STATE_WAITING
        assert len(on_actions(hass, dev["switch_entity"])) == 0

    def test_waiting_blocks_deadline_force_start_when_target_reached(
            self, make_manager, make_device, hass, now):
        mgr = make_manager([self._sd_device(
            make_device, deadline="12:30")])
        dev = mgr.devices[0]
        dev["sd_state"] = SD_STATE_WAITING
        dev["runtime_today_s"] = 120 * 60
        hass.set_state(muss_heute_entity_id(dev["slug"]), "on")
        # now = 12:00, deadline 12:30, runtime 120 min → urgent
        mgr.update(make_shared(now, 0))
        assert dev["sd_state"] == SD_STATE_WAITING
        assert dev["force_started"] is False
        assert len(on_actions(hass, dev["switch_entity"])) == 0

    def test_waiting_starts_normally_below_target(
            self, make_manager, make_device, hass, now):
        mgr = make_manager([self._sd_device(make_device, debounce_on=0)])
        dev = mgr.devices[0]
        dev["sd_state"] = SD_STATE_WAITING
        dev["runtime_today_s"] = 60 * 60  # below 120 min target
        dev["excess_since"] = now - timedelta(seconds=600)
        mgr.update(make_shared(now, 9000))
        assert dev["sd_state"] == SD_STATE_RUNNING

    def test_running_program_never_interrupted(
            self, make_manager, make_device, hass, now):
        """A RUNNING program is never killed mid-cycle, even when the
        daily target is exceeded — sd_max_runtime is the safety net."""
        mgr = make_manager([self._sd_device(make_device)])
        dev = mgr.devices[0]
        hass.set_state(dev["switch_entity"], "on")
        dev["managed_on"] = True
        dev["on_since"] = now - timedelta(hours=1)
        dev["sd_state"] = SD_STATE_RUNNING
        dev["sd_running_since"] = now - timedelta(hours=1)
        dev["sd_lockout_until"] = now + timedelta(hours=1)
        dev["runtime_today_s"] = 500 * 60
        mgr.update(make_shared(now, -3000))
        assert hass.get_state(dev["switch_entity"]) == "on"
        assert dev["sd_state"] == SD_STATE_RUNNING


# ══════════════════════════════════════════════════════════════════
#  Daily reset
# ══════════════════════════════════════════════════════════════════


class TestDailyReset:
    def test_device_runs_again_after_midnight_reset(
            self, make_manager, make_device, hass, now):
        mgr = make_manager([make_device(
            stop_after_runtime=True, estimated_runtime=100, debounce_on=0)])
        dev = mgr.devices[0]
        dev["runtime_today_s"] = 100 * 60
        assert mgr._runtime_target_reached(dev) is True
        mgr.daily_reset()
        assert mgr._runtime_target_reached(dev) is False
        dev["excess_since"] = now - timedelta(seconds=600)
        assert mgr._should_turn_on(dev, 9999, 9999, 80, 20, now) is True


# ══════════════════════════════════════════════════════════════════
#  Full-day tick simulations (15s resolution)
# ══════════════════════════════════════════════════════════════════


SUNNY = lambda t: 3000  # noqa: E731 — constant 3 kW surplus
NIGHT = lambda t: -300  # noqa: E731


def cloudy(period_sunny=2400, period_cloudy=1800, pv=3000, deficit=-800):
    """Alternating sun/cloud PV profile."""
    cycle = period_sunny + period_cloudy

    def _fn(t):
        return pv if (t % cycle) < period_sunny else deficit
    return _fn


class TestFullDaySimulation:
    def test_issue_scenario_pool_pump_400min(
            self, make_manager, make_device, hass):
        """Issue #2: pool must run 400 min, then stop — even though
        surplus would allow it to keep running until cut-off/SOC."""
        mgr = make_manager([make_device(
            name="Pool Pump", switch_entity="switch.pool",
            nominal_power=500, stop_after_runtime=True,
            estimated_runtime=400, debounce_on=60, min_off_time=60)])
        start = datetime(2026, 6, 12, 8, 0, 0)
        simulate(mgr, hass, start, 12 * 3600, SUNNY)
        dev = mgr.devices[0]
        # Stopped at the target — overshoot bounded by one tick
        assert dev["runtime_today_s"] >= 400 * 60
        assert dev["runtime_today_s"] <= 400 * 60 + 2 * TICK
        assert hass.get_state("switch.pool") == "off"
        # Exactly one ON and one OFF — no ping-pong afterwards
        assert len(on_actions(hass, "switch.pool")) == 1
        assert len(off_actions(hass, "switch.pool")) == 1

    def test_without_flag_pool_runs_all_day(
            self, make_manager, make_device, hass):
        """Regression guard: without the flag the device keeps running
        (the pre-feature behaviour the issue complained about)."""
        mgr = make_manager([make_device(
            name="Pool Pump", switch_entity="switch.pool",
            nominal_power=500, estimated_runtime=400, debounce_on=60)])
        start = datetime(2026, 6, 12, 8, 0, 0)
        simulate(mgr, hass, start, 12 * 3600, SUNNY)
        dev = mgr.devices[0]
        assert hass.get_state("switch.pool") == "on"
        assert dev["runtime_today_s"] > 400 * 60  # ran past the target

    def test_cloudy_day_accumulates_across_sessions(
            self, make_manager, make_device, hass):
        """Interrupted sessions (clouds) accumulate; the stop fires in a
        later session exactly when the daily total reaches the target."""
        mgr = make_manager([make_device(
            name="Pool Pump", switch_entity="switch.pool",
            nominal_power=500, stop_after_runtime=True,
            estimated_runtime=120, debounce_on=60, debounce_off=120,
            min_on_time=300, min_off_time=60, hysteresis_off=100)])
        start = datetime(2026, 6, 12, 8, 0, 0)
        simulate(mgr, hass, start, 12 * 3600, cloudy())
        dev = mgr.devices[0]
        assert dev["runtime_today_s"] >= 120 * 60
        assert dev["runtime_today_s"] <= 120 * 60 + 2 * TICK
        assert hass.get_state("switch.pool") == "off"
        # Multiple sessions happened before the target was met
        assert len(on_actions(hass, "switch.pool")) >= 2

    def test_multi_day_target_enforced_each_day(
            self, make_manager, make_device, hass):
        mgr = make_manager([make_device(
            name="Pool Pump", switch_entity="switch.pool",
            nominal_power=500, stop_after_runtime=True,
            estimated_runtime=60, debounce_on=60)])
        dev = mgr.devices[0]
        runtimes = []
        for day in (12, 13, 14):
            start = datetime(2026, 6, day, 8, 0, 0)
            simulate(mgr, hass, start, 6 * 3600, SUNNY)
            runtimes.append(dev["runtime_today_s"])
            mgr.daily_reset()
        for rt in runtimes:
            assert 60 * 60 <= rt <= 60 * 60 + 2 * TICK
        # One start per day
        assert len(on_actions(hass, "switch.pool")) == 3

    def test_two_devices_other_keeps_running_after_pool_stops(
            self, make_manager, make_device, hass):
        mgr = make_manager([
            make_device(
                name="Pool Pump", switch_entity="switch.pool",
                nominal_power=500, priority=70, stop_after_runtime=True,
                estimated_runtime=120, debounce_on=60),
            make_device(
                name="Heater", switch_entity="switch.heater",
                nominal_power=1000, priority=50, debounce_on=60),
        ])
        start = datetime(2026, 6, 12, 8, 0, 0)
        simulate(mgr, hass, start, 8 * 3600, lambda t: 4000)
        pool, heater = mgr.devices[0], mgr.devices[1]
        assert pool["name"] == "Pool Pump"
        assert hass.get_state("switch.pool") == "off"
        assert 120 * 60 <= pool["runtime_today_s"] <= 120 * 60 + 2 * TICK
        # Heater unaffected: still running at end of day
        assert hass.get_state("switch.heater") == "on"
        assert heater["runtime_today_s"] > pool["runtime_today_s"]

    def test_cheap_grid_night_run_stops_at_target(
            self, make_manager, make_device, hass):
        from tests.conftest import FakePricing

        mgr = make_manager([make_device(
            name="Boiler", switch_entity="switch.boiler",
            nominal_power=1500, stop_after_runtime=True,
            estimated_runtime=90, price_mode="cheap_grid",
            min_on_time=300, min_off_time=60)])
        mgr.pricing = FakePricing(price_ok=True)
        start = datetime(2026, 6, 12, 0, 0, 0)
        simulate(mgr, hass, start, 6 * 3600, NIGHT)
        dev = mgr.devices[0]
        assert hass.get_state("switch.boiler") == "off"
        assert 90 * 60 <= dev["runtime_today_s"] <= 90 * 60 + 2 * TICK
        assert len(on_actions(hass, "switch.boiler")) == 1

    def test_cheap_grid_reason_survives_turn_on(
            self, make_manager, make_device, hass):
        """Regression: update() must preserve the cheap_grid scheduling
        reason set by _should_turn_on. Before the fix _turn_on overwrote
        it with 'surplus_available', so the cheap-grid hold in
        _should_turn_off stopped applying and the device ping-ponged
        on/off all night on excess_deficit."""
        from tests.conftest import FakePricing

        mgr = make_manager([make_device(
            name="Boiler", switch_entity="switch.boiler",
            nominal_power=1500, price_mode="cheap_grid",
            min_on_time=300, min_off_time=60)])
        mgr.pricing = FakePricing(price_ok=True)
        start = datetime(2026, 6, 12, 0, 0, 0)
        simulate(mgr, hass, start, 2 * 3600, NIGHT)
        dev = mgr.devices[0]
        assert dev["_scheduling_reason"] == "cheap_grid"
        assert hass.get_state("switch.boiler") == "on"
        assert len(on_actions(hass, "switch.boiler")) == 1
        assert len(off_actions(hass, "switch.boiler")) == 0

    def test_manual_override_runs_past_target_all_day(
            self, make_manager, make_device, hass):
        mgr = make_manager([make_device(
            name="Pool Pump", switch_entity="switch.pool",
            nominal_power=500, stop_after_runtime=True,
            estimated_runtime=60, debounce_on=60)])
        dev = mgr.devices[0]
        hass.set_state(override_entity_id(dev["slug"]), "on")
        hass.set_state("switch.pool", "on")
        dev["managed_on"] = True
        start = datetime(2026, 6, 12, 8, 0, 0)
        simulate(mgr, hass, start, 6 * 3600, SUNNY)
        # Override active the whole time: AURUM never turns it off
        assert hass.get_state("switch.pool") == "on"
        assert len(off_actions(hass, "switch.pool")) == 0

    def test_state_published_with_target_flags(
            self, make_manager, make_device, hass, now):
        mgr = make_manager([make_device(
            stop_after_runtime=True, estimated_runtime=100)])
        dev = mgr.devices[0]
        dev["runtime_today_s"] = 100 * 60
        shared = make_shared(now, 0)
        mgr.update(shared)
        state = shared["device_states"][0]
        assert state["stop_after_runtime"] is True
        assert state["runtime_target_reached"] is True
