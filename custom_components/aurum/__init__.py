"""
AURUM – Solar Surplus Optimizer
================================
Automatically distributes PV surplus power to household devices
based on priority, battery SOC thresholds, and available excess.

Home Assistant custom integration using DataUpdateCoordinator.
"""

import asyncio
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PLATFORMS
from .coordinator import AurumCoordinator

_LOGGER = logging.getLogger(__name__)

SETUP_TIMEOUT = 30


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload integration when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up AURUM from a config entry."""
    try:
        coordinator = AurumCoordinator(hass, entry)

        await asyncio.wait_for(
            coordinator.async_setup(), timeout=SETUP_TIMEOUT)

        await asyncio.wait_for(
            coordinator.async_config_entry_first_refresh(),
            timeout=SETUP_TIMEOUT)

    except asyncio.TimeoutError:
        _LOGGER.error("AURUM setup timed out – integration disabled")
        return False
    except Exception as e:
        _LOGGER.error("AURUM setup failed: %s", e)
        return False

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
    }

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload AURUM config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    await coordinator.async_shutdown()

    unload_ok = await hass.config_entries.async_unload_platforms(
        entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
