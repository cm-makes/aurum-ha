"""
AURUM – Switch Platform
========================
Auto-creates one Manual Override switch and one 'Must Run Today' switch
per configured device. Both switches are persistent via RestoreEntity.

Entity IDs are deterministic:
  switch.aurum_{slug}_override    – pauses AURUM control for the device
  switch.aurum_{slug}_muss_heute  – activates the deadline for the device
"""

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up AURUM override switches for each configured device."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    entities: list = []
    for dev in coordinator.devices.devices:
        slug = dev["slug"]
        name = dev["name"]
        entities.append(AurumManualOverrideSwitch(coordinator, slug, name))
        entities.append(AurumMussHeuteSwitch(coordinator, slug, name))
    async_add_entities(entities)


# ══════════════════════════════════════════════════════════════════
#  BASE CLASS
# ══════════════════════════════════════════════════════════════════

class _AurumBaseSwitch(CoordinatorEntity, RestoreEntity, SwitchEntity):
    """Base class for AURUM device control switches."""

    _attr_should_poll = False

    def __init__(self, coordinator, slug: str, device_name: str,
                 suffix: str, friendly_suffix: str,
                 icon: str) -> None:
        """Initialize switch."""
        super().__init__(coordinator)
        self._slug = slug
        self._device_name = device_name
        self._attr_is_on = False
        self._attr_unique_id = f"aurum_{slug}_{suffix}"
        self._attr_name = f"{device_name} – {friendly_suffix}"
        self._attr_icon = icon
        self._attr_entity_category = EntityCategory.CONFIG
        # Force deterministic entity_id so devices.py can derive it
        self.entity_id = f"switch.aurum_{slug}_{suffix}"

    async def async_added_to_hass(self) -> None:
        """Restore previous state after HA restart."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._attr_is_on = last_state.state == "on"
            _LOGGER.debug(
                "AURUM switch %s restored: %s",
                self.entity_id,
                "on" if self._attr_is_on else "off",
            )
        # Always write state so HA sees the correct value immediately
        self.async_write_ha_state()

    def _handle_coordinator_update(self) -> None:
        """No-op: switch state is self-managed, not derived from coordinator."""

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the switch on."""
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the switch off."""
        self._attr_is_on = False
        self.async_write_ha_state()


# ══════════════════════════════════════════════════════════════════
#  MANUAL OVERRIDE SWITCH
# ══════════════════════════════════════════════════════════════════

class AurumManualOverrideSwitch(_AurumBaseSwitch):
    """Switch that pauses AURUM control for a device.

    When ON, AURUM will not touch the device in any cycle.
    The device can then be controlled manually via its own switch.
    """

    def __init__(self, coordinator, slug: str, device_name: str) -> None:
        """Initialize manual override switch."""
        super().__init__(
            coordinator=coordinator,
            slug=slug,
            device_name=device_name,
            suffix="override",
            friendly_suffix="Manual Override",
            icon="mdi:account-lock-open",
        )


# ══════════════════════════════════════════════════════════════════
#  MUST RUN TODAY SWITCH
# ══════════════════════════════════════════════════════════════════

class AurumMussHeuteSwitch(_AurumBaseSwitch):
    """Switch that tells AURUM this device must run today.

    When ON, the configured deadline becomes active. If the device
    has not finished by the deadline, AURUM will force-start it
    even without solar surplus (grid power).

    Auto-resets to OFF after the program completes (handled by
    DeviceManager._reset_muss_heute via hass.services.call).
    """

    def __init__(self, coordinator, slug: str, device_name: str) -> None:
        """Initialize must-run-today switch."""
        super().__init__(
            coordinator=coordinator,
            slug=slug,
            device_name=device_name,
            suffix="muss_heute",
            friendly_suffix="Muss heute",
            icon="mdi:calendar-check",
        )
