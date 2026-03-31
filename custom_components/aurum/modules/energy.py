"""
AURUM – Energy Manager
=======================
Reads grid power, PV power, and battery SOC.
Calculates excess power and EMA-smoothed values.
"""

import logging
from .helpers import get_float, ema_update, ema_update_asymmetric

_LOGGER = logging.getLogger(__name__)


class EnergyManager:
    """Read energy sensors and calculate excess."""

    def __init__(self, hass, config):
        self.hass = hass
        self.config = config

        self.grid_power_entity = config.get("grid_power_entity")
        self.pv_power_entity = config.get("pv_power_entity")
        self.battery_soc_entity = config.get("battery_soc_entity")
        self.battery_charge_power_entity = config.get(
            "battery_charge_power_entity")
        self.battery_discharge_power_entity = config.get(
            "battery_discharge_power_entity")

        self.ema_alpha = config.get("ema_alpha", 0.3)
        self.ema_alpha_down = config.get("ema_alpha_down", 0.7)
        self.ema_alpha_up = config.get("ema_alpha_up", 0.2)
        self._grid_ema = None       # symmetric EMA (battery decisions)
        self._grid_ema_asym = None  # asymmetric EMA (device decisions)

    def update(self, shared):
        """Read sensors, calculate excess, update shared dict."""
        # Grid power (positive = import, negative = export)
        grid_raw = get_float(self.hass, self.grid_power_entity, 0)

        # Symmetric EMA (alpha=0.3) – used for battery decisions
        self._grid_ema = ema_update(self._grid_ema, grid_raw, self.ema_alpha)

        # Asymmetric EMA (fast down=0.7, slow up=0.2) – used for device decisions
        # Reacts quickly to grid drops (= excess rising, real PV surplus)
        # Reacts slowly to grid spikes (= brief deficit, dampened)
        self._grid_ema_asym = ema_update_asymmetric(
            self._grid_ema_asym, grid_raw,
            self.ema_alpha_down, self.ema_alpha_up)

        shared["grid_power_raw"] = grid_raw
        shared["grid_power_ema"] = round(self._grid_ema, 1)
        shared["grid_power_ema_asym"] = round(self._grid_ema_asym, 1)

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

        # Battery charge/discharge power (optional)
        # battery_power_net = discharge - charge
        # Positive = net discharge, negative = net charge
        bat_charge = 0
        bat_discharge = 0
        if self.battery_charge_power_entity:
            bat_charge = get_float(
                self.hass, self.battery_charge_power_entity, 0)
        if self.battery_discharge_power_entity:
            bat_discharge = get_float(
                self.hass, self.battery_discharge_power_entity, 0)
        battery_power_net = bat_discharge - bat_charge
        shared["battery_power_net"] = round(battery_power_net, 1)
        shared["battery_charge_w"] = round(bat_charge, 1)
        shared["battery_discharge_w"] = round(bat_discharge, 1)

        # Excess calculation
        # Uses asymmetric EMA for turn-on (stable, dampens brief spikes)
        # Uses RAW for turn-off (fast response to clouds)
        #
        # Without battery sensors: excess = -grid (simple)
        # With battery sensors: excess = -grid - battery_power_net
        #   This gives TRUE PV surplus available for devices.
        #   Example: grid=0W, battery charging 3kW → excess = 0 - (-3000) = 3000W
        has_battery_power = (self.battery_charge_power_entity
                             or self.battery_discharge_power_entity)
        if has_battery_power:
            shared["excess"] = round(
                -self._grid_ema_asym - battery_power_net, 1)
            shared["excess_raw"] = round(
                -grid_raw - battery_power_net, 1)
        else:
            # Fallback: simple grid-only calculation
            shared["excess"] = round(-self._grid_ema_asym, 1)
            shared["excess_raw"] = round(-grid_raw, 1)
