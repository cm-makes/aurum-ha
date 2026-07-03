"""
AURUM – Solar Surplus Optimizer
================================
Automatically distributes PV surplus power to household devices
based on priority, battery SOC thresholds, and available excess.

Home Assistant custom integration using DataUpdateCoordinator.
"""

import asyncio
import logging
import os

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, PLATFORMS, CONF_DEVICES, VERSION
from .coordinator import AurumCoordinator
from .modules.helpers import slugify

_LOGGER = logging.getLogger(__name__)

SETUP_TIMEOUT = 30

# ── Dashboard panel ─────────────────────────────────────────────────
PANEL_URL_PATH = "aurum"            # sidebar route → /aurum
PANEL_STATIC_URL = "/aurum_frontend"
PANEL_JS = "aurum-panel.js"
_DATA_STATIC = "_frontend_static_registered"
_DATA_PANEL = "_frontend_panel_registered"


async def _async_register_frontend(hass: HomeAssistant) -> None:
    """Serve the panel JS and register the AURUM sidebar panel (once).

    The panel renders live from AURUM's own entities, so a single
    registration serves every config entry and self-adapts to devices.
    """
    from homeassistant.components import frontend

    domain_data = hass.data.setdefault(DOMAIN, {})
    root = os.path.join(os.path.dirname(__file__), "frontend")

    if not domain_data.get(_DATA_STATIC):
        # Set the flag BEFORE awaiting: concurrent entry setups would both
        # pass the check otherwise and register the path twice.
        domain_data[_DATA_STATIC] = True
        # cache_headers=True serves a long max-age — correct here because
        # module_url carries ?v={VERSION}, so releases bust the cache via
        # the URL. (False would mean heuristic caching: stale modules with
        # no reliable expiry.)
        try:
            from homeassistant.components.http import StaticPathConfig
            await hass.http.async_register_static_paths(
                [StaticPathConfig(PANEL_STATIC_URL, root, True)])
        except (ImportError, AttributeError):
            # Fallback for older HA cores without async_register_static_paths
            hass.http.register_static_path(PANEL_STATIC_URL, root, True)

    if not domain_data.get(_DATA_PANEL):
        frontend.async_register_built_in_panel(
            hass,
            component_name="custom",
            sidebar_title="AURUM",
            sidebar_icon="mdi:solar-power",
            frontend_url_path=PANEL_URL_PATH,
            require_admin=False,
            config={
                "_panel_custom": {
                    "name": "aurum-panel",
                    "embed_iframe": False,
                    "trust_external": False,
                    # Cache-bust on version change so users get the new UI.
                    "module_url": f"{PANEL_STATIC_URL}/{PANEL_JS}?v={VERSION}",
                }
            },
        )
        domain_data[_DATA_PANEL] = True


def _unregister_frontend(hass: HomeAssistant) -> None:
    """Remove the sidebar panel (static path stays; it can't be unbound)."""
    from homeassistant.components import frontend

    domain_data = hass.data.get(DOMAIN, {})
    if domain_data.get(_DATA_PANEL):
        try:
            frontend.async_remove_panel(hass, PANEL_URL_PATH)
        except Exception:  # noqa: BLE001 – best-effort cleanup
            pass
        domain_data[_DATA_PANEL] = False


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload integration when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_cleanup_orphaned_entities(
        hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove entity registry entries for devices no longer in config.

    Runs on every setup so stale entities from removed devices are
    cleaned up automatically – even if they were removed before the
    config-flow cleanup fix was deployed.
    """
    devices = entry.options.get(CONF_DEVICES, [])
    active_slugs = {slugify(d.get("name", "")) for d in devices}

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


async def _async_heal_entity_ids(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Migrate per-device entity_ids to the deterministic aurum_{slug} scheme.

    Older versions let HA derive object_ids from the friendly name via HA's
    slugify, which transliterates umlauts differently than AURUM's slugify
    (ä→a vs ä→ae). The dashboard panel builds ids from AURUM's slug, so
    mismatched registry entries are renamed once here. Keyed on unique_id,
    which was always deterministic.
    """
    devices = entry.options.get(CONF_DEVICES, [])
    if not devices:
        return

    # unique_id -> expected entity_id, for every configured device
    expected: dict[str, str] = {}
    for dev in devices:
        slug = slugify(dev.get("name", ""))
        if not slug:
            continue
        eid = entry.entry_id
        expected[f"{eid}_{slug}"] = f"sensor.aurum_{slug}"
        expected[f"{eid}_{slug}_power"] = f"sensor.aurum_{slug}_power"
        expected[f"{eid}_{slug}_runtime"] = f"sensor.aurum_{slug}_runtime"
        expected[f"{eid}_{slug}_energy"] = f"sensor.aurum_{slug}_energy_today"
        expected[f"{eid}_{slug}_active"] = f"binary_sensor.aurum_{slug}_active"
        expected[f"{eid}_{slug}_soc_threshold"] = (
            f"number.aurum_{slug}_soc_threshold")
        expected[f"{eid}_{slug}_max_price"] = f"number.aurum_{slug}_max_price"
        expected[f"{eid}_{slug}_deadline"] = f"time.aurum_{slug}_deadline"

    ent_reg = er.async_get(hass)
    for entity_entry in er.async_entries_for_config_entry(
            ent_reg, entry.entry_id):
        target = expected.get(entity_entry.unique_id or "")
        if not target or entity_entry.entity_id == target:
            continue
        if ent_reg.async_get(target) is not None:
            continue  # target taken — leave as-is rather than collide
        try:
            ent_reg.async_update_entity(
                entity_entry.entity_id, new_entity_id=target)
            _LOGGER.info(
                "AURUM: migrated entity_id %s -> %s",
                entity_entry.entity_id, target)
        except Exception as e:  # noqa: BLE001 – best-effort migration
            _LOGGER.warning(
                "AURUM: entity_id migration failed for %s: %s",
                entity_entry.entity_id, e)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up AURUM from a config entry."""
    # Clean up entities for devices that were removed from config
    await _async_cleanup_orphaned_entities(hass, entry)
    # Heal entity_ids from older versions (HA-slugified umlauts etc.)
    await _async_heal_entity_ids(hass, entry)

    try:
        coordinator = AurumCoordinator(hass, entry)

        await asyncio.wait_for(
            coordinator.async_setup(), timeout=SETUP_TIMEOUT)

        await asyncio.wait_for(
            coordinator.async_config_entry_first_refresh(),
            timeout=SETUP_TIMEOUT)

    except asyncio.TimeoutError as err:
        # Transient: sensors may not be available yet. Let HA retry.
        raise ConfigEntryNotReady("AURUM setup timed out, will retry") from err
    except ConfigEntryNotReady:
        # Raised by async_config_entry_first_refresh on UpdateFailed – let
        # HA handle the retry instead of swallowing it into a hard failure.
        raise
    except Exception as e:
        _LOGGER.error("AURUM setup failed: %s", e)
        return False

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
    }

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register the bundled dashboard panel (idempotent across entries/reloads).
    try:
        await _async_register_frontend(hass)
    except Exception as e:  # noqa: BLE001 – never fail setup over the panel
        _LOGGER.warning("AURUM dashboard panel registration failed: %s", e)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload AURUM config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    await coordinator.async_shutdown()

    unload_ok = await hass.config_entries.async_unload_platforms(
        entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        # Remove the sidebar panel when no AURUM entries remain.
        remaining = [
            k for k in hass.data.get(DOMAIN, {})
            if k not in (_DATA_STATIC, _DATA_PANEL)
        ]
        if not remaining:
            _unregister_frontend(hass)

    return unload_ok
