"""
AURUM – Energy Manager
=======================
Reads grid power, PV power, and battery SOC.
Calculates excess power and EMA-smoothed values.
"""

import logging
from .helpers import get_float, ema_update

_LOGGER = logging.getLogger(__name__)


class EnergyManager:
    """Read energy sensors and calculate excess."""

    def __init__(self, hass, config):
        self.hass = hass
        self.config = config

        self.grid_power_entity = config.get("grid_power_entity")
        self.pv_power_entity = config.get("pv_power_entity")
        self.battery_soc_entity = config.get("battery_soc_entity")

        self.ema_alpha = config.get("ema_alpha", 0.3)
        self._grid_ema = None

    def update(self, shared):
        """Read sensors, calculate excess, update shared dict."""
        # Grid power (positive = import, negative = export)
        grid_raw = get_float(self.hass, self.grid_power_entity, 0)
        self._grid_ema = ema_update(self._grid_ema, grid_raw, self.ema_alpha)

        shared["grid_power_raw"] = grid_raw
        shared["grid_power_ema"] = round(self._grid_ema, 1)

        # PV power (optional)
        if self.pv_power_entity:
            shared["pv_power"] = get_float(
                self.hass, self.pv_power_entity, 0)
        else:
            shared["pv_power"] = 0

        # Battery SOC (optional)
        if self.battery_soc_entity:
            shared["battery_soc"] = get_float(
                self.hass, self.battery_soc_entity, -1)
        else:
            shared["battery_soc"] = -1  # -1 = no battery

        # Excess = negative grid power = export
        # Positive excess means power available for devices
        # EMA-smoothed for turn-on decisions (stable)
        shared["excess"] = round(-self._grid_ema, 1)
        # Raw for turn-off decisions (fast response to clouds)
        shared["excess_raw"] = round(-grid_raw, 1)
