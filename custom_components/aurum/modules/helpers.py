"""
AURUM – Helper utilities
=========================
Safe state reading, EMA smoothing, CSV logging.
"""

import csv
import os
import logging

_LOGGER = logging.getLogger(__name__)


def get_float(hass, entity_id, default=0.0):
    """Safely read a numeric entity state, returning default on failure."""
    raw = hass.get_state(entity_id)
    if raw is None or raw in ("unavailable", "unknown", ""):
        return default
    try:
        return float(raw)
    except (ValueError, TypeError):
        return default


def get_state_safe(hass, entity_id, default=None):
    """Safely read an entity state as string."""
    raw = hass.get_state(entity_id)
    if raw is None or raw in ("unavailable", "unknown"):
        return default
    return raw


def ema_update(old_ema, new_value, alpha=0.3):
    """Exponential moving average: alpha * new + (1-alpha) * old."""
    if old_ema is None:
        return new_value
    return alpha * new_value + (1 - alpha) * old_ema


def ema_update_asymmetric(current_ema, raw, alpha_down=0.7, alpha_up=0.2):
    """Asymmetric EMA: fast response when grid drops, slow when it rises.

    - alpha_down=0.7: Grid sinking (excess rising) → respond fast
    - alpha_up=0.2: Grid rising (deficit spikes) → dampen

    This prevents false starts from brief excess spikes while allowing
    fast reaction to genuine PV surplus.
    """
    if current_ema is None:
        return raw
    alpha = alpha_down if raw < current_ema else alpha_up
    return alpha * raw + (1.0 - alpha) * current_ema


def slugify(name):
    """Convert a device name to a slug (lowercase, underscored)."""
    slug = name.lower().strip()
    for old, new in [("ü", "ue"), ("ö", "oe"), ("ä", "ae"), ("ß", "ss")]:
        slug = slug.replace(old, new)
    slug = "".join(c if c.isalnum() or c == "_" else "_" for c in slug)
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_")


class CSVLogger:
    """Buffered CSV writer with file rotation."""

    def __init__(self, hass, path, headers, max_lines=5000):
        self.hass = hass
        self.path = path
        self.headers = headers
        self.max_lines = max_lines
        self._buffer = []
        self._initialized = False

    def _init_file(self):
        """Create CSV file with rotation (call from executor thread)."""
        if self._initialized or not self.path:
            return
        self._initialized = True

        if os.path.exists(self.path):
            try:
                with open(self.path, 'r') as f:
                    line_count = sum(1 for _ in f)
                if line_count > self.max_lines:
                    keep = self.max_lines // 2
                    with open(self.path, 'r') as f:
                        lines = f.readlines()
                    with open(self.path, 'w', newline='') as f:
                        f.write(lines[0])  # header
                        f.writelines(lines[-keep:])
                    self.hass.log(
                        f"CSV rotated {self.path}: "
                        f"{line_count} → {keep + 1} lines")
            except Exception as e:
                self.hass.log(f"CSV rotation error: {e}", level="WARNING")
        else:
            try:
                with open(self.path, 'w', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(self.headers)
            except Exception as e:
                self.hass.log(
                    f"CSV init error: {e}", level="WARNING")

    def log_row(self, row):
        """Buffer a row for deferred write."""
        if not self.path:
            return
        self._buffer.append(row)

    def flush(self):
        """Write all buffered rows to disk (call from executor thread)."""
        if not self._buffer:
            return
        if not self._initialized:
            self._init_file()
        rows = self._buffer
        self._buffer = []
        try:
            with open(self.path, 'a', newline='') as f:
                writer = csv.writer(f)
                for row in rows:
                    writer.writerow(row)
        except Exception as e:
            self.hass.log(f"CSV write error: {e}", level="WARNING")
