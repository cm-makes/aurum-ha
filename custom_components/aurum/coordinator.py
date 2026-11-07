"""
AURUM – DataUpdateCoordinator
===============================
Orchestrates the update cycle:
  Energy → Battery → Devices → Publish → Persist
"""

import logging
import traceback
from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import DOMAIN, INPUT_UNAVAILABLE
from .hass_bridge import HassAccess
from .modules.energy import EnergyManager
from .modules.battery import BatteryManager
from .modules.budget import BudgetManager
from .modules.devices import DeviceManager
from .modules.pricing import PricingManager
from .modules.advisor import AdvisorManager
from .modules.helpers import CSVLogger, get_float
from .modules.persistence import PersistenceManager

_LOGGER = logging.getLogger(__name__)

# Inputs whose failure puts AURUM into safe mode and raises a repair issue.
# A failed PV reading already counts as 0 W (the safe value), and many
# inverters go unavailable every night, so PV gets no repair issue.
_ISSUE_INPUTS = ("grid", "battery_charge", "battery_discharge", "soc")


def summarize_cached_states(states):
    """devices_on, device_power_total and cheap_grid_active from a cached
    device_states list (odd cycles). Must agree with what DeviceManager
    publishes on even cycles: an 'unavailable' switch is not on."""
    inactive = ("off", "", "unavailable")
    devices_on = sum(1 for d in states if d.get("state") not in inactive)
    power = sum(d.get("power", 0) for d in states)
    cheap = any(
        d.get("scheduling_reason") == "cheap_grid"
        and d.get("state") not in inactive + ("standby", "done")
        for d in states)
    return devices_on, power, cheap


def budget_day_state_is_stale(saved_at, now):
    """True when restored budget day values (trajectory anchor, PV-counter
    midnight snapshot) belong to an earlier calendar day or to an unknown
    date. Learned values are not affected."""
    return saved_at is None or saved_at.date() < now.date()


def initial_device_states(devices):
    """Placeholder device_states published until the first device cycle.

    The counters come from the restored state: the energy sensors are
    TOTAL_INCREASING, and publishing 0 until the first device cycle made
    the recorder count today's energy twice after every restart/reload.
    """
    return [
        {
            "name": dev["name"],
            "slug": dev["slug"],
            "state": "off",
            "power": 0,
            "runtime_today_s": round(dev.get("runtime_today_s", 0)),
            "energy_today_wh": round(dev.get("energy_today_wh", 0.0), 1),
            "sd_state": dev.get("sd_state", ""),
            "price_mode": dev.get("price_mode", "solar_only"),
        }
        for dev in devices
    ]


