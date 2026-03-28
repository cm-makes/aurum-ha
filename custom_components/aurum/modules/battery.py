"""
AURUM – Battery Manager
========================
Determines battery mode based on SOC vs thresholds.
Does NOT control the battery – only reads SOC and decides
whether devices are allowed to run.

Modes:
  normal   – SOC above target, all devices allowed
  low_soc  – SOC below target but above min, per-device thresholds apply
  charging – SOC below min, no devices allowed
"""

import logging

from ..const import MODE_NORMAL, MODE_LOW_SOC, MODE_CHARGING

_LOGGER = logging.getLogger(__name__)


class BatteryManager:
    """Track battery SOC and determine operating mode."""

    def __init__(self, hass, config):
        self.hass = hass
        self.config = config

        self.target_soc = config.get("target_soc", 80)
        self.min_soc = config.get("min_soc", 10)

    def update(self, shared):
        """Determine battery mode from current SOC."""
        soc = shared.get("battery_soc", -1)

        # No battery configured → always normal
        if soc < 0:
            shared["battery_mode"] = MODE_NORMAL
            shared["excess_for_devices"] = shared.get("excess", 0)
            return

        # Determine mode
        if soc <= self.min_soc:
            mode = MODE_CHARGING
        elif soc < self.target_soc:
            mode = MODE_LOW_SOC
        else:
            mode = MODE_NORMAL

        shared["battery_mode"] = mode

        # In charging mode: no excess available for devices
        if mode == MODE_CHARGING:
            shared["excess_for_devices"] = 0
        else:
            shared["excess_for_devices"] = shared.get("excess", 0)
