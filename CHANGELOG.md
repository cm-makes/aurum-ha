# Changelog

All notable changes to AURUM will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
