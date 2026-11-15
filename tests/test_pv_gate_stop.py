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

    def test_stops_even_with_surplus(
            self, hass, make_manager, make_device, now):
        # The README: "a gated device stops on falling sun even while
        # surplus remains".
        mgr = _pool(make_manager, make_device)
        hass.states[SW] = "on"
        _running(mgr.devices[0], now)
        _run(mgr, now, 12, excess=400, pv=300, soc=80)
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
