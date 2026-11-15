"""
PV-gate release must act even when the meter shows no import (audit #5).

A device started by the PV gate (pv_power_threshold) stops when PV falls
below threshold minus hysteresis_off, or when SOC falls below the device's
soc_threshold, after debounce_off. Up to 1.16.3 that stop only went through
the deficit-limited shedding stage, so with no visible import (the battery
feeds the pump, no battery power sensors) the pump kept running all day.
"""

from datetime import timedelta

SW = "switch.pool"


def _shared(now, excess=0, pv=300, soc=80):
    return {
        "now": now,
        "excess_for_devices": excess,
        "excess_raw_for_devices": excess,
        "grid_power_ema_asym": -excess,
        "battery_soc": soc,
        "battery_mode": "normal",
        "device_budget_w": None,
        "pv_power": pv,
        "surplus_blind": False,
    }


def _running(dev, now, reason="solar_pv"):
    dev["managed_on"] = True
    dev["on_since"] = now - timedelta(hours=1)
    dev["_runtime_tick"] = now
    dev["_scheduling_reason"] = reason


def _run(mgr, start, minutes, **kw):
    t = start
    end = start + timedelta(minutes=minutes)
    while t <= end:
        mgr.update(_shared(t, **kw))
        t += timedelta(seconds=30)
    return t


def _pool(make_manager, make_device, **over):
    cfg = dict(switch_entity=SW, name="Pool", pv_power_threshold=1000,
               soc_threshold=25, nominal_power=600, debounce_off=600,
               hysteresis_off=100)
    cfg.update(over)
    return make_manager([make_device(**cfg)])


class TestReleaseWithoutVisibleImport:
    def test_pv_below_threshold_stops_at_zero_surplus(
            self, hass, make_manager, make_device, now):
        mgr = _pool(make_manager, make_device)
        hass.states[SW] = "on"
        _running(mgr.devices[0], now)
        _run(mgr, now, 12, excess=0, pv=300, soc=80)
        assert hass.states[SW] == "off"

    def test_soc_below_threshold_stops_at_zero_surplus(
            self, hass, make_manager, make_device, now):
        # PV is fine, but the battery fell below the pool's threshold.
        mgr = _pool(make_manager, make_device)
        hass.states[SW] = "on"
        _running(mgr.devices[0], now)
        _run(mgr, now, 12, excess=0, pv=2000, soc=20)
        assert hass.states[SW] == "off"

    def test_stops_with_a_small_surplus(
            self, hass, make_manager, make_device, now):
        # 100 W export with the 600 W pump on: a surplus start would need
        # 600 + 200 + 100, so the gate's stop stands.
        mgr = _pool(make_manager, make_device)
        hass.states[SW] = "on"
        _running(mgr.devices[0], now)
        _run(mgr, now, 12, excess=100, pv=300, soc=80)
        assert hass.states[SW] == "off"

    def test_stops_even_with_a_large_surplus(
            self, hass, make_manager, make_device, now):
        # The gate's release stands; the surplus path may start the pump
        # again later (min_off_time + debounce_on), as a surplus run.
        mgr = _pool(make_manager, make_device)
        hass.states[SW] = "on"
        _running(mgr.devices[0], now)
        _run(mgr, now, 12, excess=400, pv=300, soc=80)
        assert hass.states[SW] == "off"

    def test_battery_fed_pump_drawing_above_nominal_stops(
            self, hass, make_manager, make_device, now):
        # Review of a reverted shortcut: a measured draw above nominal at
        # 0 W export must not count as surplus that keeps it running.
        mgr = _pool(make_manager, make_device,
                    power_entity="sensor.pool_power")
        hass.states["sensor.pool_power"] = "900"
        hass.states[SW] = "on"
        _running(mgr.devices[0], now)
        _run(mgr, now, 12, excess=0, pv=300, soc=80)
        assert hass.states[SW] == "off"

    def test_battery_fed_pump_without_margins_stops(
            self, hass, make_manager, make_device, now):
        mgr = _pool(make_manager, make_device, hysteresis_on=0,
                    residual_power=0)
        hass.states[SW] = "on"
        _running(mgr.devices[0], now)
        _run(mgr, now, 12, excess=0, pv=300, soc=80)
        assert hass.states[SW] == "off"

    def test_soc_below_threshold_stops_despite_surplus(
            self, hass, make_manager, make_device, now):
        mgr = _pool(make_manager, make_device)
        hass.states[SW] = "on"
        _running(mgr.devices[0], now)
        _run(mgr, now, 12, excess=400, pv=300, soc=20)
        assert hass.states[SW] == "off"


