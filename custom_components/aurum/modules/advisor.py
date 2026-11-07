"""
AURUM – Advisor (Current Decision)
===================================
Decision transparency: turns the coordinator's shared state into a single
machine-readable "what is AURUM doing right now, and why" summary.

Design (community port from HELIOS, rebuilt for AURUM):
- Pure function of ``shared`` – no HA access and no side effects.
- Output is STRUCTURED, not prose: an aggregate decision *code* plus a
  per-device reason *code* list. Localisation happens in Home Assistant via
  the sensor's ``translation_key`` (entity state) and the dashboard panel
  (the structured attributes) – never hard-coded German/English here.
- Attributes deliberately carry NO fast-changing numbers (no watts, no
  timestamp): every attribute delta is a recorder write, so the payload is
  limited to values that change on real decision transitions. Live power
  and surplus numbers live in the dedicated numeric sensors.

Scope: "current decision" only. The HELIOS advisor's daily-plan and
next-action sensors are intentionally out of scope for this first version.
"""

from ..const import (
    DEVICE_ACTIVE_STATES,
    DEVICE_STATE_UNAVAILABLE,
    MODE_CHARGING,
    MODE_LOW_SOC,
    SCHED_REASON_CHEAP_GRID,
    SCHED_REASON_EXCESS_SUFFICIENT,
    SCHED_REASON_SOLAR_PV,
    SCHED_REASON_SURPLUS_AVAILABLE,
    SD_STATE_DETECTED,
    SD_STATE_DONE,
    SD_STATE_STANDBY,
    SD_STATE_WAITING,
)

# ── Aggregate decision codes (sensor state, translated in HA) ────────
DECISION_STARTUP = "startup"
# A hub input AURUM needs has failed (grid meter or battery power sensor
# unavailable/stale → surplus unknown, or SOC unknown). Beats every other
# headline except startup: it changes what AURUM may do.
DECISION_INPUT_FAULT = "input_fault"
DECISION_BATTERY_CHARGING = "battery_charging"
DECISION_RUNNING_SOLAR = "running_solar"
DECISION_RUNNING_CHEAP_GRID = "running_cheap_grid"
DECISION_RUNNING = "running"
DECISION_WAITING = "waiting"
DECISION_IDLE = "idle"

# Full vocabulary for the ENUM sensor ("unknown" = advisor data missing).
DECISION_OPTIONS = [
    DECISION_STARTUP,
    DECISION_INPUT_FAULT,
    DECISION_BATTERY_CHARGING,
    DECISION_RUNNING_SOLAR,
    DECISION_RUNNING_CHEAP_GRID,
    DECISION_RUNNING,
    DECISION_WAITING,
    DECISION_IDLE,
    "unknown",
]


