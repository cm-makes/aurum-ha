"""
AURUM – Device Manager
=======================
Priority-based surplus distribution to household devices.
Supports hysteresis, debounce, min on/off times, and
startup detection (state machine for washing machines etc.).

Focused on surplus distribution – no thermal model, no TRV, no comfort tracking.
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
)

_LOGGER = logging.getLogger(__name__)


class DeviceManager:
    """Manage priority-based device switching."""

    def __init__(self, hass, config):
        self.hass = hass
        self.config = config
        self.action_csv = None

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
            "nominal_power": cfg.get("nominal_power", DEFAULT_DEV_NOMINAL_POWER),
            "priority": cfg.get("priority", DEFAULT_DEV_PRIORITY),
            "soc_threshold": cfg.get("soc_threshold", DEFAULT_DEV_SOC_THRESHOLD),
            "hysteresis_on": cfg.get("hysteresis_on", DEFAULT_DEV_HYSTERESIS_ON),
            "hysteresis_off": cfg.get("hysteresis_off", DEFAULT_DEV_HYSTERESIS_OFF),
            "debounce_on": cfg.get("debounce_on", DEFAULT_DEV_DEBOUNCE_ON),
            "debounce_off": cfg.get("debounce_off", DEFAULT_DEV_DEBOUNCE_OFF),
            "min_on_time": cfg.get("min_on_time", DEFAULT_DEV_MIN_ON_TIME),
            "min_off_time": cfg.get("min_off_time", DEFAULT_DEV_MIN_OFF_TIME),

            # Deadline scheduling
            "deadline": cfg.get("deadline"),           # "HH:MM" or None
            "estimated_runtime": cfg.get("estimated_runtime", 0),  # minutes
            "force_started": False,

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
            "sd_running_since": None,
            "sd_finish_detected_at": None,

            # Runtime state
            "on_since": None,       # When AURUM turned it on (for min_on_time)
            "last_on": None,
            "last_off": None,
            "runtime_today_s": 0,
            "total_switches": 0,
            "_runtime_tick": None,  # Last runtime accumulation timestamp

            # Manual override: if device turned on externally, protect it
            "managed_on": False,    # True = AURUM turned it on
        }

    # ══════════════════════════════════════════════════════════════
    #  MAIN UPDATE
    # ══════════════════════════════════════════════════════════════

    def update(self, shared):
        """Main device control loop."""
        now = shared["now"]
        excess = shared.get("excess_for_devices", 0)
        battery_soc = shared.get("battery_soc", -1)
        battery_mode = shared.get("battery_mode", MODE_NORMAL)

        # Update runtimes for devices that are on
        self._update_runtimes(now)

        # Update startup detection state machines
        for dev in self.devices:
            if dev["startup_detection"]:
                self._update_sd_state(dev, now)

        # Decide: turn on or off
        remaining_excess = excess

        for dev in self.devices:
            is_on = self._is_device_on(dev)
            power = self._get_device_power(dev)

            # Deadline check: must this device start now?
            # Checked first – deadline overrides everything except SD running
            deadline_urgent = self._deadline_urgent(dev, now)

            # Skip SD devices that are running a program
            if dev["startup_detection"] and dev["sd_state"] == SD_STATE_RUNNING:
                if is_on:
                    remaining_excess -= power
                continue

            if deadline_urgent and not is_on:
                # Force start – deadline approaching
                self._turn_on(dev, now, excess, battery_soc)
                dev["force_started"] = True
                remaining_excess -= dev["nominal_power"]
                self.hass.log(
                    f"AURUM [{dev['name']}]: Force-started "
                    f"(deadline {dev['deadline']}, "
                    f"est. {dev['estimated_runtime']}min)")
                continue

            if deadline_urgent and is_on:
                # Already running under deadline pressure – don't turn off
                dev["force_started"] = True
                remaining_excess -= power
                continue

            # SD devices in standby: plug must stay ON for detection
            # If plug is off → turn it on (draws only ~2W standby)
            # If plug is on → keep it on, don't touch
            if dev["startup_detection"] and dev["sd_state"] in (
                    SD_STATE_STANDBY, SD_STATE_DETECTED):
                if not is_on:
                    self.hass.turn_on(dev["switch_entity"])
                    dev["managed_on"] = True
                    dev["on_since"] = now
                    self.hass.log(
                        f"AURUM SD [{dev['name']}]: "
                        f"Plug ON for program detection (standby ~2W)")
                continue

            # Manual override: device was turned on externally → don't touch
            if is_on and not dev["managed_on"]:
                if dev["on_since"] is None:
                    dev["on_since"] = now
                remaining_excess -= power
                continue

            # Battery mode restrictions
            if battery_mode == MODE_CHARGING:
                if is_on and not dev["force_started"]:
                    self._turn_off(dev, now, excess, battery_soc,
                                   "battery_charging")
                elif is_on:
                    remaining_excess -= power  # force-started, keep running
                continue

            if battery_mode == MODE_LOW_SOC:
                if battery_soc < dev["soc_threshold"]:
                    if is_on and not dev["force_started"]:
                        self._turn_off(dev, now, excess, battery_soc,
                                       "soc_below_threshold")
                    elif is_on:
                        remaining_excess -= power
                    continue

            # Turn ON logic
            if not is_on:
                needed = dev["nominal_power"] + dev["hysteresis_on"]
                if remaining_excess >= needed:
                    if self._debounce_ok(dev, now, "on"):
                        self._turn_on(dev, now, excess, battery_soc)
                        remaining_excess -= dev["nominal_power"]
            else:
                # Device is on – check if we need to turn it off
                if dev["force_started"]:
                    # Force-started device: keep running
                    remaining_excess -= power
                elif remaining_excess < -dev["hysteresis_off"]:
                    if self._min_on_ok(dev, now):
                        if self._debounce_ok(dev, now, "off"):
                            self._turn_off(dev, now, excess, battery_soc,
                                           "insufficient_excess")
                            remaining_excess += power
                        else:
                            remaining_excess -= power
                    else:
                        remaining_excess -= power
                else:
                    remaining_excess -= power

        # Publish device states
        device_states = []
        devices_on = 0
        total_power = 0
        for dev in self.devices:
            is_on = self._is_device_on(dev)
            power = self._get_device_power(dev) if is_on else 0
            state = "off"
            if is_on:
                if dev["startup_detection"] and dev["sd_state"]:
                    state = dev["sd_state"]
                elif not dev["managed_on"]:
                    state = "manual_override"
                else:
                    state = "on"
                devices_on += 1
                total_power += power

            device_states.append({
                "name": dev["name"],
                "slug": dev["slug"],
                "state": state,
                "power": round(power, 1),
                "runtime_today_s": round(dev["runtime_today_s"]),
                "sd_state": dev.get("sd_state", ""),
                "soc_threshold": dev["soc_threshold"],
                "priority": dev["priority"],
                "force_started": dev.get("force_started", False),
            })

        shared["device_states"] = device_states
        shared["devices_on"] = devices_on
        shared["device_power_total"] = round(total_power, 1)

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

    def _turn_on(self, dev, now, excess, soc):
        """Turn a device on."""
        self.hass.turn_on(dev["switch_entity"])
        dev["on_since"] = now
        dev["last_on"] = now
        dev["_runtime_tick"] = now
        dev["total_switches"] += 1
        dev["managed_on"] = True
        self._log_action(dev, "ON", excess, soc, "surplus_available")

    def _turn_off(self, dev, now, excess, soc, reason):
        """Turn a device off."""
        self.hass.turn_off(dev["switch_entity"])
        dev["on_since"] = None
        dev["last_off"] = now
        dev["_runtime_tick"] = None
        dev["managed_on"] = False
        dev["force_started"] = False
        self._log_action(dev, "OFF", excess, soc, reason)

    def _deadline_urgent(self, dev, now):
        """Check if device must start now to meet its deadline.

        Returns True if: time_remaining < estimated_runtime + buffer.
        """
        deadline_str = dev.get("deadline")
        est_runtime = dev.get("estimated_runtime", 0)
        if not deadline_str or not est_runtime:
            return False

        try:
            parts = deadline_str.split(":")
            deadline_hour = int(parts[0])
            deadline_min = int(parts[1]) if len(parts) > 1 else 0

            deadline_today = now.replace(
                hour=deadline_hour, minute=deadline_min,
                second=0, microsecond=0)

            # If deadline already passed today, not urgent
            if now >= deadline_today:
                dev["force_started"] = False
                return False

            time_remaining = (deadline_today - now).total_seconds()
            runtime_needed = est_runtime * 60  # minutes to seconds
            buffer = 300  # 5 min safety buffer

            return time_remaining <= (runtime_needed + buffer)
        except (ValueError, IndexError, AttributeError, TypeError):
            return False

    def _debounce_ok(self, dev, now, direction):
        """Check if debounce period has passed."""
        if direction == "on":
            ref = dev["last_off"]
            cooldown = dev["debounce_on"]
        else:
            ref = dev["last_on"]
            cooldown = dev["debounce_off"]

        if ref is None:
            return True
        return (now - ref).total_seconds() >= cooldown

    def _min_on_ok(self, dev, now):
        """Check if minimum on-time has been reached."""
        if dev["on_since"] is None:
            return True
        return (now - dev["on_since"]).total_seconds() >= dev["min_on_time"]

    def _update_runtimes(self, now):
        """Accumulate runtime for devices that are currently on."""
        for dev in self.devices:
            if self._is_device_on(dev):
                tick = dev.get("_runtime_tick") or dev.get("on_since")
                if tick:
                    elapsed = (now - tick).total_seconds()
                    dev["runtime_today_s"] += max(0, elapsed)
                dev["_runtime_tick"] = now
            else:
                dev["_runtime_tick"] = None

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

    # ══════════════════════════════════════════════════════════════
    #  STARTUP DETECTION STATE MACHINE
    # ══════════════════════════════════════════════════════════════

    def _update_sd_state(self, dev, now):
        """Update startup detection state machine.

        States: standby → detected → running → done → standby
        """
        if not dev["switch_entity"]:
            return

        is_on = self._is_device_on(dev)
        power = self._get_device_power(dev) if is_on else 0
        state = dev["sd_state"]

        if not state:
            dev["sd_state"] = SD_STATE_STANDBY

        # STANDBY: Waiting for power spike (program start)
        if dev["sd_state"] == SD_STATE_STANDBY:
            if is_on and power > dev["sd_power_threshold"]:
                dev["sd_state"] = SD_STATE_DETECTED
                dev["sd_detected_at"] = now
                self.hass.log(
                    f"AURUM SD [{dev['name']}]: "
                    f"Program detected ({power:.0f}W)")

        # DETECTED: Confirm it's not a spike
        elif dev["sd_state"] == SD_STATE_DETECTED:
            if not is_on or power <= dev["sd_power_threshold"]:
                dev["sd_state"] = SD_STATE_STANDBY
                dev["sd_detected_at"] = None
            elif dev["sd_detected_at"] and (
                    (now - dev["sd_detected_at"]).total_seconds()
                    >= dev["sd_detection_time"]):
                dev["sd_state"] = SD_STATE_RUNNING
                dev["sd_running_since"] = now
                self.hass.log(
                    f"AURUM SD [{dev['name']}]: "
                    f"Program confirmed, running")

        # RUNNING: Program in progress
        elif dev["sd_state"] == SD_STATE_RUNNING:
            runtime = (now - dev["sd_running_since"]).total_seconds()

            # Max runtime exceeded → done
            if runtime > dev["sd_max_runtime"]:
                dev["sd_state"] = SD_STATE_DONE
                self.hass.log(
                    f"AURUM SD [{dev['name']}]: "
                    f"Max runtime exceeded → done")
                return

            # Power dropped to finish level
            if (power <= dev["sd_finish_power"]
                    and runtime >= dev["sd_min_runtime"]):
                if dev["sd_finish_detected_at"] is None:
                    dev["sd_finish_detected_at"] = now
                elif ((now - dev["sd_finish_detected_at"]).total_seconds()
                        >= dev["sd_finish_time"]):
                    dev["sd_state"] = SD_STATE_DONE
                    self.hass.log(
                        f"AURUM SD [{dev['name']}]: "
                        f"Program finished ({runtime:.0f}s)")
            else:
                dev["sd_finish_detected_at"] = None

        # DONE: Program finished, can turn off
        elif dev["sd_state"] == SD_STATE_DONE:
            if is_on:
                self.hass.turn_off(dev["switch_entity"])
                dev["on_since"] = None
                dev["last_off"] = now
                dev["_runtime_tick"] = None
                dev["managed_on"] = False
                self._log_action(
                    dev, "OFF", 0, 0, "program_finished")
            dev["sd_state"] = SD_STATE_STANDBY
            dev["sd_running_since"] = None
            dev["sd_finish_detected_at"] = None

    def daily_reset(self):
        """Reset daily counters (call at midnight)."""
        for dev in self.devices:
            dev["runtime_today_s"] = 0
            dev["total_switches"] = 0
