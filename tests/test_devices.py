"""
Unit tests for custom_components.aurum.modules.devices.DeviceManager.

Covers turn-on/turn-off decision logic, priority-based shedding, startup
detection state machine, SD preemption, and the v1.7.7 scheduling_reason
regression.
"""

from datetime import timedelta

import pytest

from custom_components.aurum.const import (
    MODE_CHARGING,
    MODE_NORMAL,
    SD_STATE_DETECTED,
    SD_STATE_RUNNING,
    SD_STATE_STANDBY,
    SD_STATE_WAITING,
)


# ══════════════════════════════════════════════════════════════════
#  _should_turn_on
# ══════════════════════════════════════════════════════════════════


class TestShouldTurnOn:
    def test_returns_false_when_excess_below_nominal_plus_hysteresis(
            self, make_manager, make_device, now):
        mgr = make_manager([make_device(nominal_power=1000, hysteresis_on=200,
                                        residual_power=100)])
        dev = mgr.devices[0]
        # needed = 1000 + 200 + 100 = 1300
        assert mgr._should_turn_on(dev, 1200, 0, 80, 20, now) is False

    def test_first_call_at_sufficient_excess_starts_debounce_timer(
            self, make_manager, make_device, now):
        mgr = make_manager([make_device(debounce_on=300)])
        dev = mgr.devices[0]
        assert mgr._should_turn_on(dev, 2000, 0, 80, 20, now) is False
        assert dev["excess_since"] == now  # timer armed

    def test_returns_true_after_debounce_elapsed(
            self, make_manager, make_device, now):
        mgr = make_manager([make_device(debounce_on=300)])
        dev = mgr.devices[0]
        dev["excess_since"] = now - timedelta(seconds=301)
        assert mgr._should_turn_on(dev, 2000, 0, 80, 20, now) is True

    def test_respects_min_off_time(self, make_manager, make_device, now):
        mgr = make_manager([make_device(min_off_time=60)])
        dev = mgr.devices[0]
        dev["last_off"] = now - timedelta(seconds=30)
        assert mgr._should_turn_on(dev, 5000, 0, 80, 20, now) is False

    def test_uses_grid_excess_when_soc_below_threshold(
            self, make_manager, make_device, now):
        mgr = make_manager([make_device(soc_threshold=50, debounce_on=0)])
        dev = mgr.devices[0]
        dev["excess_since"] = now - timedelta(seconds=10)
        # SOC below threshold: normal excess ignored, only grid export matters.
        # grid_excess small (500) < needed (1300) → False
        assert mgr._should_turn_on(dev, 5000, 500, 40, 50, now) is False
        # grid_excess high (2000) >= needed (1300) → True
        assert mgr._should_turn_on(dev, 5000, 2000, 40, 50, now) is True

    def test_cheap_grid_price_ok_bypasses_debounce(
            self, make_manager, make_device, now):
        from tests.conftest import FakePricing

        mgr = make_manager([make_device(price_mode="cheap_grid")])
        mgr.pricing = FakePricing(price_ok=True)
        dev = mgr.devices[0]
        # Zero excess, no debounce armed — cheap_grid still returns True.
        assert mgr._should_turn_on(dev, 0, 0, 80, 20, now) is True
        assert dev["_scheduling_reason"] == "cheap_grid"

    def test_cheap_grid_price_not_ok_falls_back_to_solar_logic(
            self, make_manager, make_device, now):
        from tests.conftest import FakePricing

        mgr = make_manager([make_device(price_mode="cheap_grid")])
        mgr.pricing = FakePricing(price_ok=False)
        dev = mgr.devices[0]
        # Price not ok, no surplus → False.
        assert mgr._should_turn_on(dev, 0, 0, 80, 20, now) is False


# ══════════════════════════════════════════════════════════════════
#  _should_turn_off
# ══════════════════════════════════════════════════════════════════


