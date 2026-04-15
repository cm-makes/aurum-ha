"""
AURUM – Binary Sensor Platform
================================
Creates binary sensors for:
- Per device: active (on/off)
- Global: cheap grid active (any device currently on cheap-grid power)
"""

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, VERSION
from .sensor import _hub_device_info, _device_icon


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up AURUM binary sensors."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    entities = []
    for dev_state in coordinator.device_states:
        entities.append(
            AurumDeviceActiveSensor(coordinator, entry, dev_state))

    # Global cheap-grid flag – exposed so external automations can
    # block battery discharge / switch inverter mode while AURUM is
    # intentionally running devices on cheap grid power.
    entities.append(AurumCheapGridActiveSensor(coordinator, entry))

    async_add_entities(entities)


class AurumDeviceActiveSensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor: is the device currently active?"""

    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(self, coordinator, entry, dev_state):
        super().__init__(coordinator)
        slug = dev_state["slug"]
        self._dev_name = dev_state["name"]
        self._attr_unique_id = f"{entry.entry_id}_{slug}_active"
        self._attr_name = f"AURUM {self._dev_name} Active"
        self._attr_icon = _device_icon(self._dev_name)
        self._attr_device_info = _hub_device_info(entry.entry_id)

    @callback
    def _handle_coordinator_update(self):
        for ds in (self.coordinator.device_states or []):
            if ds["name"] == self._dev_name:
                state = ds.get("state", "off")
                self._attr_is_on = state not in ("off", "done", "standby")
                self.async_write_ha_state()
                return
        self._attr_is_on = False
        self.async_write_ha_state()


class AurumCheapGridActiveSensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor: is any device currently running on cheap grid power?

    Useful for external automations (block battery discharge, switch
    inverter charge mode, etc.) while AURUM is intentionally drawing
    grid power at a low tariff.
    """

    _attr_device_class = BinarySensorDeviceClass.POWER
    _attr_icon = "mdi:cash-lock-open"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_cheap_grid_active"
        self._attr_name = "AURUM Cheap Grid Active"
        self._attr_device_info = _hub_device_info(entry.entry_id)
        self._attr_is_on = False

    @callback
    def _handle_coordinator_update(self):
        data = self.coordinator.data or {}
        self._attr_is_on = bool(data.get("cheap_grid_active", False))
        self.async_write_ha_state()