class AdvisorManager:
    """Summarise the current control decision from shared state."""

    def __init__(self, hass, config):
        # Stateless – accepts (hass, config) only to match the other
        # modules' constructor signature; neither is needed.
        pass

    def update(self, shared):
        """Build the current-decision summary.

        Reads ``battery_mode``, ``battery_soc`` and ``device_states``
        (filled by BatteryManager and DeviceManager earlier in the cycle)
        and returns the data dict the coordinator publishes as
        ``shared["advisor"]``.
        """
        battery_mode = shared.get("battery_mode", "unknown")

        # Startup grace period: device states are unknown, so emit only
        # the headline. Omitting the counts keeps the panel banner from
        # claiming "0/0 devices" while sensors are still warming up.
        if battery_mode == "startup":
            return {
                "decision": DECISION_STARTUP,
                "mode": battery_mode,
                "devices": [],
            }

        battery_soc = shared.get("battery_soc", -1)
        device_states = shared.get("device_states", []) or []

        # Failed hub inputs (energy.py). Only identity and status – no
        # timestamps, so the attribute changes on transitions only.
        input_faults = [
            {"input": f.get("input"), "status": f.get("status"),
             "entity": f.get("entity")}
            for f in (shared.get("input_faults") or [])
        ]
        # Faults that change what AURUM may do: surplus unknown, or SOC
        # unknown (sensor configured, battery_soc None).
        control_fault = bool(shared.get("surplus_blind")) or (
            battery_soc is None)

        devices = [
            self._device_view(d, battery_mode, battery_soc, control_fault)
            for d in device_states
        ]
        running = [d for d in devices if d["state"] in DEVICE_ACTIVE_STATES]

        decision = self._aggregate(battery_mode, devices, running)
        if control_fault:
            decision = DECISION_INPUT_FAULT
        data = {
            "decision": decision,
            "mode": battery_mode,
            "devices_on": len(running),
            "devices_total": len(devices),
            "devices": devices,
            "input_faults": input_faults,
        }
        # Price context only when a price sensor feeds the pipeline.
        # shared["current_price"] is already ct/kWh (see pricing.py).
        if shared.get("price_data_available"):
            data["price_level"] = shared.get("price_level")
            price = shared.get("current_price")
            if price is not None:
                data["current_price_ct"] = round(price, 1)

        return data

    # ── per-device reason ────────────────────────────────────────────

    def _device_view(self, d, battery_mode, battery_soc,
                     control_fault=False):
        state = d.get("state", "off")
        return {
            "name": d.get("name", ""),
            "slug": d.get("slug", ""),
            "state": state,
            "reason": self._device_reason(
                d, state, battery_mode, battery_soc, control_fault),
        }

    def _device_reason(self, d, state, battery_mode, battery_soc,
                       control_fault=False):
        """Map a device's state + published flags to a stable reason code.

        Prefers flags DeviceManager publishes (disabled, condition_met,
        scheduling_reason, …) over re-deriving its logic here.
        """
        if state == DEVICE_STATE_UNAVAILABLE:
            # AURUM cannot reach the switch: it sends nothing until the
            # switch reports again.
            return "switch_unavailable"
        if state == "manual_override":
            return "manual_override"

        if state in DEVICE_ACTIVE_STATES:
            if d.get("force_started"):
                return "forced_deadline"
            sr = d.get("scheduling_reason")
            if sr == SCHED_REASON_CHEAP_GRID:
                return "cheap_grid"
            if sr == SCHED_REASON_SOLAR_PV:
                return "solar_pv"
            if sr in (SCHED_REASON_SURPLUS_AVAILABLE,
                      SCHED_REASON_EXCESS_SUFFICIENT):
                return "solar_surplus"
            return "running"

        # ── off / standby / done / waiting ──
        # Disable switch is the hard kill-switch – beats everything.
        if d.get("disabled"):
            return "disabled"
        if d.get("runtime_target_reached"):
            return "runtime_done"
        sd_state = d.get("sd_state")
        if sd_state == SD_STATE_DONE:
            return "program_done"
        if sd_state == SD_STATE_WAITING:
            return "program_paused"
        if sd_state in (SD_STATE_STANDBY, SD_STATE_DETECTED):
            # SD device is monitoring for a program start – surplus is
            # irrelevant until the user starts a program.
            return "program_standby"
        if d.get("condition_met") is False:
            return "condition_not_met"
        if battery_mode == MODE_CHARGING:
            return "battery_charging"
        if control_fault:
            # Surplus or SOC unknown: AURUM starts nothing that depends on
            # them (see the decision's input_faults attribute).
            return "input_fault"
        threshold = d.get("soc_threshold", 0) or 0
        if (battery_mode == MODE_LOW_SOC and battery_soc is not None
                and battery_soc >= 0 and battery_soc < threshold):
            return "below_soc_threshold"
        return "waiting_surplus"

    # ── aggregate decision ───────────────────────────────────────────

    def _aggregate(self, battery_mode, devices, running):
        """Collapse the per-device picture into one headline decision code."""
        if running:
            reasons = {d["reason"] for d in running}
            if reasons & {"solar_surplus", "solar_pv"}:
                return DECISION_RUNNING_SOLAR
            if "cheap_grid" in reasons:
                return DECISION_RUNNING_CHEAP_GRID
            return DECISION_RUNNING
        if battery_mode == MODE_CHARGING:
            return DECISION_BATTERY_CHARGING
        if devices:
            return DECISION_WAITING
        return DECISION_IDLE