class TestShouldTurnOff:
    def test_non_interruptible_never_turns_off(
            self, make_manager, make_device, now):
        mgr = make_manager([make_device(interruptible=False)])
        dev = mgr.devices[0]
        assert mgr._should_turn_off(dev, -9999, 80, 20, now) is None

    def test_force_started_never_turns_off(
            self, make_manager, make_device, now):
        mgr = make_manager([make_device()])
        dev = mgr.devices[0]
        dev["force_started"] = True
        assert mgr._should_turn_off(dev, -9999, 80, 20, now) is None

    def test_min_on_time_protects_running_device(
            self, make_manager, make_device, now):
        mgr = make_manager([make_device(min_on_time=600)])
        dev = mgr.devices[0]
        dev["on_since"] = now - timedelta(seconds=60)  # only 1 min
        assert mgr._should_turn_off(dev, -9999, 80, 20, now) is None

    def test_excess_deficit_arms_timer_on_first_call(
            self, make_manager, make_device, now):
        mgr = make_manager([make_device(hysteresis_off=100, debounce_off=600)])
        dev = mgr.devices[0]
        dev["on_since"] = now - timedelta(hours=1)
        # excess_raw = -200 → deficit of 200W > hysteresis_off (100) → timer armed
        assert mgr._should_turn_off(dev, -200, 80, 20, now) is None
        assert dev["_excess_deficit_since"] == now

    def test_excess_deficit_returns_reason_after_debounce(
            self, make_manager, make_device, now):
        mgr = make_manager([make_device(hysteresis_off=100, debounce_off=600)])
        dev = mgr.devices[0]
        dev["on_since"] = now - timedelta(hours=1)
        dev["_excess_deficit_since"] = now - timedelta(seconds=601)
        assert mgr._should_turn_off(dev, -200, 80, 20, now) == "excess_deficit"

    def test_excess_deficit_timer_clears_when_excess_returns(
            self, make_manager, make_device, now):
        mgr = make_manager([make_device(hysteresis_off=100)])
        dev = mgr.devices[0]
        dev["on_since"] = now - timedelta(hours=1)
        dev["_excess_deficit_since"] = now - timedelta(seconds=30)
        # Excess positive → timer should clear, return None.
        assert mgr._should_turn_off(dev, 500, 80, 20, now) is None
        assert dev["_excess_deficit_since"] is None

    def test_soc_deficit_triggers_after_debounce(
            self, make_manager, make_device, now):
        mgr = make_manager([make_device(hysteresis_off=100, debounce_off=600)])
        dev = mgr.devices[0]
        dev["on_since"] = now - timedelta(hours=1)
        dev["_soc_grid_deficit_since"] = now - timedelta(seconds=601)
        # battery_soc < soc_threshold → soc_grid_deficit path
        assert mgr._should_turn_off(
            dev, -200, 40, 50, now) == "soc_grid_deficit"

    def test_cheap_grid_price_no_longer_cheap_turns_off_immediately(
            self, make_manager, make_device, now):
        from tests.conftest import FakePricing

        mgr = make_manager([make_device(price_mode="cheap_grid")])
        mgr.pricing = FakePricing(price_ok=False)
        dev = mgr.devices[0]
        dev["on_since"] = now - timedelta(hours=1)
        dev["_scheduling_reason"] = "cheap_grid"
        assert mgr._should_turn_off(
            dev, 500, 80, 20, now) == "price_no_longer_cheap"

    def test_cheap_grid_keeps_running_during_excess_deficit(
            self, make_manager, make_device, now):
        from tests.conftest import FakePricing

        mgr = make_manager([make_device(price_mode="cheap_grid")])
        mgr.pricing = FakePricing(price_ok=True)
        dev = mgr.devices[0]
        dev["on_since"] = now - timedelta(hours=1)
        dev["_scheduling_reason"] = "cheap_grid"
        # Deep deficit, but price is still cheap → keep running.
        assert mgr._should_turn_off(dev, -9999, 80, 20, now) is None


# ══════════════════════════════════════════════════════════════════
#  _turn_on / _turn_off   (v1.7.7 regression)
# ══════════════════════════════════════════════════════════════════


class TestTurnOnTurnOff:
    def test_turn_off_clears_scheduling_reason(
            self, make_manager, make_device, now):
        """v1.7.7 regression: a stale scheduling_reason=cheap_grid must not
        leak into the next turn-on decision."""
        mgr = make_manager([make_device()])
        dev = mgr.devices[0]
        mgr._turn_on(dev, now, 2000, 80, reason="cheap_grid")
        assert dev["_scheduling_reason"] == "cheap_grid"

        mgr._turn_off(dev, now + timedelta(seconds=10), 0, 80,
                      reason="excess_deficit")
        assert dev["_scheduling_reason"] is None

    def test_turn_on_sets_managed_on_flag(
            self, make_manager, make_device, now):
        mgr = make_manager([make_device()])
        dev = mgr.devices[0]
        mgr._turn_on(dev, now, 2000, 80)
        assert dev["managed_on"] is True
        assert dev["on_since"] == now
        assert ("ON", "switch.test_device") in mgr.hass.actions

    def test_turn_off_clears_timers_and_flags(
            self, make_manager, make_device, now):
        mgr = make_manager([make_device()])
        dev = mgr.devices[0]
        dev["excess_since"] = now
        dev["_excess_deficit_since"] = now
        dev["_soc_grid_deficit_since"] = now
        dev["force_started"] = True
        mgr._turn_off(dev, now + timedelta(seconds=1), 0, 80, "reason")
        assert dev["excess_since"] is None
        assert dev["_excess_deficit_since"] is None
        assert dev["_soc_grid_deficit_since"] is None
        assert dev["force_started"] is False
        assert dev["managed_on"] is False


