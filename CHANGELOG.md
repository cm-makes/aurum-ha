# Changelog

All notable changes to AURUM will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.14.0] - 2026-07-15

### Added
- **Advisor: "Current Decision" sensor (`sensor.aurum_current_decision`)** – Decision transparency ported from the HELIOS parent project and rebuilt for AURUM's per-device model. A single ENUM sensor answers *"what is AURUM doing right now, and why"*. The state is a stable, localised decision code (`running_solar`, `running_cheap_grid`, `running`, `waiting`, `battery_charging`, `startup`, `idle`); the attributes carry a structured breakdown for dashboard cards: battery mode, price context, device counts, and a per-device list with a machine-readable `reason` code each (`solar_surplus`, `solar_pv`, `cheap_grid`, `manual_override`, `forced_deadline`, `runtime_done`, `program_done`, `program_paused`, `program_standby`, `battery_charging`, `below_soc_threshold`, `condition_not_met`, `disabled`, `waiting_surplus`). The module is a pure function of the coordinator's shared state — no extra HA polling, no side effects on control — and runs from the update loop's `finally` block so every return path (including the startup grace period) publishes a decision. The attributes deliberately carry no fast-changing numbers (no watts, no timestamps), so idle periods don't generate recorder writes; live power values stay in the dedicated numeric sensors. Always active (no configuration). Decision-state strings localised EN/DE via `translation_key` + `SensorDeviceClass.ENUM`. `current_decision` added to the reserved device-name list. Unit-tested.
- **Dashboard panel: Advisor banner** – The AURUM sidebar panel now shows a decision banner at the top ("☀️ Running on solar surplus · 2/3 active · ⚡ 1240 W · 💶 18.4 ct/kWh"). The headline uses HA's backend-localised ENUM state via `hass.formatEntityState()` (every HA language) with an EN/DE fallback for older frontends; the surplus figure comes live from `sensor.aurum_excess_power`. The per-device cards now show the advisor's translated reason ("→ solar surplus", "→ program paused", "→ disabled (force-off)") instead of the raw `scheduling_reason` code, falling back to the raw code on installs that predate the advisor.
- **`device_states` now publishes `disabled` and `condition_met`** – DeviceManager exposes its authoritative off-reasons (force-off switch, per-device run condition) in the published device state, so the advisor and external automations don't have to re-derive them. Scheduling-reason strings (`surplus_available`, `excess_sufficient`, `cheap_grid`, `solar_pv`) are now shared `SCHED_REASON_*` constants in `const.py` — producer (devices.py) and consumers (advisor, cheap-grid flag) can no longer drift.

## [1.13.0] - 2026-07-10

### Added
- **Per-device raw-PV run gate (`pv_power_threshold`)** – New optional per-device setting: run the device whenever *actual* PV generation is at or above the threshold (W) **and** battery SOC is at or above the device `soc_threshold`, independent of the computed surplus and the daily budget. Unlike the surplus/budget logic (which can reserve all solar for battery charging), this starts e.g. a pool pump on a sunny morning whenever `PV ≥ 1000 W and battery ≥ 25 %`. Debounced on both edges; turns off when PV falls a hysteresis band below the threshold or SOC drops. Exposed three ways: the device options form, a live `number.aurum_{slug}_pv_power_threshold` entity (durable via RestoreNumber), and a "Solar power ≥ (W)" control on the dashboard panel. Reason surfaces as `solar_pv`. EN/DE strings added. Unit-tested via the simulation harness. Set to 0 to disable (default).

### Fixed
- **Manual override ignored during the battery-charging emergency** – When the battery entered charging mode (SOC at `min_soc`), `DeviceManager.update()` force-off *every* running device without checking the per-device manual-override switch (`switch.aurum_{slug}_override`), violating its documented "AURUM will not touch the device in any cycle" contract. An externally-driven cycle — e.g. an anti-legionella water-heater boost held above its run-condition threshold — could be aborted mid-run when SOC dipped to `min_soc`. The emergency loop now skips overridden devices (anchoring `on_since` for min-on-time coherence), exactly as the normal control path does. Regression-tested via the simulation harness.

