"""
Regression tests for the manual-override contract in the battery-charging
emergency loop (``DeviceManager.update()``, ``MODE_CHARGING`` branch).

The override switch (``switch.aurum_{slug}_override``) promises AURUM will not
touch the device in ANY cycle. Before the fix the emergency loop force-off
every running device, aborting externally-driven cycles (e.g. an
anti-legionella water-heater boost) when battery SOC dropped to ``min_soc``.
These tests lock in the fix and guard the emergency path still working when the
device is NOT overridden.
"""

from custom_components.aurum.const import override_entity_id, MODE_CHARGING


class TestOverrideDuringChargingEmergency:
    def test_override_protects_device_in_emergency(
            self, make_manager, make_device, shared_state):
        mgr = make_manager([make_device(
            name="Water Heater", switch_entity="switch.wh",
            condition_entity="sensor.wh_temp", condition_value=48)])
        dev = mgr.devices[0]
        dev["managed_on"] = True
        mgr.hass.states["switch.wh"] = "on"
        # Run condition above threshold (mirrors an anti-legionella boost).
        mgr.hass.states["sensor.wh_temp"] = "55"
        mgr.hass.states[override_entity_id(dev["slug"])] = "on"

        shared_state["battery_mode"] = MODE_CHARGING
        mgr.update(shared_state)

        # Contract: an overridden device is untouched even in the emergency.
        assert mgr.hass.states["switch.wh"] == "on"
        assert ("OFF", "switch.wh") not in mgr.hass.actions
        # on_since is anchored so min-on-time protection stays coherent.
        assert dev["on_since"] is not None

    def test_emergency_still_sheds_unoverridden_device(
            self, make_manager, make_device, shared_state):
        mgr = make_manager([make_device(
            name="Water Heater", switch_entity="switch.wh")])
        dev = mgr.devices[0]
        dev["managed_on"] = True
        mgr.hass.states["switch.wh"] = "on"
        # No override configured.

        shared_state["battery_mode"] = MODE_CHARGING
        mgr.update(shared_state)

        # Regression guard: the emergency must still shed a normal device.
        assert mgr.hass.states["switch.wh"] == "off"
        assert ("OFF", "switch.wh") in mgr.hass.actions