# ══════════════════════════════════════════════════════════════════
#  Switch penalty (relay protection)
# ══════════════════════════════════════════════════════════════════


class TestSwitchPenalty:
    def test_no_penalty_below_threshold(self, make_manager, make_device, now):
        mgr = make_manager([make_device()])
        dev = mgr.devices[0]
        dev["_switch_times"] = [now - timedelta(minutes=i) for i in range(2)]
        assert mgr._get_switch_penalty(dev, now) == 1.0

    def test_penalty_tiers(self, make_manager, make_device, now):
        mgr = make_manager([make_device()])
        dev = mgr.devices[0]

        dev["_switch_times"] = [now - timedelta(minutes=i) for i in range(3)]
        assert mgr._get_switch_penalty(dev, now) == 1.5

        dev["_switch_times"] = [now - timedelta(minutes=i) for i in range(5)]
        assert mgr._get_switch_penalty(dev, now) == 2.0

        dev["_switch_times"] = [now - timedelta(minutes=i) for i in range(7)]
        assert mgr._get_switch_penalty(dev, now) == 3.0

    def test_penalty_ignores_entries_older_than_one_hour(
            self, make_manager, make_device, now):
        mgr = make_manager([make_device()])
        dev = mgr.devices[0]
        dev["_switch_times"] = [now - timedelta(hours=2) for _ in range(10)]
        assert mgr._get_switch_penalty(dev, now) == 1.0
        assert dev["_switch_times"] == []  # pruned


# ══════════════════════════════════════════════════════════════════
#  Startup detection state machine
# ══════════════════════════════════════════════════════════════════


