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
  It must report the total PV production of all PV systems in the house
  (every inverter, including a balcony plant): an unmetered balcony
  plant would be missing from the house consumption. With a hybrid
  inverter it must be the PV (DC input) power, not the AC output: that
  already includes the battery, which would then count twice.
- with a battery (any of SOC, charge or discharge power sensor
  configured), both battery power sensors are configured. They are
  unsigned, one direction each: with only the charge sensor a
  discharging battery is invisible and the household load it covers is
  missed (and with only the discharge sensor, charging counts as load).
- the energy step ran (it publishes input health) and the grid, PV and
  battery power sensors report.
- every AURUM device that is on reports measured power. The nominal
  power of a device without a power sensor is a guess: a heating rod at
  temperature draws nothing while AURUM still counts it. An unreachable
  switch may be on.
- the sample is plausible (within +-30 kW).

When a cycle gives no sample, the reason is counted (naming the device
for a device reason), so diagnostics can show why learning is paused.

Idea from the HELIOS coordinator (base-load sampler, hourly hand-over).
"""

import logging
from collections import Counter

from ..const import DEFAULT_UPDATE_INTERVAL, INPUT_OK

_LOGGER = logging.getLogger(__name__)

# Inputs that enter the balance (the SOC does not), named for the skip
# reasons in diagnostics.
_BALANCE_INPUTS = {
    "grid": "grid meter",
    "pv": "PV power sensor",
    "battery_charge": "battery charge power sensor",
    "battery_discharge": "battery discharge power sensor",
}

# An hour counts when at least this share of its cycles gave a sample:
# after a restart at 10:40, or a long sensor fault, too little is left to
# tell what 10:00-11:00 looks like.
MIN_COVERAGE = 0.5

# A single sample beyond +-30 kW is a glitch, not the house: a 65535 W
# register, or a device power sensor glitch that drives the sample far
# below 0. 30 kW is about a 3 x 43 A house connection. Everything within
# counts in full, so a kettle or an oven run is learned as it is. Smaller
# negative samples are kept: meters that update out of step err both
# ways, and the hour's average evens that out.
MAX_PLAUSIBLE_W = 30000.0

# An hour clearly below 0 W means the balance is off (for example a PV
# sensor that reads high); a few watts below 0 are meter tolerance.
NEGATIVE_TOLERANCE_W = 100.0

# Skip reasons that don't name a device.
SKIP_SURPLUS_BLIND = "surplus blind"
SKIP_ENERGY_STEP = "energy step failed"
SKIP_DEVICE_STEP = "device step failed"
SKIP_DEVICES_STARTING = "devices starting up"
SKIP_IMPLAUSIBLE = "implausible sample (beyond +-30 kW)"


class BaseLoadSampler:
    """Hourly household base load: house consumption minus AURUM's
    devices."""

    def __init__(self, config):
        missing_battery = [
            direction for direction, key in (
                ("charge", "battery_charge_power_entity"),
                ("discharge", "battery_discharge_power_entity"))
            if not config.get(key)]
        # Any battery sensor means there is a battery, also one power
        # sensor without a SOC sensor (the config flow allows that).
        has_battery = any(config.get(key) for key in (
            "battery_soc_entity", "battery_charge_power_entity",
            "battery_discharge_power_entity"))
        if not config.get("pv_power_entity"):
            self.disabled_reason = "no PV power sensor"
        elif has_battery and missing_battery:
            # Both directions are needed (unsigned sensors, see above).
            self.disabled_reason = "no battery %s power sensor" % (
                " or ".join(missing_battery))
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
        self._hour_skips = Counter()    # skip reasons this hour
        # For diagnostics: why cycles gave no sample since start, the
        # reason of the latest cycle (None = it gave a sample), the
        # latest skip and the outcome of the last finished hour.
        self.skipped = Counter()
        self.paused_reason = None
        self.last_skip = None
        self.last_hour = None

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
            self._hour_skips = Counter()
        self._hour_start = hour_start
        value, reason = self.measure(shared)
        self.paused_reason = reason
        if reason is None:
            self._samples.append(value)
        else:
            self._hour_skips[reason] += 1
            self.skipped[reason] += 1
            self.last_skip = {"reason": reason,
                              "at": now.isoformat(timespec="seconds")}
        return finished

    @staticmethod
    def measure(shared):
        """(watts, None) for this cycle's base load, or (None, reason)
        when it can't be told.

        Not clamped at 0: meters that update out of step err both ways,
        and the hour's average evens that out.
        """
        health = shared.get("input_health")
        if health is None:
            # The energy step failed before it checked its inputs: the
            # powers below may be missing and would read as 0 W.
            return None, SKIP_ENERGY_STEP
        for key, name in _BALANCE_INPUTS.items():
            status = health.get(key, INPUT_OK)
            if status != INPUT_OK:
                return None, "%s %s" % (name, status)
        if shared.get("surplus_blind"):
            return None, SKIP_SURPLUS_BLIND
        devices_w = shared.get("device_power_total")
        if devices_w is None or shared.get("base_load_device_data_stale"):
            # Even cycles leave the total unset when the device step fails;
            # odd cycles then reuse the cache from before the failure.
            return None, SKIP_DEVICE_STEP
        for dev in shared.get("device_states") or []:
            # Startup placeholders have no power_measured.
            if "power_measured" not in dev:
                return None, SKIP_DEVICES_STARTING
            if not dev["power_measured"]:
                return None, "%s: %s" % (
                    dev.get("name"),
                    dev.get("power_unmeasured") or "power not measured")
        house_w = ((shared.get("pv_power") or 0)
                   + (shared.get("grid_power_raw") or 0)
                   + (shared.get("battery_power_net") or 0))
        watts = house_w - devices_w
        if abs(watts) > MAX_PLAUSIBLE_W:
            return None, SKIP_IMPLAUSIBLE
        return watts, None

    def _finish(self):
        """Average of the bucket that just ended, or None."""
        hour = self._hour_start.hour
        n = len(self._samples)
        result = {"hour": hour, "samples": n, "learned_w": None,
                  "skipped_cycles": dict(self._hour_skips)}
        self.last_hour = result
        if n < self.min_samples:
            result["reason"] = "too few samples (%d of %d)" % (
                n, self.min_samples)
            _LOGGER.debug(
                "AURUM base load: hour %d not learned (%d of %d samples, "
                "skipped: %s)", hour, n, self.min_samples,
                dict(self._hour_skips))
            return None
        avg_w = sum(self._samples) / n
        if avg_w < -NEGATIVE_TOLERANCE_W:
            result["reason"] = (
                "averaged %.0f W: the energy balance does not add up (does "
                "the PV power sensor cover all PV systems?)" % avg_w)
            _LOGGER.debug(
                "AURUM base load: hour %d not learned (%.0f W, the energy "
                "balance does not add up)", hour, avg_w)
            return None
        avg_w = round(max(0.0, avg_w), 1)
        result["learned_w"] = avg_w
        _LOGGER.debug("AURUM base load: hour %d = %.0f W (%d samples)",
                      hour, avg_w, n)
        return {hour: avg_w}

    def info(self):
        """Learning status for diagnostics: whether it runs and, when it
        doesn't, why."""
        if not self.enabled:
            status, reason = "off", self.disabled_reason
        elif self.paused_reason:
            status, reason = "paused", self.paused_reason
        else:
            status, reason = "active", None
        return {
            "status": status,
            "reason": reason,
            "samples_this_hour": len(self._samples),
            "samples_needed_per_hour": self.min_samples,
            "skipped_this_hour": dict(self._hour_skips),
            "skipped_since_start": dict(self.skipped),
            "last_skip": self.last_skip,
            "last_hour": self.last_hour,
        }
