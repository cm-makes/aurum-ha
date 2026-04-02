# Changelog

All notable changes to AURUM will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.5.2] - 2026-04-02

### Fixed
- **Weather learning never updated** – `update_weather_learning()` read `pv_actual_hour_kwh` and `pv_forecast_hour_kwh` from shared, but neither key was ever written by any module. Weather learning silently returned on every call and `_weather_learned` was never updated. Fixed: `BudgetManager.update()` now computes and sets both keys each cycle using a per-hour cumulative-PV snapshot for the actual delta and the hourly forecast data for the predicted value.
- **Safety factor never adapted without `target_soc_entity`** – `adapt_safety_factor()` had an early-return guard `if not self.target_soc_entity` that skipped the entire function when `target_soc` was configured as a direct value (the common case for new installations). Safety factor stayed at its default of 0.7 permanently. Fixed: guard replaced with `_get_target_soc()` call that correctly handles all three config sources (number entity, HA entity, direct value). Battery SOC now read from `shared` first (already available) with entity fallback.

## [1.5.1] - 2026-04-02

### Fixed
- **SOC threshold blocked turn-on completely** – When battery SOC was below a device's threshold, AURUM blocked the device entirely. Now correctly falls back to grid-only excess (PV export to grid), matching HELIOS behavior. Devices can start when PV is exporting even if the battery isn't fully charged.
- **PV budget not enforced** – `device_budget_w` was calculated by the budget module but never read in device control. Devices could now exceed the daily PV budget. Budget cap is now checked before each turn-on decision.
- **SD device stuck in WAITING after deadline** – When a startup-detection device hadn't started by its deadline, `_deadline_urgent()` returned `False` instead of triggering an immediate force-start. Device remained in WAITING state until midnight reset.
- **Shedding over-shed devices** – Priority shedding used actual sensor power (`_get_device_power()`) to track freed watts, but the deficit was calculated using nominal power. Inconsistency could cause more devices to be shed than necessary. Now uses `nominal_power` consistently.
- **Orphaned entities on startup** – Ghost entities from previously removed devices are now cleaned up automatically on every HA restart, not only during the remove flow.
- **Coordinator cache uninitialized** – `_cached_device_states` was not set in `__init__`, causing an `AttributeError` on the first odd update cycle before any even cycle had run.
- **`manual_override` state not counted in odd cycles** – Device count on cached cycles excluded devices in `manual_override` state.
- **`nominal_power=0` guard** – Added `max(1, ...)` to prevent zero-power devices from corrupting budget and shedding calculations.

## [1.5.0] - 2026-04-01

### Added
- **Auto-created Override & Muss-heute switches** – AURUM now automatically creates `switch.aurum_{slug}_override` and `switch.aurum_{slug}_muss_heute` for every device. No manual `input_boolean` setup required.
- **PV Forecast Budget** – Calculates available device power budget from Solcast or Open-Meteo forecast, considering battery target SOC, weather factor, and consumption profile. Safety factor adapts daily based on whether the battery reached its target.
- **HA Diagnostics** – Full JSON snapshot of AURUM internal state downloadable via Settings → Devices & Services → AURUM → Download Diagnostics.
- **PV forecast configuration in UI** – `pv_forecast_entity` and `pv_forecast_today_entity` now configurable through the integration UI (previously missing).
- **Budget lifecycle** – Weather learning (hourly), consumption profile update (daily at 23:55), and safety factor adaptation (daily at 17:00) are now fully wired up.
- **Budget state persistence** – Safety factor and learned weather observations survive HA restarts.

### Fixed
- **Entity registry cleanup on device removal** – Removing a device via Configure now also removes all its HA entities (sensor, binary_sensor, number, switch). Previously they remained as "unavailable" ghost entities.
- **Budget target SOC ignored** – `device_budget_w` was always `null` because the budget module only accepted `target_soc_entity` (HELIOS legacy) and never read the direct config value `target_soc`. Fixed: config value used as primary source.
- **Budget always returning 0 (false after_sunset)** – `_hours_until_sunset()` returned 0 when no hourly forecast attribute was available, causing the budget to report "after_sunset" all day. Fixed: fallback to 19:00 assumed sunset when no hourly data is present.
- **Diagnostics showing null for grid/battery values** – Wrong shared-dict key names (`grid_power` vs `grid_power_raw`, `battery_charge` vs `battery_charge_w`). All key names corrected.
- **House consumption calculation sign error** – `house_consumption_w` showed inflated values due to wrong sign on battery net power term.
- **Manually-on devices never turned off** – A device physically on but not managed by AURUM was completely skipped (no turn-off evaluation). Now applies normal turn-off logic unless the explicit Override switch is ON.
- **3 HassAccess bridge API mismatches in budget.py** – `hass.services.call()`, `hass.states.get()` in `_get_hourly_forecast()` and `_get_outdoor_temp()` replaced with correct bridge API calls.
- **4 pre-deploy bugs** – Wrong coordinator dict access in switch.py and diagnostics.py, missing `async_write_ha_state()` after restore, devices.py OR logic for override detection.

### Changed
- Example dashboard updated to v1.5.0: Override/Muss-heute switch cards now active by default for all example devices; outdated `input_boolean` instructions removed.

## [1.1.0] - 2026-03-31

### Fixed
- **Critical: Event loop deadlock** causing crash-loops on startup when devices were switched. Device control now runs in executor thread.
- Persistence config path resolution (was using wrong API)
- NameError in persistence save when temp file creation fails
- `async_set` called from sync context in bridge (now uses `states.set`)
- Null guard for startup detection state after persistence restore
- Unhandled exceptions in CSV logger initialization and flush
- Broadened exception handling in deadline parsing

### Added
- **Edit device** option in integration settings (Configure → Edit a device)
- Hardened `.gitignore` for sensitive files

## [1.0.0] - 2026-03-28

### Added
- Priority-based PV surplus distribution to household devices
- Battery-aware control with three modes (normal, low_soc, charging)
- Per-device SOC threshold for fine-grained battery protection
- Startup detection for washing machines, dishwashers, and dryers
- Deadline scheduling (e.g. laundry must finish by 18:00)
- Hysteresis and debounce to prevent rapid switching
- State persistence across Home Assistant restarts
- CSV action logging for audit trail
- Full config flow with 2-step setup wizard
- Options flow for adding, removing, and editing devices
- German and English translations
- HACS compatibility
- CI/CD with HACS and Hassfest validation
