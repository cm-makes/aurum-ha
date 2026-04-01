"""
AURUM – Diagnostics
====================
Provides a safe, read-only JSON snapshot of AURUM's internal state.

Accessible via:
  Settings → Integrations → AURUM → ⋮ → Download Diagnostics

The downloaded file contains everything needed for bug reports:
current energy values, device states, budget info, coordinator health.
No credentials or passwords are stored by AURUM, so nothing is redacted.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, VERSION
from .const import override_entity_id, muss_heute_entity_id


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for the AURUM config entry."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    data = coordinator.data or {}
    cfg = coordinator.config

    # ── Integration meta ───────────────────────────────────────────
    meta = {
        "version": VERSION,
        "cycle": coordinator.cycle,
        "update_interval_s": cfg.get("update_interval", 15),
        "last_update_success": coordinator.last_update_success,
    }

    # ── Energy snapshot ────────────────────────────────────────────
    pv_w = data.get("pv_power") or 0
    grid_raw = data.get("grid_power_raw")       # positive=import, negative=export
    grid_ema = data.get("grid_power_ema")
    bat_charge = data.get("battery_charge_w")
    bat_discharge = data.get("battery_discharge_w")
    bat_net = data.get("battery_power_net")     # discharge - charge
    # House consumption = PV - excess (approx, when grid/battery available)
    house_w = None
    if grid_raw is not None and bat_net is not None:
        house_w = round(pv_w + grid_raw - bat_net, 1)
    energy = {
        "pv_power_w": data.get("pv_power"),
        "grid_power_w": grid_raw,
        "grid_power_ema_w": grid_ema,
        "house_consumption_w": house_w,
        "excess_power_w": data.get("excess"),
        "excess_for_devices_w": data.get("excess_for_devices"),
        "battery_soc_pct": data.get("battery_soc"),
        "battery_charge_w": bat_charge,
        "battery_discharge_w": bat_discharge,
    }

    # ── Battery ────────────────────────────────────────────────────
    battery = {
        "mode": data.get("battery_mode"),
        "target_soc_pct": cfg.get("target_soc"),
        "min_soc_pct": cfg.get("min_soc"),
        "capacity_wh": cfg.get("battery_capacity_wh"),
    }

    # ── Budget (optional) ──────────────────────────────────────────
    budget: dict[str, Any] = {"configured": coordinator.budget is not None}
    if coordinator.budget is not None:
        budget.update({
            "forecast_remaining_kwh": data.get("pv_forecast_remaining_kwh"),
            "device_budget_w": data.get("device_budget_w"),
            "safety_factor": data.get("safety_factor"),
            "forecast_entity": cfg.get("pv_forecast_entity"),
        })

    # ── Devices ────────────────────────────────────────────────────
    devices_diag = []
    for dev in coordinator.devices.devices:
        slug = dev["slug"]

        # Read live override state from native switches
        override_state = hass.states.get(override_entity_id(slug))
        muss_heute_state = hass.states.get(muss_heute_entity_id(slug))

        # Match with last published device_state
        published = next(
            (d for d in coordinator.device_states if d["slug"] == slug),
            {},
        )

        devices_diag.append({
            "name": dev["name"],
            "slug": slug,
            # Published state
            "state": published.get("state", "unknown"),
            "power_w": published.get("power", 0),
            "runtime_today_min": round(
                published.get("runtime_today_s", 0) / 60, 1),
            # Internal control state
            "managed_on": dev.get("managed_on", False),
            "force_started": dev.get("force_started", False),
            "total_switches_today": dev.get("total_switches", 0),
            "scheduling_reason": dev.get("_scheduling_reason"),
            # Startup detection
            "startup_detection": dev.get("startup_detection", False),
            "sd_state": dev.get("sd_state", ""),
            # Override switches
            "override_switch": (
                override_state.state if override_state else "unavailable"),
            "muss_heute_switch": (
                muss_heute_state.state if muss_heute_state else "unavailable"),
            # Legacy entities (if configured)
            "legacy_override_entity": dev.get("manual_override_entity"),
            "legacy_muss_heute_entity": dev.get("muss_heute_entity"),
            # Parameters
            "nominal_power_w": dev.get("nominal_power"),
            "priority": dev.get("priority"),
            "soc_threshold_pct": dev.get("soc_threshold"),
            "interruptible": dev.get("interruptible", True),
            "deadline": dev.get("deadline"),
            "estimated_runtime_min": dev.get("estimated_runtime"),
        })

    # ── Coordinator health ─────────────────────────────────────────
    health = {
        "last_update_success": coordinator.last_update_success,
        "startup_grace_cycles": coordinator.STARTUP_GRACE_CYCLES,
        "startup_complete": coordinator.cycle > coordinator.STARTUP_GRACE_CYCLES,
        "action_csv_active": coordinator.action_csv is not None,
        "budget_active": coordinator.budget is not None,
        "devices_configured": len(coordinator.devices.devices),
        "devices_on": data.get("devices_on", 0),
        "device_power_total_w": data.get("device_power_total", 0),
    }

    return {
        "meta": meta,
        "energy": energy,
        "battery": battery,
        "budget": budget,
        "devices": devices_diag,
        "health": health,
    }
