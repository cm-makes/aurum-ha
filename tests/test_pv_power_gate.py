"""
Unit tests for the per-device raw-PV run gate (``pv_power_threshold``).

The gate runs a device whenever actual PV generation >= the threshold AND
battery SOC >= the device ``soc_threshold``, bypassing the daily budget cap.
See ``devices.py``: ``_pv_gate_ok`` / ``_should_turn_on`` / ``_should_turn_off``.
"""

from datetime import timedelta


class TestPVGateOk:
    def test_open_when_pv_and_soc_ok(self, make_manager, make_device):
        mgr = make_manager([make_device(pv_power_threshold=1000)])
        mgr._pv_power_now = 1200
        assert mgr._pv_gate_ok(mgr.devices[0], 80, 25) is True

    def test_closed_when_soc_below(self, make_manager, make_device):
        mgr = make_manager([make_device(pv_power_threshold=1000)])
        mgr._pv_power_now = 1200
        assert mgr._pv_gate_ok(mgr.devices[0], 20, 25) is False

    def test_closed_when_pv_below(self, make_manager, make_device):
        mgr = make_manager([make_device(pv_power_threshold=1000)])
        mgr._pv_power_now = 900
        assert mgr._pv_gate_ok(mgr.devices[0], 80, 25) is False

    def test_disabled_by_default(self, make_manager, make_device):
        mgr = make_manager([make_device()])  # no pv_power_threshold → 0
        mgr._pv_power_now = 5000
        assert mgr._pv_gate_ok(mgr.devices[0], 80, 25) is False


class TestPVGateTurnOn:
    def test_turns_on_via_gate_with_reason(
            self, make_manager, make_device, now):
        mgr = make_manager([make_device(
            pv_power_threshold=1000, debounce_on=0)])
        dev = mgr.devices[0]
        mgr._pv_power_now = 1200
        dev["excess_since"] = now - timedelta(seconds=1)
        assert mgr._should_turn_on(dev, 0, 0, 80, 25, now) is True
        assert dev["_scheduling_reason"] == "solar_pv"

    def test_debounce_delays_start(self, make_manager, make_device, now):
        mgr = make_manager([make_device(
            pv_power_threshold=1000, debounce_on=300)])
        dev = mgr.devices[0]
        mgr._pv_power_now = 1200
        # First evaluation only arms the debounce timer.
        assert mgr._should_turn_on(dev, 0, 0, 80, 25, now) is False
        assert dev["excess_since"] == now


class TestPVGateBudgetBypass:
    def _shared(self, now, **over):
        s = {
            "now": now, "excess_for_devices": 0, "excess_raw_for_devices": 0,
            "grid_power_ema_asym": 0, "battery_soc": 80,
            "battery_mode": "normal", "device_budget_w": 0, "pv_power": 1200,
        }
        s.update(over)
        return s

    def test_gate_bypasses_zero_budget(self, make_manager, make_device, now):
        # Budget 0 (all solar reserved for battery) would normally block a
        # battery-powered start — the PV gate is exempt and starts anyway.
        mgr = make_manager([make_device(
            switch_entity="switch.pool", pv_power_threshold=1000,
            soc_threshold=25, debounce_on=0)])
        mgr.devices[0]["excess_since"] = now  # pre-arm debounce
        mgr.update(self._shared(now))
        assert mgr.hass.states.get("switch.pool") == "on"

    def test_gate_off_honours_budget(self, make_manager, make_device, now):
        # Regression: with the gate disabled the budget cap still blocks.
        mgr = make_manager([make_device(
            switch_entity="switch.pool", pv_power_threshold=0,
            debounce_on=0)])
        mgr.devices[0]["excess_since"] = now
        mgr.update(self._shared(now, pv_power=5000))
        assert mgr.hass.states.get("switch.pool") != "on"


class TestPVGateTurnOff:
    def _dev_on(self, mgr, now):
        dev = mgr.devices[0]
        dev["_scheduling_reason"] = "solar_pv"
        dev["on_since"] = now - timedelta(seconds=700)  # past min_on_time
        dev["force_started"] = False
        return dev

    def test_holds_while_pv_high(self, make_manager, make_device, now):
        mgr = make_manager([make_device(pv_power_threshold=1000)])
        dev = self._dev_on(mgr, now)
        mgr._pv_power_now = 1000
        dev["_pv_gate_low_since"] = None
        assert mgr._should_turn_off(dev, 0, 80, 25, now) is None

    def test_releases_when_pv_drops(self, make_manager, make_device, now):
        mgr = make_manager([make_device(pv_power_threshold=1000)])
        dev = self._dev_on(mgr, now)
        mgr._pv_power_now = 800
        dev["_pv_gate_low_since"] = now - timedelta(seconds=700)
        assert mgr._should_turn_off(
            dev, 0, 80, 25, now) == "pv_below_threshold"

    def test_releases_when_soc_drops(self, make_manager, make_device, now):
        mgr = make_manager([make_device(pv_power_threshold=1000)])
        dev = self._dev_on(mgr, now)
        mgr._pv_power_now = 1500
        dev["_pv_gate_low_since"] = now - timedelta(seconds=700)
        assert mgr._should_turn_off(
            dev, 0, 20, 25, now) == "pv_below_threshold"
