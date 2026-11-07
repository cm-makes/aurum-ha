"""
AURUM – Energy Manager
=======================
Reads grid power, PV power, and battery SOC.
Calculates excess power and EMA-smoothed values.

Input health (since 1.16)
-------------------------
Every configured hub sensor is checked on every cycle:

- A missing, unavailable or non-numeric reading is bridged with the last
  valid value for a short hold (``hold_s``), so a single dropout of a Wi-Fi
  meter neither clears nor advances the shedding timers. After the hold
  the input is *unavailable*.
- A grid or PV reading that has not been reported for ``sensor_timeout``
  minutes is *stale*: a frozen feed (MQTT without expire_after, a stalled
  cloud websocket) still shows a plausible number, so its age is the only
  signal. Readings at 0 W are not age-checked (zero export, PV at night).
- The SOC is held for ``SOC_HOLD_S`` and then becomes unknown
  (``battery_soc`` None): the battery is treated as low, but the min_soc
  emergency is not triggered on a guess.

While the grid meter or a configured battery power sensor has failed,
AURUM cannot see the surplus: ``surplus_blind`` tells DeviceManager to
start nothing on surplus and to release devices that run on surplus.
"""

import logging
from datetime import datetime

from ..const import (
    DEFAULT_SENSOR_TIMEOUT,
    DEFAULT_UPDATE_INTERVAL,
    INPUT_OK,
    INPUT_STALE,
    INPUT_UNAVAILABLE,
)
from .helpers import (
    get_float, get_power_w, ema_update, ema_update_asymmetric)

_LOGGER = logging.getLogger(__name__)

# A SOC reading is held this long when the sensor drops out (SOC changes
# slowly); after that the SOC is unknown.
SOC_HOLD_S = 1800

# Power readings below this magnitude are not age-checked: a meter that
# legitimately sits at 0 W (zero-export inverter, PV at night) may report
# nothing new for hours. A meter frozen at exactly 0 W is not detected.
STALE_MIN_ABS_W = 1.0