class TestStartupDetection:
    def test_standby_waits_for_power_above_threshold(
            self, make_manager, make_device, now):
        mgr = make_manager([make_device(
            startup_detection=True,
            sd_power_threshold=5,
            sd_detection_time=5,
        )])
        dev = mgr.devices[0]
        mgr.hass.states["switch.test_device"] = "on"

        counted, freed = mgr._handle_startup_detection(
            dev, 0, 80, actual_power=2, now=now, excess=0)
        assert counted is False
        assert freed == 0
        assert dev["sd_state"] == SD_STATE_STANDBY

    def test_standby_to_detected_after_power_persists(
            self, make_manager, make_device, now):
        mgr = make_manager([make_device(
            startup_detection=True,
            sd_power_threshold=5,
            sd_detection_time=5,
        )])
        dev = mgr.devices[0]
        mgr.hass.states["switch.test_device"] = "on"
        dev["sd_state"] = SD_STATE_STANDBY

        # First sighting: arm the timer.
        mgr._handle_startup_detection(
            dev, 0, 80, actual_power=50, now=now, excess=0)
        assert dev["sd_power_above_since"] == now

        # 6 seconds later → detection threshold crossed → state advances
        # through DETECTED straight into WAITING in the same cycle.
        later = now + timedelta(seconds=6)
        mgr._handle_startup_detection(
            dev, 0, 80, actual_power=50, now=later, excess=0)
        assert dev["sd_state"] == SD_STATE_WAITING

    def test_waiting_enforces_device_off(
            self, make_manager, make_device, now):
        """Guard against Shelly 'restore last state' restoring ON."""
        mgr = make_manager([make_device(startup_detection=True)])
        dev = mgr.devices[0]
        dev["sd_state"] = SD_STATE_WAITING
        mgr.hass.states["switch.test_device"] = "on"  # ghost-restored

        mgr._handle_startup_detection(
            dev, 0, 80, actual_power=500, now=now, excess=0)
        assert mgr.hass.states["switch.test_device"] == "off"

    def test_waiting_starts_running_when_excess_sufficient(
            self, make_manager, make_device, now):
        mgr = make_manager([make_device(
            startup_detection=True,
            nominal_power=1000,
            hysteresis_on=200,
            debounce_on=0,
        )])
        dev = mgr.devices[0]
        dev["sd_state"] = SD_STATE_WAITING
        mgr.hass.states["switch.test_device"] = "off"

        # First call arms debounce_on timer (even at zero).
        counted, freed = mgr._handle_startup_detection(
            dev, 2000, 80, actual_power=0, now=now, excess=2000)
        assert counted is False
        assert dev["excess_since"] == now

        # Second call: debounce 0 seconds satisfied → start.
        later = now + timedelta(seconds=1)
        counted, freed = mgr._handle_startup_detection(
            dev, 2000, 80, actual_power=0, now=later, excess=2000)
        assert dev["sd_state"] == SD_STATE_RUNNING
        assert counted is True
        assert freed == 1000
        assert dev["_scheduling_reason"] == "excess_sufficient"

    def test_running_smart_finish_after_low_power_period(
            self, make_manager, make_device, now):
        mgr = make_manager([make_device(
            startup_detection=True,
            sd_finish_power=5,
            sd_finish_time=600,
            sd_min_runtime=300,
        )])
        dev = mgr.devices[0]
        dev["sd_state"] = SD_STATE_RUNNING
        dev["sd_running_since"] = now - timedelta(seconds=3600)
        dev["sd_lockout_until"] = now + timedelta(hours=1)
        dev["sd_power_below_since"] = now - timedelta(seconds=601)
        mgr.hass.states["switch.test_device"] = "on"

        counted, freed = mgr._handle_startup_detection(
            dev, 0, 80, actual_power=2, now=now, excess=0)
        assert dev["sd_state"] == SD_STATE_STANDBY  # reset after finish
        assert counted is False

    def test_running_max_runtime_forces_finish(
            self, make_manager, make_device, now):
        mgr = make_manager([make_device(startup_detection=True)])
        dev = mgr.devices[0]
        dev["sd_state"] = SD_STATE_RUNNING
        dev["sd_running_since"] = now - timedelta(hours=4)
        dev["sd_lockout_until"] = now - timedelta(seconds=1)  # already expired
        mgr.hass.states["switch.test_device"] = "on"

        mgr._handle_startup_detection(
            dev, 0, 80, actual_power=800, now=now, excess=0)
        assert dev["sd_state"] == SD_STATE_STANDBY


# ══════════════════════════════════════════════════════════════════
#  Preemption (v1.7.7 over-shedding fix)
# ══════════════════════════════════════════════════════════════════


