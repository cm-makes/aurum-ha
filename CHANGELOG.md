# Changelog

All notable changes to AURUM will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
