"""
AURUM – Number Platform
========================
Creates number entities for:
- Global: target SOC, min SOC
- Per device: SOC threshold
"""

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, VERSION
from .sensor import _hub_device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up AURUM number entities."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    entities = [
        AurumTargetSOC(coordinator, entry),
        AurumMinSOC(coordinator, entry),
    ]

    for dev_state in coordinator.device_states:
        entities.append(
            AurumDeviceSOCThreshold(coordinator, entry, dev_state))

    async_add_entities(entities)


class AurumTargetSOC(CoordinatorEntity, NumberEntity):
    """Number entity: global target SOC."""

    _attr_native_min_value = 10
    _attr_native_max_value = 100
    _attr_native_step = 5
    _attr_native_unit_of_measurement = "%"
    _attr_mode = NumberMode.SLIDER
    _attr_icon = "mdi:battery-charging-high"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_target_soc"
        self._attr_name = "AURUM Target SOC"
        self._attr_device_info = _hub_device_info(entry.entry_id)
        self._attr_native_value = coordinator.battery.target_soc

    async def async_set_native_value(self, value: float) -> None:
        """Update target SOC."""
        self.coordinator.battery.target_soc = int(value)
        self._attr_native_value = int(value)
        self.async_write_ha_state()


class AurumMinSOC(CoordinatorEntity, NumberEntity):
    """Number entity: global minimum SOC."""

    _attr_native_min_value = 0
    _attr_native_max_value = 50
    _attr_native_step = 5
    _attr_native_unit_of_measurement = "%"
    _attr_mode = NumberMode.SLIDER
    _attr_icon = "mdi:battery-alert"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_min_soc"
        self._attr_name = "AURUM Min SOC"
        self._attr_device_info = _hub_device_info(entry.entry_id)
        self._attr_native_value = coordinator.battery.min_soc

    async def async_set_native_value(self, value: float) -> None:
        """Update minimum SOC."""
        self.coordinator.battery.min_soc = int(value)
        self._attr_native_value = int(value)
        self.async_write_ha_state()


class AurumDeviceSOCThreshold(CoordinatorEntity, NumberEntity):
    """Number entity: per-device SOC threshold."""

    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 5
    _attr_native_unit_of_measurement = "%"
    _attr_mode = NumberMode.SLIDER
    _attr_icon = "mdi:battery-50"

    def __init__(self, coordinator, entry, dev_state):
        super().__init__(coordinator)
        slug = dev_state["slug"]
        self._dev_name = dev_state["name"]
        self._attr_unique_id = f"{entry.entry_id}_{slug}_soc_threshold"
        self._attr_name = f"AURUM {self._dev_name} SOC Threshold"
        self._attr_device_info = _hub_device_info(entry.entry_id)

        # Get initial value from device config
        for dev in coordinator.devices.devices:
            if dev["name"] == self._dev_name:
                self._attr_native_value = dev.get("soc_threshold", 20)
                break

    async def async_set_native_value(self, value: float) -> None:
        """Update device SOC threshold."""
        for dev in self.coordinator.devices.devices:
            if dev["name"] == self._dev_name:
                dev["soc_threshold"] = int(value)
                break
        self._attr_native_value = int(value)
        self.async_write_ha_state()
