"""
Unit tests for the v1.11.0 features:

- battery_priority flag (discussion #9): surplus = grid export only
- per-device run condition (discussion #5): entity below/above threshold
"""

from datetime import timedelta

from custom_components.aurum.modules.energy import EnergyManager


# ══════════════════════════════════════════════════════════════════
#  battery_priority (EnergyManager surplus semantics)
# ══════════════════════════════════════════════════════════════════


class TestBatteryPriority:
    CFG = {
        "grid_power_entity": "sensor.grid",
        "battery_soc_entity": "sensor.soc",
        "battery_charge_power_entity": "sensor.bat_charge",
        "battery_discharge_power_entity": "sensor.bat_discharge",
    }

    def _run(self, hass, battery_priority):
        hass.states["sensor.grid"] = "-100"        # 100 W export
        hass.states["sensor.soc"] = "70"
        hass.states["sensor.bat_charge"] = "2000"  # battery absorbing 2 kW
        hass.states["sensor.bat_discharge"] = "0"
        mgr = EnergyManager(
            hass, {**self.CFG, "battery_priority": battery_priority})
        shared = {}
        mgr.update(shared)
        return shared

    def test_legacy_counts_battery_charge_as_surplus(self, hass):
        shared = self._run(hass, battery_priority=False)
        # excess = -(-100) - (0 - 2000) = 100 + 2000
        assert shared["excess_raw"] == 2100.0

    def test_battery_priority_counts_only_grid_export(self, hass):
        shared = self._run(hass, battery_priority=True)
        # Only genuine grid export counts; charging power is untouchable.
        assert shared["excess_raw"] == 100.0

    def test_default_is_legacy_behaviour(self, hass):
        hass.states.update({
            "sensor.grid": "-100", "sensor.soc": "70",
            "sensor.bat_charge": "2000", "sensor.bat_discharge": "0"})
        mgr = EnergyManager(hass, dict(self.CFG))  # no flag set
        shared = {}
        mgr.update(shared)
        assert shared["excess_raw"] == 2100.0


# ══════════════════════════════════════════════════════════════════
#  Per-device run condition
# ══════════════════════════════════════════════════════════════════


class TestConditionMet:
    def test_no_condition_configured_is_met(
            self, make_manager, make_device):
        mgr = make_manager([make_device()])
        assert mgr._condition_met(mgr.devices[0]) is True

    def test_below_met_and_not_met(self, hass, make_manager, make_device):
        mgr = make_manager([make_device(
            condition_entity="sensor.boiler_temp",
            condition_op="below", condition_value=55)])
        dev = mgr.devices[0]
        hass.states["sensor.boiler_temp"] = "48.5"
        assert mgr._condition_met(dev) is True
        hass.states["sensor.boiler_temp"] = "57.0"
        assert mgr._condition_met(dev) is False

    def test_above_met_and_not_met(self, hass, make_manager, make_device):
        mgr = make_manager([make_device(
            condition_entity="sensor.pool_ph",
            condition_op="above", condition_value=7)])
        dev = mgr.devices[0]
        hass.states["sensor.pool_ph"] = "7.4"
        assert mgr._condition_met(dev) is True
        hass.states["sensor.pool_ph"] = "6.8"
        assert mgr._condition_met(dev) is False

    def test_unavailable_sensor_fails_open(
            self, hass, make_manager, make_device):
        mgr = make_manager([make_device(
            condition_entity="sensor.boiler_temp",
            condition_op="below", condition_value=55)])
        dev = mgr.devices[0]
        hass.states["sensor.boiler_temp"] = "unavailable"
        assert mgr._condition_met(dev) is True

    def test_should_turn_on_blocked_when_condition_not_met(
            self, hass, make_manager, make_device, now):
        mgr = make_manager([make_device(
            condition_entity="sensor.boiler_temp",
            condition_op="below", condition_value=55, debounce_on=0)])
        dev = mgr.devices[0]
        dev["excess_since"] = now - timedelta(seconds=1)
        hass.states["sensor.boiler_temp"] = "60"
        assert mgr._should_turn_on(dev, 5000, 0, 80, 20, now) is False
        hass.states["sensor.boiler_temp"] = "40"
        assert mgr._should_turn_on(dev, 5000, 0, 80, 20, now) is True