class AurumCoordinator(DataUpdateCoordinator):
    """AURUM coordinator – orchestrates all modules every N seconds."""

    STARTUP_GRACE_CYCLES = 6  # 6 × 15s = 90s sensor warmup
    # After the grace, startup waits at most this long for the grid meter
    # and the SOC sensor. Then AURUM runs with the fail-safe input
    # handling (energy.py) instead of waiting forever.
    STARTUP_MAX_WAIT_S = 300
    # A failed hub input becomes an HA repair issue after this long.
    ISSUE_DELAY_S = 900

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry):
        """Initialize coordinator and all modules."""
        self.config = {**config_entry.data, **config_entry.options}
        self.config_entry = config_entry

        update_interval = self.config.get("update_interval", 15)

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=update_interval),
        )

        # ── Bridge: adapts HA Core APIs to simple interface ────────
        self.bridge = HassAccess(hass)

        # ── State ──────────────────────────────────────────────────
        self.cycle = 0
        self.device_states: list[dict] = []
        self._last_daily_reset: int = -1  # day of year
        self._first_cycle_at = None   # wall clock of cycle 1
        self._in_startup = True       # latched off when startup ends
        self._issues: dict = {}       # repair issue id -> (status, entity)

        # ── Create modules ─────────────────────────────────────────
        self.energy = EnergyManager(self.bridge, self.config)
        self.battery = BatteryManager(self.bridge, self.config)
        # Budget module: optional – only active when pv_forecast_entity set
        self.budget = (
            BudgetManager(self.bridge, self.config)
            if self.config.get("pv_forecast_entity") else None)
        self.devices = DeviceManager(self.bridge, self.config)
        self.pricing = PricingManager(self.bridge, self.config)
        self.devices.pricing = self.pricing  # expose to device manager
        self.advisor = AdvisorManager(self.bridge, self.config)
        self.persistence = PersistenceManager(self.bridge, self.config)

        # ── Daily adaptation tracking ──────────────────────────────
        self._last_adapt_day: int = -1          # day of year for 17:00 adapt
        self._last_weather_learning_hour: int = -1  # hour for hourly learning
        self._last_consumption_update_day: int = -1  # day for 23:55 profile

        # ── Device state cache (used on odd cycles) ────────────────
        self._cached_device_states: list[dict] = []

        # ── CSV loggers (initialized in async_setup) ───────────────
        self.action_csv = None

    async def async_setup(self):
        """Async initialization: restore state, init CSV."""
        config = self.config

        def _init_io():
            self.action_csv = CSVLogger(
                self.bridge,
                self.hass.config.path("aurum_actions.csv"),
                ['timestamp', 'device', 'action', 'excess',
                 'battery_soc', 'reason'],
                config.get("action_csv_max_lines", 5000))
            self.devices.action_csv = self.action_csv

            try:
                budget_state = self.persistence.restore(self.devices)
                _LOGGER.info("AURUM state restored")
                if self.budget and budget_state:
                    try:
                        self.budget.restore_state(budget_state)
                        _LOGGER.info("AURUM budget state restored")
                        # The trajectory anchor and the PV-counter midnight
                        # snapshot belong to the day they were saved; after
                        # a restart across midnight yesterday's anchor set
                        # the budget to 0 W for the whole day. Learned
                        # values (safety factor, weather) are kept.
                        saved_at = self.persistence.last_saved_at
                        now = datetime.now()
                        if budget_day_state_is_stale(saved_at, now):
                            self.budget.daily_reset()
                            _LOGGER.info(
                                "AURUM budget: state from %s, day values "
                                "reset", saved_at or "unknown date")
                        # The restored day values belong to today now: a
                        # startup that ends after midnight must still run
                        # the midnight reset (it was skipped while this was
                        # -1 on the first cycle).
                        self._last_daily_reset = now.timetuple().tm_yday
                    except Exception as be:
                        _LOGGER.warning("Budget state restore failed: %s", be)
            except Exception as e:
                _LOGGER.warning("State restore failed (fresh start): %s", e)

        await self.hass.async_add_executor_job(_init_io)

        # Pre-populate device_states for entity setup (restored counters).
        self.device_states = initial_device_states(self.devices.devices)
        # Seed the odd-cycle cache with the placeholders: the first
        # post-startup cycle is odd (grace=6 → cycle 7), and an empty
        # cache would make the advisor report "idle – no devices" for
        # one cycle on every restart even with devices configured.
        self._cached_device_states = list(self.device_states)

    async def async_save_state(self):
        """Write the state file now (executor). Never raises."""
        try:
            await self.hass.async_add_executor_job(
                self.persistence.save, self.devices, self.budget)
            return True
        except Exception as e:
            _LOGGER.warning("State save failed: %s", e)
            return False

    async def async_shutdown(self):
        """Save state, then run base coordinator teardown."""
        if await self.async_save_state():
            _LOGGER.info("AURUM state saved on shutdown")
        self._clear_repair_issues()
        # Let the base DataUpdateCoordinator cancel its refresh timer,
        # unsubscribe the EVENT_HOMEASSISTANT_STOP listener and shut down the
        # debouncer. Skipping this leaked one bus listener per reload.
        await super().async_shutdown()

    # ══════════════════════════════════════════════════════════════
    #  MAIN UPDATE LOOP
    # ══════════════════════════════════════════════════════════════

    def _run_advisor(self, shared):
        """Fill shared["advisor"] – a pure summary that must never raise
        into the control loop. Invoked from the update loop's finally
        block so it covers every return path."""
        try:
            shared["advisor"] = self.advisor.update(shared)
        except Exception as e:
            _LOGGER.warning("Advisor error: %s", e)

    def _grid_ready(self):
        """The grid meter reports a number."""
        grid = self.config.get("grid_power_entity")
        return bool(grid) and get_float(self.bridge, grid, None) is not None

    def _entities_ready(self):
        """The grid meter (and the SOC sensor, when configured) report a
        number. Without the SOC wait, a slow cloud SOC integration made
        every restart run on an unknown SOC."""
        if not self._grid_ready():
            return False
        soc = self.config.get("battery_soc_entity")
        if soc and get_float(self.bridge, soc, None) is None:
            return False
        return True

    def _is_startup(self, now):
        """Startup guard: the grace cycles, then until the sensors are
        ready, at most STARTUP_MAX_WAIT_S. Latched off once it ends, so a
        sensor that fails later is handled by the fail-safe logic.

        Returns (startup_mode, ready)."""
        if not self._in_startup:
            return False, True
        ready = self._entities_ready()
        if self._first_cycle_at is None:
            self._first_cycle_at = now
        waited = (now - self._first_cycle_at).total_seconds()
        if self.cycle <= self.STARTUP_GRACE_CYCLES or (
                not ready and waited < self.STARTUP_MAX_WAIT_S):
            return True, ready
        self._in_startup = False
        if not ready:
            _LOGGER.warning(
                "AURUM: grid or SOC sensor still not available after %d s "
                "– starting in fail-safe mode", int(waited))
        return False, ready

    def _update_repair_issues(self, shared):
        """Raise an HA repair issue for a hub input that has failed for
        ISSUE_DELAY_S, and delete it when the input recovers. Best effort:
        never raises into the control loop."""
        try:
            from homeassistant.helpers import issue_registry as ir
        except ImportError:
            return
        try:
            now = shared["now"]
            wanted = {}
            for fault in shared.get("input_faults") or []:
                if fault.get("input") not in _ISSUE_INPUTS:
                    continue
                since = fault.get("since")
                if (since is None or (now - since).total_seconds()
                        < self.ISSUE_DELAY_S):
                    continue
                wanted[f"input_{fault['input']}"] = fault
            for issue_id in list(self._issues):
                if issue_id not in wanted:
                    ir.async_delete_issue(self.hass, DOMAIN, issue_id)
                    del self._issues[issue_id]
            for issue_id, fault in wanted.items():
                key = (fault["status"], fault["entity"])
                if self._issues.get(issue_id) == key:
                    continue
                ir.async_create_issue(
                    self.hass, DOMAIN, issue_id,
                    is_fixable=False,
                    is_persistent=False,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key=f"input_{fault['status']}",
                    translation_placeholders={
                        "entity": fault["entity"] or "?"},
                )
                self._issues[issue_id] = key
        except Exception as e:  # noqa: BLE001 – issues are best effort
            _LOGGER.debug("AURUM repair issue update failed: %s", e)

    def _clear_repair_issues(self):
        """Delete every repair issue this coordinator raised."""
        if not self._issues:
            return
        try:
            from homeassistant.helpers import issue_registry as ir
            for issue_id in list(self._issues):
                ir.async_delete_issue(self.hass, DOMAIN, issue_id)
        except Exception as e:  # noqa: BLE001
            _LOGGER.debug("AURUM repair issue cleanup failed: %s", e)
        self._issues = {}

    async def _async_update_data(self):
        """Orchestrate: Energy → Battery → Devices → Persist."""
        self.cycle += 1
        shared = {"now": datetime.now(), "cycle": self.cycle}
        try:
            # ── Startup guard ──────────────────────────────────────
            startup_mode, _ready = self._is_startup(shared["now"])
            if startup_mode and not self._grid_ready():
                # No grid reading yet: skip the energy step, and mark the
                # surplus unknown so the mirror sensors are unavailable
                # rather than a live-looking 0 W. With the grid ready and
                # only the SOC missing, the energy step runs (warm-up).
                if self.cycle == 1:
                    _LOGGER.info(
                        "AURUM: Waiting for sensors (%d/%d)...",
                        self.cycle, self.STARTUP_GRACE_CYCLES)
                shared["battery_mode"] = "startup"
                shared["devices_on"] = 0
                shared["excess"] = 0
                shared["surplus_blind"] = True
                shared["input_health"] = {"grid": INPUT_UNAVAILABLE}
                return shared

            # ── Step 1: Energy sensors ─────────────────────────────
            try:
                self.energy.update(shared)
            except Exception as e:
                _LOGGER.warning("Energy error: %s", e)

            if startup_mode:
                shared["battery_mode"] = "startup"
                shared["devices_on"] = 0
                shared["excess"] = shared.get("excess", 0)
                return shared

            self._update_repair_issues(shared)

            # ── Step 2: Battery mode ───────────────────────────────
            try:
                self.battery.update(shared)
            except Exception as e:
                _LOGGER.warning("Battery error: %s", e)

            # ── Step 2b: PV forecast budget (optional) ─────────────
            if self.budget:
                try:
                    self.budget.update(shared)
                    now = shared["now"]
                    adapt_day = now.timetuple().tm_yday
                    current_hour = now.hour

                    # Hourly: weather factor learning (daytime only)
                    if (current_hour != self._last_weather_learning_hour
                            and 6 <= current_hour <= 20):
                        self.budget.update_weather_learning(shared)
                        self._last_weather_learning_hour = current_hour

                    # Late night: update consumption profile (23:55)
                    if (current_hour == 23 and now.minute >= 55
                            and adapt_day != self._last_consumption_update_day):
                        self.budget.update_consumption_profile(shared)
                        self._last_consumption_update_day = adapt_day

                    # Daily: safety-factor adaptation at 17:00
                    # Use a 5-minute window (like the 23:55 job) so a larger
                    # configured update_interval can't step over a 60s window
                    # and skip the daily adaptation. _last_adapt_day still
                    # guards against running it more than once per day.
                    if (current_hour == 17 and now.minute < 5
                            and adapt_day != self._last_adapt_day):
                        self.budget.adapt_safety_factor(shared)
                        self._last_adapt_day = adapt_day
                except Exception as e:
                    _LOGGER.warning("Budget error: %s", e)

            # ── Daily reset ───────────────────────────────────────
            # Per-device reset at each device's configured day_start_hour
            # (checked every cycle; each device resets at its own boundary).
            self.devices.daily_reset(shared["now"])

            # Budget learned-state reset stays aligned to the calendar day
            # (midnight): it is a global, forecast-driven quantity.
            today = shared["now"].timetuple().tm_yday
            if today != self._last_daily_reset:
                if self._last_daily_reset >= 0 and self.budget:
                    self.budget.daily_reset()
                    _LOGGER.info("AURUM: Budget daily reset")
                self._last_daily_reset = today

            # ── Step 2c: Pricing (optional) ───────────────────────
            if self.pricing.active:
                try:
                    self.pricing.update(shared)
                    self.pricing.snapshot(shared)
                except Exception as e:
                    _LOGGER.warning("Pricing error: %s", e)

            # ── Step 3: Device control (every 2nd cycle) ───────────
            if self.cycle % 2 == 0:
                try:
                    await self.hass.async_add_executor_job(
                        self.devices.update, shared)
                    self._cached_device_states = shared.get(
                        "device_states", [])
                except Exception as e:
                    _LOGGER.warning("Devices error: %s", e)
            else:
                shared["device_states"] = self._cached_device_states
                # Derive the summary from cached states so the binary
                # sensor doesn't flap on odd cycles.
                (shared["devices_on"], shared["device_power_total"],
                 shared["cheap_grid_active"]) = summarize_cached_states(
                    self._cached_device_states)

            # ── Step 4: Update device_states cache ─────────────────
            # Keep the previous list when the device step failed: an empty
            # list dropped every per-device sensor (energy too) to 0.
            if "device_states" in shared:
                self.device_states = shared["device_states"]

            # ── Step 5: CSV flush ──────────────────────────────────
            if self.action_csv and self.cycle % 2 == 0:
                try:
                    await self.hass.async_add_executor_job(
                        self.action_csv.flush)
                except Exception as e:
                    _LOGGER.warning("CSV flush error: %s", e)

            # ── Step 6: State persistence (every 5 min) ────────────
            if self.cycle % 20 == 0:
                try:
                    await self.hass.async_add_executor_job(
                        self.persistence.save, self.devices, self.budget)
                except Exception as e:
                    _LOGGER.warning("Persistence error: %s", e)

            return shared

        except Exception as e:
            _LOGGER.error("AURUM update error: %s\n%s",
                          e, traceback.format_exc())
            raise UpdateFailed(f"Update failed: {e}") from e
        finally:
            # ── Advisor (decision transparency) ────────────────────
            # Single exit point: runs on EVERY return path (startup
            # early-returns, main path, future guards) so no new
            # early-return can forget it. Mutates the shared dict that
            # is being returned; the advisor itself handles the startup
            # snapshot and never raises into the control loop.
            self._run_advisor(shared)