# What a failed input means for control, for the log line.
_CONSEQUENCE = {
    "grid": "no new starts on surplus, surplus runs are released",
    "battery_charge": "no new starts on surplus, surplus runs are released",
    "battery_discharge": "no new starts on surplus, surplus runs are released",
    "pv": "PV power counts as 0 W (PV gate closed)",
    "soc": "battery treated as low (no battery use, no min_soc emergency)",
}


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

        # Battery-priority surplus semantics (see const.CONF_BATTERY_PRIORITY):
        # True → only genuine grid export counts as device surplus.
        self.battery_priority = bool(config.get("battery_priority", False))

        self.ema_alpha = config.get("ema_alpha", 0.3)
        self.ema_alpha_down = config.get("ema_alpha_down", 0.7)
        self.ema_alpha_up = config.get("ema_alpha_up", 0.2)
        self._grid_ema = None       # symmetric EMA (battery decisions)
        self._grid_ema_asym = None  # asymmetric EMA (device decisions)
        # After a grid fault the EMAs restart from the first fresh reading
        # instead of blending it with the pre-fault (possibly frozen) value.
        self._grid_reseed = False

        # ── Input health ──────────────────────────────────────────────
        try:
            interval = float(config.get(
                "update_interval", DEFAULT_UPDATE_INTERVAL)
                or DEFAULT_UPDATE_INTERVAL)
        except (TypeError, ValueError):
            interval = float(DEFAULT_UPDATE_INTERVAL)
        # Bridge short dropouts with the last valid value (at least one
        # missed sample at any update_interval).
        self.hold_s = max(60.0, 3.0 * interval)
        try:
            timeout_min = float(config.get(
                "sensor_timeout", DEFAULT_SENSOR_TIMEOUT))
        except (TypeError, ValueError):
            timeout_min = float(DEFAULT_SENSOR_TIMEOUT)
        self.stale_s = timeout_min * 60.0 if timeout_min > 0 else None
        self._inputs = {}           # key -> health record (see _read)

    # ── input health ─────────────────────────────────────────────────

    def _age(self, entity_id):
        """Seconds since the sensor last reported, or None if unknown."""
        get_age = getattr(self.hass, "get_age", None)
        if get_age is None:
            return None
        try:
            return get_age(entity_id)
        except Exception:  # noqa: BLE001 – age is best effort
            return None

    def _read(self, key, entity_id, now, reader, hold_s, age_check):
        """Read one hub input and track its health.

        Returns (value, status). value is the live reading, or the last
        valid one while it is younger than hold_s; None once the input
        has failed (status unavailable or stale).
        """
        rec = self._inputs.get(key)
        if rec is None:
            rec = self._inputs[key] = {
                "entity": entity_id,
                "value": None,          # last valid reading
                "at": None,             # when it was read
                "status": INPUT_OK,
                "fault_since": None,
                "seen": False,          # any valid reading since start
            }

        value = reader(self.hass, entity_id, default=None)
        status = INPUT_OK
        if (value is not None and age_check and self.stale_s
                and abs(value) >= STALE_MIN_ABS_W):
            age = self._age(entity_id)
            if age is not None and age > self.stale_s:
                status = INPUT_STALE
                value = None
                # Never bridge a later dropout with the frozen value.
                rec["value"] = None
                rec["at"] = None

        if status == INPUT_OK:
            if value is not None:
                rec["value"] = value
                rec["at"] = now
                rec["seen"] = True
            elif (rec["value"] is not None
                    and (now - rec["at"]).total_seconds() < hold_s):
                value = rec["value"]            # bridge a short dropout
            else:
                status = INPUT_UNAVAILABLE

        self._set_status(key, rec, status, now)
        return value, status

    def _set_status(self, key, rec, status, now):
        """Record a health transition and log it once."""
        prev = rec["status"]
        if status == prev:
            return
        rec["status"] = status
        if status == INPUT_OK:
            rec["fault_since"] = None
            _LOGGER.info(
                "AURUM: %s sensor %s is reporting again (was %s)",
                key, rec["entity"], prev)
            return
        if prev == INPUT_OK:
            rec["fault_since"] = now
        if status == INPUT_STALE:
            what = "has reported no new value for more than %d min" % (
                round((self.stale_s or 0) / 60))
        else:
            what = "is unavailable"
        # A sensor that has not delivered a value since start is usually
        # an integration still loading, and many inverters take their PV
        # sensor offline every night: log those quietly.
        log = (_LOGGER.warning if rec["seen"] and key != "pv"
               else _LOGGER.info)
        log("AURUM: %s sensor %s %s – %s",
            key, rec["entity"], what, _CONSEQUENCE.get(key, "ignored"))

    # ── main update ──────────────────────────────────────────────────

    def update(self, shared):
        """Read sensors, calculate excess, update shared dict."""
        now = shared.get("now") or datetime.now()

        # Grid power (positive = import, negative = export)
        grid_raw, _ = self._read(
            "grid", self.grid_power_entity, now, get_power_w,
            self.hold_s, True)

        if grid_raw is not None:
            if self._grid_reseed:
                self._grid_ema = None
                self._grid_ema_asym = None
                self._grid_reseed = False
            # Symmetric EMA (alpha=0.3) – used for battery decisions
            self._grid_ema = ema_update(
                self._grid_ema, grid_raw, self.ema_alpha)
            # Asymmetric EMA (fast down=0.7, slow up=0.2) – used for device
            # decisions. Reacts quickly to grid drops (= excess rising, real
            # PV surplus), slowly to grid spikes (= brief deficit, dampened).
            self._grid_ema_asym = ema_update_asymmetric(
                self._grid_ema_asym, grid_raw,
                self.ema_alpha_down, self.ema_alpha_up)
        else:
            self._grid_reseed = True

        # Numeric for every consumer; availability is in input_health.
        shared["grid_power_raw"] = grid_raw if grid_raw is not None else 0.0
        shared["grid_power_ema"] = (
            round(self._grid_ema, 1) if self._grid_ema is not None else 0.0)
        shared["grid_power_ema_asym"] = (
            round(self._grid_ema_asym, 1)
            if self._grid_ema_asym is not None else 0.0)

        # PV power (optional). A failed reading counts as 0 W, which keeps
        # the PV gate closed (a frozen daytime value used to hold it open).
        if self.pv_power_entity:
            pv, _ = self._read(
                "pv", self.pv_power_entity, now, get_power_w,
                self.hold_s, True)
            shared["pv_power"] = pv if pv is not None else 0
        else:
            shared["pv_power"] = 0

        # Battery SOC (optional)
        if self.battery_soc_entity:
            # Configured but unavailable: the last SOC is held for
            # SOC_HOLD_S; after that (or when none has been seen since
            # start) it is None = unknown. It must NOT fall back to -1 (the
            # "no battery" sentinel), which disabled all battery
            # protection, nor to 0 %, which forced the min_soc emergency
            # and switched off non-interruptible and cheap-grid devices.
            soc, _ = self._read(
                "soc", self.battery_soc_entity, now, get_float,
                SOC_HOLD_S, False)
            shared["battery_soc"] = soc
        else:
            shared["battery_soc"] = -1  # -1 = no battery

        # Battery charge/discharge power (optional)
        # battery_power_net = discharge - charge
        # Positive = net discharge, negative = net charge
        bat_charge = 0.0
        bat_discharge = 0.0
        battery_power_ok = True
        if self.battery_charge_power_entity:
            value, _ = self._read(
                "battery_charge", self.battery_charge_power_entity, now,
                get_power_w, self.hold_s, False)
            if value is None:
                battery_power_ok = False
            else:
                bat_charge = value
        if self.battery_discharge_power_entity:
            value, _ = self._read(
                "battery_discharge", self.battery_discharge_power_entity,
                now, get_power_w, self.hold_s, False)
            if value is None:
                battery_power_ok = False
            else:
                bat_discharge = value
        battery_power_net = bat_discharge - bat_charge
        shared["battery_power_net"] = round(battery_power_net, 1)
        shared["battery_charge_w"] = round(bat_charge, 1)
        shared["battery_discharge_w"] = round(bat_discharge, 1)

        # Surplus needs every term: with the grid unknown, the legacy
        # formula turned battery charging into phantom surplus; with the
        # battery terms unknown, discharge went unseen.
        blind = grid_raw is None or not battery_power_ok
        shared["surplus_blind"] = blind

        shared["input_health"] = {
            key: rec["status"] for key, rec in self._inputs.items()}
        shared["input_faults"] = [
            {"input": key, "status": rec["status"],
             "entity": rec["entity"], "since": rec["fault_since"]}
            for key, rec in self._inputs.items()
            if rec["status"] != INPUT_OK]

        if blind:
            # Neutral numbers for every other consumer (sensors, budget
            # trajectory). DeviceManager acts on surplus_blind itself.
            shared["excess"] = 0.0
            shared["excess_raw"] = 0.0
            return

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
        if has_battery_power and not self.battery_priority:
            # Legacy semantics: battery charge/discharge is folded into the
            # surplus, so devices may divert power away from battery charging
            # (pv - house). Per-device SOC thresholds are the only guard.
            shared["excess"] = round(
                -self._grid_ema_asym - battery_power_net, 1)
            shared["excess_raw"] = round(
                -grid_raw - battery_power_net, 1)
        elif has_battery_power:
            # battery_priority=True: the battery absorbs PV first and ONLY
            # genuine grid export is offered to devices (community request,
            # discussion #9) — so charge power is NOT surplus. Discharge,
            # however, IS a deficit: a hybrid inverter holds grid near 0 W
            # by discharging, and a grid-only view never saw that, so a
            # running device drained the battery down to min_soc instead
            # of being shed when PV faded.
            discharge = max(0.0, battery_power_net)
            shared["excess"] = round(-self._grid_ema_asym - discharge, 1)
            shared["excess_raw"] = round(-grid_raw - discharge, 1)
        else:
            # No battery power sensors: grid-only surplus. AURUM cannot see
            # battery discharge here; configure the battery power sensors
            # so running devices are shed when the battery starts feeding
            # them.
            shared["excess"] = round(-self._grid_ema_asym, 1)
            shared["excess_raw"] = round(-grid_raw, 1)