class TestPreemptForSD:
    def test_does_not_preempt_when_no_deficit(
            self, make_manager, make_device, now):
        mgr = make_manager([
            make_device(name="SD", priority=80, startup_detection=True),
            make_device(name="Low", priority=10, switch_entity="switch.low"),
        ])
        sd = mgr.devices[0]
        low = mgr.devices[1]
        low["_cached_on"] = True
        low["managed_on"] = True
        mgr.hass.states["switch.low"] = "on"

        # turnon_excess already covers need → no preemption.
        freed = mgr._preempt_for_sd(
            sd_device=sd, needed_w=1000, turnon_excess=1500,
            battery_soc=80, soc_threshold=20, now=now, excess=1500)
        assert freed == 0
        assert mgr.hass.states["switch.low"] == "on"

    def test_preempts_single_lower_priority_device(
            self, make_manager, make_device, now):
        mgr = make_manager([
            make_device(name="SD", priority=80, startup_detection=True,
                        nominal_power=1200),
            make_device(name="Low", priority=10, nominal_power=800,
                        switch_entity="switch.low"),
        ])
        sd = mgr.devices[0]
        low = mgr.devices[1]
        low["_cached_on"] = True
        low["managed_on"] = True
        low["on_since"] = now - timedelta(hours=1)
        mgr.hass.states["switch.low"] = "on"

        # SD needs 1200, turnon_excess = 500 → deficit = 700.
        # Low draws 800 → one victim is enough.
        freed = mgr._preempt_for_sd(
            sd_device=sd, needed_w=1200, turnon_excess=500,
            battery_soc=80, soc_threshold=20, now=now, excess=500)
        assert freed == 800
        assert mgr.hass.states["switch.low"] == "off"

    def test_refuses_to_preempt_higher_priority_device(
            self, make_manager, make_device, now):
        mgr = make_manager([
            make_device(name="SD", priority=50, startup_detection=True),
            make_device(name="High", priority=90, nominal_power=1200,
                        switch_entity="switch.high"),
        ])
        # DeviceManager sorts by priority desc in __init__, so look up by name.
        sd = next(d for d in mgr.devices if d["name"] == "SD")
        high = next(d for d in mgr.devices if d["name"] == "High")
        high["_cached_on"] = True
        high["managed_on"] = True
        mgr.hass.states["switch.high"] = "on"

        freed = mgr._preempt_for_sd(
            sd_device=sd, needed_w=1000, turnon_excess=0,
            battery_soc=80, soc_threshold=20, now=now, excess=0)
        assert freed == 0
        assert mgr.hass.states["switch.high"] == "on"

    def test_drops_redundant_victims_to_minimise_over_shed(
            self, make_manager, make_device, now):
        """v1.7.7 fix: if a 800W device alone covers a 700W deficit, a 500W
        sibling that was greedily planned must be dropped."""
        mgr = make_manager([
            make_device(name="SD", priority=90, startup_detection=True,
                        nominal_power=1200),
            make_device(name="Small", priority=20, nominal_power=500,
                        switch_entity="switch.small"),
            make_device(name="Big", priority=10, nominal_power=800,
                        switch_entity="switch.big"),
        ])
        sd = mgr.devices[0]
        small, big = mgr.devices[1], mgr.devices[2]
        for d, eid in [(small, "switch.small"), (big, "switch.big")]:
            d["_cached_on"] = True
            d["managed_on"] = True
            d["on_since"] = now - timedelta(hours=1)
            mgr.hass.states[eid] = "on"

        # SD needs 1200, turnon_excess=500 → deficit=700.
        # Greedy (priority-asc): Big first (800) → covers alone.
        # Small should NOT be turned off.
        freed = mgr._preempt_for_sd(
            sd_device=sd, needed_w=1200, turnon_excess=500,
            battery_soc=80, soc_threshold=20, now=now, excess=500)
        assert freed == 800
        assert mgr.hass.states["switch.big"] == "off"
        assert mgr.hass.states["switch.small"] == "on"  # preserved

    def test_refuses_non_interruptible_victims(
            self, make_manager, make_device, now):
        mgr = make_manager([
            make_device(name="SD", priority=80, startup_detection=True),
            make_device(name="Pinned", priority=10, interruptible=False,
                        nominal_power=1000, switch_entity="switch.pinned"),
        ])
        sd = mgr.devices[0]
        pinned = mgr.devices[1]
        pinned["_cached_on"] = True
        pinned["managed_on"] = True
        mgr.hass.states["switch.pinned"] = "on"

        freed = mgr._preempt_for_sd(
            sd_device=sd, needed_w=1000, turnon_excess=0,
            battery_soc=80, soc_threshold=20, now=now, excess=0)
        assert freed == 0

    def test_respects_victim_min_on_time(
            self, make_manager, make_device, now):
        mgr = make_manager([
            make_device(name="SD", priority=80, startup_detection=True),
            make_device(name="Fresh", priority=10, nominal_power=1000,
                        min_on_time=600, switch_entity="switch.fresh"),
        ])
        sd = mgr.devices[0]
        fresh = mgr.devices[1]
        fresh["_cached_on"] = True
        fresh["managed_on"] = True
        fresh["on_since"] = now - timedelta(seconds=30)  # too young
        mgr.hass.states["switch.fresh"] = "on"

        freed = mgr._preempt_for_sd(
            sd_device=sd, needed_w=1000, turnon_excess=0,
            battery_soc=80, soc_threshold=20, now=now, excess=0)
        assert freed == 0


# ══════════════════════════════════════════════════════════════════
#  Integration: update()
# ══════════════════════════════════════════════════════════════════


