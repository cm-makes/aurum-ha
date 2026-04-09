"""
AURUM – Persistence Manager
=============================
JSON-based state save/restore with atomic writes.
Persists device runtimes, startup detection state, and control state.
"""

import json
import logging
import os
import tempfile
from datetime import datetime

_LOGGER = logging.getLogger(__name__)

# Fields that are datetime objects (save as ISO string, restore as datetime)
_DATETIME_FIELDS = (
    "on_since", "last_on", "last_off",
    "sd_detected_at", "sd_waiting_since", "sd_running_since",
    "sd_lockout_until", "sd_power_above_since", "sd_power_below_since",
)

# Fields that are simple values (save/restore as-is)
_VALUE_FIELDS = (
    "runtime_today_s", "energy_today_wh", "total_switches",
    "sd_state", "managed_on", "force_started",
)


class PersistenceManager:
    """Save and restore AURUM state to JSON file."""

    def __init__(self, hass, config):
        self.hass = hass
        config_dir = hass.config_path
        self.state_file = config.get(
            "state_file",
            os.path.join(str(config_dir), "aurum_state.json"))

    def save(self, devices, budget=None):
        """Save device state (and optional budget state) to JSON (atomic write)."""
        now = datetime.now()
        state = {
            "_meta": {
                "saved_at": now.isoformat(),
                "saved_date": now.strftime("%Y-%m-%d"),
                "version": "1.1.0",
            },
        }

        for dev in devices.devices:
            dev_state = {}

            # Save datetime fields as ISO strings
            for field in _DATETIME_FIELDS:
                val = dev.get(field)
                dev_state[field] = val.isoformat() if val else None

            # Save simple value fields
            for field in _VALUE_FIELDS:
                dev_state[field] = dev.get(field)

            state[dev["name"]] = dev_state

        # Save budget learned state (safety factor, weather observations, etc.)
        if budget is not None:
            try:
                state["_budget"] = budget.get_state_for_save()
            except Exception as e:
                _LOGGER.warning("Budget state save failed: %s", e)

        # Atomic write: write to temp file, then rename
        tmp_path = None
        try:
            dir_name = os.path.dirname(self.state_file)
            fd, tmp_path = tempfile.mkstemp(
                dir=dir_name, suffix=".tmp")
            with os.fdopen(fd, 'w') as f:
                json.dump(state, f, indent=2)
            os.replace(tmp_path, self.state_file)
        except Exception as e:
            _LOGGER.warning("State save failed: %s", e)
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def restore(self, devices):
        """Restore device state from JSON."""
        if not os.path.exists(self.state_file):
            _LOGGER.info("No state file found – fresh start")
            return

        try:
            with open(self.state_file, 'r') as f:
                state = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            _LOGGER.warning("State file corrupt, starting fresh: %s", e)
            return

        # Check if state file is from today — if not, reset daily counters
        today_str = datetime.now().strftime("%Y-%m-%d")
        saved_date = state.get("_meta", {}).get("saved_date")
        is_today = (saved_date == today_str)
        if not is_today:
            _LOGGER.info(
                "AURUM: State file is from %s (today: %s) — "
                "resetting daily counters",
                saved_date or "unknown", today_str)

        for dev in devices.devices:
            name = dev["name"]
            if name not in state:
                continue

            saved = state[name]

            # Restore simple value fields
            for field in _VALUE_FIELDS:
                if field in saved:
                    # Reset daily counters if state is from a previous day
                    if not is_today and field in ("runtime_today_s",
                                                   "energy_today_wh",
                                                   "total_switches"):
                        dev[field] = 0
                    else:
                        dev[field] = saved[field]

            # Restore datetime fields
            for field in _DATETIME_FIELDS:
                val = saved.get(field)
                if val:
                    try:
                        dev[field] = datetime.fromisoformat(val)
                    except (ValueError, TypeError):
                        dev[field] = None
                else:
                    dev[field] = None

            # Safety: if sd_state is "running" but sd_running_since
            # is missing, reset to standby (prevents crash)
            if dev.get("sd_state") == "running" and not dev.get(
                    "sd_running_since"):
                _LOGGER.warning(
                    "AURUM: %s was 'running' but no timestamp, "
                    "resetting to standby", name)
                dev["sd_state"] = "standby"
                dev["force_started"] = False

            # Same for "waiting" state
            if dev.get("sd_state") == "waiting" and not dev.get(
                    "sd_waiting_since"):
                _LOGGER.warning(
                    "AURUM: %s was 'waiting' but no timestamp, "
                    "resetting to standby", name)
                dev["sd_state"] = "standby"

            # Same for "detected" state
            if dev.get("sd_state") == "detected":
                dev["sd_state"] = "standby"
                _LOGGER.info(
                    "AURUM: %s was 'detected' at restart, "
                    "resetting to standby", name)

        # ── HELIOS pattern: verify against actual HA switch state ────
        # Saved state may be stale — always cross-check with real switch.
        # If switch is ON  → managed_on=True, restore on_since
        # If switch is OFF → managed_on=False, clear on_since
        now = datetime.now()
        for dev in devices.devices:
            is_on = devices._is_device_on(dev)

            if is_on:
                dev["managed_on"] = True
                # Only restore on_since for SD devices if in running state
                sd_ok = (
                    not dev.get("startup_detection")
                    or dev.get("sd_state") == "running")
                if not sd_ok:
                    dev["on_since"] = None
                elif not dev.get("on_since"):
                    # Device is on but no timestamp saved → use now
                    dev["on_since"] = now
            else:
                # Device is off → clear managed state
                dev["managed_on"] = False
                dev["on_since"] = None

            # Set runtime tick for all devices that have on_since
            if dev.get("on_since"):
                dev["_runtime_tick"] = now

        _LOGGER.info("AURUM state restored from %s", self.state_file)
        return state.get("_budget")  # return budget state for coordinator