## [1.12.1] - 2026-07-08

### Fixed
- **`day_start_hour` restart persistence** – restore now decides the daily-counter rollover per device against each device's own reset boundary (using the saved timestamp) instead of a single global calendar day, so a restart in a `day_start_hour > 0` device's pre-boundary window no longer wrongly zeroes runtime that still belongs to the ongoing cycle. Default (midnight) behaviour is unchanged.

### Changed
- Documentation synced to the shipping feature set: README and QUICKSTART now describe the built-in dashboard panel, battery priority, run conditions and the daily reset hour. Removed the stale manual dashboard from the Plug & Play overlay (superseded by the built-in panel); the optional legacy `example_dashboard.yaml` remains.

## [1.12.0] - 2026-07-08

### Added
- **Per-device daily reset hour (`day_start_hour`, 0–23, default 0)** (discussion #11) – the runtime/energy counters reset at the configured hour instead of midnight, so a cheap-grid device with a runtime target runs on solar first during the day and only tops up from cheap grid overnight. Different devices can have different reset hours; default 0 preserves existing behaviour.

## [1.11.0] - 2026-07-05

### Added
- **Battery priority** toggle (discussion #9) – when enabled, only genuine grid export counts as device surplus, so the battery charges first. Off (default) keeps the previous semantics.
- **Per-device run condition** (discussion #5) – an optional prerequisite sensor (below/above a limit) that must hold for the device to run (e.g. water heater only while boiler temperature is below 55). Blocks every start path, stops a running device once unmet (respecting min-on-time), never interrupts a startup-detection program, and fails open on an unavailable sensor.

## [1.10.1] - 2026-07-05

### Fixed
- **Dashboard panel localization** (#7) – panel strings are now localized (English by default, German when the HA UI language is German) instead of hard-coded German.

## [1.10.0] - 2026-07-03

### Added
- **Built-in dashboard panel** – a self-adapting AURUM sidebar panel ships with the integration (no YAML, no extra cards). Overview chips plus one card per device with a PV | Manual | Off mode selector and the per-device controls; discovered live from the entities so adding/removing a device updates it automatically.

### Fixed
- Deterministic `entity_id`s for all per-device platforms (sensor, binary_sensor, number, time), matching the switches. Previously HA derived object_ids from friendly names via its own slugify, which transliterates umlauts differently (`ä→a` vs AURUM's `ä→ae`) and broke the id contract for umlaut device names; a one-time registry migration heals existing installs.
- `slugify` ASCII-folds non-German diacritics so forced entity_ids are always valid.
- Config flow rejects device names that collide with AURUM's own hub sensor ids.

## [1.9.1] - 2026-07-01

### Fixed
- **18 findings from an adversarial code audit** (see `docs/CODE_AUDIT_2026-07-01.md`), including: `remove_device` slug-prefix collision deleting other devices' entities; a synchronous service call on the event loop (safety-factor adaptation) that could block the coordinator; startup-detection standby time counted as runtime; `force_started` never cleared (device permanently non-sheddable); the SOC trajectory learner being inert and weather-learning comparing mismatched hours; the Target-SOC slider not affecting the budget; missing slug-uniqueness on device rename; dead `_attr_available` (sensors showing "unknown" instead of "unavailable"); an unavailable battery SOC failing open and disabling battery protection; non-persistent slider/deadline values; plus several low-severity fixes.

## [1.9.0] - 2026-06-26

### Added
- **Per-device Disable (force-off) switch** – New auto-created `switch.aurum_{slug}_disable` per device. When ON it acts as a hard kill-switch: AURUM ignores PV surplus, deadline and manual override for that device and keeps it switched off every cycle. Use it to take a device out of automation temporarily without deleting its config. Persistent across HA restarts (RestoreEntity); an optional legacy `disable_entity` is also honoured. Unit-tested via the simulation harness (force-off under surplus, precedence over manual override, no turn-on while disabled). Ported from the HELIOS parent project.

## [1.8.3] - 2026-06-24

### Fixed
- **Orphaned-entity cleanup for accented device names** – The cleanup routine used a separate `slugify` copy that stripped non-umlaut Unicode (é, ñ, …) while the entity slugs kept it, so the two could disagree and risk removing live entities or leaving orphans. Both now use the canonical `slugify`.
- **Duplicate deadline notification string** – Removed a redundant notify key; the startup-detection and regular-device paths now share one definition.
- **`min_on_time` after a restart** – A startup-detection device already ON after an HA restart never anchored its run-start timestamp, so minimum-on-time protection didn't apply. It is now set on restore.

## [1.8.2] - 2026-06-24

### Fixed
- **Deadline / `muss_heute` had no effect on regular (non-SD) devices** ([#3](https://github.com/cm-makes/aurum-ha/issues/3)) – `_deadline_urgent()` was only evaluated inside the startup-detection state machine; devices on a direct smart plug/switch only checked PV surplus. Regular devices now force-start on grid when the deadline window is reached and `muss_heute` is ON, and `muss_heute` auto-resets when the daily runtime target is met.

## [1.8.1] - 2026-06-16

### Fixed
- **Runtime notifications were hardcoded German** – The push/persistent notifications emitted from the device control loop (program detected, started, finished, deadline start, preemption, daily-runtime stop) were left in German from the original port ([#2](https://github.com/cm-makes/aurum-ha/issues/2)). They are now localized: English by default, German when the Home Assistant UI language is German. Texts live in a small EN/DE table; the UI language is read from `hass.config.language` with an English fallback.

## [1.8.0] - 2026-06-12

### Added
- **Stop when daily runtime is reached (`stop_after_runtime`)** – New per-device option that turns a device off as soon as its accumulated runtime today reaches the configured duration (e.g. pool pump: run 400 minutes, then stop), even at full PV surplus ([#2](https://github.com/cm-makes/aurum-ha/issues/2)). Restarts are blocked for the rest of the day — including cheap-grid grants and deadline force-starts; the counter resets at midnight and survives HA restarts. `min_on_time` is respected before the stop fires. Running programs of startup-detection appliances are never interrupted mid-cycle, and the manual override switch always wins. Off by default — existing setups keep their behaviour. The runtime field now accepts up to 1440 min (was 480) and is labelled "Daily runtime / program duration". Device sensors expose `stop_after_runtime` and `runtime_target_reached` attributes.
- **Config-flow sensor validation** – Sensors picked during setup (and in Options → Settings) are now validated for matching units and numeric state. Power sensors must report `W`/`kW`, energy sensors `Wh`/`kWh`, the battery SOC sensor a percentage. A battery SOC sensor reporting a 0–1 fraction is detected and reported with a clear message, instead of letting the integration silently misbehave at runtime.
- **Troubleshooting section in README** – Covers the most common first-install issues: grid sign convention, battery mode stuck on charging, missing battery charge/discharge sensors, devices stuck in `waiting`, flapping.

### Fixed
- **Cheap-grid scheduling reason lost on turn-on** – `update()` called `_turn_on()` without a reason, overwriting the `cheap_grid` grant from `_should_turn_on()` with `surplus_available`. The cheap-grid hold in `_should_turn_off()` then no longer recognised the device, causing night-time on/off ping-pong on `excess_deficit` (~every 20 min with default debounce). The reason is now preserved; found by the new full-day simulation suite.
- **Oscillation on unavailable price sensor** – Cheap-grid devices are now only shed when the price is *known* expensive (tri-state `should_run_on_grid()`); an unavailable price sensor holds the current state instead of toggling.
- **Shedding power basis** – Priority shedding now accounts freed power by each victim's measured draw (falling back to nominal), consistent with the measured deficit and SD preemption; nominal accounting over-/under-shed modulating loads.
- **Setup retry & config-flow hardening** – Transient setup timeouts raise `ConfigEntryNotReady` so HA retries instead of hard-failing; duplicate/empty device names are rejected in the options flow; the electricity-price sensor no longer claims a monetary device class; battery SOC `None` handled explicitly.

### Changed
- **Bug report template** – Replaced manual version fields with a required diagnostics-file attachment. The diagnostics JSON already contains the AURUM version, HA version, sensor states and device configuration, so reporters no longer have to copy them by hand (and can't get them wrong).
- **Translation parity** – `strings.json`, `en.json` and `de.json` are fully in sync (incl. the new runtime-target strings).
- **Test coverage** – New pytest suites: DeviceManager unit tests, packaging smoke tests, and a tick-level (15 s) full-day simulation suite covering all device types and situations (114 tests total).

## [1.7.7] - 2026-04-15

### Fixed
- **Stale `scheduling_reason` after turn-off** – `_turn_off()` cleared most per-device state but left `_scheduling_reason` untouched. A device previously started for `cheap_grid` that was later turned off (e.g. price rose) kept its `cheap_grid` reason even while off. If the user then manually started the device, `_should_turn_off()` treated it as a cheap-grid device and applied price-based turn-off logic against the user's intent. Reason is now cleared on every turn-off.

### Changed
- **Preemption & priority shedding over-shed** – Both the SD preemption loop (`_preempt_for_sd`) and the priority-based shedding loop used a strictly greedy algorithm that could turn off more devices than necessary (e.g. shed a 500W + 800W device for a 1000W deficit even though the 800W device alone would suffice after the 500W one is shed). Added a second pass that drops redundant victims (smallest power first) while preserving deterministic shed order by priority ascending. No change to behaviour when the greedy result already matches the deficit exactly.

### Added
- **`binary_sensor.aurum_cheap_grid_active`** – Global flag that turns ON while any AURUM-managed device is running because of cheap grid power. Useful for external automations (block battery discharge, switch inverter mode) during a cheap-grid window. Also exposed via `coordinator.data["cheap_grid_active"]`.

## [1.5.7] - 2026-04-07

### Fixed
- **SD device shows "off" instead of "waiting" when Shelly is off** – `_publish_device_states` only used `sd_state` when the physical switch was ON. In WAITING state the Shelly is intentionally OFF, so the state fell back to "off". SD devices now always use `sd_state` as the authoritative state regardless of physical switch position.

## [1.5.6] - 2026-04-07

### Fixed
- **Shelly stays ON during SD WAITING state after HA restart** – Shellys with "restore last state" turned themselves back on after HA restart while AURUM was in SD WAITING. AURUM only sent turn_off once (on DETECTED→WAITING transition) but never re-enforced it. Device kept running despite AURUM waiting for surplus. Fixed: WAITING state now enforces switch-off every cycle.

## [1.5.5] - 2026-04-07

### Fixed
- **Device Budget sensor showed "Unbekannt" when no cap active** – When `device_budget_w` is `None` (no restriction), `native_value = None` caused HA to display "unavailable". Sensor now shows `–` when unlimited, the watt value when a cap is active. Numeric value still accessible via `extra_state_attributes.budget_w` for automations.

## [1.5.4] - 2026-04-07

### Fixed
- **Daily runtime counter not reset after restart** – On startup, `persistence.py` restored `runtime_today_s` and `total_switches` from the state file without checking whether the file was from a previous day. The coordinator skips `daily_reset()` on the very first cycle, so yesterday's runtime appeared as today's. Fixed: state file now stores `saved_date`; on restore, daily counters are zeroed if the date doesn't match today.

## [1.5.3] - 2026-04-07

### Added
- **Startup Detection parameters now configurable in UI** – `sd_power_threshold`, `sd_standby_power`, `sd_finish_power`, `sd_finish_time`, `sd_detection_time`, and `sd_max_runtime` are now exposed in the device config form (add & edit). Previously hardcoded to defaults (5W / 3W / 3W / 600s / 5s / 10800s). Recommended values for washing machines: `sd_power_threshold` = 50W, `sd_standby_power` = 3W.

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
