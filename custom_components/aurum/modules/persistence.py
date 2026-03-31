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
    "runtime_today_s", "total_switches",
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

    def save(self, devices):
        """Save device state to JSON (atomic write)."""
        state = {
            "_meta": {
                "saved_at": datetime.now().isoformat(),
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

        for dev in devices.devices:
            name = dev["name"]
            if name not in state:
                continue

            saved = state[name]

            # Restore simple value fields
            for field in _VALUE_FIELDS:
                if field in saved:
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

        _LOGGER.info("AURUM state restored from %s", self.state_file)
