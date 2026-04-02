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
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, PLATFORMS, CONF_DEVICES
from .coordinator import AurumCoordinator

_LOGGER = logging.getLogger(__name__)

SETUP_TIMEOUT = 30


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload integration when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


def _slugify(name: str) -> str:
    """Convert device name to slug (mirrors modules/helpers.py slugify)."""
    import re
    slug = name.lower().strip()
    slug = re.sub(r"[äÄ]", "ae", slug)
    slug = re.sub(r"[öÖ]", "oe", slug)
    slug = re.sub(r"[üÜ]", "ue", slug)
    slug = re.sub(r"[ß]", "ss", slug)
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    slug = slug.strip("_")
    return slug


async def _async_cleanup_orphaned_entities(
        hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove entity registry entries for devices no longer in config.

    Runs on every setup so stale entities from removed devices are
    cleaned up automatically – even if they were removed before the
    config-flow cleanup fix was deployed.
    """
    devices = entry.options.get(CONF_DEVICES, [])
    active_slugs = {_slugify(d.get("name", "")) for d in devices}

    ent_reg = er.async_get(hass)
    entries = er.async_entries_for_config_entry(ent_reg, entry.entry_id)

    removed = 0
    for entity_entry in entries:
        uid = entity_entry.unique_id or ""
        # AURUM device entity unique_ids follow the pattern:
        #   aurum_{slug}_{sensor_type}   (sensor / binary_sensor / number)
        #   aurum_{slug}_override        (switch)
        #   aurum_{slug}_muss_heute      (switch)
        if not uid.startswith("aurum_"):
            continue
        # Extract slug: second segment of underscore-split uid
        parts = uid.split("_")           # ["aurum", slug_part1, ..., type]
        if len(parts) < 3:
            continue
        # Slug is everything between "aurum_" and the last segment
        entity_slug = "_".join(parts[1:-1])
        if entity_slug not in active_slugs:
            _LOGGER.info(
                "AURUM: removing orphaned entity %s (slug '%s' not in config)",
                entity_entry.entity_id, entity_slug)
            ent_reg.async_remove(entity_entry.entity_id)
            removed += 1

    if removed:
        _LOGGER.info("AURUM: cleaned up %d orphaned entities", removed)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up AURUM from a config entry."""
    # Clean up entities for devices that were removed from config
    await _async_cleanup_orphaned_entities(hass, entry)

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
