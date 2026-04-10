"""
AURUM – Device Manager
=======================
Priority-based surplus distribution to household devices.
Supports hysteresis, debounce, min on/off times, deficit tolerance,
switch penalty, startup detection with WAITING state, SD preemption,
and priority-based shedding.

Ported 1:1 from HELIOS logic (without thermal model, comfort temps, TRV).
"""

import logging
from datetime import datetime, timedelta

from .helpers import get_float, get_state_safe, slugify
from ..const import (
    CONF_DEVICES,
    MODE_NORMAL,
    MODE_LOW_SOC,
    MODE_CHARGING,
    SD_STATE_STANDBY,
    SD_STATE_DETECTED,
    SD_STATE_WAITING,
    SD_STATE_RUNNING,
    SD_STATE_DONE,
    DEFAULT_DEV_NOMINAL_POWER,
    DEFAULT_DEV_PRIORITY,
    DEFAULT_DEV_SOC_THRESHOLD,
    DEFAULT_DEV_HYSTERESIS_ON,
    DEFAULT_DEV_HYSTERESIS_OFF,
    DEFAULT_DEV_DEBOUNCE_ON,
    DEFAULT_DEV_DEBOUNCE_OFF,
    DEFAULT_DEV_MIN_ON_TIME,
    DEFAULT_DEV_MIN_OFF_TIME,
    DEFAULT_DEV_RESIDUAL_POWER,
    DEFAULT_EXCESS_DEFICIT_TOLERANCE,
    DEFAULT_SOC_GRID_DEFICIT_TOLERANCE,
    override_entity_id,
    muss_heute_entity_id,
)

_LOGGER = logging.getLogger(__name__)


