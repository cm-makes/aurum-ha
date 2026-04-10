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

from .const import DOMAIN, VERSION, CONF_DEVICES
from .hass_bridge import HassAccess
from .modules.energy import EnergyManager
from .modules.battery import BatteryManager
from .modules.budget import BudgetManager
from .modules.devices import DeviceManager
from .modules.pricing import PricingManager
from .modules.helpers import CSVLogger
from .modules.persistence import PersistenceManager

_LOGGER = logging.getLogger(__name__)


class AurumCoordinator(DataUpdateCoordinator):
    """AURUM coordinator – orchestrates all modules every N seconds."""

    STARTUP_GRACE_CYCLES = 6  # 6 × 15s = 90s sensor warmup

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
                    except Exception as be:
                        _LOGGER.warning("Budget state restore failed: %s", be)
            except Exception as e:
                _LOGGER.warning("State restore failed (fresh start): %s", e)

        await self.hass.async_add_executor_job(_init_io)

        # Pre-populate device_states for entity setup
        self.device_states = []
        for dev in self.devices.devices:
            self.device_states.append({
                "name": dev["name"],
                "slug": dev["slug"],
                "state": "off",
                "power": 0,
                "runtime_today_s": 0,
                "sd_state": dev.get("sd_state", ""),
                "price_mode": dev.get("price_mode", "solar_only"),
            })

    async def async_shutdown(self):
        """Save state before shutdown."""
        try:
            await self.hass.async_add_executor_job(
                self.persistence.save, self.devices, self.budget)
            _LOGGER.info("AURUM state saved on shutdown")
        except Exception as e:
            _LOGGER.warning("State save on shutdown failed: %s", e)

    # ══════════════════════════════════════════════════════════════
    #  MAIN UPDATE LOOP
    # ══════════════════════════════════════════════════════════════

    def _entities_ready(self):
        """Check if critical sensors are available."""
        grid = self.config.get("grid_power_entity")
        if not grid:
            return False
        state = self.hass.states.get(grid)
        return state is not None and state.state not in (
            "unavailable", "unknown")

    async def _async_update_data(self):
        """Orchestrate: Energy → Battery → Devices → Persist."""
        try:
            self.cycle += 1
            shared = {"now": datetime.now(), "cycle": self.cycle}

            # ── Startup guard ──────────────────────────────────────
            startup_mode = self.cycle <= self.STARTUP_GRACE_CYCLES
            if startup_mode:
                if not self._entities_ready():
                    if self.cycle == 1:
                        _LOGGER.info(
                            "AURUM: Waiting for sensors (%d/%d)...",
                            self.cycle, self.STARTUP_GRACE_CYCLES)
                    shared["battery_mode"] = "startup"
                    shared["devices_on"] = 0
                    shared["excess"] = 0
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
                    if (current_hour == 17 and now.minute < 1
                            and adapt_day != self._last_adapt_day):
                        self.budget.adapt_safety_factor(shared)
                        self._last_adapt_day = adapt_day
                except Exception as e:
                    _LOGGER.warning("Budget error: %s", e)

            # ── Daily reset (midnight) ────────────────────────────
            today = shared["now"].timetuple().tm_yday
            if today != self._last_daily_reset:
                if self._last_daily_reset >= 0:
                    self.devices.daily_reset()
                    if self.budget:
                        self.budget.daily_reset()
                    _LOGGER.info("AURUM: Daily counters reset")
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
                shared["devices_on"] = sum(
                    1 for d in self._cached_device_states
                    if d.get("state") not in ("off", ""))
                shared["device_power_total"] = sum(
                    d.get("power", 0)
                    for d in self._cached_device_states)

            # ── Step 4: Update device_states cache ─────────────────
            self.device_states = shared.get("device_states", [])

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
