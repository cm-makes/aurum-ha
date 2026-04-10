"""
AURUM – Time Platform
======================
Creates time entities for:
- Per device: deadline (must finish by HH:MM)
"""

from datetime import time as dt_time

from homeassistant.components.time import TimeEntity
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
    """Set up AURUM time entities."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    entities = []
    for dev_state in coordinator.device_states:
        entities.append(
            AurumDeviceDeadline(coordinator, entry, dev_state))

    async_add_entities(entities)


class AurumDeviceDeadline(CoordinatorEntity, TimeEntity):
    """Time entity: per-device deadline (must finish by).

    When set together with muss_heute switch and estimated_runtime,
    AURUM will force-start the device in time to meet the deadline.
    Set to 00:00 to disable the deadline.
    """

    _attr_icon = "mdi:clock-alert-outline"

    def __init__(self, coordinator, entry, dev_state):
        super().__init__(coordinator)
        slug = dev_state["slug"]
        self._dev_name = dev_state["name"]
        self._attr_unique_id = f"{entry.entry_id}_{slug}_deadline"
        self._attr_name = f"AURUM {self._dev_name} Deadline"
        self._attr_device_info = _hub_device_info(entry.entry_id)

        # Get initial value from device config
        for dev in coordinator.devices.devices:
            if dev["name"] == self._dev_name:
                deadline_str = dev.get("deadline")
                if deadline_str:
                    try:
                        parts = deadline_str.split(":")
                        self._attr_native_value = dt_time(
                            int(parts[0]),
                            int(parts[1]) if len(parts) > 1 else 0)
                    except (ValueError, IndexError):
                        self._attr_native_value = None
                else:
                    self._attr_native_value = None
                break

    async def async_set_value(self, value: dt_time) -> None:
        """Update device deadline."""
        # 00:00 means disabled
        if value.hour == 0 and value.minute == 0:
            deadline_str = None
        else:
            deadline_str = f"{value.hour:02d}:{value.minute:02d}"

        for dev in self.coordinator.devices.devices:
            if dev["name"] == self._dev_name:
                dev["deadline"] = deadline_str
                break

        self._attr_native_value = value if deadline_str else None
        self.async_write_ha_state()
