"""
AURUM – Number Platform
========================
Creates number entities for:
- Global: target SOC, min SOC
- Per device: SOC threshold, max price

User-adjustable values persist across restart/reload via RestoreNumber:
the entity's last native_value is restored in async_added_to_hass and
re-applied to the in-memory model, so slider changes are durable (the
config-flow value is only the initial seed on first creation).
"""

from homeassistant.components.number import (
    NumberEntity, NumberMode, RestoreNumber)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
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
        # Max Price only applies to cheap_grid devices (is_price_ok ignores
        # it for solar_only). Create it only for those, matching the class
        # docstring and avoiding a functionless entity on solar_only devices.
        price_mode = next(
            (d.get("price_mode") for d in coordinator.devices.devices
             if d["name"] == dev_state["name"]), "solar_only")
        if price_mode == "cheap_grid":
            entities.append(
                AurumDeviceMaxPrice(coordinator, entry, dev_state))

    async_add_entities(entities)


class _AurumRestoreNumber(CoordinatorEntity, RestoreNumber):
    """CoordinatorEntity number whose value survives restart/reload.

    Subclasses implement _apply(value) to push the value into the in-memory
    model (battery/device dict) and update _attr_native_value.
    """

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            self._apply(last.native_value)

    async def async_set_native_value(self, value: float) -> None:
        self._apply(value)
        self.async_write_ha_state()

    def _apply(self, value) -> None:
        raise NotImplementedError


class AurumTargetSOC(_AurumRestoreNumber):
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

    def _apply(self, value) -> None:
        self.coordinator.battery.target_soc = int(value)
        # Keep the budget's target in sync so energy-to-target tracks the
        # live slider instead of the value frozen at config init.
        if self.coordinator.budget:
            self.coordinator.budget.set_target_soc(int(value))
        self._attr_native_value = int(value)


class AurumMinSOC(_AurumRestoreNumber):
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

    def _apply(self, value) -> None:
        self.coordinator.battery.min_soc = int(value)
        self._attr_native_value = int(value)


class AurumDeviceSOCThreshold(_AurumRestoreNumber):
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

    def _apply(self, value) -> None:
        for dev in self.coordinator.devices.devices:
            if dev["name"] == self._dev_name:
                dev["soc_threshold"] = int(value)
                break
        self._attr_native_value = int(value)


class AurumDeviceMaxPrice(_AurumRestoreNumber):
    """Number entity: per-device maximum electricity price (ct/kWh).

    Only created for devices with price_mode = cheap_grid.
    Setting to 0 disables the price threshold (uses price level / cheap
    period instead).
    """

    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "ct/kWh"
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:cash-lock"

    def __init__(self, coordinator, entry, dev_state):
        super().__init__(coordinator)
        slug = dev_state["slug"]
        self._dev_name = dev_state["name"]
        self._attr_unique_id = f"{entry.entry_id}_{slug}_max_price"
        self._attr_name = f"AURUM {self._dev_name} Max Price"
        self._attr_device_info = _hub_device_info(entry.entry_id)

        # Get initial value from device config
        for dev in coordinator.devices.devices:
            if dev["name"] == self._dev_name:
                self._attr_native_value = dev.get("max_price", 0)
                break

    def _apply(self, value) -> None:
        for dev in self.coordinator.devices.devices:
            if dev["name"] == self._dev_name:
                dev["max_price"] = round(value, 1)
                break
        self._attr_native_value = round(value, 1)
