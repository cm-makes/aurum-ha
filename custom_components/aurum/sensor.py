"""
AURUM – Sensor Platform
========================
Creates sensors for:
- Global: excess power, battery mode, cycle counter
- Per device: status, power, runtime
"""

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, VERSION


def _device_icon(name: str) -> str:
    """Guess icon from device name."""
    lower = name.lower()
    icons = {
        "wash": "mdi:washing-machine",
        "wasch": "mdi:washing-machine",
        "dish": "mdi:dishwasher",
        "spül": "mdi:dishwasher",
        "heat": "mdi:radiator",
        "heiz": "mdi:radiator",
        "pool": "mdi:pool",
        "charger": "mdi:ev-station",
        "lade": "mdi:ev-station",
    }
    for key, icon in icons.items():
        if key in lower:
            return icon
    return "mdi:power-plug"


def _hub_device_info(entry_id):
    """Return device info for the AURUM hub."""
    return {
        "identifiers": {(DOMAIN, "aurum_hub")},
        "name": "AURUM",
        "manufacturer": "AURUM Community",
        "model": "Solar Surplus Optimizer",
        "sw_version": VERSION,
    }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up AURUM sensors."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    entities = [
        AurumExcessSensor(coordinator, entry),
        AurumBatteryModeSensor(coordinator, entry),
        AurumCycleSensor(coordinator, entry),
    ]

    for dev_state in coordinator.device_states:
        entities.append(
            AurumDeviceStatusSensor(coordinator, entry, dev_state))
        entities.append(
            AurumDevicePowerSensor(coordinator, entry, dev_state))
        entities.append(
            AurumDeviceRuntimeSensor(coordinator, entry, dev_state))

    async_add_entities(entities)


class AurumExcessSensor(CoordinatorEntity, SensorEntity):
    """Sensor showing available excess power."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "W"
    _attr_icon = "mdi:solar-power"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_excess"
        self._attr_name = "AURUM Excess Power"
        self._attr_device_info = _hub_device_info(entry.entry_id)

    @callback
    def _handle_coordinator_update(self):
        data = self.coordinator.data or {}
        self._attr_native_value = data.get("excess", 0)
        self.async_write_ha_state()


class AurumBatteryModeSensor(CoordinatorEntity, SensorEntity):
    """Sensor showing current battery mode."""

    _attr_icon = "mdi:battery-charging"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_battery_mode"
        self._attr_name = "AURUM Battery Mode"
        self._attr_device_info = _hub_device_info(entry.entry_id)

    @callback
    def _handle_coordinator_update(self):
        data = self.coordinator.data or {}
        self._attr_native_value = data.get("battery_mode", "unknown")
        self.async_write_ha_state()


class AurumCycleSensor(CoordinatorEntity, SensorEntity):
    """Diagnostic: cycle counter."""

    _attr_entity_category = "diagnostic"
    _attr_icon = "mdi:counter"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_cycle"
        self._attr_name = "AURUM Cycle"
        self._attr_device_info = _hub_device_info(entry.entry_id)

    @callback
    def _handle_coordinator_update(self):
        data = self.coordinator.data or {}
        self._attr_native_value = data.get("cycle", 0)
        self.async_write_ha_state()


class AurumDeviceStatusSensor(CoordinatorEntity, SensorEntity):
    """Per-device status sensor."""

    def __init__(self, coordinator, entry, dev_state):
        super().__init__(coordinator)
        slug = dev_state["slug"]
        self._dev_name = dev_state["name"]
        self._attr_unique_id = f"{entry.entry_id}_{slug}"
        self._attr_name = f"AURUM {self._dev_name}"
        self._attr_icon = _device_icon(self._dev_name)
        self._attr_device_info = _hub_device_info(entry.entry_id)

    @callback
    def _handle_coordinator_update(self):
        for ds in (self.coordinator.device_states or []):
            if ds["name"] == self._dev_name:
                self._attr_native_value = ds.get("state", "off")
                self.async_write_ha_state()
                return
        self._attr_native_value = "unknown"
        self.async_write_ha_state()


class AurumDevicePowerSensor(CoordinatorEntity, SensorEntity):
    """Per-device power sensor."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "W"

    def __init__(self, coordinator, entry, dev_state):
        super().__init__(coordinator)
        slug = dev_state["slug"]
        self._dev_name = dev_state["name"]
        self._attr_unique_id = f"{entry.entry_id}_{slug}_power"
        self._attr_name = f"AURUM {self._dev_name} Power"
        self._attr_icon = "mdi:flash"
        self._attr_device_info = _hub_device_info(entry.entry_id)

    @callback
    def _handle_coordinator_update(self):
        for ds in (self.coordinator.device_states or []):
            if ds["name"] == self._dev_name:
                self._attr_native_value = ds.get("power", 0)
                self.async_write_ha_state()
                return
        self._attr_native_value = 0
        self.async_write_ha_state()


class AurumDeviceRuntimeSensor(CoordinatorEntity, SensorEntity):
    """Per-device runtime today sensor (minutes)."""

    _attr_native_unit_of_measurement = "min"
    _attr_icon = "mdi:timer-outline"

    def __init__(self, coordinator, entry, dev_state):
        super().__init__(coordinator)
        slug = dev_state["slug"]
        self._dev_name = dev_state["name"]
        self._attr_unique_id = f"{entry.entry_id}_{slug}_runtime"
        self._attr_name = f"AURUM {self._dev_name} Runtime"
        self._attr_device_info = _hub_device_info(entry.entry_id)

    @callback
    def _handle_coordinator_update(self):
        for ds in (self.coordinator.device_states or []):
            if ds["name"] == self._dev_name:
                secs = ds.get("runtime_today_s", 0)
                self._attr_native_value = round(secs / 60, 1)
                self.async_write_ha_state()
                return
        self._attr_native_value = 0
        self.async_write_ha_state()
