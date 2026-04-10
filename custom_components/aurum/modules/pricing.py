"""
AURUM – Pricing Manager
========================
Reads electricity price data from external sensors (Tibber, Nordpool,
aWATTar, EPEX Spot, etc.) and provides price-aware decisions for the
device manager.

Supports three data sources (all optional, user picks via entity selector):
  - price_entity:        current price in ct/kWh (numeric sensor)
  - price_level_entity:  price level enum (very_cheap/cheap/normal/...)
  - cheap_period_entity: binary sensor ON = cheap period active
"""

import logging

from .helpers import get_float, get_state_safe

_LOGGER = logging.getLogger(__name__)

# Price levels ordered from cheapest to most expensive
_LEVEL_ORDER = {
    "very_cheap": 0,
    "cheap": 1,
    "normal": 2,
    "expensive": 3,
    "very_expensive": 4,
}


class PricingManager:
    """Read electricity prices and determine if grid power is cheap."""

    def __init__(self, hass, config):
        self.hass = hass
        self.config = config
        self.price_entity = config.get("price_entity")
        self.price_level_entity = config.get("price_level_entity")
        self.cheap_period_entity = config.get("cheap_period_entity")

        self._active = bool(
            self.price_entity
            or self.price_level_entity
            or self.cheap_period_entity
        )

        if self._active:
            _LOGGER.info(
                "AURUM Pricing active: price=%s, level=%s, cheap=%s",
                self.price_entity or "-",
                self.price_level_entity or "-",
                self.cheap_period_entity or "-",
            )

    @property
    def active(self):
        """Return True if any price entity is configured."""
        return self._active

    def update(self, shared):
        """Read price sensors and publish to shared dict."""
        if not self._active:
            shared["price_active"] = False
            return

        shared["price_active"] = True

        # ── Current price (ct/kWh) ──
        current_price = None
        if self.price_entity:
            raw = get_float(self.hass, self.price_entity, None)
            if raw is not None:
                current_price = raw
        shared["current_price"] = current_price

        # ── Price level (enum string) ──
        price_level = None
        if self.price_level_entity:
            raw = get_state_safe(self.hass, self.price_level_entity)
            if raw and raw in _LEVEL_ORDER:
                price_level = raw
        shared["price_level"] = price_level
        shared["price_level_value"] = (
            _LEVEL_ORDER.get(price_level) if price_level else None
        )

        # ── Cheap period active (binary sensor) ──
        cheap_period = False
        if self.cheap_period_entity:
            raw = get_state_safe(self.hass, self.cheap_period_entity)
            cheap_period = raw == "on"
        shared["cheap_period"] = cheap_period

    def is_price_ok(self, dev):
        """Check if current price allows grid power for this device.

        Returns True if the device should be allowed to run on grid power
        based on its price_mode and max_price settings.

        Called by DeviceManager for devices with price_mode != 'solar_only'.
        """
        price_mode = dev.get("price_mode", "solar_only")
        if price_mode == "solar_only":
            return False

        max_price = dev.get("max_price")
        if max_price is not None and max_price > 0:
            # Price threshold check
            current = self._last_price
            if current is not None and current <= max_price:
                return True

        # Cheap period check (always honored for cheap_grid devices)
        if self._last_cheap_period:
            return True

        # Price level check: allow at cheap or very_cheap
        if self._last_level_value is not None and self._last_level_value <= 1:
            return True

        return False

    def snapshot(self, shared):
        """Cache shared dict values for is_price_ok() calls."""
        self._last_price = shared.get("current_price")
        self._last_level_value = shared.get("price_level_value")
        self._last_cheap_period = shared.get("cheap_period", False)
