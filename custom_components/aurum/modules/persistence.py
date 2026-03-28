"""
AURUM – Persistence Manager
=============================
JSON-based state save/restore with atomic writes.
Persists device runtimes and startup detection state.
"""

import json
import logging
import os
import tempfile
from datetime import datetime

_LOGGER = logging.getLogger(__name__)


class PersistenceManager:
    """Save and restore AURUM state to JSON file."""

    def __init__(self, hass, config):
        self.hass = hass
        config_dir = getattr(hass, 'config_path', '/config')
        if callable(config_dir):
            config_dir = config_dir
        self.state_file = config.get(
            "state_file",
            os.path.join(str(config_dir), "aurum_state.json"))

    def save(self, devices):
        """Save device state to JSON (atomic write)."""
        state = {
            "_meta": {
                "saved_at": datetime.now().isoformat(),
                "version": "1.0.0",
            },
        }

        for dev in devices.devices:
            state[dev["name"]] = {
                "runtime_today_s": dev.get("runtime_today_s", 0),
                "on_since": (dev["on_since"].isoformat()
                             if dev.get("on_since") else None),
                "last_on": (dev["last_on"].isoformat()
                            if dev.get("last_on") else None),
                "last_off": (dev["last_off"].isoformat()
                             if dev.get("last_off") else None),
                "sd_state": dev.get("sd_state", ""),
                "total_switches": dev.get("total_switches", 0),
            }

        # Atomic write: write to temp file, then rename
        try:
            dir_name = os.path.dirname(self.state_file)
            fd, tmp_path = tempfile.mkstemp(
                dir=dir_name, suffix=".tmp")
            with os.fdopen(fd, 'w') as f:
                json.dump(state, f, indent=2)
            os.replace(tmp_path, self.state_file)
        except Exception as e:
            _LOGGER.warning("State save failed: %s", e)
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def restore(self, devices):
        """Restore device state from JSON."""
        if not os.path.exists(self.state_file):
            _LOGGER.info("No state file found – fresh start")
            return

        with open(self.state_file, 'r') as f:
            state = json.load(f)

        for dev in devices.devices:
            name = dev["name"]
            if name not in state:
                continue

            saved = state[name]
            dev["runtime_today_s"] = saved.get("runtime_today_s", 0)
            dev["total_switches"] = saved.get("total_switches", 0)
            dev["sd_state"] = saved.get("sd_state", "")

            # Restore timestamps
            for field in ("on_since", "last_on", "last_off"):
                val = saved.get(field)
                if val:
                    try:
                        dev[field] = datetime.fromisoformat(val)
                    except (ValueError, TypeError):
                        pass

        _LOGGER.info("AURUM state restored from %s", self.state_file)
