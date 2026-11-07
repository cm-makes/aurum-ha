"""
AURUM – Helper utilities
=========================
Safe state reading, EMA smoothing, CSV logging.
"""

import csv
import math
import os
import logging

_LOGGER = logging.getLogger(__name__)


def get_float(hass, entity_id, default=0.0):
    """Safely read a numeric entity state, returning default on failure.

    'nan' and 'inf' parse as floats but are not readings: one NaN grid
    sample used to poison the EMAs until the next restart, so non-finite
    values count as missing too.
    """
    raw = hass.get_state(entity_id)
    if raw is None or raw in ("unavailable", "unknown", ""):
        return default
    try:
        value = float(raw)
    except (ValueError, TypeError):
        return default
    if not math.isfinite(value):
        return default
    return value


# Scale factors to AURUM's internal units, keyed by the sensor's
# unit_of_measurement. The config flow accepts all of these units, so the
# runtime must honour them too — a kW grid sensor read as W made the
# surplus 1000x too small. Unknown / missing units pass through unchanged
# (the pre-1.15.4 behaviour).
_POWER_TO_W = {"W": 1.0, "kW": 1000.0, "MW": 1_000_000.0, "mW": 0.001}
_ENERGY_TO_KWH = {"Wh": 0.001, "kWh": 1.0, "MWh": 1000.0}
# Price entities are documented as ct/kWh. The native Tibber integration
# (and most EUR sources) report EUR/kWh, which made every price look cheap.
_PRICE_TO_CT = {"EUR/kWh": 100.0, "€/kWh": 100.0}


def _get_scaled(hass, entity_id, default, factors):
    value = get_float(hass, entity_id, default=None)
    if value is None:
        return default
    unit = hass.get_state(entity_id, attribute="unit_of_measurement")
    if isinstance(unit, str):
        factor = factors.get(unit.strip())
        if factor is not None:
            # Round away float noise: 0.28 EUR * 100 must compare equal to
            # a max_price of 28 ct, not as 28.000000000000004.
            return round(value * factor, 6)
    return value


def get_power_w(hass, entity_id, default=0.0):
    """Read a power sensor in W, converting kW / MW / mW."""
    return _get_scaled(hass, entity_id, default, _POWER_TO_W)


def get_energy_kwh(hass, entity_id, default=0.0):
    """Read an energy sensor in kWh, converting Wh / MWh."""
    return _get_scaled(hass, entity_id, default, _ENERGY_TO_KWH)


def get_price_ct(hass, entity_id, default=None):
    """Read a price sensor in ct/kWh, converting EUR/kWh."""
    return _get_scaled(hass, entity_id, default, _PRICE_TO_CT)


def get_state_safe(hass, entity_id, default=None):
    """Safely read an entity state as string."""
    raw = hass.get_state(entity_id)
    if raw is None or raw in ("unavailable", "unknown"):
        return default
    return raw


def ema_update(old_ema, new_value, alpha=0.3):
    """Exponential moving average: alpha * new + (1-alpha) * old."""
    if old_ema is None or not math.isfinite(old_ema):
        return new_value
    return alpha * new_value + (1 - alpha) * old_ema


def ema_update_asymmetric(current_ema, raw, alpha_down=0.7, alpha_up=0.2):
    """Asymmetric EMA: fast response when grid drops, slow when it rises.

    - alpha_down=0.7: Grid sinking (excess rising) → respond fast
    - alpha_up=0.2: Grid rising (deficit spikes) → dampen

    This prevents false starts from brief excess spikes while allowing
    fast reaction to genuine PV surplus.
    """
    if current_ema is None or not math.isfinite(current_ema):
        return raw
    alpha = alpha_down if raw < current_ema else alpha_up
    return alpha * raw + (1.0 - alpha) * current_ema


def slugify(name):
    """Convert a device name to a slug (lowercase, underscored, ASCII).

    Must yield a valid HA entity object_id ([a-z0-9_]) because AURUM
    forces entity_ids from this slug. German umlauts get the customary
    ae/oe/ue/ss transliteration; any other non-ASCII character folds to
    its ASCII base (é→e) or drops, so names like "Café" can't produce an
    invalid entity_id.
    """
    import unicodedata
    slug = name.lower().strip()
    for old, new in [("ü", "ue"), ("ö", "oe"), ("ä", "ae"), ("ß", "ss")]:
        slug = slug.replace(old, new)
    # Fold remaining non-ASCII to ASCII base characters (é→e, ç→c, …)
    slug = unicodedata.normalize("NFKD", slug).encode(
        "ascii", "ignore").decode("ascii")
    slug = "".join(
        c if (c.isascii() and c.isalnum()) or c == "_" else "_"
        for c in slug)
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
        written = 0
        try:
            with open(self.path, 'a', newline='') as f:
                writer = csv.writer(f)
                for row in rows:
                    writer.writerow(row)
                    written += 1
        except Exception as e:
            self.hass.log(f"CSV write error: {e}", level="WARNING")
            # Re-queue only the rows NOT yet written so they are retried on
            # the next flush without dropping them — and without duplicating
            # rows already flushed before a mid-loop failure. Bound the
            # retained backlog so a persistent failure can't grow it forever.
            max_backlog = getattr(self, "max_lines", 10000) or 10000
            self._buffer = (rows[written:] + self._buffer)[-max_backlog:]
