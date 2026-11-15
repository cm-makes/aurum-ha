"""
AURUM – Household base load
============================
Learns what the house draws on its own, per hour of the day, for the PV
budget's consumption estimate (the BudgetManager consumption profile):

    base load = PV + grid + battery net - AURUM's own devices

AURUM's devices are subtracted because they run on the budget: counted as
household load, every surplus run would shrink the next day's budget.
Loads AURUM does not switch (a wallbox, a heat pump) are household load.

One sample per cycle goes into the bucket of the current clock hour. When
the hour ends, its average goes straight into the budget's per-hour
average, so a restart loses at most the hour in progress.

A cycle only gives a sample while the balance can be trusted:
- a PV power sensor is configured. Without it, grid + battery is about
  0 W while PV produces, and the budget only uses the production hours.
- with a battery (SOC sensor), a battery power sensor is configured too.
  Otherwise battery charging would count as household load.
- the grid, PV and battery power sensors report (input health).
- every AURUM device that is on reports measured power. The nominal
  power of a device without a power sensor is a guess: a heating rod at
  temperature draws nothing while AURUM still counts it.

Idea from the HELIOS coordinator (base-load sampler, hourly hand-over).
"""

import logging

from ..const import DEFAULT_UPDATE_INTERVAL, INPUT_OK

_LOGGER = logging.getLogger(__name__)

# Inputs that enter the balance (the SOC does not).
_BALANCE_INPUTS = ("grid", "pv", "battery_charge", "battery_discharge")

# An hour counts when at least this share of its cycles gave a sample:
# after a restart at 10:40, or a long sensor fault, too little is left to
# tell what 10:00-11:00 looks like.
MIN_COVERAGE = 0.5

# Share of the hour's samples dropped at each end before averaging. A
# glitch reading (a 65535 W register, meters updating out of step) can't
# drag the hour, while a kettle or an oven run still counts.
TRIM_SHARE = 0.02

# An hour clearly below 0 W means the balance is off (for example a PV
# sensor that reads high); a few watts below 0 are meter tolerance.
NEGATIVE_TOLERANCE_W = 100.0


class BaseLoadSampler:
    """Hourly household base load: house consumption minus AURUM's
    devices."""

    def __init__(self, config):
        has_battery = bool(config.get("battery_soc_entity"))
        has_battery_power = bool(
            config.get("battery_charge_power_entity")
            or config.get("battery_discharge_power_entity"))
        if not config.get("pv_power_entity"):
            self.disabled_reason = "no PV power sensor"
        elif has_battery and not has_battery_power:
            self.disabled_reason = "no battery power sensor"
        else:
            self.disabled_reason = None

        try:
            interval = float(config.get(
                "update_interval", DEFAULT_UPDATE_INTERVAL)
                or DEFAULT_UPDATE_INTERVAL)
        except (TypeError, ValueError):
            interval = float(DEFAULT_UPDATE_INTERVAL)
        self.min_samples = max(
            1, int(MIN_COVERAGE * 3600 / max(1.0, interval)))

        self._hour_start = None     # start of the hour being sampled
        self._samples = []

    @property
    def enabled(self):
        return self.disabled_reason is None

    def sample(self, shared):
        """Take this cycle's sample (call after the device step).

        Returns {hour: watts} for the hour that just ended, or None.
        """
        now = shared.get("now")
        if now is None or not self.enabled:
            return None
        hour_start = now.replace(minute=0, second=0, microsecond=0)
        finished = None
        if self._hour_start is not None and hour_start != self._hour_start:
            finished = self._finish()
            self._samples = []
        self._hour_start = hour_start
        value = self.base_load_w(shared)
        if value is not None:
            self._samples.append(value)
        return finished

    @staticmethod
    def base_load_w(shared):
        """This cycle's base load in W, or None when it can't be told.

        Not clamped at 0: meters that update out of step err both ways,
        and the hour's average evens that out.
        """
        if shared.get("surplus_blind"):
            return None
        health = shared.get("input_health") or {}
        if any(health.get(key, INPUT_OK) != INPUT_OK
               for key in _BALANCE_INPUTS):
            return None
        devices_w = shared.get("device_power_total")
        if devices_w is None:
            return None     # the device step failed this cycle
        # Startup placeholders have no power_measured: not a measurement.
        if not all(d.get("power_measured", False)
                   for d in shared.get("device_states") or []):
            return None
        house_w = ((shared.get("pv_power") or 0)
                   + (shared.get("grid_power_raw") or 0)
                   + (shared.get("battery_power_net") or 0))
        return house_w - devices_w

    def _finish(self):
        """Average of the bucket that just ended, or None."""
        hour = self._hour_start.hour
        samples = sorted(self._samples)
        n = len(samples)
        if n < self.min_samples:
            _LOGGER.debug(
                "AURUM base load: hour %d not learned (%d of %d samples)",
                hour, n, self.min_samples)
            return None
        k = int(n * TRIM_SHARE)
        kept = samples[k:n - k]
        avg_w = sum(kept) / len(kept)
        if avg_w < -NEGATIVE_TOLERANCE_W:
            _LOGGER.debug(
                "AURUM base load: hour %d not learned (%.0f W, the energy "
                "balance does not add up)", hour, avg_w)
            return None
        avg_w = max(0.0, avg_w)
        _LOGGER.debug("AURUM base load: hour %d = %.0f W (%d samples)",
                      hour, avg_w, n)
        return {hour: round(avg_w, 1)}