class TestUpdateLoop:
    def test_battery_charging_turns_off_all_regular_devices(
            self, make_manager, make_device, shared_state):
        mgr = make_manager([
            make_device(name="A", switch_entity="switch.a"),
            make_device(name="B", switch_entity="switch.b"),
        ])
        mgr.devices[0]["managed_on"] = True
        mgr.devices[1]["managed_on"] = True
        mgr.hass.states["switch.a"] = "on"
        mgr.hass.states["switch.b"] = "on"

        shared_state["battery_mode"] = MODE_CHARGING
        mgr.update(shared_state)

        assert mgr.hass.states["switch.a"] == "off"
        assert mgr.hass.states["switch.b"] == "off"

    def test_battery_charging_preserves_sd_standby_device(
            self, make_manager, make_device, shared_state):
        mgr = make_manager([
            make_device(name="Washer", switch_entity="switch.washer",
                        startup_detection=True),
        ])
        mgr.devices[0]["sd_state"] = SD_STATE_STANDBY
        mgr.hass.states["switch.washer"] = "on"

        shared_state["battery_mode"] = MODE_CHARGING
        mgr.update(shared_state)
        # SD standby must stay ON so detection keeps working.
        assert mgr.hass.states["switch.washer"] == "on"

    def test_priority_shedding_drops_redundant_victims(
            self, make_manager, make_device, shared_state, now):
        """Mirror of the preemption fix in the main update() loop."""
        mgr = make_manager([
            make_device(name="Small", switch_entity="switch.small",
                        priority=20, nominal_power=500,
                        interruptible=True, min_on_time=0,
                        debounce_off=0, hysteresis_off=100),
            make_device(name="Big", switch_entity="switch.big",
                        priority=10, nominal_power=800,
                        interruptible=True, min_on_time=0,
                        debounce_off=0, hysteresis_off=100),
        ])
        small, big = mgr.devices[0], mgr.devices[1]
        for d, eid in [(small, "switch.small"), (big, "switch.big")]:
            d["managed_on"] = True
            d["on_since"] = now - timedelta(hours=1)
            d["_excess_deficit_since"] = now - timedelta(seconds=3600)
            mgr.hass.states[eid] = "on"

        # Deficit of 700W → Big alone (800W) covers; Small should survive.
        shared_state["excess_for_devices"] = -700
        shared_state["excess_raw_for_devices"] = -700

        mgr.update(shared_state)

        assert mgr.hass.states["switch.big"] == "off"
        assert mgr.hass.states["switch.small"] == "on"

    def test_manual_override_is_not_touched_by_update(
            self, make_manager, make_device, shared_state):
        from custom_components.aurum.const import override_entity_id

        mgr = make_manager([make_device(name="X", switch_entity="switch.x")])
        dev = mgr.devices[0]
        mgr.hass.states["switch.x"] = "on"
        mgr.hass.states[override_entity_id(dev["slug"])] = "on"

        shared_state["excess_for_devices"] = -5000  # big deficit
        shared_state["excess_raw_for_devices"] = -5000
        mgr.update(shared_state)
        # Manual override: AURUM hands off → switch stays on.
        assert mgr.hass.states["switch.x"] == "on"


# ══════════════════════════════════════════════════════════════════
#  _deadline_urgent
# ══════════════════════════════════════════════════════════════════


class TestDeadline:
    def test_returns_false_without_muss_heute(
            self, make_manager, make_device, now):
        mgr = make_manager([make_device(
            deadline="13:00", estimated_runtime=60)])
        dev = mgr.devices[0]
        # muss_heute switch not set → deadline does not apply.
        assert mgr._deadline_urgent(dev, now) is False

    def test_urgent_when_remaining_time_under_runtime_plus_buffer(
            self, make_manager, make_device, now):
        from custom_components.aurum.const import muss_heute_entity_id

        mgr = make_manager([make_device(
            deadline="13:00", estimated_runtime=60)])
        dev = mgr.devices[0]
        mgr.hass.states[muss_heute_entity_id(dev["slug"])] = "on"
        # now=12:00, deadline=13:00 → 60 min remaining, runtime 60 min
        # + 5 min buffer → urgent.
        assert mgr._deadline_urgent(dev, now) is True

    def test_not_urgent_when_plenty_of_time(
            self, make_manager, make_device, now):
        from custom_components.aurum.const import muss_heute_entity_id

        mgr = make_manager([make_device(
            deadline="20:00", estimated_runtime=30)])
        dev = mgr.devices[0]
        mgr.hass.states[muss_heute_entity_id(dev["slug"])] = "on"
        # 8h remaining, only 30 min runtime → not urgent.
        assert mgr._deadline_urgent(dev, now) is False

    def test_malformed_deadline_returns_false_gracefully(
            self, make_manager, make_device, now):
        from custom_components.aurum.const import muss_heute_entity_id

        mgr = make_manager([make_device(
            deadline="not-a-time", estimated_runtime=60)])
        dev = mgr.devices[0]
        mgr.hass.states[muss_heute_entity_id(dev["slug"])] = "on"
        assert mgr._deadline_urgent(dev, now) is False