class TestGuards:
    def test_held_while_pv_within_hysteresis(
            self, hass, make_manager, make_device, now):
        mgr = _pool(make_manager, make_device)
        hass.states[SW] = "on"
        _running(mgr.devices[0], now)
        _run(mgr, now, 20, excess=0, pv=950, soc=80)  # >= 1000 - 100
        assert hass.states[SW] == "on"

    def test_waits_for_debounce_off(
            self, hass, make_manager, make_device, now):
        mgr = _pool(make_manager, make_device)
        hass.states[SW] = "on"
        _running(mgr.devices[0], now)
        _run(mgr, now, 8, excess=0, pv=300, soc=80)  # < 600 s
        assert hass.states[SW] == "on"

    def test_non_interruptible_is_not_stopped(
            self, hass, make_manager, make_device, now):
        mgr = _pool(make_manager, make_device, interruptible=False)
        hass.states[SW] = "on"
        _running(mgr.devices[0], now)
        _run(mgr, now, 15, excess=0, pv=300, soc=80)
        assert hass.states[SW] == "on"

    def test_forced_stop_counts_toward_the_deficit(
            self, hass, make_manager, make_device, now):
        # A 1000 W heater with an excess deficit and the gated pool both
        # pending: the pool's forced stop frees 600 W, which covers a
        # 400 W deficit, so the heater is not shed as well.
        mgr = make_manager([
            make_device(switch_entity=SW, name="Pool", pv_power_threshold=1000,
                        soc_threshold=25, nominal_power=600, priority=80,
                        debounce_off=600, hysteresis_off=100),
            make_device(switch_entity="switch.heater", name="Heater",
                        nominal_power=1000, priority=10, debounce_off=600,
                        hysteresis_off=100),
        ])
        hass.states[SW] = "on"
        hass.states["switch.heater"] = "on"
        _running(mgr.devices[0], now)
        _running(mgr.devices[1], now, reason="surplus_available")
        _run(mgr, now, 12, excess=-400, pv=300, soc=80)
        assert hass.states[SW] == "off"
        assert hass.states["switch.heater"] == "on"

    def test_stale_release_timer_does_not_skip_debounce_off(
            self, hass, make_manager, make_device, now):
        # A release timer left over from an earlier run (e.g. stopped by
        # another path) must not end the next run on a single low reading.
        mgr = _pool(make_manager, make_device)
        dev = mgr.devices[0]
        dev["_pv_gate_low_since"] = now - timedelta(hours=20)
        dev["excess_since"] = now - timedelta(minutes=10)
        mgr.update(_shared(now, excess=0, pv=1500, soc=80))  # gate start
        assert hass.states[SW] == "on"
        later = now + timedelta(minutes=11)  # past min_on_time
        mgr.update(_shared(later, excess=0, pv=300, soc=80))
        assert hass.states[SW] == "on"

    def test_wall_switch_off_clears_the_release_timer(
            self, hass, make_manager, make_device, now):
        # Timer armed by a dip, then the user switches the pump off at the
        # wall: seen off, the timer is cleared, so a manual restart later
        # is not stopped on its first low reading.
        mgr = _pool(make_manager, make_device)
        dev = mgr.devices[0]
        hass.states[SW] = "on"
        _running(dev, now)
        _run(mgr, now, 5, excess=0, pv=300, soc=80)
        assert dev["_pv_gate_low_since"] is not None
        hass.states[SW] = "off"
        mgr.update(_shared(now + timedelta(minutes=6), excess=0, pv=300))
        assert dev["_pv_gate_low_since"] is None

    def test_override_clears_the_release_timer(
            self, hass, make_manager, make_device, now):
        mgr = _pool(make_manager, make_device)
        dev = mgr.devices[0]
        hass.states[SW] = "on"
        _running(dev, now)
        dev["_pv_gate_low_since"] = now - timedelta(minutes=30)
        hass.states["switch.aurum_pool_override"] = "on"
        mgr.update(_shared(now, excess=0, pv=300, soc=80))
        assert dev["_pv_gate_low_since"] is None
        assert hass.states[SW] == "on"

    def test_price_end_stays_deficit_limited(
            self, hass, make_manager, make_device, now):
        # A cheap-grid device whose price turned expensive, covered by
        # surplus: no off/on, it keeps running (as before this change).
        from tests.conftest import FakePricing
        mgr = make_manager([make_device(
            switch_entity="switch.heater", name="Heater", nominal_power=1000,
            price_mode="cheap_grid", max_price=20, debounce_off=600)])
        mgr.pricing = FakePricing(price_ok=False)
        hass.states["switch.heater"] = "on"
        _running(mgr.devices[0], now, reason="cheap_grid")
        _run(mgr, now, 15, excess=500, pv=3000, soc=80)
        assert hass.states["switch.heater"] == "on"