class DeviceManager:
    """Manage priority-based device switching (HELIOS-compatible logic)."""

    def __init__(self, hass, config):
        self.hass = hass
        self.config = config
        self.action_csv = None
        self.notifications = None  # Set by coordinator if available
        self.pricing = None  # Set by coordinator if pricing module active

        # Global settings
        self.excess_deficit_tolerance = config.get(
            "excess_deficit_tolerance", DEFAULT_EXCESS_DEFICIT_TOLERANCE)
        self.soc_grid_deficit_tolerance = config.get(
            "soc_grid_deficit_tolerance", DEFAULT_SOC_GRID_DEFICIT_TOLERANCE)

        # Load device configs
        self.devices = []
        for dev_cfg in config.get(CONF_DEVICES, []):
            self.devices.append(self._init_device(dev_cfg))

        # Sort by priority (highest first)
        self.devices.sort(key=lambda d: d["priority"], reverse=True)

    def _init_device(self, cfg):
        """Initialize a device from config dict."""
        name = cfg.get("name", "Unknown")
        return {
            # Identity
            "name": name,
            "slug": slugify(name),

            # Entities
            "switch_entity": cfg.get("switch_entity"),
            "power_entity": cfg.get("power_entity"),

            # Parameters
            "nominal_power": max(1, cfg.get(
                "nominal_power", DEFAULT_DEV_NOMINAL_POWER)),
            "priority": cfg.get("priority", DEFAULT_DEV_PRIORITY),
            "soc_threshold": cfg.get(
                "soc_threshold", DEFAULT_DEV_SOC_THRESHOLD),
            "hysteresis_on": cfg.get(
                "hysteresis_on", DEFAULT_DEV_HYSTERESIS_ON),
            "hysteresis_off": cfg.get(
                "hysteresis_off", DEFAULT_DEV_HYSTERESIS_OFF),
            "debounce_on": cfg.get("debounce_on", DEFAULT_DEV_DEBOUNCE_ON),
            "debounce_off": cfg.get("debounce_off", DEFAULT_DEV_DEBOUNCE_OFF),
            "min_on_time": cfg.get("min_on_time", DEFAULT_DEV_MIN_ON_TIME),
            "min_off_time": cfg.get("min_off_time", DEFAULT_DEV_MIN_OFF_TIME),

            # Behavior
            "interruptible": cfg.get("interruptible", True),
            "manual_override_entity": cfg.get("manual_override_entity"),
            "muss_heute_entity": cfg.get("muss_heute_entity"),
            "residual_power": cfg.get(
                "residual_power", DEFAULT_DEV_RESIDUAL_POWER),

            # Price-aware scheduling
            "price_mode": cfg.get("price_mode", "solar_only"),
            "max_price": cfg.get("max_price", 0),

            # Deadline scheduling
            "deadline": cfg.get("deadline"),           # "HH:MM" or None
            "estimated_runtime": cfg.get("estimated_runtime", 0),  # minutes
            "force_started": False,
            "_scheduling_reason": None,

            # Startup detection
            "startup_detection": cfg.get("startup_detection", False),
            "sd_state": "",
            "sd_power_threshold": cfg.get("sd_power_threshold", 5),
            "sd_detection_time": cfg.get("sd_detection_time", 5),
            "sd_max_runtime": cfg.get("sd_max_runtime", 10800),
            "sd_standby_power": cfg.get("sd_standby_power", 3),
            "sd_finish_power": cfg.get("sd_finish_power",
                                       cfg.get("sd_standby_power", 3)),
            "sd_finish_time": cfg.get("sd_finish_time", 600),
            "sd_min_runtime": cfg.get("sd_min_runtime", 300),
            "sd_detected_at": None,
            "sd_waiting_since": None,
            "sd_running_since": None,
            "sd_lockout_until": None,
            "sd_power_above_since": None,
            "sd_power_below_since": None,
            "sd_power_samples": [],

            # Runtime & energy state
            "on_since": None,
            "last_on": None,
            "last_off": None,
            "runtime_today_s": 0,
            "energy_today_wh": 0.0,
            "total_switches": 0,
            "_runtime_tick": None,

            # Surplus tracking
            "excess_since": None,          # When excess first became sufficient
            "_excess_deficit_since": None,  # Deficit tolerance timer
            "_soc_grid_deficit_since": None,  # SOC grid deficit timer
            "_switch_times": [],            # Recent switch timestamps
            "_pending_off": None,           # Deferred turn-off reason
            "_cached_on": False,            # Cached is_on state for shedding

            # Manual override
            "managed_on": False,
        }

    # ══════════════════════════════════════════════════════════════
    #  MAIN UPDATE (HELIOS-compatible)
    # ══════════════════════════════════════════════════════════════

    def update(self, shared):
        """Main device control loop (ported from HELIOS)."""
        now = shared["now"]
        excess = shared.get("excess_for_devices", 0)        # EMA (turn-on)
        excess_raw = shared.get("excess_raw_for_devices", 0)  # RAW (turn-off)
        battery_soc = shared.get("battery_soc", -1)
        battery_mode = shared.get("battery_mode", MODE_NORMAL)

        # Grid-only excess: how much PV is being exported to grid right now.
        # Used as fallback when battery SOC is below device threshold —
        # device is allowed to run on genuine export even without full surplus.
        # Positive = exporting to grid (= usable), negative = importing.
        grid_excess = -shared.get("grid_power_ema_asym", 0)

        # PV Budget cap: maximum power AURUM may allocate to devices today.
        # None when budget module is not active.
        device_budget_w = shared.get("device_budget_w")

        # ── Emergency: battery charging → turn off everything ────
        if battery_mode == MODE_CHARGING:
            for dev in self.devices:
                # SD devices in standby: keep Shelly ON (3-5W)
                if (dev["startup_detection"]
                        and dev["sd_state"] in ("", SD_STATE_STANDBY)):
                    continue
                # SD running: don't interrupt program
                if (dev["startup_detection"]
                        and dev["sd_state"] == SD_STATE_RUNNING):
                    continue
                if self._is_device_on(dev):
                    self._turn_off(dev, now, excess, battery_soc,
                                   "battery_charging")
            self._publish_device_states(shared, battery_soc)
            return

        # ── Control each device (priority-ordered) ───────────────
        available_excess = excess
        devices_on = 0
        newly_allocated = 0.0

        for dev in self.devices:
            was_on = self._is_device_on(dev)
            dev["_cached_on"] = was_on
            actual_power = self._get_device_power(dev) if was_on else 0

            # Accumulate runtime + energy (SD: only count RUNNING state)
            if was_on:
                if (not dev["startup_detection"]
                        or dev["sd_state"] == SD_STATE_RUNNING):
                    self._accumulate_runtime(dev, now, actual_power)

            # ── 1. Manual override → skip device ────────────────
            if self._is_manual_override(dev):
                if was_on:
                    dev["_pending_off"] = None
                    if dev["on_since"] is None:
                        dev["on_since"] = now
                    devices_on += 1
                continue

            # ── 1b. Device on but not managed → track, apply turn-off logic ──
            # Only skip when override switch is explicitly ON (block 1).
            # A manually-started device still gets evaluated for turn-off
            # (e.g. battery protection, insufficient surplus) so AURUM can
            # shed it like any other device when needed.
            if was_on and not dev["managed_on"]:
                if dev["on_since"] is None:
                    dev["on_since"] = now
                # Fall through to step 2/3 for turn-off evaluation

            # ── 2. Startup detection devices ─────────────────────
            if dev["startup_detection"]:
                sd_turnon = excess - newly_allocated
                counted, sd_new = self._handle_startup_detection(
                    dev, sd_turnon, battery_soc, actual_power, now, excess)
                if sd_new > 0:
                    newly_allocated += sd_new
                if counted:
                    devices_on += 1
                continue

            # ── 3. Regular devices ───────────────────────────────
            soc_threshold = dev["soc_threshold"]

            if was_on:
                devices_on += 1
                # RAW excess for turn-off (fast response to clouds)
                turnoff_excess = excess_raw - newly_allocated

                should_off = self._should_turn_off(
                    dev, turnoff_excess, battery_soc,
                    soc_threshold, now)
                dev["_pending_off"] = should_off
            else:
                # EMA excess for turn-on (stable, prevents flapping)
                turnon_excess = excess - newly_allocated
                # Grid-only fallback for SOC-below-threshold case
                turnon_grid = grid_excess - newly_allocated

                # ── Budget cap: don't allocate beyond today's budget ──
                # Exception: when SOC < threshold the device runs on
                # grid export anyway (no battery used), so budget doesn't
                # apply in that case.
                in_grid_only_mode = (
                    battery_soc >= 0 and battery_soc < soc_threshold)
                budget_cap = (
                    device_budget_w is not None
                    and not in_grid_only_mode
                    and newly_allocated + dev["nominal_power"] > device_budget_w
                )
                if budget_cap:
                    if not dev.get("_budget_cap_logged"):
                        _LOGGER.debug(
                            "%s: budget cap reached "
                            "(allocated=%.0fW budget=%.0fW)",
                            dev["name"], newly_allocated, device_budget_w)
                        dev["_budget_cap_logged"] = True
                    dev["excess_since"] = None
                    continue

                dev["_budget_cap_logged"] = False
                should_on = self._should_turn_on(
                    dev, turnon_excess, turnon_grid, battery_soc,
                    soc_threshold, now)

                if should_on:
                    self._turn_on(dev, now, excess, battery_soc)
                    newly_allocated += dev["nominal_power"]
                    available_excess -= dev["nominal_power"]
                    devices_on += 1
                else:
                    # Clear excess timer if not enough surplus
                    needed = (dev["nominal_power"] + dev["hysteresis_on"]
                              + dev["residual_power"])
                    if turnon_excess < needed:
                        dev["excess_since"] = None

        # ── Priority-based shedding ──────────────────────────────
        candidates = []
        for dev in self.devices:
            reason = dev.get("_pending_off")
            if reason and dev.get("_cached_on"):
                candidates.append(dev)

        if candidates:
            # Sort by priority ascending (lowest shed first)
            candidates.sort(key=lambda d: d["priority"])

            deficit = -(excess_raw - newly_allocated)
            freed = 0.0
            for dev in candidates:
                self._turn_off(dev, now, excess, battery_soc,
                               dev["_pending_off"])
                # Use nominal_power for freed accounting (consistent with
                # newly_allocated which also uses nominal). Sensor values
                # can lag or be unavailable and would cause over-shedding.
                freed += dev["nominal_power"]
                devices_on -= 1
                if freed >= deficit:
                    break

        self._publish_device_states(shared, battery_soc)

    # ══════════════════════════════════════════════════════════════
    #  SHOULD TURN ON / OFF (HELIOS-compatible)
    # ══════════════════════════════════════════════════════════════

    def _should_turn_on(self, dev, available_excess, available_grid_excess,
                        battery_soc, soc_threshold, now):
        """Check if device should be turned on. Returns True/False."""
        # Min off-time: don't turn back on too quickly
        if (dev["last_off"]
                and (now - dev["last_off"]).total_seconds()
                < dev["min_off_time"]):
            return False

        # Select effective excess based on SOC (HELIOS-compatible):
        # Below threshold: device may only run on genuine grid export
        # (PV surplus going to grid), not on battery discharge.
        if battery_soc >= 0 and battery_soc < soc_threshold:
            eff_excess = available_grid_excess
        else:
            eff_excess = available_excess

        # ── Price-aware: cheap grid power allows immediate turn-on ──
        if (dev.get("price_mode") == "cheap_grid"
                and self.pricing
                and self.pricing.is_price_ok(dev)):
            # Debounce still applies (prevents flapping on price edges)
            if dev["excess_since"] is None:
                dev["excess_since"] = now
                return False
            elapsed = (now - dev["excess_since"]).total_seconds()
            if elapsed < dev["debounce_on"]:
                return False
            dev["_scheduling_reason"] = "cheap_grid"
            return True

        # Enough excess? (nominal + hysteresis_on + residual_power)
        needed = (dev["nominal_power"] + dev["hysteresis_on"]
                  + dev["residual_power"])
        if eff_excess < needed:
            return False

        # Debounce: excess must persist for debounce_on * penalty seconds
        penalty = self._get_switch_penalty(dev, now)
        if dev["excess_since"] is None:
            dev["excess_since"] = now
            return False

        elapsed = (now - dev["excess_since"]).total_seconds()
        if elapsed < dev["debounce_on"] * penalty:
            return False

        return True

    def _should_turn_off(self, dev, available_excess, battery_soc,
                         soc_threshold, now):
        """Check if device should be turned off. Returns reason or None."""
        # Non-interruptible devices never turn off via surplus logic
        if not dev["interruptible"]:
            return None

        # Force-started devices: never turn off via surplus logic
        if dev["force_started"]:
            return None

        # Min on-time protection
        if dev["on_since"]:
            on_duration = (now - dev["on_since"]).total_seconds()
            if on_duration < dev["min_on_time"]:
                return None

        # SOC below threshold: turn off if deficit persists
        # Uses per-device debounce_off as tolerance (same semantics).
        if battery_soc >= 0 and battery_soc < soc_threshold:
            if available_excess < -dev["hysteresis_off"]:
                if dev["_soc_grid_deficit_since"] is None:
                    dev["_soc_grid_deficit_since"] = now
                    return None
                elapsed = (
                    now - dev["_soc_grid_deficit_since"]).total_seconds()
                if elapsed < dev["debounce_off"]:
                    return None
                dev["_soc_grid_deficit_since"] = None
                return "soc_grid_deficit"
            dev["_soc_grid_deficit_since"] = None

        # Excess deficit: turn off if deficit persists for debounce_off seconds.
        # Switch penalty multiplies the threshold to protect relays.
        if available_excess < -dev["hysteresis_off"]:
            penalty = self._get_switch_penalty(dev, now)
            if dev["_excess_deficit_since"] is None:
                dev["_excess_deficit_since"] = now
                return None

            elapsed = (
                now - dev["_excess_deficit_since"]).total_seconds()
            if elapsed < dev["debounce_off"] * penalty:
                return None

            dev["_excess_deficit_since"] = None
            return "excess_deficit"

        # No deficit: clear timer
        dev["_excess_deficit_since"] = None
        return None

    def _get_switch_penalty(self, dev, now):
        """Return debounce multiplier based on recent switch frequency.

        Protects relays and prevents oscillation.
        2+ switches/hour -> 1.5x, 4+ -> 2.0x, 6+ -> 3.0x debounce.
        """
        cutoff = now - timedelta(hours=1)
        dev["_switch_times"] = [
            t for t in dev["_switch_times"] if t > cutoff]
        count = len(dev["_switch_times"])
        if count > 6:
            return 3.0
        if count > 4:
            return 2.0
        if count > 2:
            return 1.5
        return 1.0

    # ══════════════════════════════════════════════════════════════
    #  STARTUP DETECTION STATE MACHINE (HELIOS-compatible)
    #  States: STANDBY → DETECTED → WAITING → RUNNING → STANDBY
    # ══════════════════════════════════════════════════════════════

    def _handle_startup_detection(self, dev, turnon_excess,
                                  battery_soc, actual_power, now, excess):
        """Handle startup detection state machine.

        Returns (counted_as_on, newly_started_power).
        """
        sd_state = dev["sd_state"]
        soc_threshold = dev["soc_threshold"]

        if not sd_state:
            dev["sd_state"] = SD_STATE_STANDBY
            sd_state = SD_STATE_STANDBY

        # ── STANDBY: Shelly ON, device in standby, monitor power ─
        if sd_state == SD_STATE_STANDBY:
            # Ensure Shelly is ON for detection
            if not self._is_device_on(dev):
                self.hass.turn_on(dev["switch_entity"])
                dev["managed_on"] = True
                dev["on_since"] = now

            if actual_power > dev["sd_power_threshold"]:
                if dev["sd_power_above_since"] is None:
                    dev["sd_power_above_since"] = now
                elapsed = (
                    now - dev["sd_power_above_since"]).total_seconds()
                if elapsed >= dev["sd_detection_time"]:
                    # Program start detected!
                    self.hass.log(
                        f"AURUM SD [{dev['name']}]: Program detected "
                        f"({actual_power:.0f}W for {elapsed:.0f}s)")
                    dev["sd_state"] = SD_STATE_DETECTED
                    dev["sd_detected_at"] = now
                    sd_state = SD_STATE_DETECTED  # fall through
                    self._notify(
                        f"\U0001f50d {dev['name']} erkannt "
                        f"– wartet auf PV-Überschuss",
                        tag=f"aurum_sd_{dev['name']}")
                else:
                    return False, 0
            else:
                dev["sd_power_above_since"] = None
                return False, 0

        # ── DETECTED: Turn OFF immediately → WAITING (transient) ─
        if sd_state == SD_STATE_DETECTED:
            self._turn_off(dev, now, excess, battery_soc,
                           "sd_pause_program")
            dev["sd_state"] = SD_STATE_WAITING
            dev["sd_waiting_since"] = now
            dev["excess_since"] = None
            self.hass.log(
                f"AURUM SD [{dev['name']}]: Paused, "
                f"waiting for PV excess")
            return False, 0

        # ── WAITING: Device OFF, wait for PV excess + SOC ────────
        if sd_state == SD_STATE_WAITING:
            nominal = dev["nominal_power"]

            # Enforce switch-off every cycle while waiting.
            # Shelly may have restored its ON state after an HA restart
            # ("restore last state" behaviour). Without this guard the
            # machine keeps running even though AURUM is waiting for surplus.
            if self._is_device_on(dev):
                self._turn_off(dev, now, excess, battery_soc,
                               "sd_waiting_enforce_off")

            # Deadline check: force start if past latest_start
            if self._deadline_urgent(dev, now):
                self.hass.log(
                    f"AURUM SD [{dev['name']}]: Deadline start "
                    f"(grid power)")
                self._turn_on(dev, now, excess, battery_soc,
                              "deadline_forced")
                dev["sd_state"] = SD_STATE_RUNNING
                dev["sd_running_since"] = now
                dev["sd_power_samples"] = []
                dev["sd_lockout_until"] = now + timedelta(
                    seconds=dev["sd_max_runtime"])
                dev["excess_since"] = None
                dev["force_started"] = True
                self._notify(
                    f"\u26a0\ufe0f {dev['name']} per Deadline gestartet "
                    f"(Netzstrom)",
                    tag=f"aurum_sd_{dev['name']}")
                return True, nominal

            # PV excess check
            needed = nominal + dev["hysteresis_on"]
            soc_ok = battery_soc < 0 or battery_soc >= soc_threshold
            if turnon_excess >= needed and soc_ok:
                # Debounce: conditions must persist
                if dev["excess_since"] is None:
                    dev["excess_since"] = now
                    return False, 0
                elapsed = (
                    now - dev["excess_since"]).total_seconds()
                if elapsed < dev["debounce_on"]:
                    return False, 0

                # Excess sufficient + debounce passed → start
                self._turn_on(dev, now, excess, battery_soc,
                              "excess_sufficient")
                dev["sd_state"] = SD_STATE_RUNNING
                dev["sd_running_since"] = now
                dev["sd_power_samples"] = []
                dev["sd_lockout_until"] = now + timedelta(
                    seconds=dev["sd_max_runtime"])
                dev["excess_since"] = None
                dev["force_started"] = False
                dev["_scheduling_reason"] = "excess_sufficient"
                self.hass.log(
                    f"AURUM SD [{dev['name']}]: Started "
                    f"(excess={turnon_excess:.0f}W >= "
                    f"{needed:.0f}W needed)")
                self._notify(
                    f"\u25b6\ufe0f {dev['name']} läuft jetzt "
                    f"(PV-Überschuss)",
                    tag=f"aurum_sd_{dev['name']}")
                return True, nominal
            else:
                # Try preemption before giving up
                freed = self._preempt_for_sd(
                    dev, needed, turnon_excess, battery_soc,
                    soc_threshold, now, excess)
                if freed > 0:
                    return False, 0
                dev["excess_since"] = None
                return False, 0

        # ── RUNNING: Program active (lockout) ────────────────────
        if sd_state == SD_STATE_RUNNING:
            # Collect power sample
            if actual_power > dev["sd_standby_power"]:
                dev["sd_power_samples"].append(actual_power)

            running_since = dev["sd_running_since"]
            runtime_s = (
                (now - running_since).total_seconds()
                if running_since else 0)

            # A) Safety max: force finish
            max_expired = (
                now >= dev["sd_lockout_until"]
                if dev["sd_lockout_until"] else False)

            # B) Smart finish: power < finish_power for finish_time
            smart_finish = False
            if runtime_s >= dev["sd_min_runtime"]:
                if actual_power < dev["sd_finish_power"]:
                    if dev["sd_power_below_since"] is None:
                        dev["sd_power_below_since"] = now
                    below_s = (
                        now - dev["sd_power_below_since"]
                    ).total_seconds()
                    if below_s >= dev["sd_finish_time"]:
                        smart_finish = True
                else:
                    dev["sd_power_below_since"] = None

            if smart_finish or max_expired:
                reason = "smart_finish" if smart_finish else "max_runtime"
                runtime_min = int(runtime_s / 60)
                self.hass.log(
                    f"AURUM SD [{dev['name']}]: Program complete "
                    f"({reason}, {actual_power:.0f}W, "
                    f"{runtime_min}min)")
                self._sd_reset(dev)
                self._accumulate_runtime(dev, now)
                dev["on_since"] = None
                dev["_runtime_tick"] = None
                self._notify(
                    f"\u2705 {dev['name']} fertig! "
                    f"Laufzeit: {runtime_min}min ({reason})",
                    tag=f"aurum_sd_{dev['name']}")
                self._reset_muss_heute(dev)
                return False, 0

            # Still running
            return True, 0

        return False, 0

    def _sd_reset(self, dev):
        """Reset all SD state fields to standby."""
        dev["sd_state"] = SD_STATE_STANDBY
        dev["sd_detected_at"] = None
        dev["sd_waiting_since"] = None
        dev["sd_lockout_until"] = None
        dev["sd_power_above_since"] = None
        dev["sd_power_below_since"] = None
        dev["sd_running_since"] = None
        dev["sd_power_samples"] = []
        dev["force_started"] = False

    def _preempt_for_sd(self, sd_device, needed_w, turnon_excess,
                        battery_soc, soc_threshold, now, excess):
        """Preempt lower-priority devices to free up excess for SD device.

        Returns watts freed.
        """
        if battery_soc >= 0 and battery_soc < soc_threshold:
            return 0

        deficit = needed_w - turnon_excess
        if deficit <= 0:
            return 0

        candidates = []
        for dev in self.devices:
            if dev["name"] == sd_device["name"]:
                continue
            if not dev.get("_cached_on", False):
                continue
            if not dev["managed_on"]:
                continue  # manual override, don't preempt
            if not dev["interruptible"]:
                continue  # non-interruptible, don't preempt
            if dev["priority"] >= sd_device["priority"]:
                continue
            if (dev["startup_detection"]
                    and dev["sd_state"] == SD_STATE_RUNNING):
                continue
            if dev["on_since"]:
                on_s = (now - dev["on_since"]).total_seconds()
                if on_s < dev["min_on_time"]:
                    continue
            actual_w = self._get_device_power(dev)
            candidates.append((dev, actual_w))

        if not candidates:
            return 0

        candidates.sort(key=lambda x: x[0]["priority"])

        freed = 0
        victims = []
        for dev, power_w in candidates:
            if freed >= deficit:
                break
            self._turn_off(dev, now, excess, battery_soc,
                           f"preempt_for_{sd_device['name']}")
            freed += power_w
            victims.append(f"{dev['name']}({power_w:.0f}W)")

        if victims:
            self.hass.log(
                f"AURUM PREEMPT: {', '.join(victims)} OFF "
                f"for {sd_device['name']} "
                f"(needs {needed_w:.0f}W, freed {freed:.0f}W)")
            self._notify(
                f"\u26a1 {', '.join(victims)} aus "
                f"\u2192 Platz für {sd_device['name']}",
                tag=f"aurum_preempt_{sd_device['name']}")
        return freed

    # ══════════════════════════════════════════════════════════════
    #  DEVICE STATE HELPERS
    # ══════════════════════════════════════════════════════════════

    def _is_device_on(self, dev):
        """Check if device switch is currently on."""
        state = get_state_safe(self.hass, dev["switch_entity"])
        return state == "on"

    def _get_device_power(self, dev):
        """Read current power or fall back to nominal."""
        if dev["power_entity"]:
            return get_float(self.hass, dev["power_entity"],
                             dev["nominal_power"])
        return dev["nominal_power"]

    def _turn_on(self, dev, now, excess, soc, reason="surplus_available"):
        """Turn a device on."""
        self.hass.turn_on(dev["switch_entity"])
        dev["on_since"] = now
        dev["last_on"] = now
        dev["_runtime_tick"] = now
        dev["total_switches"] += 1
        dev["managed_on"] = True
        dev["_scheduling_reason"] = reason
        dev["excess_since"] = None
        dev["_excess_deficit_since"] = None
        dev["_soc_grid_deficit_since"] = None
        dev["_switch_times"].append(now)
        self._log_action(dev, "ON", excess, soc, reason)

    def _turn_off(self, dev, now, excess, soc, reason):
        """Turn a device off."""
        self.hass.turn_off(dev["switch_entity"])
        self._accumulate_runtime(dev, now)
        dev["on_since"] = None
        dev["last_off"] = now
        dev["_runtime_tick"] = None
        dev["managed_on"] = False
        dev["force_started"] = False
        dev["excess_since"] = None
        dev["_excess_deficit_since"] = None
        dev["_soc_grid_deficit_since"] = None
        dev["_switch_times"].append(now)
        self._log_action(dev, "OFF", excess, soc, reason)

    def _deadline_urgent(self, dev, now):
        """Check if device must start now to meet its deadline.

        Returns True if: time_remaining < estimated_runtime + buffer.
        If muss_heute_entity is configured, deadline only applies
        when muss_heute is ON. Without muss_heute entity, deadline
        always applies (backward compatible).
        """
        deadline_str = dev.get("deadline")
        est_runtime = dev.get("estimated_runtime", 0)
        if not deadline_str or not est_runtime:
            return False

        # Deadline force-start only when muss_heute is active.
        # _is_muss_heute() checks both the native auto-created switch
        # (switch.aurum_{slug}_muss_heute) and the optional legacy entity.
        # This guard always runs so a device with only a deadline set
        # does NOT get force-started every day without the user enabling
        # muss_heute explicitly.
        if not self._is_muss_heute(dev):
            return False

        try:
            parts = deadline_str.split(":")
            deadline_hour = int(parts[0])
            deadline_min = int(parts[1]) if len(parts) > 1 else 0

            deadline_today = now.replace(
                hour=deadline_hour, minute=deadline_min,
                second=0, microsecond=0)

            if now >= deadline_today:
                # Deadline already passed but device not yet started:
                # force-start immediately (better late than never).
                # Once force_started=True this won't re-trigger.
                if not dev.get("force_started"):
                    return True
                return False

            time_remaining = (deadline_today - now).total_seconds()
            runtime_needed = est_runtime * 60
            buffer = 300  # 5 min safety buffer

            return time_remaining <= (runtime_needed + buffer)
        except (ValueError, IndexError, AttributeError, TypeError):
            return False

    def _accumulate_runtime(self, dev, now, power_w=0):
        """Accumulate runtime and energy for device."""
        tick = dev.get("_runtime_tick") or dev.get("on_since")
        if tick:
            elapsed = max(0, (now - tick).total_seconds())
            dev["runtime_today_s"] += elapsed
            dev["energy_today_wh"] += power_w * elapsed / 3600
        dev["_runtime_tick"] = now

    def _publish_device_states(self, shared, battery_soc):
        """Publish device states to shared dict."""
        device_states = []
        devices_on = 0
        total_power = 0
        for dev in self.devices:
            is_on = self._is_device_on(dev)
            power = self._get_device_power(dev) if is_on else 0
            # SD devices: always use sd_state as authoritative state.
            # In WAITING the Shelly is OFF but the state is still "waiting",
            # not "off". Non-SD devices use the physical switch state.
            if dev["startup_detection"] and dev["sd_state"]:
                state = dev["sd_state"]
            elif is_on:
                if not dev["managed_on"]:
                    state = "manual_override"
                else:
                    state = "on"
            else:
                state = "off"
            if is_on:
                devices_on += 1
                total_power += power

            device_states.append({
                "name": dev["name"],
                "slug": dev["slug"],
                "state": state,
                "power": round(power, 1),
                "runtime_today_s": round(dev["runtime_today_s"]),
                "energy_today_wh": round(dev["energy_today_wh"], 1),
                "sd_state": dev.get("sd_state", ""),
                "soc_threshold": dev["soc_threshold"],
                "priority": dev["priority"],
                "force_started": dev.get("force_started", False),
                "interruptible": dev["interruptible"],
                "scheduling_reason": dev.get("_scheduling_reason"),
                "price_mode": dev.get("price_mode", "solar_only"),
            })

        shared["device_states"] = device_states
        shared["devices_on"] = devices_on
        shared["device_power_total"] = round(total_power, 1)

    def _is_manual_override(self, dev):
        """Check if manual override is active for this device.

        Returns True if the native switch OR the legacy entity is ON.
        Both are checked independently – either being ON is sufficient.
        """
        slug = dev["slug"]
        # Native switch (auto-created by AURUM)
        if self.hass.get_state(override_entity_id(slug)) == "on":
            return True
        # Legacy fallback (user-configured input_boolean)
        legacy = dev.get("manual_override_entity")
        if legacy:
            try:
                return self.hass.get_state(legacy) == "on"
            except Exception:
                pass
        return False

    def _is_muss_heute(self, dev):
        """Check if 'must run today' is active for this device.

        Returns True if the native switch OR the legacy entity is ON.
        Both are checked independently – either being ON is sufficient.
        """
        slug = dev["slug"]
        # Native switch (auto-created by AURUM)
        if self.hass.get_state(muss_heute_entity_id(slug)) == "on":
            return True
        # Legacy fallback (user-configured input_boolean)
        legacy = dev.get("muss_heute_entity")
        if legacy:
            try:
                return self.hass.get_state(legacy) == "on"
            except Exception:
                pass
        return False

    def _reset_muss_heute(self, dev):
        """Auto-reset muss_heute to OFF after program completion.

        Turns off both the native switch and any legacy entity.
        """
        slug = dev["slug"]
        # 1. Reset native switch
        try:
            native_id = muss_heute_entity_id(slug)
            if self.hass.get_state(native_id) == "on":
                self.hass.turn_off(native_id)
                _LOGGER.debug(
                    "AURUM: %s muss_heute -> OFF (program complete)",
                    dev["name"])
        except Exception as e:
            _LOGGER.warning(
                "Error resetting native muss_heute for %s: %s",
                dev["name"], e)
        # 2. Reset legacy entity if configured
        legacy = dev.get("muss_heute_entity")
        if legacy:
            try:
                if self.hass.get_state(legacy) == "on":
                    self.hass.turn_off(legacy)
            except Exception as e:
                _LOGGER.warning(
                    "Error resetting legacy muss_heute for %s: %s",
                    dev["name"], e)

    def _notify(self, message, tag=None, throttle_key=None, importance=None):
        """Send notification via HA persistent_notification + optional mobile push.

        Uses persistent_notification.create for broad compatibility.
        If notify_service is configured (e.g. 'notify.mobile_app_christian'),
        also sends a mobile push notification.
        """
        # ── Persistent notification (always) ──
        try:
            kwargs = {
                "message": message,
                "title": "AURUM",
            }
            if tag:
                kwargs["notification_id"] = tag
            self.hass.call_service(
                "persistent_notification/create", **kwargs)
        except Exception:
            pass  # best-effort

        # ── Mobile push (if configured) ──
        notify_svc = self.config.get("notify_service", "")
        if notify_svc:
            try:
                # notify_service can be "notify.mobile_app_christian"
                # or just "mobile_app_christian"
                svc = notify_svc if "/" in notify_svc else f"notify/{notify_svc}"
                push_kwargs = {
                    "message": message,
                    "title": "AURUM",
                }
                if tag:
                    push_kwargs["data"] = {"tag": tag}
                self.hass.call_service(svc, **push_kwargs)
            except Exception:
                pass  # best-effort

    def _log_action(self, dev, action, excess, soc, reason):
        """Log a device action to CSV."""
        if self.action_csv:
            self.action_csv.log_row([
                datetime.now().isoformat(),
                dev["name"],
                action,
                round(excess, 1),
                round(soc, 1) if soc >= 0 else "n/a",
                reason,
            ])

    def daily_reset(self):
        """Reset daily counters (call at midnight)."""
        for dev in self.devices:
            self.hass.log(
                f"AURUM daily {dev['name']}: "
                f"{dev['runtime_today_s'] / 60:.1f} min, "
                f"{dev['energy_today_wh'] / 1000:.3f} kWh")
            dev["runtime_today_s"] = 0
            dev["energy_today_wh"] = 0.0
            dev["total_switches"] = 0
            dev["_switch_times"] = []
            dev["_scheduling_reason"] = None
