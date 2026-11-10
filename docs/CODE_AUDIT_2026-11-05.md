# AURUM — Adversarial Code Audit & Gap-Analyse

**Datum:** 2026-11-05  ·  **Scope:** AURUM v1.15.3 (`custom_components/aurum`, ~7.3k Zeilen inkl. Panel), dazu eine Markt- und Anforderungsrecherche

**Methode:** Multi-Agent-Workflow (Claude Code): 6 Bereichs-Reviewer → Dedupe → adversariale Verifikation (high/medium je ein eigener Skeptiker, low gebündelt pro Bereich; Default: widerlegt) → Coverage-Kritiker → 3 Nachprüf-Bereiche. Parallel: 2 Recherche-Agenten (Markt, Anforderungen/Regulatorik) + Gap-Analyse gegen den echten Code. 93 Agenten.

**Ergebnis:** 101 Roh-Findings → 85 nach Dedupe (+ Nachprüfung) → **108 behalten** (106 bestätigt, meist mit Repro-Skript), 1 widerlegt. Mehrere Findings teilen eine Ursache (z. B. #0/#3, #9/#15, #14/#26/#45/#66).

| Severity | Anzahl |
|---|---|
| HIGH | 4 |
| MEDIUM | 44 |
| LOW | 60 |

---

## Stand der Behebung

**v1.15.4 (2026-11-05)** behebt: #0/#3 Deadline-Zwangsstart, #1 SD-Wiedererkennung nach max_runtime (der Teilaspekt „vorzeitiger Smart-Finish in langer Trockenphase“ bleibt offen; Abhilfe: *Finish time* länger als die längste Ruhephase), #2 Battery Priority ohne Entladung (#5 teilweise: ohne Batterie-Leistungssensoren weiterhin blind), #9/#15 `_scheduling_reason` über Tagesreset/Neustart, #14/#26/#45/#66 Einheiten (kW/Wh/EUR), #50/#76 `force_started` nach Neustart über die Tagesgrenze. Regressionstests: `tests/test_audit_2026_11.py`. Der Fix-Diff wurde selbst zweimal adversarial geprüft (3 + 2 Reviewer, 43 Agenten); die dabei gefundenen Rückschritte (SD-Sperre nach normalem Smart-Finish und bei Messwert-Dip, `muss_heute`-Reset bei zweiter Ladung, `day_start_hour`, Neustart und Tagesreset, `stop_after_runtime`-Fenster, MWh, Float-Rundung) sind vor dem Release behoben. Bekannte Restpunkte stehen im CHANGELOG unter *Known limitations*.

**v1.16.0 (2026-11-10)** behebt den Block „Fail-safe inputs“ (Top-Empfehlung 2) und die Neustart-Findings: #16 SOC beim Start, #21/#25 Energy-Today nach Neustart, #22 Speichern beim HA-Stopp, #23/#63 Budget-Tageswerte über Mitternacht, #24/#99/#40/#41 Netzzähler ausgefallen oder eingefroren (Sicherheitsmodus), #38/#42 nicht erreichbare Schalter, #43 NaN/Inf, #44 Sichtbarkeit (Advisor, Reparaturmeldung, Diagnose), #56 Preis-Ausfall, #71 Schalter beim Restore noch nicht geladen, #100 eingefrorene PV-Leistung, #62/#102 README. Teilweise: #10 (nicht verfügbarer Leistungssensor; SD ganz ohne Leistungssensor bleibt offen), #35 (nicht erreichbarer Schalter; vom Nutzer abgeschaltetes Gerät im Deadline-Fenster bleibt offen), #36 (nicht erreichbarer Stecker; extern abgeschalteter Stecker bleibt offen). Regressionstests: `tests/test_failsafe_inputs.py`. Der Diff wurde zweimal adversarial geprüft (4 + 2 Reviewer mit je einem Gegenprüfer und Coverage-Kritiker, 13 Agenten); die 33 bestätigten Punkte (u. a. SD-Ruhezeit über eine Messlücke, Besitz eines vom Nutzer gestarteten Geräts nach Neustart, `unknown`-Schalter, nächtliche PV-Reparaturmeldungen, Debounce über eine Schalterlücke) sind vor dem Release behoben. Dabei mitbehoben: die PV-Schwelle startete ein Gerät mit zu kleinem Überschuss nie (vorbestehend).

Alle übrigen Findings sind **offen**.

## Findings

| # | Sev | Status | Bereich | Ort | Titel |
|---|---|---|---|---|---|
| 0 | high | ✅ 1.15.4 | devices-core | `custom_components/aurum/modules/devices.py:1192` | Deadline force-start ignores the runtime already done today and, without stop_after_runtime, holds the device on the grid until midnight |
| 1 | high | ✅ 1.15.4 | devices-core | `custom_components/aurum/modules/devices.py:987` | SD 'max_runtime' finish goes straight to STANDBY and re-detects the still-running program, cutting power mid-cycle |
| 2 | high | ✅ 1.15.4 | price-energy-battery | `custom_components/aurum/modules/energy.py:113` | battery_priority=True (and the no-battery-power-sensor config) cannot see battery discharge, so running devices drain the battery down to min_soc |
| 3 | high | ✅ 1.15.4 | ha-lifecycle | `custom_components/aurum/modules/devices.py:401` | Deadline force-start ignores runtime already done and keeps a regular device on until the next daily reset |
| 4 | medium | offen | devices-core | `custom_components/aurum/modules/devices.py:437` | PV budget cap only counts devices started in the current cycle, so the total device load is never capped |
| 5 | medium | ◐ teilweise | devices-core | `custom_components/aurum/modules/devices.py:719` | With grid-only surplus (battery_priority on, or no battery power sensors) a running device is never shed while the battery feeds it, so per-device soc_threshold is ignored |
| 6 | medium | offen | devices-core | `custom_components/aurum/modules/devices.py:1060` | SD preemption sheds lower-priority devices even when freeing them cannot make room; at night this short-cycles cheap-grid devices all night |
| 7 | medium | offen | devices-core | `custom_components/aurum/modules/devices.py:822` | SD state machine is frozen during MODE_CHARGING and manual override; on resume STANDBY treats an in-progress program as a new start and cuts it |
| 8 | medium | offen | devices-core | `custom_components/aurum/modules/devices.py:1210` | Stale _runtime_tick / on_since after an external switch-off inflates runtime and energy on the next external switch-on (false stop_after_runtime) |
| 9 | medium | ✅ 1.15.4 | devices-core | `custom_components/aurum/modules/devices.py:1434` | _scheduling_reason is cleared at the daily reset and not persisted, so a cheap-grid or PV-gated device running across the boundary or a restart is shed and restarted |
| 10 | medium | ◐ 1.16.0 | devices-core | `custom_components/aurum/modules/devices.py:1116` | Startup detection without a power sensor, or with an unavailable power sensor, creates phantom program cycles all day |
| 11 | medium | offen | devices-core | `custom_components/aurum/modules/devices.py:370` | Startup-detection devices silently ignore price_mode (and pv_power_threshold / budget) |
| 12 | medium | offen | devices-core | `custom_components/aurum/modules/devices.py:262` | Battery 'charging' emergency switches off non-interruptible and deadline-forced devices mid-run |
| 13 | medium | offen | price-energy-battery | `custom_components/aurum/modules/devices.py:242` | MODE_CHARGING blocks every grid-powered start (deadline force-start, SD deadline, cheap-grid grant), so muss_heute deadlines never fire while the battery sits at min_soc |
| 14 | medium | ✅ 1.15.4 | price-energy-battery | `custom_components/aurum/modules/energy.py:43` | Power sensors in kW pass config validation but are read as W (no unit conversion), so surplus is off by a factor of 1000 |
| 15 | medium | ✅ 1.15.4 | price-energy-battery | `custom_components/aurum/modules/persistence.py:24` | _scheduling_reason is not persisted, so after an HA restart a cheap-grid or PV-gate run is treated as a plain surplus run and gets cycled |
| 16 | medium | ✅ 1.16.0 | price-energy-battery | `custom_components/aurum/modules/energy.py:78` | Configured SOC sensor still unavailable after the startup grace: synthetic 0 % forces MODE_CHARGING and kills running devices, contrary to its own comment |
| 17 | medium | offen | price-energy-battery | `custom_components/aurum/modules/pricing.py:148` | max_price is not a cap: price level / cheap period grant grid power even when the current price is above max_price, contradicting the UI text |
| 18 | medium | offen | budget-forecast | `custom_components/aurum/modules/budget.py:213` | SOC trajectory is anchored at the first excess > 0 after midnight, so one night-time export sample sets the budget to 0 for most of the day |
| 19 | medium | offen | budget-forecast | `custom_components/aurum/modules/budget.py:289` | Dynamic target SOC can be higher than the user's target (target < 50 %, or learned weather factor > 1) |
| 20 | medium | offen | budget-forecast | `custom_components/aurum/modules/advisor.py:168` | A device blocked by the budget cap is reported as 'waiting_surplus'; the budget reason and trajectory are not shown anywhere |
| 21 | medium | ✅ 1.16.0 | ha-lifecycle | `custom_components/aurum/coordinator.py:112` | Energy-today sensors drop to 0 for ~7 cycles after every restart/reload, so Energy Dashboard statistics double-count |
| 22 | medium | ✅ 1.16.0 | ha-lifecycle | `custom_components/aurum/coordinator.py:129` | State is never saved on HA stop/restart; up to 5 min of runtime and SD state are lost and a running program can be cut |
| 23 | medium | ✅ 1.16.0 | ha-lifecycle | `custom_components/aurum/coordinator.py:241` | Restart across midnight restores yesterday's budget trajectory; budget multiplier becomes 0 for the whole day |
| 24 | medium | ✅ 1.16.0 | ha-lifecycle | `custom_components/aurum/coordinator.py:170` | Grid sensor unavailable after startup is read as 0 W; running devices are never shed during the outage |
| 25 | medium | ✅ 1.16.0 | entities-config | `custom_components/aurum/sensor.py:315` | Per-device and total 'Energy Today' sensors drop to 0 after every restart/reload, so today's energy is counted twice in statistics |
| 26 | medium | ✅ 1.15.4 | entities-config | `custom_components/aurum/config_flow.py:121` | Config validator accepts kW/MW/mW power sensors and Wh/MWh forecast sensors, but the runtime treats every value as W / kWh |
| 27 | medium | offen | entities-config | `custom_components/aurum/config_flow.py:422` | Options flow cannot clear an optional field once it is set (default= instead of suggested_value), and settings merge resurrects entry.data keys |
| 28 | medium | offen | entities-config | `custom_components/aurum/strings.json:171` | 'Maximum price' is documented as a cap, but the logic ORs it with cheap period and price level, so devices run above max_price |
| 29 | medium | offen | entities-config | `custom_components/aurum/number.py:45` | Startup-detection devices ignore price_mode, max_price and pv_power_threshold, but the UI offers these settings and creates entities for them |
| 30 | medium | offen | entities-config | `custom_components/aurum/strings.json:158` | SOC threshold and charge-target descriptions contradict the control logic ('Set to 0 ... only full surplus' is inverted) |
| 31 | medium | offen | advisor-panel | `custom_components/aurum/modules/devices.py:1228` | Every AURUM turn-off is published as state 'manual_override' for ~30 s, so the advisor explains it as a manual override and 'Devices running' |
| 32 | medium | offen | advisor-panel | `custom_components/aurum/modules/devices.py:287` | Disabling an SD device mid-program leaves sd_state='running': the advisor reports it as running, and re-enabling sends a false 'finished' notification and clears Must-run-today |
| 33 | medium | offen | advisor-panel | `custom_components/aurum/modules/advisor.py:152` | 'program_done' reason (and status 'done') is documented but never produced, so the README's 'washing machine finished' automation never fires |
| 34 | medium | offen | advisor-panel | `custom_components/aurum/frontend/aurum-panel.js:170` | Panel ignores `narrow` and has no menu button, so on phones the HA sidebar cannot be opened from the AURUM panel |
| 35 | medium | ◐ 1.16.0 | actuator-feedback | `custom_components/aurum/modules/devices.py:1200` | Deadline force-start before the deadline re-fires every device cycle when the switch does not report 'on': ON-command and push storm, phantom allocation, and AURUM fights a user who switches the device off |
| 36 | medium | ◐ 1.16.0 | actuator-feedback | `custom_components/aurum/modules/devices.py:276` | Startup detection: an unavailable (or externally switched-off) plug during RUNNING is read as 0 W, so the program is falsely 'finished', muss_heute is cleared, and the still-running program is cut when the plug reconnects |
| 37 | medium | offen | actuator-feedback | `custom_components/aurum/modules/devices.py:311` | External switch-off is never reconciled: last_off, managed_on, _scheduling_reason and force_started stay stale (min_off_time ignored, cheap-grid restarts within 30 s, later manual starts are mis-handled) |
| 38 | medium | ✅ 1.16.0 | actuator-feedback | `custom_components/aurum/modules/devices.py:1108` | Offline or unavailable switch is treated as 'off' and re-commanded on the surplus path: phantom allocations reset lower-priority devices' debounce (starvation of 20-60+ min), switch penalty inflated, and the advisor shows 'waiting_surplus' |
| 39 | medium | offen | actuator-feedback | `custom_components/aurum/modules/devices.py:1024` | _preempt_for_sd has no settling memory: with ≥ one device cycle of switch or grid-sensor latency it preempts an extra victim on each following cycle |
| 40 | medium | ✅ 1.16.0 | input-failure-matrix | `custom_components/aurum/modules/energy.py:117` | Grid sensor unavailable while the battery charges from the grid: legacy surplus turns the charge power into phantom surplus and starts devices on grid |
| 41 | medium | ✅ 1.16.0 | input-failure-matrix | `custom_components/aurum/modules/helpers.py:16` | No staleness check on any input: a frozen grid value breaks the control loop and AURUM starts every device |
| 42 | medium | ✅ 1.16.0 | input-failure-matrix | `custom_components/aurum/modules/devices.py:1200` | Unavailable device switch is treated as OFF: the deadline force-start re-fires every cycle with a push notification, and the surplus path issues phantom ONs |
| 43 | medium | ✅ 1.16.0 | input-failure-matrix | `custom_components/aurum/modules/helpers.py:20` | A 'nan' or 'inf' reading permanently poisons the grid EMAs until HA restarts |
| 44 | medium | ✅ 1.16.0 | input-failure-matrix | `custom_components/aurum/sensor.py:369` | Nothing tells the user that AURUM is running blind: hub sensors publish 0 W, held SOC looks live, no repairs issue or advisor code |
| 45 | medium | ✅ 1.15.4 | input-failure-matrix | `custom_components/aurum/modules/devices.py:498` | Device power sensor unit is never validated: a kW sensor sheds all candidates at once, disables startup detection and reads energy 1000x too low |
| 46 | medium | offen | provider-data-contracts | `custom_components/aurum/modules/budget.py:577` | The fixed 19:00 'sunset' fallback runs for every user without hourly forecast attributes and gets the budget badly wrong in both seasons, with no warning |
| 47 | medium | offen | provider-data-contracts | `custom_components/aurum/modules/budget.py:564` | Forecast hours are compared against a naive datetime.now() (process time zone), not HA's configured time zone |
| 48 | low | offen | devices-core | `custom_components/aurum/modules/devices.py:1180` | Deadline only works while the muss_heute switch is ON, but the config UI and README describe it as unconditional |
| 49 | low | offen | devices-core | `custom_components/aurum/modules/devices.py:1005` | SD 'done' state is never produced, so the advisor's program_done reason and the README automation example can never fire |
| 50 | low | ✅ 1.15.4 | devices-core | `custom_components/aurum/modules/persistence.py:152` | force_started survives a restart that spans the daily-reset boundary (partial regression of audit #4) |
| 51 | low | offen | devices-core | `custom_components/aurum/modules/devices.py:471` | Stale debounce timer in the grid-only path (SOC below device threshold) lets a one-cycle export blip start a device |
| 52 | low | offen | devices-core | `custom_components/aurum/modules/devices.py:1232` | Published device state is stale right after AURUM switches (async service): turned-off devices show as 'manual_override' for a cycle |
| 53 | low | offen | devices-core | `custom_components/aurum/modules/devices.py:1286` | Override, muss_heute and disable switches are looked up by a hard-coded entity_id; renaming one silently disables it (the kill-switch fails open) |
| 54 | low | offen | devices-core | `custom_components/aurum/modules/devices.py:631` | Price-granted starts have no debounce, though the README says debounce still applies |
| 55 | low | offen | devices-core | `custom_components/aurum/modules/devices.py:778` | Switch-penalty docstring tiers do not match the code |
| 56 | low | ✅ 1.16.0 | price-energy-battery | `custom_components/aurum/modules/devices.py:742` | Price-sensor outage makes the cheap-grid hold unbounded: a device started on cheap grid runs on grid indefinitely |
| 57 | low | offen | price-energy-battery | `custom_components/aurum/modules/devices.py:595` | PV gate never opens on battery-less systems: _pv_gate_ok fails closed on SOC<0, which now only means 'no battery configured' |
| 58 | low | offen | price-energy-battery | `custom_components/aurum/modules/devices.py:690` | scheduling_reason sticks to the start path: an expensive price leaves a PV-covered device labelled cheap_grid all day, and a fading-PV to cheap-window transition causes an off/on |
| 59 | low | offen | price-energy-battery | `custom_components/aurum/modules/pricing.py:101` | Price level match is case-sensitive; uppercase levels (Tibber API, e.g. 'VERY_CHEAP') are silently treated as 'no price data' |
| 60 | low | offen | price-energy-battery | `custom_components/aurum/modules/pricing.py:142` | max_price cannot express '<= 0 ct' or fractional thresholds (0 means disabled, step 1, min 0) |
| 61 | low | offen | price-energy-battery | `README.md:190` | README says cheap-grid starts are debounced; the code grants and releases price runs immediately |
| 62 | low | ✅ 1.16.0 | price-energy-battery | `README.md:492` | README troubleshooting: 'no battery configured -> SOC treated as 0 -> charging mode' is wrong |
| 63 | low | ✅ 1.16.0 | budget-forecast | `custom_components/aurum/modules/budget.py:957` | Budget learned state from yesterday is restored after a restart across midnight, and the first-day budget reset is skipped |
| 64 | low | offen | budget-forecast | `custom_components/aurum/modules/budget.py:477` | Adaptive consumption profile is dead code: hourly_consumption_w is never produced, so the budget always assumes a flat 500 W household load |
| 65 | low | offen | budget-forecast | `custom_components/aurum/modules/budget.py:281` | budget_combined_floor (0.85) cancels any safety factor below 0.85 and every downward in-day correction |
| 66 | low | ✅ 1.15.4 | budget-forecast | `custom_components/aurum/modules/budget.py:273` | pv_forecast_entity in Wh passes validation but is read as kWh, which effectively disables the budget |
| 67 | low | offen | budget-forecast | `custom_components/aurum/modules/budget.py:715` | 17:00 safety-factor evaluation checks the SOC at 17:00, not whether the target was reached; with no battery every day counts as a miss |
| 68 | low | offen | budget-forecast | `custom_components/aurum/modules/budget.py:605` | Lifetime-counter detection treats a daily PV counter above 100 kWh as a lifetime total, which corrupts in-day correction and weather learning |
| 69 | low | offen | budget-forecast | `custom_components/aurum/modules/budget.py:200` | Weather learning uses only the first half-hour slot as the forecast for the whole hour with Solcast data |
| 70 | low | offen | budget-forecast | `custom_components/aurum/sensor.py:536` | AurumBudgetWSensor overrides the final SensorEntity.state / unit_of_measurement and switches unit between W and none |
| 71 | low | ✅ 1.16.0 | ha-lifecycle | `custom_components/aurum/modules/persistence.py:196` | Restore treats a not-yet-loaded switch as OFF; AURUM-managed device then shows as manual_override |
| 72 | low | offen | ha-lifecycle | `custom_components/aurum/__init__.py:129` | Orphan cleanup misparses muss_heute unique_ids (deleted every setup) and never cleans {entry_id}_ entities |
| 73 | low | offen | ha-lifecycle | `custom_components/aurum/coordinator.py:217` | 23:55 consumption-profile job is a permanent no-op (hourly_consumption_w is never produced) |
| 74 | low | offen | ha-lifecycle | `custom_components/aurum/modules/devices.py:1401` | notify_service entered as 'notify.mobile_app_x' builds service 'notify/notify.mobile_app_x'; push silently fails |
| 75 | low | offen | ha-lifecycle | `custom_components/aurum/time.py:79` | Deadline set to 00:00 (disabled) is not restored; config deadline returns after restart |
| 76 | low | ✅ 1.15.4 | ha-lifecycle | `custom_components/aurum/modules/persistence.py:147` | Rolled-over restore only zeroes 3 counters; force_started survives a restart across the day boundary |
| 77 | low | offen | ha-lifecycle | `custom_components/aurum/coordinator.py:209` | First weather-learning sample after every (re)start uses a partial hour, biasing learned factors low |
| 78 | low | offen | ha-lifecycle | `custom_components/aurum/modules/devices.py:1369` | Regional German UI locales (de-CH, de-AT) get English notifications |
| 79 | low | offen | ha-lifecycle | `custom_components/aurum/diagnostics.py:30` | Diagnostics: KeyError when entry is not loaded; target/min SOC shown from config instead of live sliders |
| 80 | low | offen | ha-lifecycle | `custom_components/aurum/modules/helpers.py:92` | CSVLogger only rotates at startup; the action log grows unbounded between restarts |
| 81 | low | offen | entities-config | `custom_components/aurum/strings.json:20` | PV power sensor is described as 'display only, can be left empty', but pv_power_threshold depends on it |
| 82 | low | offen | entities-config | `custom_components/aurum/sensor.py:340` | 'AURUM Energy Today' total is TOTAL_INCREASING but resets partially (per-device day_start_hour, device removal), so statistics double-count |
| 83 | low | offen | entities-config | `custom_components/aurum/config_flow.py:275` | notify_service in the 'notify.xxx' format (what Developer Tools shows) silently breaks push notifications |
| 84 | low | offen | entities-config | `custom_components/aurum/time.py:94` | Deadline 00:00 means 'force-start now' from the config flow but 'disabled' on the time entity, and the meaning flips after restart |
| 85 | low | offen | entities-config | `custom_components/aurum/binary_sensor.py:64` | binary_sensor.aurum_{slug}_active is ON while an SD program is paused (waiting/detected) and the plug is off |
| 86 | low | offen | entities-config | `custom_components/aurum/strings.json:33` | Translation gaps: initial setup step shows raw keys for the notify and price fields; missing or incorrect descriptions |
| 87 | low | offen | entities-config | `custom_components/aurum/config_flow.py:746` | Editing a device silently drops legacy manual_override_entity / muss_heute_entity |
| 88 | low | offen | entities-config | `custom_components/aurum/config_flow.py:17` | Reserved-slug list is incomplete: device 'Excess' collides with the hub excess sensor, and removing a device named House/Target/Min/... deletes hub entities |
| 89 | low | offen | entities-config | `custom_components/aurum/sensor.py:652` | House consumption sensor is computed with PV = 0 when no PV sensor is configured |
| 90 | low | offen | entities-config | `custom_components/aurum/config_flow.py:789` | remove_device uses self.config_entry, which does not exist on HA < 2024.11, while hacs.json/README declare 2024.1+ |
| 91 | low | offen | entities-config | `custom_components/aurum/config_flow.py:190` | soc_is_fraction check rejects a real battery at exactly 1 % |
| 92 | low | offen | entities-config | `custom_components/aurum/strings.json:44` | update_interval does not mean what the UI says; fixed cycle counts scale grace, control and persistence |
| 93 | low | offen | advisor-panel | `custom_components/aurum/modules/advisor.py:129` | Advisor never looks at the override switch: the panel's Manual mode is explained as 'waiting for surplus', and a device AURUM will still shed is labelled 'manual override – AURUM hands off' |
| 94 | low | offen | advisor-panel | `custom_components/aurum/frontend/aurum-panel.js:635` | Deadline time input commits every intermediate value, which can trigger an immediate deadline force-start |
| 95 | low | offen | advisor-panel | `custom_components/aurum/frontend/aurum-panel.js:650` | Panel cosmetics and i18n: untranslated badge states, 'manual_override' has no colour, unknown shown as 'off', stale deadline field, power units assumed to be W |
| 96 | low | offen | advisor-panel | `custom_components/aurum/frontend/aurum-panel.js:234` | Panel rescans all HA states and rewrites every card on every hass update |
| 97 | low | offen | actuator-feedback | `custom_components/aurum/modules/devices.py:1148` | A lost or ignored turn-off is re-labelled as a manual start: no retry for min_on_time + debounce_off, a higher-priority device is shed instead, and the UI says 'manual override – AURUM hands off' |
| 98 | low | offen | actuator-feedback | `custom_components/aurum/modules/devices.py:1375` | _notify accepts throttle_key and importance but ignores both: there is no de-duplication or rate limit for mobile pushes |
| 99 | low | ✅ 1.16.0 | input-failure-matrix | `custom_components/aurum/modules/devices.py:771` | A single unavailable grid sample resets the shed timer, so a flaky meter keeps a device on grid indefinitely |
| 100 | low | ✅ 1.16.0 | input-failure-matrix | `custom_components/aurum/modules/devices.py:705` | Frozen PV power keeps a PV-gate device running on battery for hours, because the gate release bypasses the deficit checks |
| 101 | low | offen | input-failure-matrix | `custom_components/aurum/modules/devices.py:543` | Run-condition entity: a non-numeric state is treated as 'condition met', with no config validation |
| 102 | low | ✅ 1.16.0 | input-failure-matrix | `README.md:482` | README's sign-flip template uses float(0), which turns a meter outage into a live 0 W reading |
| 103 | low | offen | provider-data-contracts | `custom_components/aurum/modules/budget.py:571` | Production end is taken from the start of the last forecast slot; with hourly data (Open-Meteo, Solcast detailedHourly) the budget spikes to ~7 kW and then reports 'after_sunset' 1–1.5 h early |
| 104 | low | offen | provider-data-contracts | `README.md:214` | README says Nordpool provides a price level, but it has none; picking it as price_level_entity silently disables cheap-grid scheduling |
| 105 | low | offen | provider-data-contracts | `custom_components/aurum/modules/pricing.py:126` | Tibber Prices 'best price starts in' reports hours (suggested unit), but AURUM shows it as minutes |
| 106 | low | offen | provider-data-contracts | `custom_components/aurum/modules/budget.py:839` | Docs name a Solcast `forecast` attribute that does not exist; the parser checks it first and doesn't fall through when it is malformed |
| 107 | low | offen | provider-data-contracts | `custom_components/aurum/modules/budget.py:596` | PV-actual unit heuristic flips per sample for unitless Wh counters: 3 Wh read as 3 kWh, then misdetected as a lifetime counter |

## Details

### 0. [HIGH] Deadline force-start ignores the runtime already done today and, without stop_after_runtime, holds the device on the grid until midnight
`custom_components/aurum/modules/devices.py:1192` · devices-core · bug · Verdict: confirmed

**Beschreibung:** _deadline_urgent compares the time left against the full estimated_runtime and never looks at runtime_today_s. After a force-start, force_started=True makes _should_turn_off return None, so nothing turns the device off again. The only exits are 1c (which needs stop_after_runtime=True), MODE_CHARGING, disable, the run condition, or the daily reset clearing force_started. muss_heute is only auto-reset in 1c and at SD finish. CHANGELOG 1.x (#3) says 'muss_heute auto-resets when the daily runtime target is met', but for stop_after_runtime=False (the default) it never resets. The whole thing therefore repeats every day.

**Fehlerszenario:** Regular device, 1500 W, deadline 18:00, estimated_runtime 60, stop_after_runtime off (default), muss_heute ON. Reproduced: it runs on PV 10:05–13:10 (185 min, already 3x the target). At 16:55 it is force-started on grid anyway, stays non-sheddable and is only turned off at 00:10 the next day by excess_deficit after the midnight reset cleared force_started. That is about 7 h and 11 kWh of grid energy. muss_heute is still ON, so it happens again every day.

**Fix-Vorschlag:** In _deadline_urgent use the remaining runtime (estimated_runtime*60 - runtime_today_s) and return False when it is <= 0. End the force_started immunity once runtime_today_s reaches estimated_runtime or the deadline passes. Reset muss_heute when the target is met even without stop_after_runtime (or document that it never resets).

**Beleg (Verifier):** custom_components/aurum/modules/devices.py:1161-1206: `_deadline_urgent` never reads `runtime_today_s`. Lines 1200-1204 return `time_remaining <= est_runtime*60 + 300` and do not check `force_started` before the deadline.
devices.py:401-411: block-3 force-start for any device that is off, setting `force_started=True`.
devices.py:674-676: `if dev["force_started"]: return None` in `_should_turn_off`, placed before the SOC-threshold and excess-deficit checks.
devices.py:550-558: `_runtime_target_reached` returns False unless `stop_after_runtime` is set.
devices.py:341 and 995: the only two `_reset_muss_heute` call sites.
devices.py:1437: `force_started` is cleared only by the daily reset.
switch.py:128-133: docstring "If the device has not finished by the deadline ... Auto-resets to OFF after the program completes".
README.md:118: "Deadline | Time by which the device must have run".
CHANGEL …

### 1. [HIGH] SD 'max_runtime' finish goes straight to STANDBY and re-detects the still-running program, cutting power mid-cycle
`custom_components/aurum/modules/devices.py:987` · devices-core · bug · Verdict: confirmed

**Beschreibung:** On smart finish or max_runtime the RUNNING branch calls _sd_reset, which sets STANDBY immediately and keeps the plug on. The next STANDBY evaluation sees actual_power > sd_power_threshold. After sd_detection_time it goes to DETECTED, which calls _turn_off on the plug ('sd_pause_program'), and the device waits in WAITING for PV. The DONE state that HELIOS had (SD_STATE_DONE, removed in 1bc1b22) would have blocked re-detection until the power fell to standby. The default sd_max_runtime is 10800 s (3 h), shorter than common EU eco programs (dishwasher Eco ~3:30–4:10 h, washer Eco 40-60 ~3:30 h). A premature smart finish during a long low-power phase (dishwasher drying, then a pump-out) triggers the same cut.

**Fehlerszenario:** Dishwasher with SD, defaults (sd_max_runtime 10800). Started on PV at 09:05 with a 3 h 50 min eco program. Reproduced: at 12:05 'finished (max_runtime)' is sent and muss_heute is reset. At 12:06 power is still >5 W, so it is 'detected', the plug is switched OFF mid-program and the device goes to WAITING. It restarts only when surplus returns; if clouds come in, the machine sits powerless (water in the tub) for hours. The user also gets a false 'finished' and a new 'detected' notification.

**Fix-Vorschlag:** After finish, enter a post-run state (reintroduce SD_STATE_DONE) that only re-arms STANDBY detection once power has stayed below sd_standby_power or sd_finish_power for a while. Never act on a max_runtime finish by cutting a plug that still draws program-level power. Consider a higher default sd_max_runtime (e.g. 5 h).

**Beleg (Verifier):** Code path:
- devices.py:927-928 sets `sd_lockout_until = now + sd_max_runtime` (default 10800, devices.py:178 / const.py:140).
- devices.py:962-964 sets `max_expired`. devices.py:980-996 then logs the finish, calls `_sd_reset(dev)` (STANDBY, plug left on, devices.py:1003-1013), sends the "sd_finished" notification, and calls `_reset_muss_heute(dev)`.
- devices.py:276 reads the real power because the plug is still on. Blocks 1c and 1d skip SD devices (devices.py:322, :352).
- devices.py:822-834: power above `sd_power_threshold` (5) for at least `sd_detection_time` (5 s) leads to DETECTED.
- devices.py:854-857: `_turn_off(... "sd_pause_program")` sets WAITING.
- devices.py:890 / 1180: the deadline fallback is dead because `muss_heute` was just reset. devices.py:908-939: the restart only happens on PV surplus.
- tests/test_devices.py:387-398 asserts STANDBY while `actual_power=800` at finis …

### 2. [HIGH] battery_priority=True (and the no-battery-power-sensor config) cannot see battery discharge, so running devices drain the battery down to min_soc
`custom_components/aurum/modules/energy.py:113` · price-energy-battery · bug · Verdict: confirmed

**Beschreibung:** With battery_priority=True, energy.py sets excess = -grid_ema_asym and excess_raw = -grid_raw and ignores battery_power_net in both directions. Not counting charge power as surplus is intended. Not counting discharge as a deficit is the bug. A hybrid inverter in self-consumption mode holds grid near 0 W by discharging, so excess_raw stays near 0. The excess-deficit turn-off never fires, and the per-device SOC guard in _should_turn_off (devices.py:719, `available_excess < -hysteresis_off`) never fires either. The device only stops when SOC reaches min_soc and MODE_CHARGING kills everything. The setup with no charge/discharge sensors behaves the same way. strings.json says battery priority means 'the battery charges first', and that per-device SOC thresholds are the guard. Neither holds for a device that is already running.

**Fehlerszenario:** Simulated with EnergyManager, BatteryManager and DeviceManager together (10 kWh battery, 5 kW inverter). A 2 kW heater (soc_threshold 50) was started on export at 15:00 with the battery at 100 %. From 17:00 PV falls from 3 kW to 0 over 2 h. With battery_priority=False plus battery sensors, the heater is shed at 17:38 at SOC 100 %. With battery_priority=True, or without battery power sensors, the heater runs until 01:39 and is only switched off when SOC hits min_soc 10 % (MODE_CHARGING). That is about 9 kWh of stored PV spent on the heater, so the house buys expensive grid power that night.

**Fix-Vorschlag:** In the battery_priority branch, count discharge as a deficit but not charge as a surplus: excess = -grid_ema_asym - max(0, battery_power_net), and the same for excess_raw. When no battery power sensors are configured, add a SOC guard to _should_turn_off for devices below soc_threshold, e.g. stop when SOC keeps falling while the device runs. At least document that the per-device SOC threshold cannot stop a running device in that setup.

**Beleg (Verifier):** **Code references**
- custom_components/aurum/modules/energy.py:111-127: battery_power_net is folded in only `if has_battery_power and not self.battery_priority`. The else branch sets `excess_raw = -grid_raw`.
- custom_components/aurum/modules/battery.py:53-59: excess_raw is passed through unchanged except in MODE_CHARGING.
- custom_components/aurum/modules/devices.py:386-390: turnoff_excess is excess_raw minus newly_allocated.
- devices.py:719-730: the SOC guard needs `available_excess < -hysteresis_off`.
- devices.py:756-768: the excess-deficit check uses the same comparison.
- devices.py:242-266: the MODE_CHARGING emergency is the only other stop.
- devices.py:432-438: the budget cap affects turn-on only.
- strings.json:158: the soc_threshold description promises the device is not allowed below that level.
- tests/test_v1_11_features.py:18-53: covers only the charge side (bat_discharg …

### 3. [HIGH] Deadline force-start ignores runtime already done and keeps a regular device on until the next daily reset
`custom_components/aurum/modules/devices.py:401` · ha-lifecycle · bug · Verdict: confirmed

**Beschreibung:** Outside my scope (deadline logic), included because the only thing that ends the run is the daily reset. For a non-SD device with muss_heute ON, _deadline_urgent fires without checking runtime_today_s against estimated_runtime. The force start sets force_started=True, and _should_turn_off then returns None. With stop_after_runtime=False (the default) nothing turns the device off: no runtime stop, and muss_heute is never auto-reset. Only the midnight (day_start_hour) daily_reset clears force_started, after which the device is shed for deficit about 10 min later. muss_heute is never reset daily either, so this repeats every day.

**Fehlerszenario:** Simulated: a 2 kW heater with deadline 18:00, estimated_runtime 60 and muss_heute ON had already run 4 h on PV. It was force-started at 16:55 and stayed ON until about 00:10. That is about 7 h and roughly 14 kWh of grid or battery energy instead of 0-1 h.

**Fix-Vorschlag:** In _deadline_urgent, return False once runtime_today_s >= estimated_runtime*60. Treat a deadline force start as bounded: turn off, or drop force_started, after estimated_runtime of forced runtime even when stop_after_runtime is off. Optionally reset muss_heute at the daily boundary.

**Beleg (Verifier):** Code:
- custom_components/aurum/modules/devices.py:401-411: deadline force start on a regular device, sets force_started=True.
- devices.py:1161-1206 (_deadline_urgent): no runtime_today_s check.
- devices.py:550-558 (_runtime_target_reached): returns False unless stop_after_runtime is set; default False at devices.py:164.
- devices.py:674-676 (_should_turn_off): returns None for any force_started device.
- devices.py:1424-1437 (_reset_device_counters): only clears force_started at day_start_hour.
- devices.py:322-342 and 995: the only callers of _reset_muss_heute.
- README.md:118 and translations/en.json:166-168: the documented deadline and runtime semantics.
- tests/simulation.py:595: "deadline passed → no longer urgent, can turn off normally".

Repro script: <scratch>/deadline_forced_unbounded.py

Setup: 2 kW heater, deadline 18:00, estimated_runtime 60, muss_heute ON, no PV (excess - …

### 4. [MEDIUM] PV budget cap only counts devices started in the current cycle, so the total device load is never capped
`custom_components/aurum/modules/devices.py:437` · devices-core · bug · Verdict: confirmed

**Beschreibung:** The cap test is `newly_allocated + dev["nominal_power"] > device_budget_w`. `newly_allocated` only sums devices switched on in THIS update() call. Devices that are already running are not counted. budget.py documents device_budget_w as 'devices allowed up to this wattage total', and the comment at devices.py:237 says 'maximum power AURUM may allocate to devices today'. In practice the cap only stops a device whose own nominal power is larger than the budget. Any number of smaller devices can start one after another in consecutive cycles. Running devices are also never shed when the budget falls.

**Fehlerszenario:** Default (legacy) surplus mode, battery charging at 4 kW so excess_for_devices is about 4000 W. device_budget_w = 1000 W. Three solar_only devices of 800 W each. Reproduced with the real DeviceManager: after 20 minutes all three are ON (2400 W, i.e. 2.4x the budget). The battery charge that the budget was meant to protect goes to the devices, the battery misses target SOC and the house imports from the grid in the evening.

**Fix-Vorschlag:** Include the power of already-running devices that count against the budget (managed, solar-sourced, not price-granted or forced or PV-gated; actual power via _get_device_power) in the comparison, e.g. `running_solar_w + newly_allocated + nominal > device_budget_w`. Decide whether running devices should be shed when the budget drops well below their draw.

**Beleg (Verifier):** **Code**
- custom_components/aurum/modules/devices.py:271: `newly_allocated = 0.0`, reset on every update().
- devices.py:375, :405, :464: the only places `newly_allocated` grows, and only for devices started in that call.
- devices.py:383-390: the `was_on` branch never adds running power.
- devices.py:432-438: the cap uses `newly_allocated + dev["nominal_power"] > device_budget_w`.
- Shedding (devices.py:479-533) and `_should_turn_off` never read `device_budget_w`.
- modules/budget.py:19/43/236: budget documented as "devices allowed up to this wattage total".
- energy.py:113-119 with config_flow.py:273: legacy surplus (battery charge folded into excess) is the default whenever battery power sensors are set.

**HELIOS parent** (<local path>)
- Line 600: `heating_power_on += actual_power`  …

### 5. [MEDIUM] With grid-only surplus (battery_priority on, or no battery power sensors) a running device is never shed while the battery feeds it, so per-device soc_threshold is ignored
`custom_components/aurum/modules/devices.py:719` · devices-core · bug · Verdict: confirmed

**Beschreibung:** Every turn-off path in _should_turn_off needs a measured deficit: `available_excess < -hysteresis_off`. This applies to the SOC-below-threshold path at line 719, the generic excess-deficit path at line 756 and the pv_below_threshold release, which is only run by the shedding stage when `deficit > 0`. When battery_priority is on, or when no battery charge/discharge sensors are set, energy.py sets excess_raw = -grid. A hybrid inverter holds the grid at about 0 W by discharging the battery, so excess_raw stays around 0 and no deficit ever appears. The README promises 'SOC threshold: Device only runs when battery is above this level', but on the turn-off side that is never enforced in this mode. Only the global MODE_CHARGING at min_soc stops the device.

**Fehlerszenario:** battery_priority=True, 10 kWh battery, heater 2 kW with soc_threshold=40, started at noon on real export. From 18:00 PV is gone and the inverter covers the heater from the battery, so the grid reads ±5 W. Simulated with the real EnergyManager, BatteryManager and DeviceManager: the heater ran from SOC 45 % down to 9.9 % and was only stopped by MODE_CHARGING at 19:31. That is about 35 % of the battery drained against a configured 40 % floor, and the house then imports all night.

**Fix-Vorschlag:** For the SOC-below-threshold turn-off (and the excess-deficit turn-off in grid-only mode), also treat battery discharge as a deficit, e.g. use shared['battery_power_net'] > hysteresis_off. Or, when SOC < soc_threshold, turn the device off unless there is genuine grid export (grid_excess >= 0), debounced by debounce_off.

**Beleg (Verifier):** Code:
- custom_components/aurum/modules/energy.py:113-131: grid-only branch, excess_raw = -grid_raw. Used when battery_priority is on or no battery power sensors are set.
- custom_components/aurum/modules/battery.py: passes excess_raw through as excess_raw_for_devices except in MODE_CHARGING.
- custom_components/aurum/modules/devices.py:384-390: running device is checked with turnoff_excess = excess_raw - newly_allocated.
- devices.py:719-731: SOC-below-threshold path is gated on available_excess < -hysteresis_off.
- devices.py:756: excess-deficit path has the same gate.
- devices.py:485-496: shedding uses deficit = -(excess_raw - newly_allocated); with deficit <= 0 the `if freed >= deficit: break` exits at once and nothing is shed.
- devices.py:432: budget_cap is only in the turn-on branch.
- devices.py:242: MODE_CHARGING (SOC <= min_soc) is the only remaining stop.
- README.md:115 prom …

### 6. [MEDIUM] SD preemption sheds lower-priority devices even when freeing them cannot make room; at night this short-cycles cheap-grid devices all night
`custom_components/aurum/modules/devices.py:1060` · devices-core · bug · Verdict: confirmed

**Beschreibung:** _preempt_for_sd adds victims greedily `until freed >= deficit`. If all candidates together free less than the deficit, it still turns every one of them off and returns freed > 0. The SD device then still cannot start. Victims are also chosen without checking whether they run on surplus at all: a cheap_grid device running on grid frees no PV. The victim restarts after min_off_time (price grant, no debounce), runs min_on_time and is preempted again. The loop is not damped by the switch penalty and sends a push notification every time.

**Fehlerszenario:** Dishwasher with startup detection (priority 80) is paused in WAITING overnight, the usual case of 'started after dinner, wait for tomorrow's PV'. Water heater 2 kW, priority 50, price_mode cheap_grid, cheap night tariff, SOC 60 %. Reproduced 01:00–03:00: the heater toggled 21 times (on 10 min, off 1 min, repeatedly), there were 10 '⚡ Heater aus → Platz für Dishwasher' notifications, and the dishwasher never started (no PV). The same pattern happens by day with surplus devices whenever their power is smaller than the SD shortfall.

**Fix-Vorschlag:** Only preempt when sum(candidate power) >= deficit (otherwise return 0 without touching anything). Exclude victims whose _scheduling_reason is cheap_grid or deadline_forced, or that are not running on surplus. Consider requiring the SD shortfall to persist (debounce) before preempting.

**Beleg (Verifier):** Code:
- custom_components/aurum/modules/devices.py:111 sorts devices by priority, highest first, so SD is evaluated before the victim.
- devices.py:940-948: the WAITING else-branch always calls _preempt_for_sd.
- devices.py:1021-1048 holds the only guards (SD soc_threshold, deficit<=0, managed_on / interruptible / priority / min_on_time). Nothing checks _scheduling_reason, force_started, or whether the candidates' total power covers the deficit.
- devices.py:1058-1064: the greedy loop sheds even when freed < deficit.
- devices.py:1085-1102: turn_off plus _notify on every call, no throttle.
- devices.py:430-438 / 560-580 / 630-632: the price grant restarts the victim with no debounce or penalty and is exempt from the budget.
- devices.py:1149: _turn_off clears force_started, so _deadline_urgent (1192-1204) re-forces the victim at once.
- const.py:130-131: MIN_ON 600 s, MIN_OFF 60 s.
- dev …

### 7. [MEDIUM] SD state machine is frozen during MODE_CHARGING and manual override; on resume STANDBY treats an in-progress program as a new start and cuts it
`custom_components/aurum/modules/devices.py:822` · devices-core · bug · Verdict: confirmed

**Beschreibung:** In MODE_CHARGING update() returns before _handle_startup_detection (lines 255-261 just `continue` for SD in STANDBY or RUNNING). With the override ON the device is skipped entirely (block 1). A program started during that time is never moved to RUNNING. When normal processing resumes, the device is still in STANDBY. Power above threshold is then read as a fresh program start, and DETECTED switches the plug off mid-program.

**Fehlerszenario:** SD washing machine in STANDBY. At 07:02 the battery hits min_soc and the mode becomes charging. The user starts a wash at 07:32 and it runs on grid. At 08:02 SOC recovers (low_soc). Reproduced: at 08:02:30 AURUM 'detects' the program, turns the plug OFF 30 minutes into the wash and waits for PV with a drum full of water. The same happens if the user turns the override switch off while a program they started under override is still running.

**Fix-Vorschlag:** Keep evaluating the SD state machine in MODE_CHARGING and under override, but without switching (e.g. move STANDBY to RUNNING when power rises). Or, when STANDBY resumes after a freeze with power already above threshold, adopt the run as RUNNING instead of DETECTED.

**Beleg (Verifier):** Code path:
- custom_components/aurum/modules/devices.py:242-266: the MODE_CHARGING emergency loop does `continue` for an SD device in ""/STANDBY or RUNNING and then returns before _handle_startup_detection.
- devices.py:297-304: under override the device is skipped entirely.
- devices.py:822-834: in STANDBY, power above sd_power_threshold for sd_detection_time (default 5 s, devices.py:177) moves the device to DETECTED.
- devices.py:845-856: DETECTED calls _turn_off(..., "sd_pause_program") and moves to WAITING.
- devices.py:872-874: WAITING forces the plug off every cycle.
- battery.py:44: `soc <= self.min_soc` sets MODE_CHARGING with no hysteresis.
- coordinator.py:196/258: battery.update runs before devices.update.

Reproduction script: <scratch>/sd_freeze_repro.py
It uses the real BatteryManager and DeviceManager, an SD washer with sd_power_threshold=50, min_soc=10 and a 30 s tick.

O …

### 8. [MEDIUM] Stale _runtime_tick / on_since after an external switch-off inflates runtime and energy on the next external switch-on (false stop_after_runtime)
`custom_components/aurum/modules/devices.py:1210` · devices-core · bug · Verdict: confirmed

**Beschreibung:** _accumulate_runtime uses `_runtime_tick or on_since` as the start of the interval. When a managed device is switched off outside AURUM (HA UI, Shelly app, automation), _turn_off never runs, so _runtime_tick, on_since and managed_on stay set. If the device is later switched on outside AURUM too, the first accumulation adds the whole off period to runtime_today_s and actual_power × off period to energy_today_wh. energy_today_wh is a TOTAL_INCREASING sensor used by the Energy dashboard. The stale on_since also makes min_on_time look satisfied, and managed_on=True makes the device show as 'on' instead of 'manual_override'.

**Fehlerszenario:** Pool pump, stop_after_runtime with 120 min. AURUM starts it at 10:05. The user switches it off at 10:15 (10 min runtime). There is no surplus until 13:15, when the user switches it on by hand. Reproduced: the next cycle reports runtime 190.5 min and +2540 Wh of phantom energy. Block 1c immediately turns the pump OFF with 'runtime_target_reached', sends the 'daily runtime reached' notification and clears muss_heute, after only 10 real minutes.

**Fix-Vorschlag:** When a device is seen off while _runtime_tick/on_since/managed_on are set, clear them (on_since=None, _runtime_tick=None, managed_on=False, last_off=now). Treat a switch state of unavailable separately, depending on whether downtime should be counted.

**Beleg (Verifier):** Code references:
- custom_components/aurum/modules/devices.py:1208-1215 `_accumulate_runtime`: `tick = dev.get("_runtime_tick") or dev.get("on_since")`
- devices.py:1121-1128 `_turn_on` sets the fields; devices.py:1141-1148 `_turn_off` is the only regular-device path that clears them
- devices.py:258-264: accumulation runs whenever `was_on`; devices.py:308-313 (block 1b) re-anchors `on_since` only if it is None; devices.py:323-343 (block 1c) does the `min_on_time` check on the stale `on_since`, then `_turn_off`, notify and `_reset_muss_heute`
- devices.py:1424-1437 `_reset_device_counters` does not clear `_runtime_tick` or `on_since`
- persistence.py:209-213 clears `managed_on`, `on_since` and `_runtime_tick` for an off switch, but only at restore
- sensor.py:296 and 327: the energy sensors are TOTAL_INCREASING
- No `async_track*` or `state_changed` listener anywhere in custom_components …

### 9. [MEDIUM] _scheduling_reason is cleared at the daily reset and not persisted, so a cheap-grid or PV-gated device running across the boundary or a restart is shed and restarted
`custom_components/aurum/modules/devices.py:1434` · devices-core · bug · Verdict: confirmed

**Beschreibung:** _reset_device_counters sets `_scheduling_reason = None` even when the device is ON. persistence.py does not save _scheduling_reason (_VALUE_FIELDS). Without the reason, _should_turn_off loses the cheap-grid hold (and the SOLAR_PV gate hold) and falls through to the generic excess-deficit check. At night that check always fires after debounce_off, the device is shed, and the price grant switches it back on after min_off_time. cheap_grid_active and the advisor also report wrong values in the meantime.

**Fehlerszenario:** Water heater 2 kW, cheap_grid, price cheap 23:30–01:30, day_start_hour 0. Reproduced: on at 23:30, then OFF at 00:10 ('excess_deficit'), then ON at 00:11, although the price stayed cheap. The same happens after an HA restart at night (reproduced via PersistenceManager save/restore: excess_deficit off, then on again 60 s later), and at day_start_hour=9 for a pv_power_threshold device whose surplus is hidden by house load. Each case costs an extra relay or compressor cycle.

**Fix-Vorschlag:** Do not clear _scheduling_reason at the daily reset while the device is on (only clear it for devices that are off). Add _scheduling_reason to persistence _VALUE_FIELDS (it is a plain string).

**Beleg (Verifier):** Code: devices.py:1434 (reason cleared at reset, unconditionally); devices.py:1455-1467 (reset fires when the device's day boundary is crossed); coordinator.py:235 then :258 (reset runs before update every cycle); devices.py:383-391 (an ON device only runs _should_turn_off, so the reason is never re-set); devices.py:690, 701, 742 (cheap-grid and PV-gate holds are keyed on _scheduling_reason); devices.py:756-768 (excess_deficit fallback); devices.py:630-632 (price re-grant after min_off_time); persistence.py:24-27 (_VALUE_FIELDS has no _scheduling_reason); persistence.py:195-208 (restore marks an ON switch managed_on=True, reason stays None from devices.py:166); devices.py:1272-1276 (cheap_grid_active depends on the reason).

Repro scripts (all under <scratch>/):

verify_sched_reason_reset.py — 2 kW cheap_grid boiler, price cheap the whole time, 15 s ticks, daily_reset(now) before update() …

### 10. [MEDIUM] Startup detection without a power sensor, or with an unavailable power sensor, creates phantom program cycles all day
`custom_components/aurum/modules/devices.py:1116` · devices-core · robustness · Verdict: confirmed

**Beschreibung:** _get_device_power falls back to nominal_power when power_entity is missing or unavailable. In STANDBY that value is always above sd_power_threshold, so a 'program' is detected. In RUNNING it never falls below sd_finish_power, so the run only ends at sd_max_runtime, and the cycle then starts again. The config flow allows startup_detection with no power sensor ('Power measurement (optional) … Can be left empty'), and no validation or warning ties them together.

**Fehlerszenario:** SD dishwasher configured without a power sensor (or the separate power meter reports 'unavailable' while the plug is on). No one presses Start. Reproduced over 8 h: STANDBY, detected and paused, waiting, then 3 h 'running' on PV (plug on), 'finished (max_runtime)', repeated 3 times. There were 8 notifications, muss_heute was cleared, and nominal power was booked as runtime and energy.

**Fix-Vorschlag:** Require power_entity when startup_detection is enabled (config-flow error). In the SD state machine, treat an unavailable power reading as 'no information': hold the state instead of using nominal_power.

**Beleg (Verifier):** Code references:
- custom_components/aurum/modules/devices.py:1113-1118: falls back to `nominal_power`.
- helpers.py:14-22: `get_float` returns the default for unavailable, unknown, empty or non-numeric states.
- devices.py:126: `nominal_power` is at least 1; config_flow.py:318-321 allows 10-10000 W.
- devices.py:176: `sd_power_threshold` defaults to 5.
- devices.py:276: `actual_power` is taken from the fallback whenever the plug is on.
- devices.py:822-837: STANDBY detection.
- devices.py:845-862: DETECTED pauses the device and moves to WAITING.
- devices.py:909-939: WAITING starts on PV surplus.
- devices.py:969: smart finish never fires because nominal power is never below finish power.
- devices.py:980-996: max_runtime finish, then `_sd_reset` to STANDBY with the plug still on, `_reset_muss_heute` and the `sd_finished` notification.
- config_flow.py:311-314: `power_entity` is Optiona …

### 11. [MEDIUM] Startup-detection devices silently ignore price_mode (and pv_power_threshold / budget)
`custom_components/aurum/modules/devices.py:370` · devices-core · docs-mismatch · Verdict: confirmed

**Beschreibung:** SD devices take the `_handle_startup_detection` branch and `continue`. WAITING only starts on `turnon_excess >= nominal + hysteresis_on` or a deadline. _price_grant and _pv_gate_ok are never consulted, and the budget cap is skipped. The config flow still offers price_mode, max_price and pv_power_threshold for SD devices, and the README says 'A device with cheap_grid mode turns on when any of these is true: … cheap_period_entity is ON …'.

**Fehlerszenario:** Washing machine with SD and price_mode=cheap_grid. Program started at 22:00 and paused (WAITING). The Tibber best-price window runs 01:00–04:00 and there is no deadline. Expected: resume in the cheap window. Actual: it stays paused until PV surplus the next day (or never, on a cloudy day).

**Fix-Vorschlag:** In WAITING, allow a start when self._price_grant(dev, battery_soc, soc_threshold) (and optionally _pv_gate_ok). Or hide or reject price_mode / pv_power_threshold for SD devices in the config flow and document it.

**Beleg (Verifier):** Code:
- custom_components/aurum/modules/devices.py:370-378: SD branch calls _handle_startup_detection, then `continue`; the price grant (430-431) and the PV gate (422) are never reached.
- devices.py:889-906: the deadline is the only grid path out of WAITING.
- devices.py:908-911: `needed = nominal + hysteresis_on; soc_ok = ...; if turnon_excess >= needed and soc_ok:`, the only other path out; no _price_grant or _pv_gate_ok call.
- config_flow.py:335-338 and 446-486: the same device schema offers startup_detection, price_mode, max_price and pv_power_threshold; there is no validation in the add or edit step.
- strings.json:170: the price_mode help says cheap grid "ALSO turns on when electricity is cheap ... even at night or on cloudy days".
- README.md:184-188: "A device with cheap_grid mode turns on when any of these is true: ... cheap_period_entity is ON".
- README.md:116: SD "resumes w …

### 12. [MEDIUM] Battery 'charging' emergency switches off non-interruptible and deadline-forced devices mid-run
`custom_components/aurum/modules/devices.py:262` · devices-core · docs-mismatch · Verdict: confirmed

**Beschreibung:** The MODE_CHARGING branch protects override devices and SD devices in STANDBY or RUNNING. It calls _turn_off on every other device that is on, without checking dev['interruptible'] or force_started. The config UI says 'Interruptible … Disable for devices that must not be interrupted (e.g. 3D printer, aquarium heater)', and the README says 'If disabled, AURUM will not turn the device off mid-cycle'. The battery-mode table says 'All devices off'. The docs contradict each other, and the code also treats SD programs differently from non-interruptible devices.

**Fehlerszenario:** 3D printer configured interruptible=false (150 W), started on surplus at 15:00 for an 8 h print. At 21:00 SOC reaches min_soc and the mode becomes charging. AURUM cuts the printer ('battery_charging') and the print is ruined. Likewise, a deadline-forced device is killed and, once the mode clears, force-started again (_turn_off cleared force_started).

**Fix-Vorschlag:** Skip devices with interruptible=False (and possibly force_started) in the emergency loop, as is already done for SD RUNNING. Otherwise state explicitly in the interruptible description that battery protection overrides it.

**Beleg (Verifier):** custom_components/aurum/modules/devices.py:241-266: emergency loop; skips only override (249), SD ""/STANDBY (255-257) and SD RUNNING (259-261); 262-264 turn off everything else, with no interruptible, force_started or min_on_time check.
devices.py:670-676: _should_turn_off returns None for non-interruptible or force_started devices. 348-357: condition_not_met honours interruptible. 1036-1037: preemption honours interruptible.
devices.py:1149: _turn_off sets force_started=False. 1192-1204: _deadline_urgent re-triggers once force_started is False.
battery.py:44-45: soc <= min_soc gives MODE_CHARGING with no hysteresis.
README.md:117 "If disabled, AURUM will not turn the device off mid-cycle" vs README.md:250 "charging | SOC <= min | All devices off (battery protection)".
strings.json:169 (and translations/en.json:169, de.json:169): "Disable for devices that must not be interrupted (e.g. 3 …

### 13. [MEDIUM] MODE_CHARGING blocks every grid-powered start (deadline force-start, SD deadline, cheap-grid grant), so muss_heute deadlines never fire while the battery sits at min_soc
`custom_components/aurum/modules/devices.py:242` · price-energy-battery · bug · Verdict: confirmed

**Beschreibung:** When battery_mode == MODE_CHARGING, update() runs the emergency loop and returns early. _deadline_urgent is never evaluated, the SD WAITING state machine (whose deadline branch starts on grid) is never entered, and _price_grant is never consulted. A regular device that was deadline-forced on is also turned off (`battery_charging`). These start paths run on grid by definition: the README says 'If a deadline is set and PV never arrives, AURUM starts on grid power as a fallback', and QUICKSTART says cheap-grid devices run 'auch nachts und unabhängig vom Akku'. BatteryManager uses `soc <= min_soc` while strings.json says 'Below this level'. A battery parked exactly at its inverter floor (users usually set AURUM min_soc to the same value) therefore stays in MODE_CHARGING for long stretches in winter. Those are exactly the days when PV never arrives and the grid fallback is needed. Blocking a grid-powered load also does not protect the battery, because the inverter will not discharge below its floor.

**Fehlerszenario:** December, min_soc 10, battery parked at 10 %. Washer: SD, deadline 18:00, estimated_runtime 120, muss_heute ON, sd_state waiting. Dryer: regular, deadline 18:00, 90 min. Boiler: cheap_grid with the price cheap. Simulated 12:00-23:00 at SOC 10: zero switch actions, the washer is still 'waiting' and muss_heute is still ON at 23:00. The same run at SOC 11 starts the washer and the dryer at their deadline windows.

**Fix-Vorschlag:** In the MODE_CHARGING branch, still evaluate deadline-urgent devices (regular and SD WAITING) and leave force_started devices running, since they are explicit grid runs. Decide explicitly whether a live cheap_grid grant may start a device in charging mode; the documentation says it is independent of the battery. Align the `<=` with the 'below' wording, or add a small hysteresis.

**Beleg (Verifier):** Code:
- custom_components/aurum/modules/devices.py:242-266: the MODE_CHARGING emergency loop returns early. It exempts only manual override, SD standby and SD RUNNING. Lines 262-264 turn off any other on device, including force_started ones, with "battery_charging".
- devices.py:401: regular-device deadline force-start, reached only in the normal loop.
- devices.py:890: SD WAITING deadline grid start, reached only via the normal loop.
- devices.py:430 and 630: _price_grant, likewise only reached in the normal loop.
- custom_components/aurum/modules/battery.py:44: `if soc <= self.min_soc: mode = MODE_CHARGING`.

Docs:
- Documented as intended: README.md:250 ("charging | SOC <= min | All devices off (battery protection)"); strings.json:43 and :106 ("ALL devices are turned off"); battery.py:11 docstring; tests/simulation_7day.py:1242-1244.
- Contradicting promises: README.md:116 ("If a dead …

### 14. [MEDIUM] Power sensors in kW pass config validation but are read as W (no unit conversion), so surplus is off by a factor of 1000
`custom_components/aurum/modules/energy.py:43` · price-energy-battery · bug · Verdict: confirmed

**Beschreibung:** config_flow._validate_energy_sources accepts {W, kW, mW, MW} for grid, PV and battery charge/discharge power, and the error text says '(W, kW)'. EnergyManager reads all of them with get_float and never looks at unit_of_measurement, so every comparison against nominal_power, hysteresis and pv_power_threshold (all in W) is wrong by 1000x for kW sensors. HassAccess.get_state already supports reading attributes, so a conversion would be cheap.

**Fehlerszenario:** Tesla Powerwall core integration: sensor.powerwall_site_now reports kW. At 3.2 kW export, grid = -3.2, so excess = 3.2 W and nothing ever starts (needs nominal + 300 W). A device the user switches on is never shed, because a deficit of -2.4 'W' never falls below -hysteresis_off. With kW battery charge/discharge sensors in legacy mode, battery power is effectively ignored. A kW PV sensor never reaches a pv_power_threshold of 1000.

**Fix-Vorschlag:** In EnergyManager (and _get_device_power), read the unit_of_measurement attribute and scale kW/MW/mW to W, or have the config flow reject non-W units with a clear message. Add a test with a kW grid sensor.

**Beleg (Verifier):** - <local path> `_VALID_POWER_UNITS = {"W", "kW", "mW", "MW"}`; lines 154-156 raise `invalid_power_unit` only for units outside that set; lines 172-175 apply this to grid, PV and battery charge/discharge; lines 550 and 650 are the user and options flows.
- <local path> says "This sensor's unit isn't a power unit (W, kW)…". Line 19 says the grid sensor "Must report current power in watts". Lines 22-23 say battery charge/discharge are "in watts".
- <local path>, 61-62, 93-97 read power with get_float and never look at the unit. Lines 117-127 compute excess = -grid (- battery_power_net).
- <local path> get_float is a plain float(state).
- <local path> …

### 15. [MEDIUM] _scheduling_reason is not persisted, so after an HA restart a cheap-grid or PV-gate run is treated as a plain surplus run and gets cycled
`custom_components/aurum/modules/persistence.py:24` · price-energy-battery · robustness · Verdict: confirmed

**Beschreibung:** _VALUE_FIELDS persists managed_on and force_started but not _scheduling_reason. On restore, a device that is ON gets managed_on=True and reason None. For a cheap_grid run, the cheap-grid hold and price_no_longer_cheap are skipped and the generic excess-deficit path sheds it. For a PV-gate (solar_pv) run, the PV-gate hold is skipped and the device is shed whenever house load hides the surplus. Both then restart via their grant. cheap_grid_active reads False after the restart while the device is still running on grid.

**Fehlerszenario:** cheap_grid heater running at 02:00 with the price cheap. HA restarts (update or reboot). Simulated with PersistenceManager save/restore: reason None and cheap_grid_active False on the first cycle; OFF at +600 s (excess_deficit), ON at +660 s with cheap_grid.

**Fix-Vorschlag:** Add '_scheduling_reason' to _VALUE_FIELDS (cleared on rollover or when the switch is found off), or re-derive it on restore from _price_grant / _pv_gate_ok for devices that are ON.

**Beleg (Verifier):** Code:
- custom_components/aurum/modules/persistence.py:24-27: _VALUE_FIELDS has no `_scheduling_reason`.
- persistence.py:195-213: an ON switch gets managed_on=True and nothing else.
- devices.py:166: the reason defaults to None.
- devices.py:690, 701, 742: the cheap_grid and solar_pv off-checks depend on the reason.
- devices.py:756-768: the excess_deficit fallback.
- devices.py:481-522: shedding.
- devices.py:1272-1276 and coordinator.py:273-276: cheap_grid_active is derived from the reason.
- Separate bug: devices.py:640-642 together with 467-472 (the PV-gate debounce timer is cleared every cycle when surplus < needed).

Repro scripts (throwaway):
- <scratch>/verify_sched_reason_restart.py
- <scratch>/verify_sched_reason_restart_pv.py

Output, cheap_grid heater (2 kW, no battery, 02:00, importing 2500 W, price cheap):
pre-restart: on reason=cheap_grid cheap_grid_active=True; held for  …

### 16. [MEDIUM] Configured SOC sensor still unavailable after the startup grace: synthetic 0 % forces MODE_CHARGING and kills running devices, contrary to its own comment
`custom_components/aurum/modules/energy.py:78` · price-energy-battery · robustness · Verdict: confirmed

**Beschreibung:** Not a regression of audit #10. The 0 % fallback was that fix's chosen design. Its consequence contradicts the code comment, though: 'assume a protective low SOC so devices can't drain the battery (they may still run on genuine grid export, which needs no battery)'. 0.0 <= min_soc (also when min_soc is 0) puts BatteryManager into MODE_CHARGING, which zeroes excess_for_devices and turns off every running device that is neither overridden nor SD. That includes non-interruptible devices, cheap-grid runs and deadline-forced runs. Nothing can start on grid export either. _last_soc is not persisted, and coordinator._entities_ready only waits for the grid sensor (6 cycles), so every restart with a slow cloud SOC integration hits this path. The battery SOC sensor shows 0 % and the advisor reports 'battery_charging'.

**Fehlerszenario:** HA restart at 03:00. The grid sensor (local P1) is ready, the SOC sensor (cloud integration) stays 'unavailable' for 3 min. A non-interruptible dishwasher and a cheap_grid boiler are ON. Simulated: battery_soc is published as 0.0, mode 'charging', and both switches are turned OFF in the first device cycle. The dishwasher program is aborted.

**Fix-Vorschlag:** Wait for the SOC entity (when configured) in _entities_ready. If no SOC has been seen since start, freeze device actions (no starts, no emergency stops) instead of synthesizing 0 %. Persist _last_soc. Fix the comment.

**Beleg (Verifier):** Code: custom_components/aurum/modules/energy.py:38 (_last_soc=None), :67-83 (fallback to 0.0 with the inaccurate comment at :75-77); coordinator.py:36 (STARTUP_GRACE_CYCLES=6), :155-162 (_entities_ready checks only the grid sensor), :170-192 (grace ends by cycle count); battery.py:44-56 (soc<=min_soc gives MODE_CHARGING, excess_for_devices=0); devices.py:242-266 (charging emergency turns off every ON device except override and SD standby/running, ignores interruptible, then returns); config_flow.py:258-263 and number.py:110-127 (min_soc range 0-50); sensor.py:424-435 (publishes 0.0 % as valid); advisor.py:162-163; persistence.py never stores _last_soc. Introduced in commit d7dc839 (audit fix #10). No test covers the energy SOC fallback.

Repro using the real coordinator loop with a fake HA: <scratch>/soc_startup.py. Config: min_soc=10, a non-interruptible 'Dishwasher' and a cheap_grid 'B …

### 17. [MEDIUM] max_price is not a cap: price level / cheap period grant grid power even when the current price is above max_price, contradicting the UI text
`custom_components/aurum/modules/pricing.py:148` · price-energy-battery · docs-mismatch · Verdict: confirmed

**Beschreibung:** is_price_ok ORs three sources: price <= max_price, cheap_period ON, and level <= cheap. When max_price > 0 and the price is above it, a 'cheap' level or an active best-price period still returns True. strings.json tells the user the opposite: price_level_entity is 'Used as fallback when no max_price is set on a device', and max_price is the 'Maximum electricity price ... at which this device may use grid power. Set to 0 to use price level / cheap period detection instead'. The README's 'any of these is true' and the code comment 'always honored' match the code, so the UI help text and the README disagree. A user who sets max_price as a hard ceiling gets runs above it, and price_no_longer_cheap never fires while the level stays 'cheap'.

**Fehlerszenario:** price_entity and price_level_entity both configured. Device cheap_grid with max_price 20. Expensive week: Tibber level 'cheap' (relative to the trailing average) at 31.5 ct. Verified: should_run_on_grid(dev) returns True, so the device runs on 31.5 ct grid power despite the 20 ct ceiling.

**Fix-Vorschlag:** When max_price > 0 and a current price is known, treat it as a hard ceiling (require price <= max_price in addition to, or instead of, level/period), or fix strings.json/en/de to describe the OR semantics. A clear per-device 'ceiling' would be the safer meaning.

**Beleg (Verifier):** The demo script is <scratch>/maxprice_cap.py. It runs the real `PricingManager` (`update`, `snapshot`, `should_run_on_grid`) against stub states, with `max_price` = 20 and a price of 31.5 ct:
- level=cheap, period=off: cheap_grid -> True, cheap_grid_soc -> True
- level=normal, period=on: cheap_grid -> True, cheap_grid_soc -> True
- level=normal, period=off: cheap_grid -> False, cheap_grid_soc -> False

Code references:
- custom_components/aurum/modules/pricing.py:141-156: OR logic, with the comment 'always honored' at :148.
- pricing.py:169-173: `should_run_on_grid` passes `is_price_ok` through.
- custom_components/aurum/modules/devices.py:574: `_price_grant`.
- devices.py:690-693: `price_no_longer_cheap`, only when the result is False.
- devices.py:743-753: cheap-grid hold.
- devices.py:155: `max_price` default 0.

Docs references:
- custom_components/aurum/strings.json:110: '...Used as …

### 18. [MEDIUM] SOC trajectory is anchored at the first excess > 0 after midnight, so one night-time export sample sets the budget to 0 for most of the day
`custom_components/aurum/modules/budget.py:213` · budget-forecast · bug · Verdict: confirmed

**Beschreibung:** The trajectory start is set on the first update after the midnight reset where `excess_for_devices > 0`. Nothing checks for PV production, daylight or a sustained surplus, and the anchor is never re-evaluated. Without battery charge/discharge sensors, or with battery_priority=True, excess is just -grid_power_ema_asym. With zero-export battery regulation the grid meter often shows a few seconds of small export at night when a load switches off, and the asymmetric EMA (alpha_down 0.7) passes that through. The linear ramp then starts at a night SOC and time. The battery keeps draining until sunrise, so the deviation becomes very negative and the multiplier (band 5 %, 0.5 per band) clamps to 0. Before the July fix #5 this code path never ran; that fix turned it on.

**Fehlerszenario:** Budget configured, no battery power sensors, target 80 %, 10 kWh battery, November day (production 08-16). One 15 s sample of 5 W export at 01:00 with SOC 41 % sets the anchor. Simulated with the real BudgetManager: device_budget_w is 0 (trajectory_multiplier 0.0, reason budget_exhausted) from 03:00 until 12:00. The same day anchored normally at sunrise gives 296-2919 W. All regular solar_only devices without an exemption are blocked by the cap all morning, even with real surplus.

**Fix-Vorschlag:** Anchor only on real daylight production: pv_power above a threshold, or the current hour having forecast watts > 50, and the excess sustained for a few minutes. Alternatively, anchor at the forecast production start using the SOC at that moment. Also re-anchor if SOC falls below the start SOC before production begins.

**Beleg (Verifier):** Code:
- custom_components/aurum/modules/budget.py:212-217 sets the anchor on the first `excess > 0`, with no daylight or sustained-surplus check.
- custom_components/aurum/modules/budget.py:649-686 is the trajectory multiplier, clamped to [0, 2] with band 5.
- custom_components/aurum/modules/budget.py:555-573: _hours_until_sunset counts down to the last forecast production hour, so the budget is also computed at night.
- custom_components/aurum/modules/energy.py:111-127: excess = -grid_ema_asym when there are no battery power sensors or battery_priority=True.
- custom_components/aurum/modules/helpers.py:40-52: alpha_down=0.7.
- custom_components/aurum/modules/battery.py:56-58: excess passes through in low_soc mode.
- custom_components/aurum/coordinator.py:200-244: budget.update runs every cycle; the anchor is only cleared by daily_reset at the calendar-day change.
- custom_components/aur …

### 19. [MEDIUM] Dynamic target SOC can be higher than the user's target (target < 50 %, or learned weather factor > 1)
`custom_components/aurum/modules/budget.py:289` · budget-forecast · bug · Verdict: confirmed

**Beschreibung:** `effective_target = max(budget_dynamic_target_min (50), target_soc - (1 - weather_factor) * 30)`. The feature is meant to lower the target in bad weather, but nothing caps it at target_soc. (a) With target_soc below 50 (the config flow allows 10-100), effective_target is always 50. (b) Weather learning lets learned factors reach 1.5. With 'sunny' learned at 1.3, the reduction is negative and effective_target becomes target + 9 (up to +15, which can exceed 100 %). energy_to_target and the trajectory then aim higher than the user asked for. The early return `battery_soc >= target_soc` still uses the raw target.

**Fehlerszenario:** target_soc = 40, SOC 30 %, 10 kWh battery: effective_target_soc = 50 and energy_to_target = 2000 Wh instead of 1000 Wh (verified), so the budget is about 1 kWh / hours_remaining too low and devices are held back. Or target 80 with learned sunny factor 1.3: effective_target = 89 % (verified), and the budget reserves 9 % of capacity that the user never asked for.

**Fix-Vorschlag:** `reduction = max(0.0, (1 - w) * max_reduction)`; `effective_target = min(target_soc, max(min(budget_dynamic_target_min, target_soc), target_soc - reduction))`.

**Beleg (Verifier):** custom_components/aurum/modules/budget.py:82-86 sets the defaults (dynamic on, max_reduction 30, min 50). None of them is configurable in config_flow.py or number.py.
custom_components/aurum/modules/budget.py:285-291 computes `effective_target = max(self.budget_dynamic_target_min, target_soc - reduction)`, with no upper cap at target_soc or 100.
budget.py:259 makes the early return use the raw target_soc. budget.py:294 (energy_to_target) and budget.py:311 (trajectory) use effective_target.
budget.py:534 clamps the learning ratio to 1.5 and applies an EMA. budget.py:383-386 returns the learned factor. coordinator.py:208-212 runs the learning hourly.
config_flow.py:251-254 and number.py:83-84 allow target_soc from 10 to 100.
devices.py:432-437 applies the budget cap to non-grid-only devices without a PV gate or price grant.

Repro: <scratch>/dyn_target.py, run with the real BudgetManager a …

### 20. [MEDIUM] A device blocked by the budget cap is reported as 'waiting_surplus'; the budget reason and trajectory are not shown anywhere
`custom_components/aurum/modules/advisor.py:168` · budget-forecast · ux · Verdict: confirmed

**Beschreibung:** When the cap blocks a start (devices.py:439-447), the only state change is a debug log and excess_since = None. Nothing about it reaches device_states, so the advisor falls through to 'waiting_surplus'. shared['budget_info'] (reason after_sunset / budget_exhausted / soc_above_target, trajectory_multiplier, effective_target_soc, combined_factor) has no consumer: it is not in sensor attributes or diagnostics. Users cannot see why devices stay off, and the problems in the other findings (multiplier at 0, raised effective target) cannot be diagnosed.

**Fehlerszenario:** 10:00, the panel shows a surplus of 2500 W and budget 0 W (trajectory multiplier clamped to 0). The 1000 W heater stays off, and the advisor and device card say 'waiting for surplus' even though the surplus tile is green. Diagnostics show device_budget_w 0 but not why.

**Fix-Vorschlag:** Set a per-device flag (e.g. dev['_budget_capped']) when the cap blocks and clear it otherwise. Publish it in device_states and map it to a new advisor reason 'budget_cap' (EN/DE strings). Expose the slowly changing budget_info fields (reason, effective_target_soc, trajectory_multiplier rounded to 0.1, combined_factor) as attributes of sensor.aurum_budget and in diagnostics.

**Beleg (Verifier):** custom_components/aurum/modules/devices.py:432-447 (cap: debug log + excess_since=None + continue, no published state); devices.py:1241-1262 (device_states has no budget field); custom_components/aurum/modules/advisor.py:145-168 (no budget branch, falls through to 'waiting_surplus'); custom_components/aurum/modules/budget.py:226 (budget_info written; grep for budget_info/last_info in custom_components/aurum finds no reader); custom_components/aurum/sensor.py:547-557 (only budget_w attribute); custom_components/aurum/diagnostics.py:75-82 (no budget reason/trajectory); custom_components/aurum/frontend/aurum-panel.js:111,153 (reason text), 441-444 (Budget tile shows the W value only); coordinator.py:64-66 + const.py:47 (budget active with forecast entity, target_soc default 80). Repro <scratch>/test_budget_reason_visibility.py, setup: 1000 W solar_only device, SOC 60, threshold 20, excess 2 …

### 21. [MEDIUM] Energy-today sensors drop to 0 for ~7 cycles after every restart/reload, so Energy Dashboard statistics double-count
`custom_components/aurum/coordinator.py:112` · ha-lifecycle · bug · Verdict: confirmed

**Beschreibung:** async_setup fills device_states with placeholders that hardcode runtime_today_s=0 and leave out energy_today_wh, even though persistence.restore has already loaded the real counters into self.devices.devices. During the startup grace (cycles 1-6) the update loop returns before Step 4. On odd cycle 7 it republishes the same seeded cache. So coordinator.device_states stays the placeholder list until cycle 8 (about 2 min at 15 s). AurumDeviceEnergySensor and AurumDeviceEnergyTotalSensor (TOTAL_INCREASING, advertised in the README as 'HA Energy Dashboard compatible') therefore write 0 on every coordinator tick in that window, then jump back to the restored value. Second trigger, same effect: if devices.update raises (the Step 3 except), Step 4 sets self.device_states = shared.get('device_states', []), which is an empty list, and every per-device sensor falls to 0 or unknown for that cycle. I confirmed the 0 -> restored sequence with a stubbed coordinator run: cycles 1-7 published energy 0, cycle 8 published 3500.

**Fehlerszenario:** Heater has 3500 Wh today and sensor.aurum_heater_energy_today is in the Energy Dashboard. The user restarts HA after a HACS update, or edits any device, which reloads the entry. The sensor goes 3500 -> unknown -> 0 (about 90 s) -> 3500. The recorder treats the drop of more than 10% as a meter reset, then counts +3500 Wh, so the long-term sum double-counts the whole day so far on every restart or reload. The runtime sensors also show 0 min for about 2 minutes.

**Fix-Vorschlag:** Seed the placeholders from the restored device dicts, for example by calling self.devices._publish_device_states(shared, -1) after restore and using its device_states, or copy runtime_today_s and energy_today_wh from dev. In Step 4 keep the previous device_states when the devices step failed (only assign when 'device_states' in shared).

**Beleg (Verifier):** Code path:
- custom_components/aurum/modules/persistence.py:144-152: restore puts energy_today_wh=3500 and runtime_today_s into self.devices.devices.
- custom_components/aurum/coordinator.py:112-122: placeholder dicts with `"runtime_today_s": 0` and no `energy_today_wh`. Line 127 seeds `_cached_device_states` from them.
- coordinator.py:36, 170-192: grace cycles 1-6 return before Step 4. Lines 263-264 and 279: odd cycle 7 republishes the placeholders. Lines 255-260: the first real publish is at cycle 8.
- coordinator.py:279: `self.device_states = shared.get("device_states", [])` becomes [] when devices.update raised (lines 256-262).
- custom_components/aurum/__init__.py:201-206: first refresh (cycle 1) runs before entities exist. Lines 96-98: options change triggers a full reload.
- custom_components/aurum/sensor.py:292-321 (AurumDeviceEnergySensor, TOTAL_INCREASING, `ds.get("energy_toda …

### 22. [MEDIUM] State is never saved on HA stop/restart; up to 5 min of runtime and SD state are lost and a running program can be cut
`custom_components/aurum/coordinator.py:129` · ha-lifecycle · ha-integration · Verdict: confirmed

**Beschreibung:** The only save outside the 20-cycle periodic save is AurumCoordinator.async_shutdown. HA calls that from async_unload_entry and from the base class's config_entry.async_on_unload hook. Current HA core does not unload config entries when it stops: ConfigEntries._async_shutdown only cancels setup retries. A coordinator tied to a config entry also registers no EVENT_HOMEASSISTANT_STOP listener (async_register_shutdown is only for coordinators without an entry). AURUM registers no stop listener of its own. So on a normal HA restart the state file is whatever the last periodic save wrote: 20 cycles, 5 min at 15 s, 20 min at 60 s. The README says device runtimes and energy counters 'survive restarts'.

**Fehlerszenario:** A washing machine with SD is in WAITING. The periodic save at 10:00:00 records sd_state=waiting. At 10:02 surplus arrives and AURUM sets it to RUNNING and turns the Shelly on. At 10:04 the user restarts HA. On boot it is restored as WAITING with the Shelly on. On the first control cycle the WAITING branch's 'enforce off' calls _turn_off and cuts power to the program mid-wash, then waits for surplus plus debounce_on before restarting it. In every restart, 0-5 min of runtime/energy is lost, so stop_after_runtime devices overrun by that amount. An SD finish in the window is also replayed, giving a duplicate 'finished' notification.

**Fix-Vorschlag:** In async_setup_entry, register entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, lambda _: hass.async_create_task(coordinator.async_save()))) with a save-only helper, or save on EVENT_HOMEASSISTANT_FINAL_WRITE. Also save immediately after SD state transitions, or move to helpers.storage.Store with async_delay_save.

**Beleg (Verifier):** - Saves only in custom_components/aurum/coordinator.py:129-140 (async_shutdown) and coordinator.py:289-295 (`if self.cycle % 20 == 0`).
- custom_components/aurum/__init__.py:191-234 registers no stop listener; it only registers the options update listener (line 224). async_shutdown is called only from async_unload_entry (line 240).
- A grep of the repo for EVENT_HOMEASSISTANT / homeassistant_stop / Store( / async_will_remove_from_hass finds only the comment at coordinator.py:138.
- HA core dev, helpers/update_coordinator.py: `if self.config_entry: self.config_entry.async_on_unload(self.async_shutdown)`. async_register_shutdown does `if self.config_entry: raise RuntimeError("This should only be used outside of config entries.")` and is the only place EVENT_HOMEASSISTANT_STOP is listened to. A missing config_entry for custom integrations is filled from the current_entry ContextVar (custom_ …

### 23. [MEDIUM] Restart across midnight restores yesterday's budget trajectory; budget multiplier becomes 0 for the whole day
`custom_components/aurum/coordinator.py:241` · ha-lifecycle · bug · Verdict: confirmed

**Beschreibung:** budget.restore_state restores trajectory_start_soc, trajectory_start_time and pv_total_midnight with no date check. On the first non-startup cycle, _last_daily_reset is -1, so the coordinator records today without calling budget.daily_reset(). CHANGELOG 1.x fixed exactly this first-cycle skip for device counters but not for the budget. The stale trajectory start makes _get_trajectory_multiplier compute progress close to 1, so expected SOC is about the target, and any SOC more than 10 points below target clamps the multiplier to 0. With a lifetime PV counter, the stale pv_total_midnight also folds yesterday's production into today's in-day correction, which clamps to 1.5.

**Fehlerszenario:** Budget is configured (pv_forecast_entity), target 80%. The last save is at 23:58 with the trajectory started yesterday 08:00 at 30%. HA comes back at 00:03. At 10:00 SOC is 45%, forecast 25 kWh remaining, raw budget about 1472 W. Reproduced: with the stale trajectory, trajectory_multiplier=0.0 and device_budget_w=0. With today's trajectory it is 1.59 and 2342 W. Every solar_only device with SOC at or above its threshold is budget-capped until the battery is within about 10% of target, all day, until the next midnight reset.

**Fix-Vorschlag:** Persist the save date with the budget state. In restore_state (or in the coordinator after restore), call budget.daily_reset(), or skip the trajectory and pv_total_midnight fields, when the saved date is before today. Alternatively let the first cycle run budget.daily_reset() when the restored state predates today.

**Beleg (Verifier):** Code path:
- persistence.py:40-49 saves `_meta.saved_at` and `saved_date`; persistence.py:66-68 saves `_budget`; persistence.py:220 returns `state.get("_budget")` with no date filtering.
- coordinator.py:100-102 calls budget.restore_state(budget_state).
- budget.py:957-972 restores trajectory_start_soc, trajectory_start_time and pv_total_midnight with no date check.
- coordinator.py:58 sets `_last_daily_reset = -1`; coordinator.py:240-244 runs `if self._last_daily_reset >= 0 and self.budget: self.budget.daily_reset()`, which is skipped on the first cycle.
- budget.py:213 only sets a new trajectory start when the current one is None.
- budget.py:665-683: elapsed is measured from the stale start, and the multiplier is clamped to 0 when the deviation is -10 or worse.
- devices.py:432-447: the budget cap skips regular devices that are not grid-only, not PV-gated and not price-granted.
- CHAN …

### 24. [MEDIUM] Grid sensor unavailable after startup is read as 0 W; running devices are never shed during the outage
`custom_components/aurum/coordinator.py:170` · ha-lifecycle · robustness · Verdict: confirmed

**Beschreibung:** The coordinator only checks that grid_power_entity is available during the 6 startup cycles (_entities_ready). After that, energy.update uses get_float(grid, 0), so an unavailable or unknown grid meter is read as a perfectly balanced 0 W. Without battery power sensors, or with battery_priority=True, excess becomes 0. That is never below -hysteresis_off, so no running device is ever shed while the meter is out; only new starts are blocked. The startup guard shows that grid availability was meant to matter, but the main loop does not handle it.

**Fehlerszenario:** A Tibber Pulse or cloud-based grid meter drops out at 17:30 while a 2 kW solar_only heater is running on surplus. The sun sets, and the heater keeps running on grid (or on the battery down to min_soc) for as long as the sensor stays unavailable, possibly hours. Normally it would be shed within debounce_off.

**Fix-Vorschlag:** Re-check _entities_ready (or have energy.update flag grid as unavailable) on every cycle. While the meter is unavailable after a short tolerance, treat excess as a deficit for interruptible devices (fail closed) or skip device control, and surface it in the Advisor.

**Beleg (Verifier):** Code:
- custom_components/aurum/coordinator.py:155-162 (`_entities_ready`), called only at coordinator.py:170-180 inside `if startup_mode:` (STARTUP_GRACE_CYCLES = 6, coordinator.py:36). The main loop after that (coordinator.py:182 onward) never checks again.
- custom_components/aurum/modules/energy.py:42 `grid_raw = get_float(self.hass, self.grid_power_entity, 0)`.
- custom_components/aurum/modules/helpers.py:17-18: returns the default for None, "unavailable", "unknown" or "".
- energy.py:121-127: grid-only excess `excess_raw = -grid_raw`, used when there are no battery power sensors or when battery_priority=True.
- battery.py:36-41 and 57-60: passes excess_raw through.
- devices.py:386: `turnoff_excess = excess_raw - newly_allocated`.
- devices.py:720 and 756: shedding requires `available_excess < -hysteresis_off` (default 100, const.py:127).
- devices.py:478: `deficit = -(excess_raw - …

### 25. [MEDIUM] Per-device and total 'Energy Today' sensors drop to 0 after every restart/reload, so today's energy is counted twice in statistics
`custom_components/aurum/sensor.py:315` · entities-config · bug · Verdict: confirmed

**Beschreibung:** AurumDeviceEnergySensor and AurumDeviceEnergyTotalSensor read coordinator.device_states. After setup, coordinator.async_setup (coordinator.py:113-122) fills device_states with placeholders that have no 'energy_today_wh' and set runtime_today_s=0. During the startup grace (cycles 2-6) and the odd cycle 7, the coordinator returns early and never replaces these placeholders, so ds.get('energy_today_wh', 0) gives 0. Real values only come back at cycle 8, the first devices.update. Both sensors are SensorStateClass.TOTAL_INCREASING. The HA recorder treats a drop of more than 10% as a new meter cycle and adds the whole next value again. A scratch simulation (scratchpad/audit/restart_energy.py) with a restored 3000 Wh shows 0 Wh for cycles 1-7 and 3000 Wh from cycle 8. The runtime sensor shows 0 min over the same window; that is only cosmetic.

**Fehlerszenario:** Heater has used 3000 Wh today and sensor.aurum_heater_energy_today is in the Energy dashboard. The user adds another device in Options, which triggers async_reload, or restarts HA. The sensor goes 3000 -> unknown -> 0 for about 90-105 s -> 3000. The recorder sees 3000 -> 0 as a reset and then adds +3000 Wh, so the dashboard shows 6000 Wh for the day. This happens again on every restart and every options save, for every device and for sensor.aurum_energy_today.

**Fix-Vorschlag:** Seed the placeholders in coordinator.async_setup from the restored device dicts (runtime_today_s, energy_today_wh, sd_state-based state). Alternatively, have the energy sensors keep their previous value or return None while 'energy_today_wh' is missing, or make them RestoreSensor. Add a test that a reload never publishes a lower energy value.

**Beleg (Verifier):** Code path:
- custom_components/aurum/coordinator.py:112-122: the placeholders have no 'energy_today_wh' and set 'runtime_today_s': 0.
- coordinator.py:127: the cache is seeded with the placeholders.
- coordinator.py:170-192: startup early returns, so device_states is not reassigned.
- coordinator.py:263-279: the odd cycle 7 copies the cached placeholders.
- custom_components/aurum/modules/devices.py:1246-1247: real energy_today_wh is published only from cycle 8.
- custom_components/aurum/sensor.py:295-321: AurumDeviceEnergySensor is ENERGY / TOTAL_INCREASING and uses ds.get('energy_today_wh', 0).
- sensor.py:324-343: the total sensor sums the same key.
- custom_components/aurum/__init__.py:93-95: every options save triggers async_reload.
- __init__.py:197-221: order is async_setup -> first_refresh -> platforms.
- custom_components/aurum/modules/persistence.py:25 and 143-151: energy_today …

### 26. [MEDIUM] Config validator accepts kW/MW/mW power sensors and Wh/MWh forecast sensors, but the runtime treats every value as W / kWh
`custom_components/aurum/config_flow.py:121` · entities-config · bug · Verdict: confirmed

**Beschreibung:** _VALID_POWER_UNITS = {W, kW, mW, MW}, and the invalid_power_unit error text even says '(W, kW)'. energy.py:43-97 and devices.py _get_device_power use get_float() on the raw state with no unit conversion anywhere: a grep for unit_of_measurement in modules finds only the pv_actual_today auto-detection. The same applies to pv_forecast_entity: _check_energy accepts Wh/MWh, but budget.py:267-273 always multiplies the value by 1000 as if it were kWh. Device power_entity units are not validated at all. QUICKSTART lists Tesla Powerwall, whose instant-power sensors report kW, and any HA user can switch a POWER sensor's display unit to kW.

**Fehlerszenario:** The grid and battery sensors report kW. Exporting 3.2 kW gives excess = 3.2, read as 3.2 W, so no surplus device ever starts. Deficits are also tiny (|excess| < 10, never < -hysteresis_off of 100 W). A device that is manually switched on, cheap-grid-started or deadline-started is therefore never shed for excess_deficit or soc_grid_deficit, and keeps drawing grid or battery power until SOC reaches min_soc. A PV sensor in kW (3.5) never reaches pv_power_threshold 1000, so the PV gate never opens. An SD device whose power sensor reports kW (1.8) never exceeds sd_power_threshold 5 W, so the program is never detected.

**Fix-Vorschlag:** Either normalise every power reading by its unit_of_measurement in EnergyManager and DeviceManager (kW x1000, MW x1e6, mW /1000) and every energy reading in the budget, or restrict the validator to 'W' (and 'kWh' for the forecast) with an explicit error. Validate device power_entity the same way.

**Beleg (Verifier):** custom_components/aurum/config_flow.py:121-122 (_VALID_POWER_UNITS = {"W","kW","mW","MW"}, _VALID_ENERGY_UNITS = {"Wh","kWh","MWh"}), :154-156, :168-170
custom_components/aurum/strings.json:54 ("isn't a power unit (W, kW)"); CHANGELOG.md:126 ("Power sensors must report `W`/`kW`, energy sensors `Wh`/`kWh`")
custom_components/aurum/hass_bridge.py:21-36 (raw state.state, no conversion); modules/helpers.py:14-22 (get_float = float(raw))
custom_components/aurum/modules/energy.py:43, 61-62, 92-97, 117-127 (grid/pv/battery power used as W)
custom_components/aurum/modules/budget.py:267-273 (remaining_kwh * 1000, unconditional) vs budget.py:584-613 (only pv_actual_today auto-detects Wh)
custom_components/aurum/modules/devices.py:1113-1118 (_get_device_power, no unit), :822 (actual_power > sd_power_threshold, default 5 at :176), :592-597 (_pv_gate_ok), :720/:756 (available_excess < -hysteresis_off …

### 27. [MEDIUM] Options flow cannot clear an optional field once it is set (default= instead of suggested_value), and settings merge resurrects entry.data keys
`custom_components/aurum/config_flow.py:422` · entities-config · ha-integration · Verdict: confirmed

**Beschreibung:** Every optional selector in _schema_energy, _schema_battery (price/level/cheap-period entities) and _schema_add_device (power_entity, deadline, estimated_runtime, condition_entity, condition_value) uses vol.Optional(key, default=<current value>) in the options flow. Per the HA data-entry-flow docs, default= is re-inserted by voluptuous when the user leaves the field empty; only description={'suggested_value': ...} allows clearing. When the frontend clears an entity, time or number picker, the key is omitted, and voluptuous puts the old value back. Settings has a second barrier: async_step_settings stores only the form result as options, and the coordinator uses {**entry.data, **entry.options}. Any key set during the initial setup (entry.data), including notify_service, therefore comes back even if the form submits it absent. There are no config-flow tests.

**Fehlerszenario:** A device has condition_entity sensor.boiler_temp < 55. The user removes the boiler sensor from the edit form and saves; the condition is still in the config. The deadline and estimated_runtime fields cannot be emptied either. In Energy & Battery, clearing pv_forecast_entity to switch off the budget, or price_entity after leaving Tibber, has no effect. The only workaround is deleting and re-adding the device, which loses counters and restored slider values, or the whole integration entry, which loses all devices.

**Fix-Vorschlag:** Build the options schemas with suggested_value (self.add_suggested_values_to_schema) instead of default= for optional fields. In async_step_settings, write the full merged dict, explicitly dropping keys the user cleared, so entry.data cannot resurrect them. Add config-flow tests for clearing.

**Beleg (Verifier):** Code:
- <local path>
  - :204-235 and :280-295: optional entity pickers with default=d.get(...)
  - :276-277: notify_service with suggested_value
  - :311-314, :388-398, :422-425, :439-444: power_entity, deadline, estimated_runtime, condition_entity, condition_value with default=
  - :594: self._current = {**config_entry.data, **config_entry.options}
  - :650-654: settings saves options = user_input + devices only
  - :656-661: schema defaults built from the merged dict
  - :757: edit form built with the device dict as defaults
- coordinator.py:40 config = {**entry.data, **entry.options}; :64-66 budget is created whenever pv_forecast_entity is truthy
- devices.py:539-542 the condition applies whenever entity and value are both set
- time.py:96-104 deadline time entity, 00:00 disables (this is why the deadline part is moot)
- strings.jso …

### 28. [MEDIUM] 'Maximum price' is documented as a cap, but the logic ORs it with cheap period and price level, so devices run above max_price
`custom_components/aurum/strings.json:171` · entities-config · docs-mismatch · Verdict: confirmed

**Beschreibung:** strings.json, en.json and de.json describe max_price as 'Maximum electricity price in ct/kWh at which this device may use grid power. Set to 0 to use price level / cheap period detection instead'. The README table says 'Grid power only below this price'. price_level_entity is described as 'Used as fallback when no max_price is set on a device' (strings.json:110). In pricing.is_price_ok (pricing.py:141-156), a price above max_price does not return False; the code falls through to the cheap_period and price_level checks, which grant grid power regardless of max_price. should_run_on_grid uses the same function, so the turn-off path does not stop the device either. The README's 'How it works' list documents the OR behaviour, which contradicts its own table and the UI text.

**Fehlerszenario:** A device in cheap_grid mode has max_price = 20 ct, and Tibber Prices supplies the price level and best-price period. On an expensive day, Tibber's relative level is 'cheap' or the best-price window is ON at 32 ct/kWh. is_price_ok returns True and the device runs on grid at 32 ct, although the user set a 20 ct maximum in the field and on the 'Max Price' number entity.

**Fix-Vorschlag:** Choose one semantic. Either make max_price > 0 an AND cap (price must be <= max_price, and period/level only refine it), or rewrite the UI and README text to say max_price is one of several OR'ed triggers and does not cap the period/level grants.

**Beleg (Verifier):** Code:
- custom_components/aurum/modules/pricing.py:141-156. The max_price branch returns True only when the price is at or below the cap. Above the cap it falls through to the cheap_period check (149-150) and the level <= 1 check (153-154), and either one returns True.
- pricing.py:171-173. should_run_on_grid returns is_price_ok(dev) unchanged.
- devices.py:574 (_price_grant), :690-693 (price_no_longer_cheap fires only on False), :743-753 (cheap-grid hold while not False). None of them checks max_price on its own.

Docs and UI text:
- strings.json:171, translations/en.json:171, translations/de.json:171: max_price help says "Maximum electricity price ... may use grid power. Set to 0 to use price level / cheap period detection instead".
- strings.json:110, en.json:110, de.json:110: price_level_entity is "Used as fallback when no max_price is set on a device".
- README.md:180 says "Grid pow …

### 29. [MEDIUM] Startup-detection devices ignore price_mode, max_price and pv_power_threshold, but the UI offers these settings and creates entities for them
`custom_components/aurum/number.py:45` · entities-config · bug · Verdict: confirmed

**Beschreibung:** For startup_detection devices, update() hands control to _handle_startup_detection. The WAITING branch (devices.py:865-948) starts a paused program only on deadline or on surplus >= nominal+hysteresis_on with soc_ok. It never calls _price_grant, pricing or _pv_gate_ok. The config flow still lets SD devices pick cheap_grid / cheap_grid_soc, max_price and pv_power_threshold. number.py creates AurumDevicePVPowerThreshold for every device, and AurumDeviceMaxPrice for price-aware SD devices. The status sensor publishes price attributes for them. Nothing in strings or the README says these are inert for SD devices. A scratch simulation (scratchpad/audit/sd_price.py) shows an SD dishwasher in cheap_grid mode during a cheap price, with pv_power 800 W over a 500 W threshold, staying in 'waiting' with 0 pricing calls.

**Fehlerszenario:** A dishwasher with SD has price_mode = cheap_grid and max_price = 25. The user presses Start at 22:00; AURUM detects and pauses it. The Tibber best-price window from 01:00 to 04:00 passes at 18 ct and the program stays paused. It starts the next day on PV, or at the deadline on grid at whatever the price is then. The 'Max Price' and 'PV Power Threshold' controls for it do nothing.

**Fix-Vorschlag:** Either add the price grant (and optionally the PV gate) as start conditions in the SD WAITING branch, or hide or reject these options for SD devices: do not create the number entities, and state the limitation in the strings.

**Beleg (Verifier):** Code (all paths under <local path>):
- modules/devices.py:370-378: SD devices are handed to _handle_startup_detection and then `continue`; the regular block at devices.py:380-472 never runs for them.
- modules/devices.py:865-948: the WAITING branch has only the _deadline_urgent start (890) and the surplus start (909-939: `turnon_excess >= needed and soc_ok`). Nothing in it references _price_grant, self.pricing or _pv_gate_ok.
- config_flow.py:335-338 (startup_detection), 446-470 (price_mode, max_price), 480-486 (pv_power_threshold): all offered for every device, no cross-validation.
- number.py:45-46: PV threshold entity created for every device. number.py:50-56: MaxPrice created for cheap_grid and cheap_grid_soc, with no SD exclusion.
- sensor.py:220-227: price attributes published for price-aware devices, SD included.
- frontend/aurum-panel.js:49-50 …

### 30. [MEDIUM] SOC threshold and charge-target descriptions contradict the control logic ('Set to 0 ... only full surplus' is inverted)
`custom_components/aurum/strings.json:158` · entities-config · docs-mismatch · Verdict: confirmed

**Beschreibung:** The soc_threshold text (en/de) says 'Set to 0 if the device should only run with full surplus'. In code, threshold 0 is the most permissive setting: battery_soc < 0 is never true, so the device always uses the full excess, which with battery power sensors and battery_priority off includes battery-charging power. It is never in grid-only mode and never subject to soc_grid_deficit shedding. target_soc is described as 'At what charge level should all devices be allowed to run... below this AURUM only runs devices with special permission' and 'Above this level, all devices are allowed'. But DeviceManager never reads battery_mode LOW_SOC; target_soc only feeds the budget, which exists only when pv_forecast_entity is set, and the advisor wording. A device's soc_threshold applies even when SOC is above target_soc.

**Fehlerszenario:** The user wants the battery to charge first and sets the heater's 'Minimum battery level' to 0, as the text suggests. With SOC 30% and 3.5 kW of battery charging, excess = 3500 W, so the 2 kW heater starts and the battery charges at 1.5 kW. Threshold 100 would have done what the user wanted. Separately, with no forecast entity, moving 'Charge target' from 80 to 100 changes no device decision.

**Fix-Vorschlag:** Rewrite soc_threshold as: 'Below this SOC the device may only use genuine grid export; at or above it, it may also use power that would charge the battery. 100 = battery always first, 0 = never protect the battery.' Rewrite target_soc to say it drives the PV budget and battery-mode display, not device permission.

**Beleg (Verifier):** Code path:
- `custom_components/aurum/strings.json:158` (same in `translations/en.json:158` and `de.json:158`): "...Set to 0 if the device should only run with full surplus." `:234`: "Below charge target: ...". `:42` and `:105` hold the target_soc texts.
- `modules/devices.py:242`: only `MODE_CHARGING` is checked; `MODE_LOW_SOC` is never read in DeviceManager.
- `modules/devices.py:619-622`: `if battery_soc >= 0 and battery_soc < soc_threshold: eff_excess = available_grid_excess else: eff_excess = available_excess`
- `modules/devices.py:417-418` (grid-only budget exemption) and `:719` (`soc_grid_deficit`) use the same predicate.
- `modules/energy.py:113-119`: `excess = -grid_ema_asym - battery_power_net` when battery power sensors are set and `battery_priority` is off.
- `modules/battery.py:44-49`: target_soc only selects the mode.
- `modules/budget.py:262`: SOC ≥ target gives an unlimit …

### 31. [MEDIUM] Every AURUM turn-off is published as state 'manual_override' for ~30 s, so the advisor explains it as a manual override and 'Devices running'
`custom_components/aurum/modules/devices.py:1228` · advisor-panel · bug · Verdict: confirmed

**Beschreibung:** `_turn_off()` sets `managed_on=False` right away, but `hass.turn_off()` goes through `services.call(..., blocking=False)`. That call returns before the switch entity has changed state, which is always the case for Shelly, Tasmota or Zigbee plugs. A few microseconds later, in the same executor job, `_publish_device_states()` reads `_is_device_on()` as still 'on' while `managed_on` is already False, so it publishes `state='manual_override'` (lines 1230-1232). The following odd cycle reuses that cache, so the wrong state stays up for one full device cycle (~30 s). The advisor maps this state to reason `manual_override`, counts the device as active and returns the headline `running`. The same thing affects `sensor.aurum_{slug}`, which records a 'manual_override' blip in history after every AURUM turn-off, and `binary_sensor.aurum_{slug}_active`. Related lag in the other direction: after a cheap-grid start, `cheap_grid_active` stays False for the first ~30 s because it also reads the stale switch state. Tests miss this because `MockHass.turn_off` changes the state synchronously.

**Fehlerszenario:** Reproduced with a MockHass whose turn_on/turn_off take effect after the cycle, like a real plug. Pool (solar_only, 1000 W) running on surplus; at 12:40 the surplus drops to -1500 W and stays below the off threshold for debounce_off → AURUM sheds it. Published for 12:40:00-12:40:30: state 'manual_override', advisor decision 'running', reason 'manual_override'. The panel shows 'Devices running · 1/1 active' and '→ manual override' just after AURUM switched the device off itself. An automation triggered on `sensor.aurum_pool` = 'manual_override' fires on every AURUM shed.

**Fix-Vorschlag:** Do not derive 'manual_override' from `is_on and not managed_on` on the cycle where AURUM issued the command. Either publish the commanded state (track `dev['_commanded_state']` plus a timestamp from `_turn_on`/`_turn_off` and prefer it for one or two cycles), or require `last_off` to be older than a grace period (e.g. 2 × update_interval) before calling an on-but-unmanaged device 'manual_override'. Add a test with a deferred-switch MockHass.

**Beleg (Verifier):** - custom_components/aurum/hass_bridge.py:63-69: `turn_off` uses `self._hass.services.call(domain, "turn_off", {...}, blocking=False)`, which returns before the state changes on network plugs.
- custom_components/aurum/modules/devices.py:1141-1148: `_turn_off` calls `hass.turn_off`, then sets `dev["managed_on"] = False`.
- custom_components/aurum/modules/devices.py:519-524 (shedding) and 262-265 (battery_charging emergency): `_turn_off` is followed directly by `_publish_device_states` in the same executor job.
- custom_components/aurum/modules/devices.py:1223, 1230-1232: `is_on = self._is_device_on(dev)` and `if not dev["managed_on"]: state = "manual_override"`.
- custom_components/aurum/coordinator.py:255-276: devices update only on even cycles; odd cycles reuse `_cached_device_states`.
- custom_components/aurum/const.py:49 and 148: `DEFAULT_UPDATE_INTERVAL = 15`; `DEVICE_ACTIVE_STATES = …

### 32. [MEDIUM] Disabling an SD device mid-program leaves sd_state='running': the advisor reports it as running, and re-enabling sends a false 'finished' notification and clears Must-run-today
`custom_components/aurum/modules/devices.py:287` · advisor-panel · bug · Verdict: confirmed

**Beschreibung:** The disable branch in `DeviceManager.update()` calls `_turn_off(..., 'device_disabled')` and `continue`s, but never resets the startup-detection state machine. An SD device that was RUNNING stays `sd_state='running'` for as long as it is disabled. `_publish_device_states` uses sd_state as the authoritative state, so the device is published as 'running'. The advisor checks `state in DEVICE_ACTIVE_STATES` before it checks `disabled`, so it counts the device as active (reason 'running', headline 'Devices running'). When the disable switch is cleared, the RUNNING branch runs with `actual_power=0`. After `sd_finish_time` it takes the smart_finish path: it sends '✅ … finished! Runtime: N min' and calls `_reset_muss_heute()`, even though the program was interrupted, not finished.

**Fehlerszenario:** Simulated: washing machine with SD, RUNNING for 30 min on surplus. The user presses 'Off' in the panel. Switch goes off; advisor shows decision 'running', devices_on 1/1, reason 'running'. The panel headline says 'Devices running · 1/1 active' while the card badge says 'off'. Muss-heute is then switched ON and the device re-enabled → 10 min later a '✅ Wash finished! Runtime: 45 min (smart_finish)' notification arrives and `switch.aurum_wash_muss_heute` is turned off, so the deadline force-start that should finish the interrupted wash is silently dropped.

**Fix-Vorschlag:** In the disable branch, when `startup_detection` is on and `sd_state` is RUNNING, WAITING or DETECTED, call `_sd_reset(dev)` without the finish notification or muss_heute reset (or set a dedicated 'disabled' sd state). In the advisor, evaluate `disabled` before the active-state reasons whenever the device is physically off, or publish `state='off'` for disabled SD devices.

**Beleg (Verifier):** Code path:
- custom_components/aurum/modules/devices.py:276: `actual_power = self._get_device_power(dev) if was_on else 0`
- devices.py:287-295: the disable branch calls `_turn_off` and then `continue`; no `_sd_reset` call.
- devices.py:1141-1159: `_turn_off` leaves the sd_* fields unchanged and clears `_scheduling_reason` and `force_started`.
- devices.py:951-996: in the RUNNING branch, runtime_s is measured from the old sd_running_since, the smart_finish/max_expired check runs, and then the `sd_finished` notify and `_reset_muss_heute(dev)` run. The branch never turns the switch on.
- devices.py:1228-1229: SD devices publish `state = dev["sd_state"]`.
- modules/advisor.py:132-143: the active-state branch returns 'running' before the `disabled` check at :147. advisor.py:93 counts the device in devices_on.
- frontend/aurum-panel.js:655-659: the badge is overridden to 'off' when disabled.  …

### 33. [MEDIUM] 'program_done' reason (and status 'done') is documented but never produced, so the README's 'washing machine finished' automation never fires
`custom_components/aurum/modules/advisor.py:152` · advisor-panel · docs-mismatch · Verdict: confirmed

**Beschreibung:** The advisor maps `sd_state == SD_STATE_DONE` to `program_done`, and the README documents `program_done` ('Done for today', line 356), the status-sensor state 'done' (line 288), and an automation condition `... first == 'program_done'` (lines 389-393). Nothing in devices.py ever assigns `sd_state = 'done'`. On smart_finish or max_runtime the state machine calls `_sd_reset()`, which goes straight back to STANDBY, and the advisor then reports `program_standby` ('waiting for program start'). The 'done' checks in binary_sensor.py and coordinator.py are dead code for the same reason. test_advisor.py only covers this path with a hand-made `sd_state: 'done'` input.

**Fehlerszenario:** A user copies the README condition `{{ state_attr('sensor.aurum_current_decision','devices') | selectattr('slug','eq','washing_machine') | map(attribute='reason') | first == 'program_done' }}`. The washer finishes at 14:30 (smart_finish), the reason becomes 'program_standby', the condition is never true, and the 'laundry done' automation never runs.

**Fix-Vorschlag:** Either add a real DONE state (set `sd_state='done'` after finish, treat DONE like STANDBY for detection so the next program start still works, and clear it at daily reset), or remove `program_done`/'done' from the advisor, README, binary_sensor and coordinator. In the second case, give users a reliable signal instead, e.g. a `last_program_finished` attribute or an event fired on finish.

**Beleg (Verifier):** custom_components/aurum/modules/advisor.py:151-153 — `if sd_state == SD_STATE_DONE: return "program_done"`. This is the only consumer of SD_STATE_DONE, which is defined at const.py:155.
custom_components/aurum/modules/devices.py:980-996 — on smart_finish or max_runtime it calls `self._sd_reset(dev)`, and devices.py:1003-1005 `_sd_reset` sets `dev["sd_state"] = SD_STATE_STANDBY`. Nothing in the package writes "done" (searched every sd_state assignment: devices.py:807, 832, 856, 896, 924, 1005 and persistence.py:172, 181, 185).
devices.py:1228-1229 — the published state of a startup-detection device is sd_state, so after a finish it is 'standby' and never 'done'.
Dead checks: binary_sensor.py:64 `state not in ("off", "done", "standby")`, coordinator.py:275, frontend/aurum-panel.js:104 and :146 (reason_program_done labels).
Tests: tests/test_devices.py:384 and :398 assert SD_STATE_STANDBY a …

### 34. [MEDIUM] Panel ignores `narrow` and has no menu button, so on phones the HA sidebar cannot be opened from the AURUM panel
`custom_components/aurum/frontend/aurum-panel.js:170` · advisor-panel · ux · Verdict: confirmed

**Beschreibung:** `set narrow(_v) {}` throws the value away, and the header (lines 275-280) is plain text. In narrow layouts (phones, HA Companion app, windows < ~870 px) HA hides the sidebar in a modal drawer that only opens when the current panel's toolbar fires `hass-toggle-menu` (the `ha-menu-button` that built-in panels and custom panels such as Alarmo or KNX render). A custom panel without it leaves the user with no on-screen way to reach other dashboards.

**Fehlerszenario:** A user opens the AURUM sidebar entry in the HA Companion app on an iPhone. The panel renders, but there is no hamburger button, and iOS has no hardware back button, so the user cannot get back to the sidebar or other dashboards without restarting the app or editing the URL.

**Fix-Vorschlag:** Store `narrow` (and include it in the build signature). When it is true, render a header button that dispatches `new Event('hass-toggle-menu', {bubbles: true, composed: true})`, or embed `<ha-menu-button>` with `.hass` and `.narrow` set.

**Beleg (Verifier):** - custom_components/aurum/frontend/aurum-panel.js:170: `set narrow(_v) {}`, the only place `narrow` is mentioned.
- custom_components/aurum/frontend/aurum-panel.js:274-280: the header is `<div class="aurum-title">☀️ AURUM</div><div class="aurum-sub">Solar Surplus Optimizer</div>`, with no button.
- custom_components/aurum/frontend/aurum-panel.js:741-743: header CSS for text only.
- A grep of the panel for menu, toggle or hass-toggle-menu finds nothing.
- custom_components/aurum/__init__.py:63-79: `async_register_built_in_panel(component_name="custom", ..., "_panel_custom": {"name": "aurum-panel", "embed_iframe": False, ...})`.
- HA frontend dev, src/panels/custom/ha-panel-custom.ts: when not embedded in an iframe, it calls `createCustomPanelElement(config)` and `this.appendChild(element)`, renders no toolbar or ha-menu-button, and passes `narrow: this.narrow` to the panel.
- HA frontend  …

### 35. [MEDIUM] Deadline force-start before the deadline re-fires every device cycle when the switch does not report 'on': ON-command and push storm, phantom allocation, and AURUM fights a user who switches the device off
`custom_components/aurum/modules/devices.py:1200` · actuator-feedback · bug · Verdict: confirmed

**Beschreibung:** In _deadline_urgent, the force_started guard only exists in the post-deadline branch (1192-1198). Inside the pre-deadline window (1200-1204) it returns True on every call. update() (401-411) reaches that branch whenever was_on is False. So any time the switch is not reported 'on' (plug offline/unavailable, command lost or ignored, user or another automation switched it off, cloud switch reporting slower than one device cycle), AURUM calls _turn_on again, sends a push (_notify has no throttle), adds an action-log row, bumps total_switches/_switch_times, and adds nominal_power to newly_allocated in every cycle. The device was never confirmed on, so that phantom allocation hides the real surplus from every lower-priority device for the whole window. The deadline path also skips min_off_time, so a compressor/relay device the user just switched off is re-energised within 30 s. Nothing checks that the earlier command took effect.

**Fehlerszenario:** Verified with MockHass subclasses (scratchpad audit/af_deadline_user_off.py, af_gap_fixed.py). (1) Dryer 2000 W, muss_heute ON, deadline 18:00, estimated_runtime 90, plug offline (state 'unavailable'): 120 ON commands and 120 mobile pushes per hour from 16:25 until 18:00. (2) Same dryer with a working plug, force-started at 16:25; the user presses its off button at 16:40 and keeps pressing for 5 min: AURUM re-sends ON in every cycle (16:40:00, 16:40:30, ... 16:44:30), 11 pushes in 5 min. (3) A cloud switch whose state arrives 45 s after the command: 2 ON commands and 2 'started by deadline' pushes per force start. (4) Offline 1500 W must-run plug (prio 90) plus a 1000 W device (prio 10) with 2000 W of real PV export: the small device never starts during the whole window, so the 2000 W is exported.

**Fix-Vorschlag:** Track the commanded state: after _turn_on, store dev['_cmd'] = ('on', now). Count nominal power in newly_allocated only while that command is less than ~2 device cycles old. If the switch has not reported 'on' by then, record a failure and retry with exponential backoff, and push at most once per tag. Treat an observed on→off transition that AURUM did not command as a user stop: set a flag that suppresses deadline re-forcing until muss_heute is toggled again or the next day, or at least apply min_off_time. Apply the force_started / 'already attempted' guard in the pre-deadline branch as well.

**Beleg (Verifier):** Code:
- custom_components/aurum/modules/devices.py:1192-1198 — the `force_started` guard exists only in the branch after the deadline.
- devices.py:1200-1204 — before the deadline it returns `time_remaining <= runtime+300` with no earlier-attempt guard.
- devices.py:392-411 — the `was_on=False` branch calls `_turn_on`, sets `newly_allocated += nominal_power` and calls `_notify` every device cycle.
- devices.py:1108-1111 — `_is_device_on` is `state == 'on'`, so 'unavailable' is treated as off.
- devices.py:1375-1410 — `_notify` has no throttle (`throttle_key` is unused).
- coordinator.py:255 — the device loop runs every 2nd cycle (`update_interval` default 15 s, so 30 s).
- tests/test_devices.py:742-782 — the TestDeadline tests cover only the `_deadline_urgent` return values, not repeated firing.

Repro script: <scratch>/vfy_deadline_refire.py

Output:
--- 1) dead plug 16:00-18:10
ON comm …

### 36. [MEDIUM] Startup detection: an unavailable (or externally switched-off) plug during RUNNING is read as 0 W, so the program is falsely 'finished', muss_heute is cleared, and the still-running program is cut when the plug reconnects
`custom_components/aurum/modules/devices.py:276` · actuator-feedback · bug · Verdict: confirmed

**Beschreibung:** update() sets actual_power = 0 whenever the switch is not 'on' (line 276), and get_state_safe maps 'unavailable'/'unknown' to not-on. In SD RUNNING (951-996) that 0 W counts as 'below sd_finish_power'. After sd_min_runtime plus sd_finish_time, smart_finish fires: _sd_reset, push '✅ finished!', and _reset_muss_heute. The state machine then goes to STANDBY, which calls hass.turn_on in every cycle while the plug is offline. When the plug reconnects with the relay still on and the program still drawing power, STANDBY detects it as a new program and DETECTED calls _turn_off (sd_pause_program), cutting power mid-program. The WAITING deadline start has the same problem (890-906). It enters RUNNING after an unconfirmed _turn_on, so an offline plug is reported 'started by deadline' and then 'finished' 15 min later, and muss_heute (the deadline) is consumed although the appliance never ran. The tail (STANDBY re-detecting and cutting a running program) is the same mechanism as the already-reported max_runtime finding, but the trigger here (switch availability) is different and not covered.

**Fehlerszenario:** Verified (audit/af_sd_offline.py). Washer with startup_detection, power sensor on the same Shelly, muss_heute ON, deadline 18:00. A: sunny day, the program starts on PV at 10:07, Shelly WiFi drops 10:15-10:35 (relay stays on locally, washer keeps running). At 10:25 AURUM sends '✅ washer finished! Runtime: 18 min' and switches muss_heute OFF. At 10:35:30 the plug reconnects, the running program is 'detected' and AURUM switches the plug OFF mid-wash. 21 ON commands were sent to the offline plug. B: no PV, program paused in WAITING, plug goes offline at 15:50. The deadline start at 15:55 pushes 'started by deadline', and at 16:10 pushes '✅ finished! Runtime: 15 min' and clears muss_heute. The washer never ran and the deadline no longer applies.

**Fix-Vorschlag:** In the SD machine, distinguish 'switch unavailable/unknown' from 'off'. While the switch (or the power sensor) is unavailable, freeze RUNNING: do not sample, do not advance sd_power_below_since, do not finish. Enter RUNNING only once the switch has been observed 'on' after the start command, and retry or back off otherwise. If the plug is seen 'off' without AURUM having commanded it, end with an 'aborted' outcome: no 'finished' push, keep muss_heute, and do not immediately turn the plug back on.

**Beleg (Verifier):** - custom_components/aurum/modules/devices.py:274-276: `was_on = self._is_device_on(dev)` and `actual_power = self._get_device_power(dev) if was_on else 0`.
- devices.py:1108-1111 together with modules/helpers.py:25-30: 'unavailable' and 'unknown' map to None, so the switch is treated as not on.
- devices.py:966-976: below-finish timer, then devices.py:978-995: `_sd_reset`, `sd_finished` notify, `_reset_muss_heute`.
- devices.py:815-819: STANDBY calls `hass.turn_on` every cycle while not on.
- devices.py:822-843 then 846-863: re-detection after 5 s (`sd_detection_time` default, const.py:136), then DETECTED calls `_turn_off` "sd_pause_program".
- devices.py:890-906: deadline start sets RUNNING without confirming the switch is on.
- devices.py:1113-1118: an unavailable power sensor falls back to `nominal_power`, so a sensor-only outage is harmless.
- Defaults: const.py:139 `DEFAULT_DEV_SD_F …

### 37. [MEDIUM] External switch-off is never reconciled: last_off, managed_on, _scheduling_reason and force_started stay stale (min_off_time ignored, cheap-grid restarts within 30 s, later manual starts are mis-handled)
`custom_components/aurum/modules/devices.py:311` · actuator-feedback · bug · Verdict: confirmed

**Beschreibung:** Only _turn_off updates last_off and clears managed_on, _scheduling_reason, force_started and on_since. When the device goes off from outside (user, appliance or plug protection, another automation, input_boolean reset), update() just sees was_on=False and none of this state changes. Consequences: (a) the min_off_time check in _should_turn_on (611-614) uses the stale last_off, so compressor/relay protection is not enforced after an external off. (b) For price-granted devices there is no debounce, so AURUM restarts the device in the very next cycle. (c) When the user later starts the device by hand, it inherits the stale managed_on, the cheap_grid reason and the old on_since. The min_on_time check (679-682) is bypassed and 'price_no_longer_cheap' kills the manual run at once, which is exactly what the comment in _turn_off (1153-1156) says it wants to prevent. (d) A stale force_started=True makes a later manual run immune to SOC and surplus shedding until midnight, and the advisor shows 'forced_deadline'. This is the external-on variant that the audit #4 fix (_turn_on and daily reset clear force_started) did not cover. It is not a regression of that fix. The runtime/energy inflation from the stale on_since/_runtime_tick is already reported and not repeated here.

**Fehlerszenario:** Verified (audit/af_external_off.py, af_force_residual.py). F1: a cheap_grid boiler with min_off_time 1800 s runs on a cheap night price; the user switches it off at 01:00 and AURUM switches it back ON in the 01:00 cycle. F3: a heat pump with min_off_time 1200 s and surplus present is switched off externally at 11:15; AURUM restarts it at 11:17. F2: the cheap_grid boiler is switched off by the user at 05:30 and the price turns expensive. The user switches it on by hand at 06:00 and AURUM switches it off in the same cycle, instead of after min_on_time + debounce_off (20 min) as for any manual start. Force residual: a dryer is deadline-forced at 16:55, switched off by the user at 18:05 and on again by hand at 20:00 with SOC 35 % (below its soc_threshold of 40) and 2000 W of import. It runs until 22:00+ without being shed, and the advisor reason is 'forced_deadline'.

**Fix-Vorschlag:** Each cycle, compare the observed state with dev['_cached_on'] from the previous cycle (or with the commanded state). On an on→off transition that AURUM did not command, apply the same bookkeeping as _turn_off without sending a command: set last_off=now and clear managed_on, on_since, _runtime_tick, _scheduling_reason and force_started. Optionally add a 'user_stopped' hold-off so price or deadline grants do not restart the device immediately.

**Beleg (Verifier):** Code: custom_components/aurum/modules/devices.py
- 274-275: was_on is only cached; nothing compares it with the previous cycle.
- 311-313: on_since is re-anchored only when managed_on is False, so the old managed_on=True skips it.
- 611-614: min_off_time is measured from last_off, which only _turn_off sets (1146).
- 675: if force_started is set, _should_turn_off returns None.
- 679-682: the min_on_time guard uses on_since.
- 690-693: 'price_no_longer_cheap' depends on _scheduling_reason.
- 1034: _preempt_for_sd skips devices with managed_on False.
- 1124-1157: the bookkeeping in _turn_on and _turn_off.
- 1430-1437: the daily reset clears only the counters, _scheduling_reason and force_started.
Other files:
- persistence.py:196-213: switch state is checked against the saved state only on restore at startup.
- No async_track_state_change or state_changed listener exists anywhere in custom_ …

### 38. [MEDIUM] Offline or unavailable switch is treated as 'off' and re-commanded on the surplus path: phantom allocations reset lower-priority devices' debounce (starvation of 20-60+ min), switch penalty inflated, and the advisor shows 'waiting_surplus'
`custom_components/aurum/modules/devices.py:1108` · actuator-feedback · robustness · Verdict: confirmed

**Beschreibung:** _is_device_on maps 'unavailable'/'unknown' to False, and nothing tracks availability. On the surplus path (450-466), an offline plug passes debounce and _turn_on, newly_allocated += nominal_power, and in the same cycle every lower-priority device gets turnon_excess < needed. Their excess_since is reset at 471-472, which restarts their debounce. Because _turn_on also resets the offline device's excess_since, this repeats every debounce_on×penalty. Each phantom command is appended to _switch_times and counted in total_switches, pushing the penalty to 3.0, which slows debounce_on and debounce_off ×3 for an hour after the plug comes back. SD STANDBY (813-816) calls hass.turn_on directly in every cycle while the plug is offline. _publish_device_states and the advisor show the offline device as 'off' / 'waiting_surplus' with plenty of surplus, so the user cannot see that the plug is unreachable. Note: the earlier gap_probe4.py 'full hour' result was an artefact of a mock in which the lower-priority switch was dead too. The real figures are below.

**Fehlerszenario:** Verified (audit/af_offline_start.py, af_offline_advisor.py). Offline 1500 W plug (prio 90) and a 1000 W device (prio 10) with 2000 W of steady export. With equal debounce_on (300 s), the small device first starts after 21.5 min. With debounce_on 600 s on the small device, it starts only after 63.5 min. The plug gets 7 phantom ON commands and its penalty reaches 3.0. During all this the advisor reports both devices as 'waiting_surplus' and the decision 'waiting'.

**Fix-Vorschlag:** If the switch state is 'unavailable'/'unknown' (or the entity is missing), skip the device: no command, no allocation, no runtime. Publish state 'unavailable' with advisor reason 'switch_unavailable'. Do not append unconfirmed commands to _switch_times or total_switches. In SD STANDBY, do not re-send turn_on while the switch is unavailable.

**Beleg (Verifier):** Code references:
- `custom_components/aurum/modules/devices.py:1108-1111`: `_is_device_on` returns `state == "on"` via `get_state_safe`. `custom_components/aurum/modules/helpers.py:25-30` maps 'unavailable', 'unknown' and None to the default, None.
- `devices.py:274-276`: `was_on` is False, so no runtime is accumulated and the device goes to the turn-on branch.
- `devices.py:454-466`: `_turn_on` followed by `newly_allocated += nominal_power`.
- `devices.py:467-472`: a lower-priority device with `turnon_excess < needed` gets `excess_since = None`.
- `devices.py:437/446`: the budget cap also resets `excess_since`.
- `devices.py:1120-1139`: `_turn_on` increments `total_switches`, appends to `_switch_times` and clears `excess_since`.
- `devices.py:774-790`: penalty is capped at 3.0.
- `devices.py:811-816`: SD STANDBY calls `hass.turn_on` every cycle when the switch does not read 'on'.
- `dev …

### 39. [MEDIUM] _preempt_for_sd has no settling memory: with ≥ one device cycle of switch or grid-sensor latency it preempts an extra victim on each following cycle
`custom_components/aurum/modules/devices.py:1024` · actuator-feedback · robustness · Verdict: confirmed

**Beschreibung:** WAITING calls _preempt_for_sd in every cycle while turnon_excess < needed (942-948), and computes the deficit from the current measured excess. Nothing records that power was freed in the previous cycle. If the victim's switch state, or the grid sensor behind excess_for_devices, has not caught up within one device cycle (30 s by default; cloud switches and inverter integrations polled every 30-60 s are common), the next cycle still sees the old deficit. The first victim is no longer a candidate (managed_on=False), so the next lower-priority device is preempted as well, with another push. The over-shed devices then restart in an arbitrary order. This is distinct from the already-reported 'preempts even when freeing cannot make room': here the first preemption was sufficient.

**Fehlerszenario:** Verified (audit/af_preempt_lag.py). Washer (SD, prio 80, 2000 W) is waiting. Loads A (prio 10, 800 W) and B (prio 20, 800 W) are on, measured surplus is 1700 W, and 2200 W are needed, so shedding A alone covers the deficit. With immediate state updates, only A is preempted. With 45 s state latency, A is preempted at 12:01:30 and B at 12:02:00 as well. At 12:07:30 A (lower priority) is restarted while B stays off.

**Fix-Vorschlag:** After a preemption, store dev['_preempt_pending'] = (freed_w, now). Until the measured excess reflects it, or for a settling time of e.g. max(debounce_off, 2 device cycles), add the pending freed power to turnon_excess and skip further preemption. Only preempt devices whose switch has confirmed their last command.

**Beleg (Verifier):** Code:
- custom_components/aurum/modules/devices.py:910-911: `needed = nominal + hysteresis_on`; the start check is `turnon_excess >= needed`.
- devices.py:940-948: the else branch calls `_preempt_for_sd` on every cycle and keeps no state.
- devices.py:1024: `deficit = needed_w - turnon_excess`, with no adjustment for power freed earlier.
- devices.py:1032-1046: the candidate filter (`_cached_on`, `managed_on`, `interruptible`, priority, `min_on_time`) only excludes the previous victim.
- devices.py:1141-1158: `_turn_off` sets `managed_on=False` and records nothing about pending freed power.
- devices.py:221, 371: the SD turn-on excess is `excess_for_devices`, the EMA value.
- modules/energy.py: `excess = -grid_ema_asym` (alpha_down=0.7, alpha_up=0.2).
- coordinator.py: energy updates every 15 s; `devices.update` runs only when `cycle % 2 == 0`.
- hass_bridge.py:55-69: `turn_on` / `turn_o …

### 40. [MEDIUM] Grid sensor unavailable while the battery charges from the grid: legacy surplus turns the charge power into phantom surplus and starts devices on grid
`custom_components/aurum/modules/energy.py:117` · input-failure-matrix · bug · Verdict: confirmed

**Beschreibung:** After the startup grace, an unavailable or unknown grid sensor is read as 0 W (line 43). With battery power sensors configured and battery_priority off, which is the default, the surplus is computed as -grid - battery_power_net (117-120). With grid=0 that is just +charge_power. Whenever the battery is charging from the grid, that charge power is offered to devices as solar surplus. Device starts do not change the dead reading, so lower-priority devices start on the following cycles as well. The already-reported coordinator.py:170 finding is about running devices not being shed. This one is different: AURUM actively starts devices that were off.

**Fehlerszenario:** Tibber setup, 02:00, the inverter force-charges the battery from the grid at 3 kW on a cheap hour. House load is 500 W, so the meter reads +3500 W. SOC is 50 %, no pv_forecast_entity is set, and there are two solar_only devices (heater 2000 W, pool 800 W). The Shelly 3EM drops off Wi-Fi and the grid sensor goes 'unavailable'. excess_for_devices jumps to +3000 W. The heater starts at 02:08 and the pool at 02:13, so the real import is 6.3 kW. AURUM's grid sensor shows 0 W, its excess sensor shows +3000 W, and nothing is shed while the outage lasts (see scratchpad/audit/ifm/a_grid_unavail_gridcharge.py). With a budget configured, the night budget of 0 W blocks regular devices only while SOC < target. Once SOC >= target the budget returns None and the start goes through. SD devices ignore the budget entirely, so a paused washing machine also starts on grid.

**Fix-Vorschlag:** Do not substitute 0 for a missing grid reading. In EnergyManager.update, track grid availability. When it is unavailable or stale, hold the last value for a short tolerance (for example 2-3 cycles), then publish excess/excess_raw as None or set shared['inputs_ok']=False. DeviceManager.update should then skip all surplus-based starts while still applying the price, deadline and min_soc paths. Never fold battery_power_net into the surplus when the grid term is unknown.

**Beleg (Verifier):** Code:
- custom_components/aurum/modules/energy.py:43 `grid_raw = get_float(self.hass, self.grid_power_entity, 0)`
- energy.py:111-120: legacy surplus `-self._grid_ema_asym - battery_power_net` and `-grid_raw - battery_power_net`
- modules/helpers.py:17: unavailable or unknown returns the default
- coordinator.py: _entities_ready() is only consulted when `startup_mode = self.cycle <= self.STARTUP_GRACE_CYCLES`
- modules/battery.py:56-59: excess is passed through in low_soc and normal modes
- modules/devices.py (_should_turn_on): `if battery_soc >= 0 and battery_soc < soc_threshold: eff_excess = available_grid_excess else: eff_excess = available_excess`
- const.py:125: DEFAULT_DEV_SOC_THRESHOLD = 20
- config_flow.py:272-273: battery_priority defaults to False
- budget.py:262-264: returns None when battery_soc >= target_soc

Repro: the reviewer's script <scratch>/ifm\a_grid_unavail_gridchar …

### 41. [MEDIUM] No staleness check on any input: a frozen grid value breaks the control loop and AURUM starts every device
`custom_components/aurum/modules/helpers.py:16` · input-failure-matrix · robustness · Verdict: confirmed

**Beschreibung:** get_float and HassAccess.get_state only read state.state. last_updated and last_reported are never looked at. AURUM's control loop relies on each started device showing up in the measured grid power: newly_allocated is reset every cycle (devices.py:271), so the next cycle relies on the meter to reflect the devices just started. If the grid sensor freezes on an export value, the loop no longer closes. Each cycle sees the same surplus, starts the next device, and never sheds. Common sources of frozen values are MQTT sensors without expire_after (Shelly/Tasmota/ESPHome/OpenDTU over MQTT), cloud and websocket integrations that keep the last value after a disconnect, and template sensors. The same applies to a frozen battery charge sensor, which adds a constant phantom offset to the legacy surplus.

**Fehlerszenario:** No battery (or battery_priority=True). At 13:00 PV exports 2000 W and the meter then freezes at -2000 W. There are three solar_only devices of 1500 W each. With a live meter only device A starts. With the frozen meter, A starts at 13:05, B at 13:11 and C at 13:16. A later cloud is never seen, so at 14:00 the house imports 4.5 kW while AURUM still shows -2000 W of export (scratchpad/audit/ifm/b_grid_frozen.py). Nothing marks the input as stale, so this continues until the integration recovers or HA restarts.

**Fix-Vorschlag:** Expose a get_age(entity_id) in HassAccess using max(state.last_updated, state.last_reported), available on HA 2024.3+. Treat the grid, battery-power and PV sensors as unavailable when they are older than a configurable timeout (default about 5 min, at least 10 x update_interval). A cheap extra plausibility check: after AURUM starts a device of nominal X W, expect the grid reading to move by about X within a few cycles. If it does not move at all over several starts, suspect a frozen meter and stop starting devices.

**Beleg (Verifier):** - custom_components/aurum/hass_bridge.py:21-35: `get_state` returns only `state.state`; no timestamps are read.
- custom_components/aurum/modules/helpers.py:14-22: `get_float` handles only None, unavailable, unknown and "".
- custom_components/aurum/coordinator.py:155-162: `_entities_ready` checks only for unavailable/unknown, during startup grace.
- custom_components/aurum/modules/energy.py:42 and 116-127: grid_raw becomes excess and excess_raw directly; the legacy mode subtracts `battery_power_net`, so a frozen charge sensor adds a phantom offset.
- custom_components/aurum/modules/devices.py:271: `newly_allocated = 0.0` is reset every cycle.
- custom_components/aurum/modules/devices.py:376-382: turn-off uses `excess_raw - newly_allocated`, so a frozen export never sheds.
- custom_components/aurum/modules/devices.py:432-438: the budget cap is per cycle (`newly_allocated + nominal > devi …

### 42. [MEDIUM] Unavailable device switch is treated as OFF: the deadline force-start re-fires every cycle with a push notification, and the surplus path issues phantom ONs
`custom_components/aurum/modules/devices.py:1200` · input-failure-matrix · robustness · Verdict: confirmed

**Beschreibung:** _is_device_on returns False for an 'unavailable' switch (1108-1111), so AURUM keeps trying to start the device. HA silently skips service calls to unavailable entities. Before the deadline time, _deadline_urgent only checks the time window (1200-1204), not force_started. So every 30 s device cycle calls _turn_on, sets force_started, adds nominal_power to newly_allocated and sends the 'started by deadline (grid power)' persistent notification and mobile push again. In the surplus path the device is 'turned on' every debounce_on x penalty. Each attempt adds to total_switches and _switch_times, so the relay-protection penalty is already 1.5-3x when the plug comes back. The published state is 'off' and the advisor says waiting_surplus. Nothing says the switch is unreachable.

**Fehlerszenario:** Dryer with deadline 18:00, estimated_runtime 90 and muss_heute ON. The smart plug is offline (state 'unavailable') from 16:00. Between 16:25 and 17:00 AURUM sends 70 turn_on commands and 70 push notifications, and keeps going until 18:00 (about 190 pushes). Measured by scratchpad/audit/critic_deadline_dead_plug.py. In the surplus path, a dead 2 kW heater got 3 phantom ONs in 1 h and its switch penalty was raised to 1.5 (scratchpad/audit/ifm/d_switch_unavail.py).

**Fix-Vorschlag:** Treat a switch state of unavailable/unknown/None as 'unknown', not 'off'. Skip control of that device for the cycle: no _turn_on, no allocation, no notification. Publish a distinct state or advisor reason such as 'switch_unavailable'. In _deadline_urgent, also return False when force_started is already True and the start was issued less than N cycles ago.

**Beleg (Verifier):** Code:
- custom_components/aurum/modules/devices.py:1108-1111: `_is_device_on` returns `state == "on"`, where the state comes from `get_state_safe` (helpers.py:25-30 maps 'unavailable' and 'unknown' to None).
- devices.py:274: `was_on = self._is_device_on(dev)`.
- devices.py:401-411: the deadline branch calls `_turn_on`, sets `force_started=True`, does `newly_allocated += nominal_power` and calls `_notify`, with no guard against re-firing.
- devices.py:1192-1204: `force_started` is checked only when `now >= deadline_today`; before the deadline the function returns `time_remaining <= runtime_needed + 300`.
- devices.py:1375-1410: `_notify` has no throttling (`throttle_key` is unused).
- devices.py:1120-1139: `_turn_on` increments `total_switches` and appends to `_switch_times`.
- devices.py:774-790: the switch penalty.
- devices.py:630-632: a cheap_grid grant has no debounce.
- devices.py: …

### 43. [MEDIUM] A 'nan' or 'inf' reading permanently poisons the grid EMAs until HA restarts
`custom_components/aurum/modules/helpers.py:20` · input-failure-matrix · robustness · Verdict: confirmed

**Beschreibung:** get_float accepts any string that float() parses, including 'nan', 'inf' and '-inf'. A single NaN grid sample makes _grid_ema and _grid_ema_asym NaN forever: alpha*x + (1-alpha)*nan stays NaN, and the asymmetric comparison never picks a path that recovers. The turn-on path uses the EMA. In _should_turn_on, 'if eff_excess < needed: return False' is False for NaN, so the check passes and devices start after debounce. Turn-off uses the live raw value and sheds them again. The result is endless on/off cycling on grid power. 'inf' poisons the EMAs the same way. A NaN SOC turns battery protection off (all SOC comparisons are False, so MODE_NORMAL) and is then held by the SOC outage hold.

**Fehlerszenario:** At 20:00 the house imports 400 W from the grid. The grid sensor (MQTT or template without numeric validation, or a Modbus read error) reports 'nan' for one sample. AURUM's excess sensor shows 'nan' from then on, and two 1500 W solar_only devices are started 16 times and shed 14 times over the next 4 h, all on grid (scratchpad/audit/ifm/g_nan.py). This continues until a reload or restart.

**Fix-Vorschlag:** In get_float, return the default unless math.isfinite(value). Optionally, have ema_update / ema_update_asymmetric reset to the raw value when the old EMA is not finite.

**Beleg (Verifier):** custom_components/aurum/modules/helpers.py:14-22 (get_float, no isfinite check); helpers.py:33-52 (ema_update / ema_update_asymmetric: NaN or inf never recovers); modules/energy.py:43-57 (EMAs updated from grid_raw; the only owner of the state, not persisted); energy.py:118,126 (excess = -_grid_ema_asym); modules/battery.py:36-47 (NaN SOC fails every comparison, so MODE_NORMAL); modules/devices.py:235 (grid_excess is NaN as well); devices.py:652 (`if eff_excess < needed` is False for NaN, so a start goes ahead); devices.py:433-438 (budget cap blocks this at night only when the budget module is active); hass_bridge.py:21-36 (raw state string passed through).

Repro: <scratch>/verify_nan\v_nan.py
get_float: 'nan'->nan, 'NaN'->nan, 'inf'->inf, '-inf'->-inf, 'Infinity'->inf, '1e999'->inf
control (no bad sample): ema_asym=400.0 excess=-400.0 ON=0 OFF=0
nan, no budget: ema_asym=nan excess=nan  …

### 44. [MEDIUM] Nothing tells the user that AURUM is running blind: hub sensors publish 0 W, held SOC looks live, no repairs issue or advisor code
`custom_components/aurum/sensor.py:369` · input-failure-matrix · ha-integration · Verdict: confirmed

**Beschreibung:** AurumGridPowerSensor, AurumPVPowerSensor, the battery charge/discharge sensors and House Consumption publish data.get(..., 0). The shared values have already had 0 substituted for unavailable inputs, so they show a plausible 0 W instead of 'unavailable'. The battery SOC sensor shows the held value as if it were live. The Budget sensor shows the same '–' for 'forecast unavailable, cap disabled' as for 'SOC above target'. The advisor has no input-health code and reports running_solar or waiting as usual. Nothing in the integration creates a repairs issue or persistent notification for a missing, renamed, unavailable or stale source entity. The coordinator only checks grid readiness during the 6 startup cycles (_entities_ready). Diagnostics, which the README recommends for bug reports, also show the substituted 0 rather than the source entity's real state.

**Fehlerszenario:** The user renames their meter entity, or the Shelly 3EM dies. From cycle 7 on, AURUM reads grid=0 permanently. The AURUM panel shows Grid 0 W, Excess 0 W (or +charge W, see the grid-charging finding) and 'Waiting for surplus'. The user only notices when the electricity bill or the Energy Dashboard shows devices running on grid for days.

**Fix-Vorschlag:** Track per-input health (configured, missing, unavailable, stale) in EnergyManager and publish it in shared. Mark the hub mirror sensors unavailable (via _AttrAvailabilityMixin) when their source is. Add an advisor decision such as 'input_unavailable' with the affected entity in its attributes. After N minutes, raise a repairs issue with homeassistant.helpers.issue_registry.async_create_issue, and clear it when the input recovers. Include the raw source states and their ages in diagnostics.

**Beleg (Verifier):** custom_components/aurum/modules/helpers.py:14-22 (get_float returns the default on None/unavailable/unknown); custom_components/aurum/modules/energy.py:42 (grid_raw default 0), :59-62 (PV default 0), :66-82 (SOC held or 0.0, DEBUG log only), :91-97 (battery charge/discharge default 0); custom_components/aurum/hass_bridge.py:21-24 (a missing entity becomes None); custom_components/aurum/coordinator.py:155-163 and 168-180 (_entities_ready only checked while cycle <= 6); custom_components/aurum/sensor.py:352-388 (Grid and PV mirror sensors use data.get(...,0) without the availability mixin), :421-435 (SOC sensor available whenever soc >= 0), :438-475 (charge/discharge with default 0), :515-556 (Budget '–' for every None), :621-655 (House Consumption built from the 0 defaults); custom_components/aurum/modules/advisor.py:37-56 (no input-health decision code); custom_components/aurum/diagnosti …

### 45. [MEDIUM] Device power sensor unit is never validated: a kW sensor sheds all candidates at once, disables startup detection and reads energy 1000x too low
`custom_components/aurum/modules/devices.py:498` · input-failure-matrix · bug · Verdict: confirmed

**Beschreibung:** _validate_energy_sources only checks the hub entities. add_device and edit_device do not validate power_entity at all (config_flow.py:312, no unit or numeric check). _get_device_power returns the raw value as W. It is used by shedding (freed power, 498), SD preemption, SD detection and smart-finish, energy_today_wh and the per-device power sensor. With a kW sensor (several EV-charger and heat-pump integrations report kW), each victim 'frees' a few W, so the greedy shed loop never covers the deficit and selects every candidate. An unavailable power sensor falls back to nominal_power, which inflates energy_today_wh for modulating loads; the SD phantom effect of this fallback is already reported.

**Fehlerszenario:** Three 1500 W devices each have a power sensor in kW reading '1.5'. A small cloud causes a 500 W deficit. With W sensors AURUM sheds only C. With kW sensors it sheds A, B and C in the same cycle, then restarts them after min_off and debounce (scratchpad/audit/ifm/e_devpower_kw.py). For an SD washing machine with a kW plug sensor, 2.0 'W' never exceeds sd_power_threshold=5, so the program is never detected or paused.

**Fix-Vorschlag:** Validate power_entity (and condition_entity) in add_device and edit_device with the same _check_power logic. Better still, convert by unit at runtime: read unit_of_measurement and scale kW, MW and mW to W in one helper used for all power inputs, which also fixes the known hub kW issue.

**Beleg (Verifier):** Code:
- custom_components/aurum/modules/devices.py:1113-1118: `_get_device_power` returns the raw `get_float` value.
- custom_components/aurum/modules/helpers.py:14-22: `get_float` is a plain `float()`.
- devices.py:276/282/1214: energy accounting.
- devices.py:495-500: greedy shed with `freed += power_w`.
- devices.py:1047-1064: SD preempt.
- devices.py:822: SD detection, `actual_power > dev["sd_power_threshold"]` (default 5, devices.py:176).
- devices.py:953/969: SD running samples and smart-finish.
- config_flow.py:110-111: `_SENSOR` selector with no device_class.
- config_flow.py:311-314: `power_entity` field.
- config_flow.py:669-743: device steps validate only the name.
- config_flow.py:121: `_VALID_POWER_UNITS` includes "kW", so `_check_power` would not reject kW.

Repro 1, reviewer script `<scratch>/ifm\e_devpower_kw.py`:
  device power in W: still on ['A', 'B']; OFF actions ['sw …

### 46. [MEDIUM] The fixed 19:00 'sunset' fallback runs for every user without hourly forecast attributes and gets the budget badly wrong in both seasons, with no warning
`custom_components/aurum/modules/budget.py:577` · provider-data-contracts · bug · Verdict: confirmed

**Beschreibung:** `_hours_until_sunset()` falls back to a hard-coded 19:00 whenever `_get_hourly_forecast()` returns None. That happens in three cases. (a) `pv_forecast_today_entity` is left empty. The config UI says 'Can be left empty' and the budget module only needs `pv_forecast_entity`. (b) The user runs HA core Forecast.Solar. I checked its sensor.py: no sensor has `extra_state_attributes`, so the fallback is permanent. (c) The user picks an entity without detailed attributes, for example Solcast 'Forecast Remaining Today' or Open-Meteo `energy_production_today_remaining`. Only `energy_production_today` carries `watts`/`wh_period`. The broad `except Exception: return None` in `_get_hourly_forecast()` (line 862) also lands here silently. Nothing is logged, `budget_info.hours_remaining` is not exposed anywhere, and `_validate_energy_sources` never checks the hourly entity. The user therefore never learns that the fallback is active. Because `budget_w = budget_wh / hours_remaining` and the house-load estimate is `500 W × hours_remaining`, the fixed end time distorts the budget across the whole afternoon, not just after 19:00. In summer (real production until about 21:00–21:30 CEST) the budget is far too high, then drops to 0 'after_sunset' at 19:00 while PV still delivers 1–2 kW. In winter (sunset about 16:00) up to 3 h of after-dark house load are charged against PV, so the budget is 0 all day.

**Fehlerszenario:** Simulated with the real HassAccess bridge and BudgetManager, core Forecast.Solar, no attributes, 10 kWh battery, target 80 %. June 21, SOC 77 %. With fallback vs. with real hourly data: 17:00 2538 W vs 1019 W; 18:00 2685 W vs 562 W; 18:45 6120 W vs 236 W; 19:00 0 W 'after_sunset' vs 115 W 'budget_ok'. Same day at SOC 70 %: 10:00 4347 W vs 3466 W; 15:00 3458 W vs 2138 W. So the cap allows 1.3–25× the load the budget is meant to allow on exactly the days where SOC is below target, and the battery misses its target and imports at night. Dec 21, SOC 60 %: at 10:00 the fallback gives 0 W ('budget_exhausted', 9 h × 500 W house load subtracted) where the real 5 h window gives 256 W, so PV-surplus starts are blocked all winter day.

**Fix-Vorschlag:** Replace the constant with the real solar day. Read `sun.sun` (`next_setting`, from default_config) and convert it with `dt_util.as_local`, or compute sunset from `hass.config.latitude/longitude` with astral, which HA already ships. Keep 19:00 only as a last resort. Log once (warning) when the hourly entity is configured but none of the known attributes parse. Expose the source of `hours_remaining` (hourly / sun / fixed) in the budget sensor or diagnostics. In `_validate_energy_sources`, warn when `pv_forecast_today_entity` has none of `watts`, `wh_period`, `detailedForecast`, `detailedHourly`. Add pytest coverage for BudgetManager with these payloads.

**Beleg (Verifier):** **Code:**
- custom_components/aurum/modules/budget.py:575-578: `assumed_sunset_hour = 19.0; return max(0.0, assumed_sunset_hour - current_hour)`
- budget.py:298-308: `hours_remaining <= 0` returns `0, "after_sunset"`; `consumption_wh = self._estimate_consumption_wh(hours_remaining)`; `budget_w = budget_wh / hours_remaining`
- budget.py:787-789: returns None when `pv_forecast_today_entity` is unset
- budget.py:862-863: `except Exception: return None`, with no log
- coordinator.py:63-66: the budget module is enabled by `pv_forecast_entity` alone
- config_flow.py:176-177: only `pv_forecast_entity` and `pv_actual_today_entity` are validated
- devices.py:417-438: budget cap conditions; it uses per-cycle `newly_allocated` and has the in_grid_only, pv_gate and price_grant exemptions
- energy.py: with battery power sensors and `battery_priority` off, `excess = -grid - battery_power_net`
- const. …

### 47. [MEDIUM] Forecast hours are compared against a naive datetime.now() (process time zone), not HA's configured time zone
`custom_components/aurum/modules/budget.py:564` · provider-data-contracts · robustness · Verdict: confirmed

**Beschreibung:** BudgetManager (lines 444, 564, 663, 799) and the coordinator (`shared['now']`, coordinator.py:167) use naive `datetime.now()`, which follows the process TZ (`TZ` env or /etc/localtime). Provider timestamps are tz-aware in HA's time zone. Solcast uses `period_start.astimezone(api.tz)`. Open-Meteo uses a fixed offset taken from the API's `utc_offset_seconds` for the location. `_get_hourly_forecast` takes `dt.hour` without converting to a common zone, and `_hours_until_sunset` subtracts the process-local `now.hour`. On HA OS the Supervisor sets TZ, so the two agree. In a HA Container started without `-e TZ=...` the process runs in UTC and every hour comparison shifts by 1–2 h. That covers sunset, the consumption window, the weather-learning ended_hour, and the date filter `dt.date() != today` between 00:00 and 01:00/02:00 local. HA's developer guidance is to use `dt_util.now()` for this reason.

**Fehlerszenario:** HA Container without a TZ env, HA configured as Europe/Berlin, Solcast 'Forecast Today', June 21, SOC 77 %. At 18:00 local the process clock reads 16:00. `hours_until_sunset` is 5.00 instead of 3.00, and the budget is 142 W instead of 570 W. At 12:00 local it is 11.00 h / 2146 W instead of 9.00 h / 2734 W. The same skew moves the daily budget reset to 01:00/02:00 local and the 17:00 safety-factor evaluation to 18:00/19:00 local.

**Fix-Vorschlag:** Use `homeassistant.util.dt.now()` for `shared['now']` and inside BudgetManager. Convert tz-aware provider timestamps with `dt_util.as_local(dt)` before taking `.hour`/`.date()`. Treat naive timestamps as local. Pass `now` from `shared` into `_hours_until_sunset`, `_estimate_consumption_wh` and `_get_trajectory_multiplier` instead of calling `datetime.now()` again, which also makes them testable.

**Beleg (Verifier):** Code:
- custom_components/aurum/coordinator.py:167 `shared = {"now": datetime.now(), ...}`; lines 204-244 use `now.hour`, `tm_yday`, the 17:00 window and the midnight budget reset.
- custom_components/aurum/modules/budget.py:564-573 `now = datetime.now(); current_hour = now.hour + ...; if watts > 50 and hour > current_hour`.
- budget.py:799/809 `today = datetime.now().date(); if dt.date() != today`.
- budget.py:851-853 `dt = datetime.fromisoformat(str(entry["period_start"])); hour = dt.hour + ...` (no tz conversion).
- budget.py:299-301 `hours_remaining <= 0` returns budget 0 with reason after_sunset.
- devices.py:432-447 the budget cap blocks starts.
- devices.py:1188 the deadline is computed from the same naive `now`.
- hass_bridge.py:27-31 passes attributes through unchanged.

HA source (github home-assistant/core dev):
- core_config.py `async_set_time_zone` only calls `dt_util.set_de …

### 48. [LOW] Deadline only works while the muss_heute switch is ON, but the config UI and README describe it as unconditional
`custom_components/aurum/modules/devices.py:1180` · devices-core · docs-mismatch · Verdict: confirmed

**Beschreibung:** _deadline_urgent returns False unless _is_muss_heute(dev). The strings.json description reads 'When does this device need to be finished? … AURUM will start the device in time — even without solar surplus.' The README says 'If a deadline is set and PV never arrives, AURUM starts on grid power as a fallback'. Neither mentions that the auto-created muss_heute switch must be turned on, and turned on again after each completion because it auto-resets. The docstring of _deadline_urgent ('Without muss_heute entity, deadline always applies') is also stale, since the native switch always exists.

**Fehlerszenario:** User configures washer deadline 18:00 and estimated_runtime 120 in the device dialog and never touches switch.aurum_washer_muss_heute. On a cloudy day nothing starts the washer by 18:00. The laundry is not done, with no notification or advisor hint.

**Fix-Vorschlag:** Mention the muss_heute requirement in the deadline / estimated_runtime descriptions (strings.json, translations, README) and fix the docstring. Optionally have the advisor report 'deadline set but muss_heute off'.

**Beleg (Verifier):** Code and tests:
- custom_components/aurum/modules/devices.py:1180 `if not self._is_muss_heute(dev): return False`
- devices.py:1177-1179: comment saying the guard is intended ("does NOT get force-started every day without the user enabling muss_heute explicitly")
- devices.py:1165-1167: outdated docstring ("Without muss_heute entity, deadline always applies (backward compatible)")
- devices.py:401 and :890: the only callers that start a device because of its deadline (regular and startup-detection paths)
- devices.py:341 and :995: `_reset_muss_heute` turns the switch off again after each run
- switch.py:62: the switch starts at `_attr_is_on = False`
- tests/test_devices.py:743-749 `test_returns_false_without_muss_heute`. Running `python -m pytest tests/test_devices.py -q -k TestDeadline` gave "4 passed, 47 deselected".

Docs that leave out the switch:
- strings.json:166, translations/en. …

### 49. [LOW] SD 'done' state is never produced, so the advisor's program_done reason and the README automation example can never fire
`custom_components/aurum/modules/devices.py:1005` · devices-core · docs-mismatch · Verdict: confirmed

**Beschreibung:** devices.py never assigns SD_STATE_DONE (it was dropped in the HELIOS port, commit 1bc1b22). After a finish, _sd_reset goes straight back to STANDBY. advisor._device_reason maps 'done' to 'program_done', and the README documents a sensor state 'done', a 'program_done | Done for today' reason, and an automation condition `… | first == 'program_done'`. Only test_advisor.py, which hand-crafts sd_state='done', exercises it. In reality a finished washer reports 'program_standby'.

**Fehlerszenario:** User copies the README automation 'has the washing machine finished its program today?'. After a completed wash the reason is 'program_standby', so the condition stays false forever.

**Fix-Vorschlag:** Reintroduce a DONE state after finish (this also fixes the max_runtime re-detect issue) that lasts until power returns to standby or until the daily reset. Otherwise remove program_done/'done' from the docs and the advisor.

**Beleg (Verifier):** - custom_components/aurum/modules/devices.py:20-23: imports only SD_STATE_STANDBY, SD_STATE_DETECTED, SD_STATE_WAITING and SD_STATE_RUNNING, not SD_STATE_DONE.
- devices.py:980-996: on smart_finish or max_runtime it calls self._sd_reset(dev).
- devices.py:1003-1005: `def _sd_reset(self, dev): ... dev["sd_state"] = SD_STATE_STANDBY`.
- devices.py:1228-1229: the published state for SD devices is sd_state.
- advisor.py:149-159: runtime_target_reached -> runtime_done; sd_state == 'done' -> program_done (unreachable); standby/detected -> program_standby.
- const.py:155: SD_STATE_DONE = "done" is defined but never assigned.
- README.md:288 lists 'done' as a sensor state; README.md:356 has `runtime_done` / `program_done` = Done for today; README.md:389-393 is the automation `... | first == 'program_done'`; example_dashboard.yaml:277-311 has 'done' branches.
- tests/test_devices.py:384 and :398  …

### 50. [LOW] force_started survives a restart that spans the daily-reset boundary (partial regression of audit #4)
`custom_components/aurum/modules/persistence.py:152` · devices-core · bug · Verdict: confirmed

**Beschreibung:** Audit #4 made daily_reset clear force_started. On restore, though, rolled_over only zeroes runtime, energy and switches. force_started is restored as saved, and _last_reset is anchored to the current cycle start, so daily_reset does not run for the new cycle. A device that was force-started yesterday therefore keeps its shedding immunity for the whole new day if HA was down across the boundary.

**Fehlerszenario:** Deadline-forced dryer (no stop_after_runtime) running at 23:50, HA restart or update straddles midnight. Reproduced: after restore runtime=0 but force_started=True, and after 2 h at a -1800 W deficit the dryer is still ON (never shed) until the next midnight. If the device is off, force_started=True also suppresses the 'deadline passed' fallback for that day.

**Fix-Vorschlag:** In restore, when rolled_over, also reset force_started=False (and _scheduling_reason / muss_heute-related state) for that device.

**Beleg (Verifier):** Repro script at <scratch>/verify_low_0_1.py: save at 2026-11-04 23:50 with force_started=True and the device on, then restore at 2026-11-05 00:10. Result: runtime 0, force_started True, _last_reset 2026-11-05 00:00. After 240 cycles (2 h) of excess_raw=-1800 with SOC 80 the switch is still 'on' and no actions were taken. Control run without a restart: daily_reset clears force_started at midnight (False). Code: persistence.py:24-27, 129, 145-152; devices.py:675-676, 1424-1437, 1455-1467.

### 51. [LOW] Stale debounce timer in the grid-only path (SOC below device threshold) lets a one-cycle export blip start a device
`custom_components/aurum/modules/devices.py:471` · devices-core · bug · Verdict: confirmed

**Beschreibung:** When SOC < soc_threshold, _should_turn_on compares eff_excess = grid-only excess and returns False before touching excess_since. The caller only clears excess_since when `turnon_excess < needed` (the legacy excess including battery charge). If the legacy excess stays high while grid export is zero, an old excess_since survives indefinitely. The next single cycle of export then passes the debounce check at once.

**Fehlerszenario:** SOC 15 % < threshold 20 %, legacy mode, battery absorbing 3 kW. One cycle of 1.4 kW export at 10:00 sets excess_since=10:00. Grid export stays at 0 for an hour. Reproduced: one export cycle at 11:00:30 starts the 1 kW heater immediately (no 300 s debounce), and it then runs at least min_on_time on battery or grid.

**Fix-Vorschlag:** Clear excess_since inside _should_turn_on whenever eff_excess < needed (or have the caller test eff_excess rather than turnon_excess).

**Beleg (Verifier):** Same repro script: a manager with SOC 15 and threshold 20, one cycle with grid_power_ema_asym=-1400 and excess_for_devices=3000 at 10:00 sets excess_since=10:00. 120 cycles with grid EMA 0 and legacy 3000 leave excess_since at 10:00 and the switch off. One cycle with grid EMA -1400 at 11:00:30 then gives switch 'on', actions [('ON','switch.heater')], with no 300 s debounce. Code: devices.py:394-396, 440-447, 468-472, 618-664.

### 52. [LOW] Published device state is stale right after AURUM switches (async service): turned-off devices show as 'manual_override' for a cycle
`custom_components/aurum/modules/devices.py:1232` · devices-core · ux · Verdict: plausible

**Beschreibung:** hass_bridge.turn_on/turn_off use services.call(blocking=False). HA schedules the entity call as a task, so for network devices (Shelly, Zigbee) the state machine still holds the old state when _publish_device_states calls _is_device_on in the same update. After _turn_off, managed_on=False plus switch still 'on' is published as 'manual_override' (advisor reason manual_override, binary active on). After _turn_on it shows 'off', and cheap_grid_active stays False. This lasts until the next device cycle (30 s, because odd cycles reuse the cache). Preemption victims processed later in the same loop also get a fresh on_since set by block 1b. Plausible from HA's ServiceRegistry semantics; the MockHass in the tests flips state synchronously, so the tests cannot show it.

**Fehlerszenario:** Shelly heater shed for excess_deficit. For about 30 s sensor.aurum_heater = manual_override and the advisor says 'You took over', which confuses users and any automation keyed on manual_override or cheap_grid_active (README suggests the latter for battery-discharge blocking).

**Fix-Vorschlag:** Publish from AURUM's intended state for devices switched in this cycle (track a per-cycle 'commanded' flag), or use blocking=True from the executor thread.

**Beleg (Verifier):** hass_bridge.py:55-69 (services.call blocking=False); coordinator.py:255-276 (executor run, odd-cycle cache, 15 s default interval); devices.py:1141-1158 (_turn_off sets managed_on=False), 1217-1275 (_publish_device_states reads live switch state), 306-309 (block 1b on_since), 1015-1050 (_preempt_for_sd), 111 (descending sort); advisor.py:129-130; binary_sensor.py:63-64. grep finds no cheap_grid_active mention in README.md or docs/*.md.

### 53. [LOW] Override, muss_heute and disable switches are looked up by a hard-coded entity_id; renaming one silently disables it (the kill-switch fails open)
`custom_components/aurum/modules/devices.py:1286` · devices-core · ha-integration · Verdict: confirmed

**Beschreibung:** _is_manual_override, _is_disabled, _is_muss_heute and _reset_muss_heute read `switch.aurum_{slug}_{suffix}` directly. switch.py only suggests that entity_id. If the user changes it in the entity settings (HA allows this), get_state returns None and the feature quietly stops working.

**Fehlerszenario:** User renames switch.aurum_pool_disable to switch.pool_disable and turns it ON to keep the pump off during maintenance. AURUM never sees it and switches the pump on at the next surplus.

**Fix-Vorschlag:** Resolve the entity_id from the entity registry by unique_id (aurum_{slug}_{suffix}) at setup, or let the switch entities write their state into the coordinator / device dict directly.

**Beleg (Verifier):** devices.py:1278-1290, 1297-1315, 1317-1334, 1336-1350; const.py:163-175; switch.py:63 (unique_id aurum_{slug}_{suffix}), 67-68 ('Force deterministic entity_id so devices.py can derive it'). README.md and docs/QUICKSTART.md contain no rename warning (grep for 'rename' found nothing relevant). The only er.async_get uses are cleanup in __init__.py:112/171 and config_flow.py:787, not lookups.

### 54. [LOW] Price-granted starts have no debounce, though the README says debounce still applies
`custom_components/aurum/modules/devices.py:631` · devices-core · docs-mismatch · Verdict: confirmed

**Beschreibung:** _should_turn_on returns True immediately on _price_grant ('No debounce needed … React immediately'). The README Price-Aware section says 'Debounce timers still apply to prevent flapping on price edges.' Only min_on_time and min_off_time limit flapping. (Price semantics themselves are left to the pricing reviewer.)

**Fehlerszenario:** 15-min Tibber prices hovering at max_price: the device starts in the same cycle the price dips, as the code comment intends but contrary to the README statement.

**Fix-Vorschlag:** Align the README with the code (no debounce; min_on/min_off protect) or add a short debounce on price edges.

**Beleg (Verifier):** README.md:184-190; devices.py:603-613 (min_off_time is the only time guard before the grant), 623-631 (_price_grant then return True with no excess_since or debounce), 683-692 (immediate price_no_longer_cheap turn-off after min_on_time).

### 55. [LOW] Switch-penalty docstring tiers do not match the code
`custom_components/aurum/modules/devices.py:778` · devices-core · docs-mismatch · Verdict: confirmed

**Beschreibung:** The docstring says '2+ switches/hour -> 1.5x, 4+ -> 2.0x, 6+ -> 3.0x', but the code uses `> 2`, `> 4`, `> 6` (3+, 5+, 7+), and the tests pin the code behaviour. Each on/off pair also adds two entries, so a 'switch' is half a cycle.

**Fehlerszenario:** A developer tuning relay protection from the docstring expects 1.5x after 2 switches; the code applies 1.0x until the 3rd.

**Fix-Vorschlag:** Fix the docstring (or the thresholds) so both agree.

**Beleg (Verifier):** devices.py:777-793 (docstring vs '> 6 / > 4 / > 2'); devices.py:1139 and 1157 (append in both _turn_on and _turn_off); tests/test_devices.py:255-272 (range(2) -> 1.0, range(3) -> 1.5, range(5) -> 2.0, range(7) -> 3.0).

### 56. [LOW] Price-sensor outage makes the cheap-grid hold unbounded: a device started on cheap grid runs on grid indefinitely
`custom_components/aurum/modules/devices.py:742` · price-energy-battery · robustness · Verdict: confirmed

**Beschreibung:** should_run_on_grid returns None when no configured price source is available. In _should_turn_off, `is not False` treats None as 'hold' and also resets _excess_deficit_since, so neither price_no_longer_cheap nor the excess-deficit turn-off can fire for as long as the outage lasts. The hold was introduced to avoid flapping on a flaky sensor, but it has no time limit. Starting is fail-closed (no grant on None), stopping is fail-open forever.

**Fehlerszenario:** cheap_grid EV charger or heater without a run condition, started at 03:00 in a cheap window. At 04:00 the Tibber Prices integration goes unavailable (API outage or expired token) until someone restarts it in the evening. The device keeps drawing grid power through the 06:00-09:00 and 17:00-20:00 price peaks, and solar-deficit shedding is suppressed as well.

**Fix-Vorschlag:** Keep the hold only for a bounded time (e.g. 15-30 min since price data was last available, tracked in PricingManager), then treat the grant as expired and fall through to the generic surplus logic.

**Beleg (Verifier):** Code:
- custom_components/aurum/modules/pricing.py:115-119 sets price_data_available only from usable readings, and :171-172 returns None when no data is available.
- custom_components/aurum/modules/devices.py:574 grant needs `is True`; :690-693 release needs `is False`; :742-752 hold uses `is not False` and resets _excess_deficit_since.
- devices.py:719-730 soc_grid_deficit is checked before the hold, so it still fires.
- devices.py:242-266 MODE_CHARGING emergency turns everything off.
- devices.py:1434 _reset_device_counters clears _scheduling_reason.
- persistence.py:17-27 does not persist _scheduling_reason.
- tests/test_devices.py test_cheap_grid_holds_when_price_data_unavailable and tests/test_cheap_grid_soc.py test_holds_when_price_data_unavailable pin the unbounded hold as intended.
- CHANGELOG.md:131.

Repro: <scratch>/price_outage_hold.py. It runs a 3.7 kW cheap_grid device wit …

### 57. [LOW] PV gate never opens on battery-less systems: _pv_gate_ok fails closed on SOC<0, which now only means 'no battery configured'
`custom_components/aurum/modules/devices.py:595` · price-energy-battery · bug · Verdict: confirmed

**Beschreibung:** About the known item (permissive price gate vs fail-closed PV gate on unknown SOC). Since the audit #10 fix, energy.py never publishes a negative SOC when a SOC entity is configured; it holds the last value or 0 %. battery_soc < 0 therefore only ever means 'no battery configured'. In that light the permissive price gate is the right choice. The fail-closed `battery_soc < 0` branch in _pv_gate_ok is the wrong one: it permanently disables pv_power_threshold for installations without a battery. The release side (_should_turn_off, `soc_ok = battery_soc < 0 or ...`) is already permissive, so the two sides are inconsistent. The test docstring calling -1 'SOC unavailable' is outdated.

**Fehlerszenario:** PV without a battery (no battery_soc_entity), pool pump with pv_power_threshold 1000, PV at 3 kW, house load hiding the surplus. _pv_gate_ok returns False on every cycle, so the documented 'run whenever PV >= 1000 W' never happens, with no log or advisor hint.

**Fix-Vorschlag:** Treat battery_soc < 0 as 'no battery, SOC condition satisfied' in _pv_gate_ok, mirroring _price_grant and the release path, and update the test docstrings.

**Beleg (Verifier):** Code:
- custom_components/aurum/modules/energy.py:67-85: a configured SOC entity holds its last value or 0.0; -1 is set only in the "no battery_soc_entity" else branch.
- custom_components/aurum/modules/devices.py:595 `if battery_soc < 0 or battery_soc < soc_threshold: return False` is fail-closed. These are all permissive on <0: devices.py:578, 704, 747, 910; battery.py:36 (no battery → MODE_NORMAL); the grid-only checks at devices.py:418, 619 and 719 (`battery_soc >= 0 and ...`).
- budget.py:160-162 and 252: no battery gives device_budget_w None, so there is no cap.
- devices.py:638-642 (the PV gate arms excess_since and returns False) and devices.py:467-472 (`if turnon_excess < needed: dev["excess_since"] = None`): this is the separate bug that clears the gate's debounce every cycle.
- Commits: d7dc839 2026-07-01 (SOC hold fix) predates 7249b54 2026-07-10 (PV gate).

Repro scripts, un …

### 58. [LOW] scheduling_reason sticks to the start path: an expensive price leaves a PV-covered device labelled cheap_grid all day, and a fading-PV to cheap-window transition causes an off/on
`custom_components/aurum/modules/devices.py:690` · price-energy-battery · bug · Verdict: confirmed

**Beschreibung:** (A) A device started on cheap grid whose price later turns expensive while PV covers it: _should_turn_off returns 'price_no_longer_cheap' every cycle, the shedding stage keeps it because deficit <= 0, and the reason stays cheap_grid. So cheap_grid_active stays True, the advisor reports running_cheap_grid, and the first raw deficit sample (e.g. a kettle) sheds it with no debounce_off. (B) A device running on surplus whose evening coincides with a cheap window is not recognised as cheap-grid-justified: it is shed by excess_deficit and restarted 1 min later with reason cheap_grid.

**Fehlerszenario:** (A) Simulated: cheap_grid heater ON at 05:00 (cheap), price expensive from 07:00, 500 W export with the heater on. At 12:00 it is still ON with reason cheap_grid and cheap_grid_active True. (B) Simulated: heater ON since 12:00 (surplus_available), price cheap from 18:00 with import: OFF at 18:10, ON at 18:11 (cheap_grid).

**Fix-Vorschlag:** While the device is running, re-label the reason each cycle: drop to surplus_available when the price grant ends but there is no deficit, and promote to cheap_grid (and hold) when _price_grant becomes live for a price-aware device.

**Beleg (Verifier):** Scratch sim <scratch>/verify_low_pe.py using the real DeviceManager + conftest MockHass/FakePricing. (A) 'A 12:00 on cheap_grid True price_no_longer_cheap', then a single 1500 W import sample gives 'A kettle off'. (B) 'B on? on surplus_available', then 'B transitions [('18:10:00','off',None), ('18:11:00','on','cheap_grid')]'. Code: devices.py:485-500 (deficit/break), 690-693, 742-752, 1134, 1157, 1272-1276; advisor.py:136-137, 177-178.

### 59. [LOW] Price level match is case-sensitive; uppercase levels (Tibber API, e.g. 'VERY_CHEAP') are silently treated as 'no price data'
`custom_components/aurum/modules/pricing.py:101` · price-energy-battery · robustness · Verdict: confirmed

**Beschreibung:** `raw in _LEVEL_ORDER` only accepts lowercase keys. The Tibber API, and the native Tibber price sensor's price_level attribute that users typically wrap in a template sensor, use uppercase enums (NORMAL, CHEAP, VERY_CHEAP). With level as the only source, data_available stays False and should_run_on_grid returns None, so cheap-grid devices never start, without any log entry.

**Fehlerszenario:** price_level_entity = template sensor '{{ state_attr("sensor.electricity_price_home","price_level") }}' with value 'VERY_CHEAP'. Verified: price_data_available False and should_run_on_grid None, so no cheap-grid run ever happens.

**Fix-Vorschlag:** Normalise with raw.strip().lower() before the lookup, and log once at WARNING when a configured level entity reports a value outside _LEVEL_ORDER.

**Beleg (Verifier):** Sim: PricingManager with price_level_entity state 'VERY_CHEAP' gives shared price_level None, price_level_value None, price_data_available False, and should_run_on_grid({'price_mode':'cheap_grid'}) returns None. Code: pricing.py:21-27, 97-103, 161-162. Docs: README.md:159 and strings.json:110 list lowercase values only.

### 60. [LOW] max_price cannot express '<= 0 ct' or fractional thresholds (0 means disabled, step 1, min 0)
`custom_components/aurum/modules/pricing.py:142` · price-energy-battery · ux · Verdict: confirmed

**Beschreibung:** `max_price is not None and max_price > 0` makes 0 the 'off' value, and the config flow / number entity use min=0, step=1. With spot-price sensors (EPEX Spot, Nordpool without fees), the most useful rule 'run only when the price is negative or zero' cannot be configured. With only price_entity configured and max_price 0, a price-aware device never gets a price grant, even at -3 ct.

**Fehlerszenario:** Only price_entity (EPEX spot, ct/kWh), device cheap_grid, user sets max_price 0 meaning 'free power only'. Verified: at -3.0 ct should_run_on_grid returns False, so the device never runs on negative prices.

**Fix-Vorschlag:** Use None (or a separate enable flag) as 'disabled', allow negative values and step 0.1 in the number entity and selector.

**Beleg (Verifier):** Sim: price_entity '-3.0', should_run_on_grid({'price_mode':'cheap_grid','max_price':0}) returns False, and with max_price 0.5 it returns True. Code: pricing.py:142-146; config_flow.py:464-470; number.py:206-217, 241.

### 61. [LOW] README says cheap-grid starts are debounced; the code grants and releases price runs immediately
`README.md:190` · price-energy-battery · docs-mismatch · Verdict: confirmed

**Beschreibung:** README: 'Debounce timers still apply to prevent flapping on price edges.' _should_turn_on returns True on a price grant before any debounce ('No debounce needed ... React immediately'), and price_no_longer_cheap is returned without debounce_off. In the shedding stage it fires on the first raw deficit sample.

**Fehlerszenario:** A user relies on debounce_on/off to smooth price-edge behaviour, but the device switches on in the first device cycle of a cheap slot, and once the price turns expensive a single raw deficit sample sheds it.

**Fix-Vorschlag:** Fix the README sentence, or apply debounce_off to the price_no_longer_cheap release.

**Beleg (Verifier):** README.md:190 vs devices.py:624-632 (comment at 625-626), devices.py:684-693, devices.py:481-522 (shedding has no timer). Sim [0](A): a single 1500 W import sample sheds the price_no_longer_cheap device right away.

### 62. [LOW] README troubleshooting: 'no battery configured -> SOC treated as 0 -> charging mode' is wrong
`README.md:492` · price-energy-battery · docs-mismatch · Verdict: confirmed

**Beschreibung:** Without battery_soc_entity, energy.py publishes -1 and battery.py returns MODE_NORMAL for soc < 0, so a battery-less setup never enters charging mode. The real cause of a 0 % / charging state is a configured SOC sensor that has been unavailable since startup (energy.py:78). Related: the README Battery Modes table and troubleshooting say per-device SOC thresholds apply 'during low_soc mode', but devices.py applies them in every mode (MODE_LOW_SOC is never read by devices.py).

**Fehlerszenario:** A user stuck in 'charging' follows the README, removes the SOC entity and sets min_soc 0, when the actual problem was a slow or unavailable SOC sensor.

**Fix-Vorschlag:** Reword the item to 'SOC sensor configured but unavailable since startup -> AURUM assumes 0 %'. State that per-device thresholds apply regardless of battery mode.

**Beleg (Verifier):** README.md:487-492, 503, 249; energy.py:65-85; battery.py:33-48; grep shows only energy.py:83/85 write shared['battery_soc']; devices.py:618-622, 717-730 (no battery_mode check); advisor.py:162-167.

### 63. [LOW] Budget learned state from yesterday is restored after a restart across midnight, and the first-day budget reset is skipped
`custom_components/aurum/modules/budget.py:957` · budget-forecast · bug · Verdict: confirmed

**Beschreibung:** persistence.restore() returns `_budget` without checking `_meta.saved_at`; it does check the date for device counters. BudgetManager.restore_state() then restores trajectory_start_soc/time and pv_total_midnight without any date check. On the first cycle after start, coordinator.py:239-244 skips budget.daily_reset() because `_last_daily_reset` is -1 (the `>= 0` guard). If the saved state is from the previous day, the trajectory anchor and the PV-counter midnight snapshot from that day stay active for the whole new day.

**Fehlerszenario:** HA shuts down at 23:50 (update or power cut) and comes back at 00:05. The restored trajectory start is yesterday 08:00 at SOC 30 %. Simulated: progress about 0.76, expected SOC about 68 %, multiplier 0.0 and budget 0 until SOC catches up (12:00 in the simulation). With a lifetime PV counter as pv_actual_today_entity, the restored pv_total_midnight is yesterday's, so 'PV today' includes yesterday's 25 kWh. In-day correction clamps to 1.5 and the budget is inflated all day, so the battery misses its target.

**Fix-Vorschlag:** Pass saved_at into restore_state, or check the date in persistence. Drop day-scoped fields (trajectory_start_*, pv_total_midnight) when saved_at is before today's midnight. Learned fields (safety factor, weather, consumption) can stay.

**Beleg (Verifier):** - <local path> saved_at is parsed and used only for the per-device `rolled_over`. Line 220: `return state.get("_budget")`, returned unconditionally.
- <local path> `self._last_daily_reset: int = -1`. Lines 98-103: budget.restore_state(budget_state) with no date check. Lines 240-244: `if today != self._last_daily_reset: if self._last_daily_reset >= 0 and self.budget: self.budget.daily_reset()`, which is skipped on the first cycle.
- <local path> restore_state restores trajectory_start_soc/time and pv_total_midnight without a date check.
- budget.py:213: the anchor is re-created only when None. Lines 899-901: daily_reset is the only place it is cleared.
- budget.py:665-676: elapsed is measured from yeste …

### 64. [LOW] Adaptive consumption profile is dead code: hourly_consumption_w is never produced, so the budget always assumes a flat 500 W household load
`custom_components/aurum/modules/budget.py:477` · budget-forecast · docs-mismatch · Verdict: confirmed

**Beschreibung:** update_consumption_profile() (called daily at 23:55 by coordinator.py:215-218) reads shared['hourly_consumption_w'] and returns at once because no module writes that key; grep finds no producer. `_consumption_profile` therefore stays at `[avg_consumption_w]*24`, and avg_consumption_w (default 500) is not in the config flow, so users cannot change it. CHANGELOG 1.5.0 says the budget considers the consumption profile and that the 23:55 profile update is 'fully wired up'. AURUM already computes house consumption (sensor.aurum_house_consumption = pv + grid + bat_net) but never feeds it in.

**Fehlerszenario:** A house with about 1.2 kW daytime base load (heat pump circulation, home office). At 10:00 with 8 h of production left, the budget subtracts 4 kWh of consumption instead of about 9.6 kWh, so device_budget_w is about 700 W too high. Devices are allowed while the house itself uses the solar the battery needed, and the battery misses its target. A 250 W house gets the opposite: devices are held back for no reason.

**Fix-Vorschlag:** In the coordinator or budget, add up hourly house consumption (pv + grid_raw + battery_power_net) per hour of the day and publish shared['hourly_consumption_w'] before the 23:55 call. Add avg_consumption_w to the options flow. Correct the CHANGELOG claim.

**Beleg (Verifier):** Code:
- custom_components/aurum/modules/budget.py:477-479 reads `hourly_data = shared.get("hourly_consumption_w")` and returns when it is empty. A grep finds no writer anywhere in custom_components/.
- budget.py:65 sets `self.avg_consumption_w = config.get("avg_consumption_w", 500)`, and budget.py:112 builds the flat 24-hour profile from it.
- budget.py:304-307 subtracts the estimated consumption in the budget formula.
- coordinator.py:40 builds the config as `{**config_entry.data, **config_entry.options}`.
- coordinator.py:214-218 makes the 23:55 call.
- config_flow.py has no avg_consumption_w.
- CHANGELOG.md:198 and :201 make the false claims.
- devices.py:417-438 is where the budget cap applies.
- budget.py:649-685 is the trajectory multiplier that limits the impact.

Repro script: <scratch>/consumption_profile_check.py
Output:
```
avg_consumption_w default: 500
profile before: {500}
 …

### 65. [LOW] budget_combined_floor (0.85) cancels any safety factor below 0.85 and every downward in-day correction
`custom_components/aurum/modules/budget.py:281` · budget-forecast · bug · Verdict: confirmed

**Beschreibung:** The code computes `combined = max(0.85, weather * safety * inday)`. With the default safety factor 0.7 and no weather entity, combined is always 0.85. A safety factor anywhere in [0.55, 0.85] gives the identical budget, and the 17:00 'miss' adaptation (-0.03/day) has no effect below 0.85. Worse, the in-day correction is clamped to [0.3, 1.5] and its docstring says 'if morning production was only 60 % of predicted, the remaining forecast is corrected by 0.6', yet it can never lower the budget by more than 15 %. strings.json promises that AURUM 'compares forecast vs. reality and adjusts the budget accordingly'. The Safety Factor sensor shows 70 % while 85 % is actually applied. A note in tests/simulation_calibrate_budget.py mentions the sf clamp, but not that it disables the in-day correction.

**Fehlerszenario:** Foggy morning, Solcast over-forecasts: forecast today 30 kWh, remaining 20 kWh, actual so far 5 kWh, so in-day correction = 0.5. With sf = 1.0 the result is still combined_factor 0.85 and budget 944 W (verified). The budget is based on 85 % of a forecast that has been running at 50 %, devices are allowed, and the battery misses its target. At 17:00 sf is lowered, which changes nothing.

**Fix-Vorschlag:** Floor only the term the floor was meant for (the weather factor double-counting cloud cover), e.g. `combined = max(floor, weather) * sf * inday`, or floor `weather*sf` and apply inday outside the floor. Publish the effective combined factor (e.g. as a Safety Factor sensor attribute) so the UI matches what is applied.

**Beleg (Verifier):** **Code:**
- custom_components/aurum/modules/budget.py:79 `self.budget_combined_floor = config.get("budget_combined_floor", 0.85)`
- budget.py:68 sf default 0.7; budget.py:75 sf_min 0.55
- budget.py:278-281 `combined = (weather_factor * self.budget_safety_factor * inday_correction); combined = max(self.budget_combined_floor, combined)`
- budget.py:615-643 in-day correction is clamped to [0.3, 1.5]; the docstring says "corrected by 0.6"
- budget.py:753-756 a miss steps sf down to no lower than 0.55, which has no effect at or below 0.85
- budget.py:181 and sensor.py:576-581 the Safety Factor sensor publishes the raw sf
- budget.py:319 `combined_factor` is only in `budget_info`; a grep shows nothing outside budget.py reads it
- coordinator.py:40 config = data + options; config_flow.py exposes neither budget_combined_floor nor budget_safety_factor
- strings.json:26 and 102 promise "compares f …

### 66. [LOW] pv_forecast_entity in Wh passes validation but is read as kWh, which effectively disables the budget
`custom_components/aurum/modules/budget.py:273` · budget-forecast · bug · Verdict: confirmed

**Beschreibung:** config_flow._check_energy() accepts Wh, kWh and MWh for pv_forecast_entity (_VALID_ENERGY_UNITS). _calculate_budget and _get_inday_correction always treat the state as kWh (`remaining_wh = remaining_kwh * 1000`), and AurumForecastRemainingSensor publishes it as kWh. HA lets users switch an energy sensor's display unit to Wh, and template forecast sensors are often in Wh. _get_pv_today_kwh does detect Wh, so the handling is inconsistent. strings.json says 'in kWh', but the validator that should catch the mistake approves it.

**Fehlerszenario:** The user picks a remaining-forecast sensor showing 20000 Wh. AURUM computes remaining_pv_wh = 20,000,000 and device_budget_w ≈ 1.89 MW (verified), so the budget never caps anything. sensor.aurum_forecast_remaining shows '20000 kWh'. The in-day correction compares Wh with kWh and clamps to 0.3.

**Fix-Vorschlag:** Read unit_of_measurement for pv_forecast_entity and pv_forecast_today_entity and convert to kWh (Wh /1000, MWh *1000), or reject non-kWh units in _validate_energy_sources with a clear error.

**Beleg (Verifier):** custom_components/aurum/config_flow.py:122 (`_VALID_ENERGY_UNITS = {"Wh", "kWh", "MWh"}`), :160-170 (_check_energy only rejects units outside that set), :176 (applied to pv_forecast_entity; pv_forecast_today_entity is not checked)
custom_components/aurum/modules/helpers.py:14-22 (get_float returns the raw float, no unit handling)
custom_components/aurum/modules/budget.py:171-180 (raw value published as pv_forecast_remaining_kwh), :267-273 (`remaining_wh = remaining_kwh * 1000`, no unit check), :631-643 (in-day correction mixes raw forecast units with the kWh actual), :594-613 (_get_pv_today_kwh does detect Wh, so handling is inconsistent)
custom_components/aurum/sensor.py:494-509 (ForecastRemaining fixed to kWh, shows the raw value)
custom_components/aurum/modules/devices.py:432-438 (budget used only as a start cap, so a huge value means no cap)
custom_components/aurum/strings.json:24,10 …

### 67. [LOW] 17:00 safety-factor evaluation checks the SOC at 17:00, not whether the target was reached; with no battery every day counts as a miss
`custom_components/aurum/modules/budget.py:715` · budget-forecast · bug · Verdict: confirmed

**Beschreibung:** The docstring asks 'did we reach target SOC?', but `success = current_soc >= target_soc` uses the SOC at 17:00 against the raw target. It ignores the day's peak and the lower effective target the budget actually aimed for in bad weather. In winter, production ends around 16:00 and the house drains the battery before 17:00. Without a battery, shared['battery_soc'] = -1, which is not None, so -1 >= target is False and a miss is logged every day ('SOC=-1%').

**Fehlerszenario:** December: the battery reaches 85 % (target 80) at 14:00, house load drains it to 76 % by 17:00, and the day counts as a miss, so sf drops by 0.03 every winter day. A PV-forecast setup without a battery SOC sensor sees sensor.aurum_safety_factor fall to 55 % within days even though the budget is never used.

**Fix-Vorschlag:** Track the maximum SOC since the daily reset and compare that with the target (or the effective target). Skip adaptation when battery_soc < 0 or no SOC entity is configured.

**Beleg (Verifier):** budget.py:707-715 `current_soc = shared.get("battery_soc")` ... `success = current_soc >= target_soc`; energy.py `shared["battery_soc"] = -1  # -1 = no battery`. Scratch run with {pv_forecast_entity, target_soc:80}, battery_soc=-1, six 17:00 calls: sf 0.67, 0.64, 0.61, 0.58, 0.55, 0.55, with device_budget_w None throughout.

### 68. [LOW] Lifetime-counter detection treats a daily PV counter above 100 kWh as a lifetime total, which corrupts in-day correction and weather learning
`custom_components/aurum/modules/budget.py:605` · budget-forecast · robustness · Verdict: confirmed

**Beschreibung:** While _pv_total_midnight is None (always true for a daily-reset sensor), every read checks `raw > 100` (kWh) or `raw > 100000` (Wh). A daily sensor on a large array that passes 100 kWh during the day is then treated as a lifetime counter: the snapshot is set to about 100 and 'PV today' drops to about 0. The snapshot is also persisted. The MWh unit is treated as kWh.

**Fehlerszenario:** A 20 kWp farm in June: the daily counter reaches 100.2 kWh at 14:00. From then on pv_actual_today_kwh is about 0, the hour delta is max(0, 0 - 98) = 0, weather learning records ratio 0.1 for 'sunny' and pulls the learned factor down, and the in-day correction collapses.

**Fix-Vorschlag:** Decide between daily and lifetime counters once, from state_class/last_reset or the first value after midnight, not on every read. Or add an explicit config option. Handle MWh.

**Beleg (Verifier):** budget.py:605 `if (is_wh and raw > 100_000) or (not is_wh and raw > 100): self._pv_total_midnight = raw ... return 0.0`. Scratch run (unit kWh): raw 92 gives pv_today 92; raw 100.2 gives pv_today 0.0 and midnight 100.2; at the 14:00 boundary raw 102 gives pv_today 1.8 and hour_kwh 0.0. MWh entity with 25.3 gives 25.3.

### 69. [LOW] Weather learning uses only the first half-hour slot as the forecast for the whole hour with Solcast data
`custom_components/aurum/modules/budget.py:200` · budget-forecast · bug · Verdict: confirmed

**Beschreibung:** With Solcast detailedForecast (30-minute slots), hourly_forecast contains both (h.0, w1) and (h.5, w2). `next(w for h,w in hourly_forecast if int(h)==ended_hour)` returns only w1 and divides it by 1000 as the hour's kWh, while the actual is the energy of the full hour. This is left over from the fixed audit item #6 (hour matching is now correct; the slot aggregation is not).

**Fehlerszenario:** Morning ramp 08:00-09:00: forecast 400 W for 08:00 and 1200 W for 08:30, actual 0.8 kWh. The forecast used is 0.4 kWh, so ratio 2.0 is clamped to 1.5 and the learned 'sunny' factor creeps above 1.0. Together with the dynamic-target finding, that raises the effective target.

**Fix-Vorschlag:** Average all entries with int(h) == ended_hour (or add up wh_period values) before dividing by 1000.

**Beleg (Verifier):** Scratch run with detailedForecast [08:00 0.4 kW, 08:30 1.2 kW, 09:00 1.6 kW] plus detailedHourly [08:00 0.8 kW]: hourly_forecast = [(8.0,400),(8.5,1200),(9.0,1600)]. With an actual of 0.8 kWh for 08:00-09:00, the 09:00 boundary gives pv_actual_hour_kwh=0.8 and pv_forecast_hour_kwh=0.4, so the ratio is 2.0 and gets clamped to 1.5.

### 70. [LOW] AurumBudgetWSensor overrides the final SensorEntity.state / unit_of_measurement and switches unit between W and none
`custom_components/aurum/sensor.py:536` · budget-forecast · ha-integration · Verdict: confirmed

**Beschreibung:** In HA, SensorEntity.state and unit_of_measurement are @final. Overriding them skips native_value handling and gets flagged by HA's lint/quality checks, which matters for the Marketplace listing. Showing '–' with no unit and a number with 'W' gives an entity whose unit changes back and forth, which breaks history graphs and numeric-state automations.

**Fehlerszenario:** Budget alternates between None (SOC >= target) and a number during the day: the history graph switches between a text timeline and a line chart, and a numeric_state trigger on sensor.aurum_budget fails on '–'.

**Fix-Vorschlag:** Use native_value = None (unknown) or keep a fixed W unit, and expose 'unlimited' as an attribute (budget_w already exists). Do not override state/unit_of_measurement.

**Beleg (Verifier):** sensor.py: `@property def state(self): if self._budget_w is None: return "–"; return str(int(self._budget_w))` and `@property def unit_of_measurement(self): return "W" if self._budget_w is not None else None`. CHANGELOG.md:164 documents the '–' choice and the budget_w attribute for automations. README.md:277 describes sensor.aurum_budget as 'Device power budget (W)'.

### 71. [LOW] Restore treats a not-yet-loaded switch as OFF; AURUM-managed device then shows as manual_override
`custom_components/aurum/modules/persistence.py:196` · ha-lifecycle · ha-integration · Verdict: confirmed

**Beschreibung:** restore() runs in coordinator.async_setup at HA boot and immediately cross-checks devices._is_device_on(dev). At boot the controlled switch (Shelly, Zigbee, Z-Wave) is often still 'unavailable', either as HA's restored placeholder or because the integration has not connected yet. The code treats that as OFF: managed_on=False, on_since=None. When the switch then reports 'on', update() takes the 'on but not managed' path. managed_on is only set again by _turn_on, so the device is published as 'manual_override' ('You took over — AURUM hands off'). It is also skipped by SD preemption (the 'manual override, don't preempt' check) until AURUM switches it off and on again. Reproduced with a stubbed restore: managed_on False, then published state manual_override.

**Fehlerszenario:** A pool pump was turned on by AURUM on surplus, HA restarts, and AURUM's setup runs before the Shelly integration has loaded. For the rest of the run the dashboard, panel and Advisor say the user took over, although AURUM still sheds it. A higher-priority SD washer can no longer preempt it, so the washer keeps waiting.

**Fix-Vorschlag:** Make the cross-check tri-state. If the switch state is unavailable or unknown, keep the saved managed_on, on_since and reason. Alternatively defer the cross-check to the first non-startup control cycle, when the startup guard has given integrations time to load.

**Beleg (Verifier):** - `custom_components/aurum/modules/persistence.py:195-213`: the cross-check sets `managed_on=False` and `on_since=None` whenever `_is_device_on` is falsy; there is no unavailable/unknown branch.
- `custom_components/aurum/modules/helpers.py:25-30`: `get_state_safe` maps None, 'unavailable' and 'unknown' to None.
- `custom_components/aurum/modules/devices.py:1108-1111`: `_is_device_on` returns `state == "on"`.
- `custom_components/aurum/coordinator.py:84-109` and `custom_components/aurum/__init__.py:201-202`: restore runs in `async_setup` at entry setup, before the first refresh and before the `STARTUP_GRACE_CYCLES` guard (`coordinator.py:36,170`).
- `custom_components/aurum/manifest.json`: dependencies are only frontend and http.
- `custom_components/aurum/modules/devices.py`:
  - `:311-314`: on but not managed, falls through to the turn-off logic (so it is still shed).
  - `:1128`: the  …

### 72. [LOW] Orphan cleanup misparses muss_heute unique_ids (deleted every setup) and never cleans {entry_id}_ entities
`custom_components/aurum/__init__.py:129` · ha-lifecycle · bug · Verdict: confirmed

**Beschreibung:** _async_cleanup_orphaned_entities takes the slug as '_'.join(parts[1:-1]), which assumes a one-word suffix. (a) Switch unique_id aurum_{slug}_muss_heute parses as slug '{slug}_muss', which is never active. So every active device's muss_heute switch registry entry is removed on every setup and re-created by the platform a moment later, with an INFO line on each start. On current HA most customizations come back from deleted_entities, but this is pointless registry churn and misleading logs. (b) Sensor, binary_sensor, number and time unique_ids are f'{entry_id}_{slug}_...', which do not start with 'aurum_', so the cleanup never touches them. edit_device does no cleanup either. Verified with a stubbed registry: removed = [switch.aurum_washer_muss_heute, switch.aurum_pool_pump_muss_heute, switch.aurum_old_name_override]. sensor.aurum_old_name_power and number.aurum_old_name_soc_threshold were kept.

**Fehlerszenario:** The user renames 'Washer' to 'Waschmaschine'. After the reload the old sensor.aurum_washer, _power, _runtime, _energy_today, binary_sensor _active, number _soc_threshold, _pv_power_threshold, _max_price and time _deadline stay in the registry as 'no longer provided' ghosts forever. This contradicts the CHANGELOG ('Ghost entities ... are now cleaned up automatically on every HA restart'). In addition, every HA start logs 'removing orphaned entity switch.aurum_<slug>_muss_heute (slug '<slug>_muss' not in config)' for every device.

**Fix-Vorschlag:** Match on known suffixes instead of splitting on '_'. For each entity, strip the prefix ('aurum_' or f'{entry.entry_id}_') and test whether the remainder equals an active slug or starts with an active slug followed by '_<known suffix>'. Use longest-slug arbitration as remove_device does.

**Beleg (Verifier):** custom_components/aurum/__init__.py:122-134 (startswith("aurum_") filter; entity_slug = "_".join(parts[1:-1])); switch.py:63,142 (unique_id aurum_{slug}_muss_heute); sensor.py:200,246,274,305, binary_sensor.py:52, number.py:144,186,226, time.py:54 ({entry_id}_{slug}_... unique_ids); config_flow.py:719-760 (edit_device: no registry cleanup), config_flow.py:762-814 (remove_device: entity_id-based, all platforms); CHANGELOG.md:189 (claim); frontend/aurum-panel.js:207-210 (panel keys on override switch); git a6dd036 (cleanup introduced 2026-04-02, bug present since).

Repro script: <scratch>/orphan_cleanup_verify.py (stubbed registry; active device "Washer", stale device "old_name"). Output:
removed: ['switch.aurum_washer_muss_heute', 'switch.aurum_old_name_override', 'switch.aurum_old_name_muss_heute', 'switch.aurum_old_name_disable']
kept: ['switch.aurum_washer_override', 'switch.aurum_was …

### 73. [LOW] 23:55 consumption-profile job is a permanent no-op (hourly_consumption_w is never produced)
`custom_components/aurum/coordinator.py:217` · ha-lifecycle · docs-mismatch · Verdict: confirmed

**Beschreibung:** The coordinator calls budget.update_consumption_profile(shared) daily at 23:55. That method returns immediately unless shared['hourly_consumption_w'] is set, and no module (energy, battery, devices, pricing, coordinator) ever writes that key. The consumption profile used by _estimate_consumption_wh therefore stays at the flat default avg_consumption_w=500 W per hour forever, and that value is not exposed in the config flow. CHANGELOG says 'consumption profile update (daily at 23:55) ... are now fully wired up'.

**Fehlerszenario:** A household with 1.2 kW average evening load and a battery target of 80%: the budget always assumes 500 W per hour for the rest of the day. It overestimates the device budget by about 700 W x hours_remaining, and the battery misses its target. Only the coarse 17:00 safety-factor step partially compensates.

**Fix-Vorschlag:** Accumulate house consumption (pv + grid + battery_net, which diagnostics already derives) into hourly averages in the coordinator or energy module and pass them as shared['hourly_consumption_w'] at 23:55, persisting the accumulators. Or remove the job and correct the CHANGELOG.

**Beleg (Verifier):** - custom_components/aurum/coordinator.py:167: `shared = {"now": datetime.now(), "cycle": self.cycle}`, rebuilt every cycle.
- custom_components/aurum/coordinator.py:214-218: the 23:55 job calls `self.budget.update_consumption_profile(shared)`.
- custom_components/aurum/modules/budget.py:477-479: `hourly_data = shared.get("hourly_consumption_w")` followed by `if not hourly_data: return`.
- Repo-wide search for `hourly_consumption_w`: the only match is budget.py:477. There is no writer in energy, battery, devices, pricing, advisor, coordinator, hass_bridge or the tests.
- budget.py:65 and :112: `avg_consumption_w` defaults to 500 and the profile starts as `[500]*24`. The key does not appear in config_flow.py or strings.json.
- CHANGELOG.md:201: "consumption profile update (daily at 23:55) ... are now fully wired up".
- Mitigation: budget.py:649-685, the trajectory multiplier, gives budget  …

### 74. [LOW] notify_service entered as 'notify.mobile_app_x' builds service 'notify/notify.mobile_app_x'; push silently fails
`custom_components/aurum/modules/devices.py:1401` · ha-lifecycle · bug · Verdict: confirmed

**Beschreibung:** _notify only checks for '/'. The code comment says the 'notify.mobile_app_christian' format is supported, but that string becomes 'notify/notify.mobile_app_christian'. The bridge then schedules services.async_call('notify', 'notify.mobile_app_christian', ...) with hass.add_job. That raises ServiceNotFound inside the fire-and-forget task, so the surrounding try/except never sees it. No push is delivered, and the only trace is an unhandled-task error in the HA log. The option description sends users to Developer Tools, where actions are listed as 'notify.mobile_app_…'. Also, strings.json says pushes come 'when devices are turned on/off', but normal surplus on/off sends nothing. Only SD, deadline, runtime-target, disable and preempt events notify.

**Fehlerszenario:** The user copies 'notify.mobile_app_pixel' from Developer Tools → Actions into the option. A washing machine is detected and started later, and no push ever arrives. Verified: the generated call is ('notify', 'notify.mobile_app_christian', {...}).

**Fix-Vorschlag:** Normalize the value: strip a leading 'notify.' or 'notify/' and build f'notify/{name}'. Validate in the config flow with hass.services.has_service('notify', name). Fix the strings.json wording to list the events that actually notify.

**Beleg (Verifier):** Code:
- custom_components/aurum/modules/devices.py:1379, 1399-1401: the comment claims 'notify.mobile_app_christian' is supported, but the code does `svc = notify_svc if "/" in notify_svc else f"notify/{notify_svc}"`.
- custom_components/aurum/hass_bridge.py:51-53: `domain, service_name = service.split("/", 1); self._hass.add_job(self._hass.services.async_call, domain, service_name, kwargs)`. This is fire-and-forget, so the exception never reaches _notify's try/except.
- custom_components/aurum/config_flow.py:275-279: a plain TextSelector with no validation or normalization. coordinator.py:40, 67 passes the config through unchanged.
- _notify call sites: devices.py:292 (disabled), 337 (runtime target), 408 (deadline), 835/903/936/991 (SD), 1097 (preempt). The plain surplus on/off paths have none.
- Inaccurate wording: strings.json:108, translations/en.json:108, translations/de.json:108,  …

### 75. [LOW] Deadline set to 00:00 (disabled) is not restored; config deadline returns after restart
`custom_components/aurum/time.py:79` · ha-lifecycle · bug · Verdict: confirmed

**Beschreibung:** Out of my listed files but a restore-on-restart defect. Setting the time entity to 00:00 disables the deadline: _apply sets native_value=None, so the HA state becomes 'unknown'. On restart, async_added_to_hass skips restore for 'unknown', so the entity and dev['deadline'] keep the config-flow seed from __init__. The user's 'disabled' choice is lost and the configured deadline is active again. This is different from the documented trade-off where a restored value overrides a config edit.

**Fehlerszenario:** A dishwasher is configured with deadline 18:00 and runtime 120 min, and muss_heute is ON. The user sets the time entity to 00:00 to stop the grid fallback. HA restarts, the deadline is 18:00 again, and at 15:55 AURUM force-starts the dishwasher on grid power.

**Fix-Vorschlag:** Keep the disabled state restorable: keep native_value = time(0,0) with a 'disabled' attribute, or save a sentinel in extra_restore_state_data and restore None from it.

**Beleg (Verifier):** Code path:
- `custom_components/aurum/time.py:93-104`: `_apply` maps 00:00 to `deadline_str=None` and `_attr_native_value=None`. HA's `TimeEntity.state` then returns None, which is stored as "unknown".
- `custom_components/aurum/time.py:79-80`: `if last is not None and last.state not in (None, "unknown", "unavailable")`. An "unknown" state is never restored.
- `custom_components/aurum/time.py:61-74`: the constructor seeds `native_value` from the config deadline.
- `custom_components/aurum/modules/devices.py:162`: `"deadline": cfg.get("deadline")`. The device dict is rebuilt from config on each setup.
- `custom_components/aurum/modules/devices.py:1169-1204`: `_deadline_urgent` uses `dev["deadline"]`, gated only by `_is_muss_heute`.
- `custom_components/aurum/switch.py:70-82`: `muss_heute` is restored across restarts. Its docstring (lines 132-133) says it resets only after the program comp …

### 76. [LOW] Rolled-over restore only zeroes 3 counters; force_started survives a restart across the day boundary
`custom_components/aurum/modules/persistence.py:147` · ha-lifecycle · bug · Verdict: confirmed

**Beschreibung:** When the save predates the device's cycle start, restore zeroes runtime_today_s, energy_today_wh and total_switches. It then anchors _last_reset to the current cycle start, so daily_reset will not run this cycle. The rest of _reset_device_counters, in particular force_started=False (fix #4 of the 2026-07 audit), is never applied. A force_started=True from yesterday is restored as-is.

**Fehlerszenario:** A deadline-forced regular device without stop_after_runtime is still ON at 23:58. HA is down from 23:58 to 00:05. After restore force_started=True, so the device stays immune to surplus and SOC shedding for the whole new day, running on grid until the next midnight. This reintroduces the stuck non-sheddable device from audit #4 through the restart path.

**Fix-Vorschlag:** When rolled_over, call devices._reset_device_counters(dev), or at least clear force_started, instead of zeroing three fields by hand.

**Beleg (Verifier):** I reproduced it with scratchpad/audit/v0_force.py, using real DeviceManager and PersistenceManager with datetime frozen. I saved at 2026-07-09 23:58 with force_started=True and the switch on, then restored at 2026-07-10 00:05. Output: 'after restore: force_started= True runtime= 0 _last_reset= 2026-07-10 00:00:00', then 'after daily_reset(now): force_started= True', then '_should_turn_off with deficit: None' (SOC 5 < threshold 20, excess -3000 W).

### 77. [LOW] First weather-learning sample after every (re)start uses a partial hour, biasing learned factors low
`custom_components/aurum/coordinator.py:209` · ha-lifecycle · bug · Verdict: confirmed

**Beschreibung:** After a start or reload at, say, 10:37, budget.update takes its first PV snapshot mid-hour. At 11:00 it publishes the 10:37-11:00 production as pv_actual_hour_kwh and pairs it with the forecast for the full hour 10. update_weather_learning then learns a ratio of about 0.38 of the true value, clamped at 0.1 or more, and counts it as an observation.

**Fehlerszenario:** On setup day the user edits devices five times in different daytime hours, which means five reloads. That gives five low-biased samples for the current weather condition. After min_obs the EMA pulls the learned factor down and the budget becomes systematically smaller.

**Fix-Vorschlag:** Do not publish the delta for the first boundary after start (track a 'snapshot taken on an hour boundary' flag), or persist _pv_hour_snapshot_kwh and _pv_hour_snapshot_h together with the date.

**Beleg (Verifier):** scratchpad/audit/v1_weather.py: real BudgetManager with weather_entity=sunny, uniform PV of 3 kWh/h and a 3 kWh/h forecast for hour 10. First update at 10:37, next at 11:00:15. Output: '2026-07-09 11:00:15 actual 1.1499... fc 3.0 obs {'sunny': 1}', which is a ratio of about 0.38 counted as a valid observation. Code: budget.py:188-206 (snapshot and ended_hour pairing) and budget.py:515-545.

### 78. [LOW] Regional German UI locales (de-CH, de-AT) get English notifications
`custom_components/aurum/modules/devices.py:1369` · ha-lifecycle · ux · Verdict: confirmed

**Beschreibung:** _t looks up _NOTIFY_STRINGS[key].get(self.lang) with the full HA language code. 'de-CH' or 'de-AT' miss and fall back to English. The panel already uses startsWith('de').

**Fehlerszenario:** An HA UI set to Schweizerdeutsch (de-CH) receives '▶️ Waschmaschine is running now (PV surplus)'. Verified with a stub.

**Fix-Vorschlag:** Normalize with self.lang.split('-')[0].lower() before the lookup.

**Beleg (Verifier):** scratchpad/audit/v2_lang.py output: 'de' gives '... per Deadline gestartet (Netzstrom)', while 'de-CH', 'de-AT' and 'de_DE' each give '... started by deadline (grid power)'. Code: devices.py:97 (self.lang = getattr(hass,'language','en')), devices.py:1369 (variants.get(self.lang) or variants.get('en', key)).

### 79. [LOW] Diagnostics: KeyError when entry is not loaded; target/min SOC shown from config instead of live sliders
`custom_components/aurum/diagnostics.py:30` · ha-lifecycle · robustness · Verdict: confirmed

**Beschreibung:** hass.data[DOMAIN][entry_id] raises KeyError when the entry is in setup_retry or failed, which is exactly when users need a diagnostics dump. battery.target_soc_pct and min_soc_pct come from cfg (the config entry) instead of coordinator.battery.target_soc and min_soc, which the RestoreNumber sliders override.

**Fehlerszenario:** The user moved the Target SOC slider to 60 while the config says 80. The diagnostics report says 80, which misleads bug triage. During ConfigEntryNotReady retries, 'Download diagnostics' fails with a 500 error.

**Fix-Vorschlag:** Return a minimal payload (config with entity IDs and state) when the coordinator is missing, and read live values from coordinator.battery.

**Beleg (Verifier):** diagnostics.py:30 (hass.data[DOMAIN][config_entry.entry_id]), diagnostics.py:69-70 (cfg.get target_soc/min_soc). number.py:99-105 and 125-127 (_apply sets coordinator.battery.target_soc/min_soc only). __init__.py:219-222 (hass.data entry is populated only after a successful first refresh).

### 80. [LOW] CSVLogger only rotates at startup; the action log grows unbounded between restarts
`custom_components/aurum/modules/helpers.py:92` · ha-lifecycle · robustness · Verdict: confirmed

**Beschreibung:** _init_file, the only rotation point, runs once per process because of the _initialized flag. max_lines (5000) is only enforced at the first flush after HA starts.

**Fehlerszenario:** A long-uptime HA (months without restart) with several frequently switching devices lets aurum_actions.csv grow far beyond 5000 lines until the next restart.

**Fix-Vorschlag:** Track the written line count and rotate in flush() when it exceeds max_lines.

**Beleg (Verifier):** helpers.py:90-93 (if self._initialized ...: return; self._initialized = True), helpers.py:127-128 (flush calls _init_file only when not initialized), coordinator.py:89-95 (CSVLogger built in async_setup), coordinator.py:281-287 (flush every 2nd cycle, no rotation).

### 81. [LOW] PV power sensor is described as 'display only, can be left empty', but pv_power_threshold depends on it
`custom_components/aurum/strings.json:20` · entities-config · docs-mismatch · Verdict: confirmed

**Beschreibung:** config.step.user and options.settings data_description (en and de) say the PV power entity is 'Only used for display, not for calculations. Can be left empty' and '(optional, display only)'. DeviceManager reads shared['pv_power'] for _pv_gate_ok and the SOLAR_PV turn-off (devices.py:229, 597, 705). Without the entity, energy.py sets pv_power = 0, so any pv_power_threshold > 0 silently never fires. The pv_power_threshold description does not mention the dependency; only the README does. The config flow does not warn when a device has pv_power_threshold > 0 and no PV entity is configured. The house-consumption sensor also depends on the PV entity.

**Fehlerszenario:** Following the UI text, a user leaves the PV sensor empty and later sets the pool pump to 'Solar power threshold 1000 W'. On a sunny day with house load hiding the surplus, the pump never starts and the advisor shows 'waiting_surplus'.

**Fix-Vorschlag:** Update the pv_power_entity descriptions (en, de, strings) to say it is required for the solar-power threshold and house consumption. Validate in add/edit_device that pv_power_threshold > 0 requires a configured PV entity, or show a warning.

**Beleg (Verifier):** - custom_components/aurum/strings.json:20 and translations/en.json:20: "Only used for display, not for calculations. Can be left empty."
- strings.json:96: "(optional, display only)".
- translations/de.json:20 and :96: "nur zur Anzeige".
- modules/energy.py:60-64:
  if self.pv_power_entity: shared["pv_power"] = get_float(...)
  else: shared["pv_power"] = 0
- modules/devices.py:229: self._pv_power_now = shared.get("pv_power", 0)
- modules/devices.py:592-597: _pv_gate_ok returns self._pv_power_now >= threshold.
- modules/devices.py:638-647: SOLAR_PV turn-on.
- modules/devices.py:701-715: SOLAR_PV hold/release.
- sensor.py:644-651: house = pv + grid + bat_discharge - bat_charge.
- config_flow.py:669-745 (add_device / edit_device): no check of pv_power_threshold against pv_power_entity.
- strings.json:173 and de.json:173 (pv_power_threshold description): no mention that the PV sensor is requ …

### 82. [LOW] 'AURUM Energy Today' total is TOTAL_INCREASING but resets partially (per-device day_start_hour, device removal), so statistics double-count
`custom_components/aurum/sensor.py:340` · entities-config · bug · Verdict: confirmed

**Beschreibung:** AurumDeviceEnergyTotalSensor sums energy_today_wh across devices and declares ENERGY + TOTAL_INCREASING. Since v1.11, each device resets at its own day_start_hour, so the sum drops partway at each non-midnight reset hour. It also drops when a device is removed. The recorder interprets a drop of more than 10% as a meter reset and re-adds the remaining value. A drop of 10% or less is logged as 'not strictly increasing' and subtracted.

**Fehlerszenario:** Heater (day_start_hour 0) has 3000 Wh and the pool pump (day_start_hour 9) has 2000 Wh. At 09:00 the pump resets and the total goes 5000 -> 3000. HA detects a new cycle and the next statistics period adds the full 3000 Wh again, so the heater's morning energy is counted twice in long-term statistics.

**Fix-Vorschlag:** Give the total sensor state_class TOTAL with last_reset handling, or drop the state_class (keep it informational) and steer users to the per-device sensors. Alternatively, keep a monotonically increasing lifetime total that is independent of per-device resets.

**Beleg (Verifier):** custom_components/aurum/sensor.py:323-344 (TOTAL_INCREASING; total = sum of per-device energy_today_wh)
custom_components/aurum/modules/devices.py:1424-1431 (_reset_device_counters zeroes one device), 1439-1467 (per-device boundary from that device's day_start_hour)
custom_components/aurum/coordinator.py:235 (daily_reset(now) called every cycle)
strings.json:182 / translations: documented example of setting day_start_hour to 9 for a cheap-grid device; tests/test_day_start_hour.py:76-91 (independent resets)
Script: <scratch>/energy_total_stats.py (real DeviceManager, Heater at hour 0 and Pool Pump at hour 9, plus a replica of HA's TOTAL_INCREASING sum logic with the 0.9 reset threshold). Output:
  before 09:00: heater 3000.0 pump 2000.0 | total-sensor sum 3000.0 | per-dev sum 3000.0
  after 09:01: heater 3000.0 pump 0.0 total state 3000.0
  total-sensor LTS sum: 6000.0  per-device LTS sum …

### 83. [LOW] notify_service in the 'notify.xxx' format (what Developer Tools shows) silently breaks push notifications
`custom_components/aurum/config_flow.py:275` · entities-config · bug · Verdict: confirmed

**Beschreibung:** The notify_service description tells users to find the name under Developer Tools -> Services -> notify, where it appears as 'notify.mobile_app_x'. The config flow stores free text without validation or normalisation. DeviceManager._notify (devices.py:1401) builds svc = 'notify/' + value unless the value contains '/'. Its own comment claims 'notify.mobile_app_christian' is accepted, but the call becomes domain 'notify', service 'notify.mobile_app_christian' (checked with scratchpad/audit/notify_check.py). Because the call goes through hass.add_job, the ServiceNotFound only ends up as a background task error.

**Fehlerszenario:** The user enters 'notify.mobile_app_pixel', copied from the Actions page. Every AURUM push (program detected, deadline start, runtime reached) silently fails; only the persistent notifications appear.

**Fix-Vorschlag:** Normalise in the config flow: strip a leading 'notify.' or 'notify/' and validate with hass.services.has_service('notify', name), returning a form error if missing. Also strip the 'notify.' prefix in _notify.

**Beleg (Verifier):** Code:
- <local path> (docstring: "e.g. 'notify.mobile_app_christian'")
- devices.py:1399-1401:
  # notify_service can be "notify.mobile_app_christian" / or just "mobile_app_christian"
  svc = notify_svc if "/" in notify_svc else f"notify/{notify_svc}"
- <local path> domain, service_name = service.split("/", 1); self._hass.add_job(self._hass.services.async_call, domain, service_name, kwargs)
- <local path> free-text TextSelector. Neither config_flow.py:561-571 nor 646-654 normalises or validates the value.
- strings.json:108 / translations/en.json:108 / de.json:108: "Find it under Developer Tools → Services → notify" ("Entwicklerwerkzeuge → Aktionen → notify")

Repro, using the existing scratch scripts (a fake  …

### 84. [LOW] Deadline 00:00 means 'force-start now' from the config flow but 'disabled' on the time entity, and the meaning flips after restart
`custom_components/aurum/time.py:94` · entities-config · bug · Verdict: confirmed

**Beschreibung:** The config flow's TimeSelector stores '00:00:00'. The time entity's __init__ shows it as 00:00 but does not call _apply, so dev['deadline'] stays '00:00:00'. devices._deadline_urgent computes deadline_today = today 00:00, so now >= deadline and the device is force-started immediately once muss_heute is ON. The time entity documents 'Set to 00:00 to disable the deadline'. After a restart, the restored '00:00:00' state goes through _apply and becomes None, so the same configuration is disabled after a restart and active before it.

**Fehlerszenario:** The user picks 00:00 in the edit form, meaning 'by midnight' or 'none', and turns on 'Muss heute' at 10:00. AURUM immediately force-starts the 2 kW device on grid at 10:00. After the next HA restart the same setting no longer does anything.

**Fix-Vorschlag:** Use one meaning. Normalise '00:00(:00)' to None in _init_device/config_flow, or interpret 00:00 as end of day, and document it in the deadline description.

**Beleg (Verifier):** A throwaway script (scratchpad/audit/verify_deadline_midnight.py) built a DeviceManager with deadline '00:00:00' and estimated_runtime 120. Stored deadline = '00:00:00'. At 10:00 with muss_heute ON, _deadline_urgent = True, so it would force-start immediately. After setting dev['deadline']=None (what time._apply does with 00:00 on restore), it = False. The edit-form text says 'Leave empty if no time requirement', while time.py:42 says 'Set to 00:00 to disable the deadline'.

### 85. [LOW] binary_sensor.aurum_{slug}_active is ON while an SD program is paused (waiting/detected) and the plug is off
`custom_components/aurum/binary_sensor.py:64` · entities-config · ux · Verdict: confirmed

**Beschreibung:** is_on is set to state not in ('off','done','standby'). SD devices publish sd_state as their state, so 'waiting' (Shelly switched OFF, program paused for PV) and 'detected' report ON with device_class RUNNING. The advisor uses DEVICE_ACTIVE_STATES = ('on','running','manual_override') from const.py and calls the same situation 'program_paused'. The two contradict each other.

**Fehlerszenario:** The washer is paused in 'waiting' from 08:00 to 13:00. An automation on binary_sensor.aurum_washer_active ('washer is running -> announce / block other loads') fires at 08:00, five hours before the machine actually runs.

**Fix-Vorschlag:** Use DEVICE_ACTIVE_STATES: is_on = state in DEVICE_ACTIVE_STATES. If 'program pending' is needed, expose it as an attribute or a separate entity.

**Beleg (Verifier):** binary_sensor.py:64 `self._attr_is_on = state not in ("off", "done", "standby")`. devices.py:1228 `if dev["startup_detection"] and dev["sd_state"]: state = dev["sd_state"]`. devices.py:864-875: in WAITING the plug is enforced off every cycle. advisor.py:154-155 `if sd_state == SD_STATE_WAITING: return "program_paused"`. const.py:148 DEVICE_ACTIVE_STATES = ("on", "running", "manual_override").

### 86. [LOW] Translation gaps: initial setup step shows raw keys for the notify and price fields; missing or incorrect descriptions
`custom_components/aurum/strings.json:33` · entities-config · docs-mismatch · Verdict: confirmed

**Beschreibung:** _schema_battery (used in the initial config step 'battery') contains notify_service, price_entity, price_level_entity, cheap_period_entity and cheap_period_starts_in_entity. config.step.battery.data and data_description define only 5 keys, so first-time users see raw field names and miss the ct/kWh warning. en.json and de.json lack options.step.edit_device.data_description.pv_power_threshold, which only strings.json has; edit_device also lacks descriptions for price_mode, max_price and condition_op. The stop_after_runtime text says 'The counter resets at midnight' / 'Reset um Mitternacht', ignoring day_start_hour. The notify_service text promises pushes 'when devices are turned on/off', but only SD, deadline, disable, runtime and preempt events notify. The init step's device_list placeholder is hard-coded English.

**Fehlerszenario:** During initial setup, step 2 shows bare 'price_entity' and 'cheap_period_entity' labels with no hint that ct/kWh is required. A user with day_start_hour 9 reads that the runtime counter resets at midnight.

**Fix-Vorschlag:** Add the five keys to config.step.battery in strings, en and de. Sync edit_device descriptions into en and de. Replace 'midnight' with 'at the daily reset hour'. Fix the notify wording. Add a test that every schema key has a label in every translation file.

**Beleg (Verifier):** A key comparison script reported config.battery.data = ['battery_capacity_wh','battery_priority','min_soc','target_soc','update_interval'] in all three files. Missing edit_device descriptions: en/de ['condition_op','max_price','price_mode','pv_power_threshold'], strings.json ['condition_op','max_price','price_mode']. de edit stop_after_runtime: 'Reset um Mitternacht.' config_flow.py:612 `description = f"{len(self._devices)} devices configured"`.

### 87. [LOW] Editing a device silently drops legacy manual_override_entity / muss_heute_entity
`custom_components/aurum/config_flow.py:746` · entities-config · bug · Verdict: confirmed

**Beschreibung:** async_step_edit_device replaces the stored device dict wholesale with user_input. The schema no longer contains the legacy keys, which were removed from the UI in v1.5.0, but the code comment (config_flow.py:415-418) and devices.py promise they 'remain supported as fallback'. One edit for any reason erases them.

**Fehlerszenario:** A v1.4 install drives an input_boolean 'muss_heute' from an automation. The user edits the device to change its priority. The legacy key is gone and the automation no longer arms the deadline.

**Fix-Vorschlag:** Merge instead of replace: new = {**old_dev, **user_input}, with deliberate removal of keys the user cleared. Or migrate the legacy keys to the native switches once.

**Beleg (Verifier):** config_flow.py:746-749 `self._devices = [user_input if d["name"] == name else d for d in self._devices]`. config_flow.py:415-418 promises the legacy fallback. devices.py:142-143 `"manual_override_entity": cfg.get(...)`, `"muss_heute_entity": cfg.get(...)`. Commit 3baf7f5 message: 'Legacy manual_override_entity / muss_heute_entity configs remain supported as a transparent fallback'.

### 88. [LOW] Reserved-slug list is incomplete: device 'Excess' collides with the hub excess sensor, and removing a device named House/Target/Min/... deletes hub entities
`custom_components/aurum/config_flow.py:17` · entities-config · bug · Verdict: confirmed

**Beschreibung:** Slug 'excess' is not reserved, but its forced sensor.aurum_excess_power (device power) equals the hub 'AURUM Excess Power' id. In remove_device, the bounded-prefix match also claims hub object_ids for any device whose slug equals their first word: house (sensor.aurum_house_consumption), target and min (number.aurum_target_soc / min_soc), safety, forecast, electricity, current. Those are not in _RESERVED_SLUGS.

**Fehlerszenario:** The user adds a device 'House' (slug house) and later removes it. The remove step also calls ent_reg.async_remove('sensor.aurum_house_consumption'), so the hub sensor's registry customisations (name, area, entity_id) are lost when it is recreated.

**Fix-Vorschlag:** Derive the reserved set from the real hub object_ids and their first segments (excess, house, target, min, safety, forecast, electricity, current), or restrict remove_device to the known per-device suffixes.

**Beleg (Verifier):** config_flow.py:17-25 reserves 'excess_power', 'house_consumption', 'forecast_remaining', 'safety_factor', 'electricity_price' and 'current_decision', but not 'excess', 'house', 'target', 'min', 'safety', 'forecast', 'electricity' or 'current'. sensor.py:113-114 hub name 'AURUM Excess Power', no explicit entity_id. sensor.py:251 `self.entity_id = f"sensor.aurum_{slug}_power"`. number.py:94-95 / 120-121 'AURUM Target SOC' / 'AURUM Min SOC'. aurum-panel.js:18 `surplus: "sensor.aurum_excess_power"`, :41 `power: `sensor.aurum_${slug}_power``.

### 89. [LOW] House consumption sensor is computed with PV = 0 when no PV sensor is configured
`custom_components/aurum/sensor.py:652` · entities-config · bug · Verdict: confirmed

**Beschreibung:** house = pv + grid + discharge - charge, where pv defaults to 0 when pv_power_entity is unset. The PV entity is optional and described as display-only, yet the sensor always exists and reports a confident but wrong number.

**Fehlerszenario:** No PV sensor is configured. At noon with 2 kW export, sensor.aurum_house_consumption shows 0 W (clamped). With 300 W import it shows 300 W, although the house is using PV plus 300 W.

**Fix-Vorschlag:** Mark the sensor unavailable (via _AttrAvailabilityMixin) when pv_power_entity is not configured, or create it only when it is.

**Beleg (Verifier):** energy.py:63-64 `else: shared["pv_power"] = 0`. sensor.py:644-653 `pv = data.get("pv_power", 0) ... house = pv + grid + bat_discharge - bat_charge; self._attr_native_value = round(max(0, house), 1)`. sensor.py:79 sensor appended unconditionally.

### 90. [LOW] remove_device uses self.config_entry, which does not exist on HA < 2024.11, while hacs.json/README declare 2024.1+
`custom_components/aurum/config_flow.py:789` · entities-config · ha-integration · Verdict: confirmed

**Beschreibung:** AurumOptionsFlowHandler stores the entry in self._config_entry, but async_step_remove_device reads self.config_entry. Plain OptionsFlow only gained that property in HA 2024.11. hacs.json declares homeassistant 2024.1.0 and the README badge says 2024.1+.

**Fehlerszenario:** On HA 2024.6, 'Remove a device' raises AttributeError and the dialog shows 'Unknown error'; the device cannot be removed.

**Fix-Vorschlag:** Use self._config_entry.entry_id, or raise the minimum HA version in hacs.json and the README to 2024.11.

**Beleg (Verifier):** config_flow.py:593 `self._config_entry = config_entry`. config_flow.py:788-789 `er.async_entries_for_config_entry(ent_reg, self.config_entry.entry_id)`. hacs.json `"homeassistant": "2024.1.0"`. README.md:11 badge 'Home Assistant-2024.1+', README.md:67 'Home Assistant 2024.1.0+'.

### 91. [LOW] soc_is_fraction check rejects a real battery at exactly 1 %
`custom_components/aurum/config_flow.py:190` · entities-config · robustness · Verdict: confirmed

**Beschreibung:** The fraction heuristic flags any reading with 0 < val <= 1, even when the unit is '%'. Validation runs on the whole settings form, so a deeply discharged battery at 1% blocks saving any unrelated settings change.

**Fehlerszenario:** In winter the battery sits at 1% and the user tries to change update_interval or the price sensor. The form fails with 'reports battery level as 0-1 (fraction)'.

**Fix-Vorschlag:** Apply the fraction heuristic only when the unit is empty or missing, or require val < 1 together with a non-integer value.

**Beleg (Verifier):** config_flow.py:185-191 `if unit and unit not in _VALID_PERCENT_UNITS: ... elif _is_numeric(st.state): val = float(st.state); if 0 < val <= 1: errors[CONF_BATTERY_SOC_ENTITY] = "soc_is_fraction"`. config_flow.py:650 `errors = _validate_energy_sources(self.hass, user_input)` in async_step_settings.

### 92. [LOW] update_interval does not mean what the UI says; fixed cycle counts scale grace, control and persistence
`custom_components/aurum/strings.json:44` · entities-config · docs-mismatch · Verdict: confirmed

**Beschreibung:** The description says 'How often AURUM checks sensors and controls devices'. Devices are only controlled every 2nd cycle (coordinator.py:255). STARTUP_GRACE_CYCLES = 6 and persistence every 20 cycles are cycle counts, so at the allowed maximum of 300 s the startup grace is 30 min with no control, persistence runs every 100 min, and sd_detection_time (1-60 s) effectively becomes at least 2 x update_interval.

**Fehlerszenario:** With update_interval = 300 s, after a restart no device is controlled for 30 minutes. A crash loses up to 100 minutes of runtime, so a stop_after_runtime pool pump overshoots its daily target.

**Fix-Vorschlag:** Express grace and persistence in seconds (for example cycles = ceil(90 / interval)), document that devices are evaluated every 2 x interval, or cap update_interval at around 60 s.

**Beleg (Verifier):** coordinator.py:36 `STARTUP_GRACE_CYCLES = 6  # 6 × 15s = 90s sensor warmup`. coordinator.py:170 `startup_mode = self.cycle <= self.STARTUP_GRACE_CYCLES`. coordinator.py:255 `if self.cycle % 2 == 0:`. coordinator.py:289-290 `# ── Step 6: State persistence (every 5 min) ── if self.cycle % 20 == 0:`. config_flow.py:267-268 update_interval min=5 max=300. strings.json:44 'How often AURUM checks sensors and controls devices (in seconds)'.

### 93. [LOW] Advisor never looks at the override switch: the panel's Manual mode is explained as 'waiting for surplus', and a device AURUM will still shed is labelled 'manual override – AURUM hands off'
`custom_components/aurum/modules/advisor.py:129` · advisor-panel · docs-mismatch · Verdict: confirmed

**Beschreibung:** `_device_reason` returns `manual_override` only when the published state is 'manual_override', which devices.py sets when the device is physically on but `managed_on` is False. The actual override switch (`switch.aurum_{slug}_override`, the panel's 'Manual' mode) is not in `device_states` at all. That gives three wrong explanations: (a) override ON with the device off → devices.py skips the device every cycle (step 1) and AURUM will never start it, but the advisor says `waiting_surplus` ('Waiting for surplus'); (b) override ON with the device on after AURUM had started it (`managed_on` True) → state 'on' → reason `solar_surplus`/`cheap_grid` and headline 'Running on solar surplus', although AURUM no longer controls it; (c) override OFF with the device switched on outside AURUM → reason `manual_override`. The README (line 354) says this means 'You took over — AURUM hands off', but devices.py step 1b still evaluates such a device for turn-off and sheds it. For SD devices, override is not visible at all, because state is always the sd_state.

**Fehlerszenario:** (a) Simulated: Pool with override switch 'on', switch 'off', 3000 W surplus, SOC 90 % → the device stays off forever, and the advisor reports decision 'waiting' with reason 'waiting_surplus'. The panel shows the 'Manual' button active next to '→ waiting for surplus'. (c) Simulated: the user switches Pool on in the Shelly app at 20:00 with override OFF and -800 W surplus → the advisor shows '→ manual override' ('you took over'), and AURUM switches it off at ~20:20 (min_on_time + debounce_off).

**Fix-Vorschlag:** Publish `override: self._is_manual_override(dev)` (and `managed_on`) in `_publish_device_states`. In `_device_reason`, check `override` first (after `disabled`) and return `manual_override` whether the device is on or off. Map the on-but-unmanaged case to its own code (e.g. `external_on`: 'switched on outside AURUM – may be switched off on deficit') and document it in the README table and in the panel STRINGS.

**Beleg (Verifier):** Code:
- custom_components/aurum/modules/advisor.py:129-130: the only manual_override check, based on the state string.
- advisor.py:145-168: off-path checks that end in 'waiting_surplus'.
- custom_components/aurum/modules/devices.py:1217-1262: _publish_device_states has no override or managed_on field. Lines 1230-1232: state 'manual_override' = on && !managed_on.
- devices.py:297-304: override → continue, the device is never started.
- devices.py:306-314: on-but-unmanaged falls through to the turn-off check. Lines 383-391 and 474-522: _pending_off and shedding.
- custom_components/aurum/switch.py:87-95: the override toggle does not touch managed_on.
- custom_components/aurum/frontend/aurum-panel.js:679-686: reason line comes from the advisor. Lines 691-693: Manual button comes from the override switch.
- README.md:354 ("You took over — AURUM hands off") and README.md:294 contradict READM …

### 94. [LOW] Deadline time input commits every intermediate value, which can trigger an immediate deadline force-start
`custom_components/aurum/frontend/aurum-panel.js:635` · advisor-panel · ux · Verdict: confirmed

**Beschreibung:** The deadline `<input type=time>` sends `time.set_value` on every `change` event. In Chromium (and in segmented AM/PM locales), `change` fires each time a segment edit produces a complete valid time, not on blur. Partial edits are therefore committed. `_deadline_urgent` treats any deadline earlier than now as 'passed → force-start immediately (better late than never)' when muss_heute is ON. The max-price and PV-threshold inputs guard against empty input; the deadline input commits '00:00' (= disabled) on empty and commits partial values unguarded. Not verified in a real browser.

**Fehlerszenario:** Muss-heute ON, estimated_runtime 120, deadline 18:00, now 10:00. The user retypes the hour as '20' and pauses after the first digit. The panel sends 02:00:00, dev.deadline becomes '02:00', and if a device cycle runs before the '0' is typed, `now >= deadline_today` force-starts the device on grid with force_started=True (immune to shedding until runtime or daily reset).

**Fix-Vorschlag:** Commit the deadline on `blur` (or Enter), or debounce `change` by ~1.5 s and skip it while the input matches ':focus'. Optionally show that 00:00 means 'no deadline'.

**Beleg (Verifier):** Headless Chrome via CDP (script at <scratch>/time_change_probe.py), <input type=time value=18:00>, focused, real key events. de-DE: after '2' -> ["input:02:00","change:02:00"]; after '0' -> "change:20:00". en-US (12h): after '2' -> "change:14:00". Backspace -> change with value "". Backend check (deadline_probe.py): DeviceManager._deadline_urgent at 10:00 with muss_heute=True and estimated_runtime=120 returns 18:00 False, 02:00 True, 20:00 False. Panel code: deadlineInput.addEventListener('change', () => this._callService('time','set_value',{entity_id: e.deadline, time: (deadlineInput.value || '00:00') + ':00'})).

### 95. [LOW] Panel cosmetics and i18n: untranslated badge states, 'manual_override' has no colour, unknown shown as 'off', stale deadline field, power units assumed to be W
`custom_components/aurum/frontend/aurum-panel.js:650` · advisor-panel · ux · Verdict: confirmed

**Beschreibung:** (1) The badge shows raw state codes ('running', 'waiting', 'standby', 'manual_override') even in German; only the disabled case is translated. (2) STATE_COLOR has no 'manual_override' entry, so it falls back to grey. (3) An 'unavailable'/'unknown' status is rendered as 'off', which hides a sensor problem while the device may be running. (4) The deadline input is only overwritten when the entity holds a valid time, so if the deadline is disabled elsewhere (00:00 → state 'unknown') the old time stays visible. (5) The energy chip honours `unit_of_measurement`, but the power values (device power, PV, grid, surplus, house) are printed as 'W' even when the user switched the display unit to kW (1.2 kW shown as '1 W'). (6) Numbers are formatted with '.' regardless of locale.

**Fehlerszenario:** A German user sees 'manual_override' in a grey badge. Another user sets the deadline to 00:00 from the entity dialog to disable it; the panel still shows 'Fertig bis 18:00'. A user who set `sensor.aurum_pool_power` to display kW sees '⚡ 1 W'.

**Fix-Vorschlag:** Add `state_*` entries to STRINGS and a colour for manual_override; show '–'/'unavailable' instead of 'off'; clear the deadline input when the state is not a valid time; convert W/kW via `unit_of_measurement` the same way as for energy; use `toLocaleString(hass.locale.language)` for numbers.

**Beleg (Verifier):** aurum-panel.js updater: `let state = (this._st(e.status) || "off").toLowerCase(); if (state === "unavailable" || state === "unknown") state = "off"; badge.textContent = state;`. STATE_COLOR has keys running, on, waiting, standby, detected, done, off and disabled only. Deadline updater: `if (v && /^\d{2}:\d{2}/.test(v)) deadlineInput.value = v.slice(0, 5);`. time.py _apply: 00:00 sets deadline_str None, so _attr_native_value is None. sensor.py:193 AurumDeviceStatusSensor has no device_class or translation_key. sensor.py:238-240, 355-357, 376-378, 630-632 declare POWER with unit 'W'. The power chips format as `${Math.round(v)} W`.

### 96. [LOW] Panel rescans all HA states and rewrites every card on every hass update
`custom_components/aurum/frontend/aurum-panel.js:234` · advisor-panel · performance · Verdict: confirmed

**Beschreibung:** `set hass` → `_sync()` runs a regex over every entity_id in `hass.states` (`_devices()`), JSON-stringifies a signature, and then reruns every updater, assigning textContent and style for each card. This happens on every state change anywhere in Home Assistant, not only for AURUM entities. With thousands of entities, frequent updates and many devices, this is avoidable main-thread work and DOM churn.

**Fehlerszenario:** An install with ~3000 entities and fast-updating power sensors pushes several hass updates per second. The panel does an O(entities) scan plus a full re-render each time, even when no AURUM entity changed.

**Fix-Vorschlag:** Keep the previous `hass.states` object references for the AURUM entity ids the panel uses and return early when none changed. Rescan for devices only when the number of states changes or a `switch.aurum_*_override` appears or disappears. Skip DOM writes when the text is unchanged.

**Beleg (Verifier):** aurum-panel.js: `set hass(hass) { this._hass = hass; this._sync(); }`. _devices(): `for (const id of Object.keys(this._hass.states)) { const m = /^switch\.aurum_(.+)_override$/.exec(id); ...`. _sync() always ends with `this._update(devices)`, which loops over all this._refs updaters. Benchmark at <scratch>/scan_bench.js: 'per scan ms: 0.351' for 3010 entities.

### 97. [LOW] A lost or ignored turn-off is re-labelled as a manual start: no retry for min_on_time + debounce_off, a higher-priority device is shed instead, and the UI says 'manual override – AURUM hands off'
`custom_components/aurum/modules/devices.py:1148` · actuator-feedback · robustness · Verdict: confirmed

**Beschreibung:** _turn_off clears managed_on and on_since before the switch has confirmed. If the command is lost (common with Zigbee and WiFi) or ignored, the next cycle sees was_on=True with managed_on=False. Step 1b (311-313) then sets on_since=now, so the device is treated as freshly started by the user. min_on_time (679-682) and then debounce_off×penalty block a retry for about 20 min with defaults. Meanwhile the deficit it causes persists, so the shedding stage picks other candidates, including higher-priority ones. _publish_device_states reports it as 'manual_override', so the advisor tells the user they took over and AURUM is hands-off, and the actuator fault stays hidden.

**Fehlerszenario:** Verified (audit/af_lost_off.py). Heater 2000 W (prio 10) and pool pump 800 W (prio 80) are AURUM-managed, PV drops, and excess_raw is -1500 W. At 12:10:00 AURUM sheds the heater but the OFF is lost. From 12:10:30 the heater is published as 'manual_override'. At 12:20:30 the higher-priority pool is shed instead, and the heater OFF is only retried at 12:30:30. Result: 20 min of 2000 W from battery/grid and the wrong device shed. A single retry 30 s later would have fixed it.

**Fix-Vorschlag:** Keep managed_on until the switch has confirmed the new state, and store dev['_cmd'] = ('off', now). If the switch still reports 'on' on the next cycle, retry the OFF a bounded number of times with backoff instead of reclassifying the device as a manual start. After N failures, publish a 'switch_unresponsive' state or advisor reason and notify once.

**Beleg (Verifier):** Code:
- custom_components/aurum/modules/devices.py:1141-1159: `_turn_off` sets `managed_on=False` and `on_since=None` with no confirmation and no pending-command state.
- custom_components/aurum/hass_bridge.py:63-69: `services.call(..., blocking=False)`.
- devices.py:311-313: step 1b re-anchors `on_since=now` when was_on and not `managed_on`.
- devices.py:679-682: `min_on_time` gate.
- devices.py:751-764 with 774-791: `debounce_off` × penalty.
- devices.py:472-519: shedding only picks devices with `_pending_off`.
- devices.py:1230-1232: 'manual_override' label.
- advisor.py:129-130; README.md:354 ("You took over — AURUM hands off").
- devices.py:239-262 and 284-292: the charging emergency and disable paths retry every cycle, which limits the damage.
- const.py:129-130: defaults `DEBOUNCE_OFF` = 600 and `MIN_ON_TIME` = 600.

Repro 1: the reviewer's script <scratch>/af_lost_off.py (30 s st …

### 98. [LOW] _notify accepts throttle_key and importance but ignores both: there is no de-duplication or rate limit for mobile pushes
`custom_components/aurum/modules/devices.py:1375` · actuator-feedback · ux · Verdict: confirmed

**Beschreibung:** The signature suggests throttling, but every call sends a persistent_notification and, if configured, a mobile push. The persistent notification is de-duplicated by notification_id. The push is not: on Android the companion app replaces a tagged notification but alerts again each time unless alert_once is set. This makes every repeated control decision a push storm: the deadline retry loop (120/h), the disable enforcement (120/h), runtime_target_reached with a relay that does not turn off (a push and a muss_heute reset every min_on_time), and SD phantom detect/finish cycles. No caller passes throttle_key.

**Fehlerszenario:** notify_service configured, dryer with muss_heute and an offline plug in its deadline window: 120 identical '⚠️ dryer started by deadline' pushes per hour (af_deadline_user_off.py, critic_deadline_dead_plug.py).

**Fix-Vorschlag:** Implement throttling: keep a {tag: last_sent} map and suppress a push with the same tag within e.g. 15-30 min, or only when the message text changes. Default throttle_key to tag. Either use importance (e.g. data.priority / alert_once for Android) or remove the unused parameters.

**Beleg (Verifier):** devices.py:1375 `def _notify(self, message, tag=None, throttle_key=None, importance=None):` and neither parameter appears in the body (1382-1410). Push: `push_kwargs['data'] = {'tag': tag}; self.hass.call_service(svc, **push_kwargs)` with no throttle or alert_once. Grep for `throttle_key` across custom_components/aurum finds only line 1375. Deadline loop: devices.py:401-411 together with `_deadline_urgent` 1192-1204, where the force_started check applies only after the deadline. Control cadence: coordinator.py:255 `if self.cycle % 2 == 0`, with the default update_interval of 15 s. Repro output: critic_deadline_dead_plug.py printed 'ON commands in 1 h: 70 / push notifications: 70 / force_started: True' (window opens at 16:25 for deadline 18:00 with 90 min runtime). af_deadline_user_off.py printed 'total pushes 11' with an ON command and a push every 30 s from 16:40 to 16:44:30.

### 99. [LOW] A single unavailable grid sample resets the shed timer, so a flaky meter keeps a device on grid indefinitely
`custom_components/aurum/modules/devices.py:771` · input-failure-matrix · bug · Verdict: confirmed

**Beschreibung:** _should_turn_off needs a continuous deficit for debounce_off x penalty. Any cycle without a deficit clears _excess_deficit_since (line 771), and _soc_grid_deficit_since (line 730) the same way. Because an unavailable grid sample is read as 0 W, excess_raw becomes 0, which is not < -hysteresis_off. So one bad sample restarts the 600 s countdown. The known coordinator.py:170 item covers a continuous outage. This is a separate, broader consequence: shedding stops working even when the sensor is available about 97 % of the time. The same reset happens with a discharge sensor that blips while the battery feeds the devices.

**Fehlerszenario:** Heater 2000 W, debounce_off 600 s, running at 15:00 when PV fades, so the grid imports 2 kW. The meter (Wi-Fi Shelly or a polling cloud API) reports 'unavailable' for one 15 s sample every 6 or 10 minutes. With a clean meter the heater is shed at 15:10. With the blips it is never shed during the 2 h simulation and keeps importing 2 kW (scratchpad/audit/ifm/f_blip.py: blips every 360 s or 600 s give 'never'; blips every 660 s or more shed at 15:10).

**Fix-Vorschlag:** Treat an unavailable reading as 'no information' rather than 'no deficit'. Hold the last valid grid value (or skip the turn-off evaluation) for the cycles where the input is missing, so that deficit timers are neither cleared nor advanced by a missing sample. This is the same root fix as for the 0 W substitution.

**Beleg (Verifier):** Code path:
- custom_components/aurum/modules/helpers.py:17-18: an unavailable state returns the default.
- modules/energy.py:43: grid_raw = get_float(..., 0), with no hold. Compare the SOC hold at energy.py:67-82.
- energy.py:127 sets excess_raw = -grid_raw (energy.py:119-120 when battery sensors are configured).
- modules/battery.py:39-40 and 59-60 pass it through.
- coordinator.py:255: devices.update runs only when cycle % 2 == 0.
- devices.py:386-390: turnoff_excess = excess_raw - newly_allocated goes into _should_turn_off.
- devices.py:756-771: the excess-deficit timer is cleared when available_excess >= -hysteresis_off.
- devices.py:719-730: the SOC-deficit timer is cleared the same way.
- const.py:127,129: hysteresis_off defaults to 100 W, debounce_off to 600 s.
- tests/: no test covers an unavailable grid sensor (grep found only price-unavailable tests).

Repros:
- The reviewer's  …

### 100. [LOW] Frozen PV power keeps a PV-gate device running on battery for hours, because the gate release bypasses the deficit checks
`custom_components/aurum/modules/devices.py:705` · input-failure-matrix · robustness · Verdict: confirmed

**Beschreibung:** For a device started by the PV gate (_scheduling_reason=solar_pv), _should_turn_off returns None as long as pv_power >= threshold - hysteresis_off and SOC >= soc_threshold. That check runs before the SOC-grid and excess-deficit blocks. _pv_gate_ok also starts devices without looking at surplus or budget. An unavailable PV sensor reads 0 and fails safe. A PV sensor that freezes on its last daytime value does not: the device runs on battery (or grid) until SOC falls below the device's soc_threshold. Examples are OpenDTU/MQTT without expire_after or zeroing at night, and inverter or cloud integrations that keep the last value when the inverter sleeps.

**Fehlerszenario:** Pool pump 800 W with pv_power_threshold 1000 and soc_threshold 25 (the README example), a 10 kWh battery with legacy surplus and live battery sensors, SOC 85 % at 17:00. Real PV drops to 0 but the PV sensor stays at 2500 W. With a live PV sensor the pump stops at 17:10 (SOC 82.9 %). With the frozen sensor it runs until 22:10 and drains the battery to 22.9 %, even though the legacy surplus has been about -1200 W the whole time (scratchpad/audit/ifm/c_pv_frozen_gate.py).

**Fix-Vorschlag:** Apply the same freshness check to pv_power_entity and treat a stale value as 0 for the gate. Also keep a battery-drain guard inside the PV-gate hold: if excess_raw < -hysteresis_off persists for debounce_off while PV is claimed above the threshold, release the gate. That combination is physically implausible and indicates a bad PV reading.

**Beleg (Verifier):** - custom_components/aurum/modules/devices.py:229 sets self._pv_power_now = shared.get("pv_power", 0).
- devices.py:701-707 is the solar_pv hold: `if self._pv_power_now >= off_level and soc_ok: ... return None`. It runs before the SOC-grid block (719) and the excess-deficit block (756).
- devices.py:582-597: _pv_gate_ok ignores surplus and budget, and returns False when SOC < 0.
- custom_components/aurum/modules/energy.py:60-62 reads pv_power with get_float(...,0) and no staleness check. Grepping for stale|last_updated|last_changed|last_reported finds no freshness logic.
- Reviewer repro, run unchanged (<scratch>/ifm\c_pv_frozen_gate.py):
  "PV frozen=False: pool off at 17:10 SOC 82.9%"
  "PV frozen=True: pool off at 22:10 SOC 22.9%"
  The battery stops just under the device's soc_threshold of 25.
- Frozen-grid comparison, same class of gap and worse (<scratch>/ifm\b_grid_frozen.py):
  "f …

### 101. [LOW] Run-condition entity: a non-numeric state is treated as 'condition met', with no config validation
`custom_components/aurum/modules/devices.py:543` · input-failure-matrix · robustness · Verdict: confirmed

**Beschreibung:** _condition_met uses get_float(default=None) and returns True for None. That covers unavailable and unknown (documented as fail-open) but also any non-numeric state. The selector allows any sensor, including enum or text sensors (e.g. 'heating'/'idle', 'on'/'off'), and the flows never check that the entity is numeric. Such a condition is silently ignored forever, and the advisor never shows condition_not_met. A frozen numeric value (stale temperature) is also acted on indefinitely; the README only mentions the unavailable case.

**Fehlerszenario:** The user picks sensor.boiler_state (enum: 'heating'/'ready') with 'below 1', expecting the heater to stop when the boiler is ready. get_float returns None for 'ready', so the condition is always met, and the heater runs whenever there is surplus, including after the boiler is satisfied. The advisor never reports condition_not_met.

**Fix-Vorschlag:** In add_device and edit_device, reject a condition_entity whose current state is non-numeric (as _is_numeric does for the hub). At runtime, log a warning once when the condition entity is non-numeric. Optionally publish condition_met=None ('unknown') so the advisor can show 'condition sensor unavailable' instead of silently running.

**Beleg (Verifier):** devices.py:543-545 `current = get_float(self.hass, entity, default=None)` / `if current is None: return True`. helpers.py:19-22 returns the default on ValueError. config_flow.py:110 `_SENSOR = selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor"))` is used at line 425 for CONF_DEV_CONDITION_ENTITY, and no validator touches it. A scratch run of get_float(default=None) gave 'ready'->None, 'heating'->None, 'on'->None, '42.5'->42.5, so every enum state is treated as condition met.

### 102. [LOW] README's sign-flip template uses float(0), which turns a meter outage into a live 0 W reading
`README.md:482` · input-failure-matrix · docs-mismatch · Verdict: plausible

**Beschreibung:** The troubleshooting section recommends `state: "{{ -1 * states('sensor.your_grid_sensor') | float(0) }}"` for inverted meters. When the source meter is unavailable, the template reports 0 W as a valid, fresh value. That bypasses even the startup _entities_ready check and would defeat any future unavailable or staleness handling. AURUM sees a perfectly balanced grid, so running devices are never shed and the user sees nothing wrong.

**Fehlerszenario:** A user with an inverted meter follows the README. The meter goes offline at 16:00 with a 2 kW heater running. The template sensor reports 0 W (not unavailable), so AURUM keeps the heater on grid for the whole outage, and even a fixed AURUM could not detect it.

**Fix-Vorschlag:** Change the example to add `availability: "{{ has_value('sensor.your_grid_sensor') }}"` and use `| float` without a default (or keep it guarded by the availability template), so the derived sensor goes unavailable together with its source.

**Beleg (Verifier):** README.md:482 template with `| float(0)` and no availability key. energy.py:43 `grid_raw = get_float(self.hass, self.grid_power_entity, 0)`. In a scratch run, EnergyManager.update with the grid state 'unavailable' gave excess 0 / excess_raw 0, and with '-0.0' gave excess 0.0, so both paths are identical. coordinator.py:36 STARTUP_GRACE_CYCLES = 6, and coordinator.py:170-192 return early in startup mode with devices_on=0 in both branches.

### 103. [LOW] Production end is taken from the start of the last forecast slot; with hourly data (Open-Meteo, Solcast detailedHourly) the budget spikes to ~7 kW and then reports 'after_sunset' 1–1.5 h early
`custom_components/aurum/modules/budget.py:571` · provider-data-contracts · bug · Verdict: confirmed

**Beschreibung:** `_hours_until_sunset()` uses `hour > current_hour` and `last_production_hour = hour`, where `hour` is the slot START. The Open-Meteo `watts` branch also averages the four 15-min instantaneous values into hour buckets (lines 811–821). The last bucket above 50 W therefore starts up to 1 h before production actually ends, and the final partial hour often averages below 50 W and drops out completely. As `hours_remaining` approaches 0 while `pv_forecast_entity` still reports the energy of that last hour, `budget_wh / hours_remaining` blows up. At the bucket start the result becomes 0 with reason 'after_sunset'. With Solcast `detailedForecast` (30 min) the error is about 0.5 h and harmless in practice. With `detailedHourly` only (half-hourly attribute disabled in Solcast) or with Open-Meteo it is about 1–1.4 h. The 50 W cut-off is absolute regardless of array size.

**Fehlerszenario:** rany2 Open-Meteo `energy_production_today` payload (watts dict with ISO keys, +02:00), June 21, 10 kWp-class profile, SOC 78 %, target 80 %. At 15:00 `hours_until_sunset` = 5.00, but production runs until about 21:24 (6.4 h). At 19:45 the budget is 1284 W. At 19:58 it is 7015 W (hours_remaining 0.03, remaining 0.53 kWh), which effectively lifts the cap, so any device can start. At 20:00 it is 0 W 'after_sunset' while PV is still 811 W and 0.49 kWh are forecast.

**Fix-Vorschlag:** Treat each forecast entry as an interval. Detect the slot length from consecutive timestamps (15/30/60 min). Use `hour + slot_len > current_hour` and `last_production_hour = hour + slot_len`, and don't average the Open-Meteo `watts` into hour buckets for this purpose, or use `wh_period_15m`. Consider a threshold relative to the day's peak, e.g. 2–3 % of max, instead of a fixed 50 W. Also clamp the divisor, e.g. `max(hours_remaining, 0.25)`, so the budget cannot explode as the window closes.

**Beleg (Verifier):** Code:
- <local path> (`if watts > 50 and hour > current_hour: last_production_hour = hour`, i.e. the slot start)
- budget.py:811-821 (Open-Meteo `watts` averaged into `dt.hour` buckets)
- budget.py:831, 853 (period start used as `hour`)
- budget.py:298-308 (`after_sunset` → 0; `budget_wh / hours_remaining`)
- budget.py:304 (consumption estimated only over the shortened window)
- budget.py:262 (SOC at or above target returns None before the sunset check)
- devices.py:432-447 (the cap only blocks starts; exemptions for grid-only mode, pv_gate and price_grant)
- devices.py:649-665 (a start still needs real excess and debounce)

Repro: <scratch>/sunset_slot.py and <scratch>/sunset_slot_steep.py. Setup: 7.5 kW peak profile on 2026-06-21, SOC 78 %, target 80 %, 10 kWh battery, 500 W consumption.

- Solcast `detailedHourly` only (sc …

### 104. [LOW] README says Nordpool provides a price level, but it has none; picking it as price_level_entity silently disables cheap-grid scheduling
`README.md:214` · provider-data-contracts · docs-mismatch · Verdict: confirmed

**Beschreibung:** README 'Works with' says 'Nordpool — price sensor + price level'. In custom-components/nordpool, sensor.py exposes only a numeric price state (EUR/kWh, or cents with `price_in_cents`) plus attributes such as `low_price` (bool) and `price_percent_to_average`. There is no level enum. HA core's Nord Pool integration has no level sensor either. `PricingManager.update()` only accepts states in `_LEVEL_ORDER`. A numeric state becomes `price_level=None` and does not set `data_available`. If the level entity is the only price source, which README encourages ('Set [max_price] to 0 to use price level / cheap period instead'), `should_run_on_grid()` returns None permanently. No warning is given, and the advisor hides price context because `price_data_available` is False. This is distinct from the already-reported uppercase-level issue: here the vocabulary is entirely absent.

**Fehlerszenario:** price_level_entity = sensor.nordpool_kwh_de_eur_3_10_019 (state '0.123'), no price_entity, device on cheap_grid with max_price 0. Feeding this through PricingManager gives level=None, price_data_available=False, should_run_on_grid=None on every cycle. The device never gets a price grant, even at negative prices, and nothing in the UI says why.

**Fix-Vorschlag:** Fix the README. Nordpool supplies a price sensor, so use `price_entity` with `price_in_cents: true` and a device `max_price`. Optionally add a template example that maps `low_price`/`price_percent_to_average` to cheap/normal. In the settings step, validate `price_level_entity`: warn if its state, or `options` for ENUM sensors, is not a subset of very_cheap…very_expensive. Log a one-time warning at runtime when a configured level entity reports an unknown value.

**Beleg (Verifier):** - <local path> "[Nordpool](https://github.com/custom-components/nordpool) — price sensor + price level". Lines 159 and 170-171 tell the user to "leave `max_price` at `0` and rely on the price level / cheap period instead".
- Upstream custom-components/nordpool sensor.py (master, fetched): one sensor, `self._attr_native_value = self.current_price`, device_class MONETARY. The attributes have no level enum, only `low_price` (bool: current_price < average * low_price_cutoff) and `price_percent_to_average`.
- <local path> `if raw and raw in _LEVEL_ORDER:` is the only place that sets price_level and data_available. pricing.py:171-172: `if not self._last_data_available: return None`.
- <local path> `if not self.pricing or self.pricing.should_ru …

### 105. [LOW] Tibber Prices 'best price starts in' reports hours (suggested unit), but AURUM shows it as minutes
`custom_components/aurum/modules/pricing.py:126` · provider-data-contracts · ha-integration · Verdict: confirmed

**Beschreibung:** README and strings.json recommend tibber_prices 'Bestpreis startet in' (`sensor.tibber_bestpreis_startet_in`) for `cheap_period_starts_in_entity`. That entity is `best_price_next_in_minutes`: device_class DURATION, `native_unit_of_measurement=MINUTES`, `suggested_unit_of_measurement=HOURS`, display precision 2. HA therefore registers it in hours and the state is e.g. '2.25'. `PricingManager.update()` reads the raw float without looking at `unit_of_measurement` and publishes `round(2.25)` = 2 as `cheap_period_starts_in_min`. That value appears as the `cheap_period_starts_in_min` attribute on sensor.aurum_electricity_price and on per-device sensors.

**Fehlerszenario:** The cheap window starts in 2 h 15 min. The tibber_prices state is '2.25' (unit h). AURUM's attribute `cheap_period_starts_in_min` = 2, so dashboards and automations see 2 minutes. A countdown under 1 h (e.g. 0.4 h) rounds to 0.

**Fix-Vorschlag:** Read `unit_of_measurement` and convert h/s/d to minutes; for DURATION sensors HA's `DurationConverter` can do it. Alternatively accept a TIMESTAMP sensor (`best_price_next_start_time`) and compute the minutes. Document that the entity's display unit must be minutes otherwise.

**Beleg (Verifier):** pricing.py:124-126 `raw = get_float(...); cheap_starts_in = round(raw)` with no unit check. Upstream tibber_prices definitions.py:934-942: `key="best_price_next_in_minutes", device_class=SensorDeviceClass.DURATION, native_unit_of_measurement=UnitOfTime.MINUTES, suggested_unit_of_measurement=UnitOfTime.HOURS, suggested_display_precision=2`. Upstream de.json: best_price_next_in_minutes -> 'Bestpreis startet in'. README.md:161 recommends sensor.tibber_bestpreis_startet_in as 'Minutes until next cheap period'. example_dashboard.yaml:143 shows '{{ starts }} min'.

### 106. [LOW] Docs name a Solcast `forecast` attribute that does not exist; the parser checks it first and doesn't fall through when it is malformed
`custom_components/aurum/modules/budget.py:839` · provider-data-contracts · docs-mismatch · Verdict: confirmed

**Beschreibung:** README:144 and the strings.json description of `pv_forecast_today_entity` say: Solcast 'Forecast Today' with `forecast` attribute. Current BJReplay Solcast publishes `detailedForecast` (30-min) and `detailedHourly` on the forecast-day sensors. `period_start` is a tz-aware datetime in HA's zone and `pv_estimate` is the average kW of the period. There is no `forecast` attribute. The parser still works because it also tries `detailedForecast`. However, it stops at the first attribute name present. If an entity has a `forecast` list whose entries lack `period_start`, it returns None (19:00 fallback) instead of trying `detailedForecast`. It also always uses `pv_estimate`, while the Solcast state and the 'remaining' sensor may be configured to `pv_estimate10`/`90`.

**Fehlerszenario:** A user searches for a `forecast` attribute as the README says, doesn't find it on any Solcast entity, and leaves the field empty or picks 'Forecast Remaining Today'. The budget then silently runs on the 19:00 fallback (see the fallback finding).

**Fix-Vorschlag:** Change README/strings.json to name `detailedForecast`/`detailedHourly`, and Open-Meteo `energy_production_today` with `watts`. In `_get_hourly_forecast`, iterate over all candidate attributes and use the first one that yields at least one parsed entry.

**Beleg (Verifier):** budget.py:837-859: `for attr_name in ("forecast", "detailedForecast", "detailedHourly"): if attr_name in attrs: forecast_data = attrs[attr_name]; break` and later `watts = float(entry.get("pv_estimate", 0)) * 1000`. Upstream Solcast const.py: DETAILED_FORECAST='detailedForecast', DETAILED_HOURLY='detailedHourly'; forecast.py builds result with DAY_NAME, DATA_CORRECT, ANALYSIS, DETAILED_FORECAST, DETAILED_HOURLY and no 'forecast' key. Scratch script output: 'solcast detailed: [(7.0, 1200.0), ...]' and 'malformed forecast first: None'.

### 107. [LOW] PV-actual unit heuristic flips per sample for unitless Wh counters: 3 Wh read as 3 kWh, then misdetected as a lifetime counter
`custom_components/aurum/modules/budget.py:596` · provider-data-contracts · robustness · Verdict: confirmed

**Beschreibung:** `is_wh = (unit == 'Wh' or (unit is None and raw > 500))` is decided per reading. For a daily Wh counter without a unit (template sensor; `_check_energy` accepts unitless), morning values ≤ 500 are taken as kWh. Values above 100 then trigger the 'lifetime counter' snapshot (`_pv_total_midnight = raw`, which is persisted), and from 501 Wh on the same counter is treated as Wh minus a snapshot recorded in the other unit. The wrong actual feeds `_get_inday_correction` (pinned at the 1.5 clamp) and `pv_actual_hour_kwh` for weather learning (ratio pinned at 1.5).

**Fehlerszenario:** Unitless daily PV counter, fed through `_get_pv_today_kwh`. raw 3 gives 3.0 kWh (true 0.003). raw 80 gives 80.0. raw 120 gives 0.0 and snapshot=120. raw 450 gives 330.0 kWh. raw 501 gives 0.381 (true 0.501). raw 9000 gives 8.88 (true 9.0) for the rest of the day.

**Fix-Vorschlag:** Decide the unit once per day, or only from `unit_of_measurement`. Treat a missing unit as kWh, or reject unitless energy sensors in `_validate_energy_sources`. Never mix units between `_pv_total_midnight` and later readings.

**Beleg (Verifier):** Scratch script against the real BudgetManager: '3 -> 3.0 snapshot None', '80 -> 80.0', '120 -> 0.0 snapshot 120.0', '450 -> 330.0', '501 -> 0.381', '9000 -> 8.88'. budget.py:596 `is_wh = (unit == "Wh" or (unit is None and raw > 500))`; budget.py:605-606 `if (is_wh and raw > 100_000) or (not is_wh and raw > 100): self._pv_total_midnight = raw`; config_flow.py:168-170 only rejects a non-empty wrong unit.

## Widerlegt

- `custom_components/aurum/modules/devices.py:1188` Deadline is anchored to the calendar day and ignores day_start_hour, so muss_heute set after the deadline time causes an immediate grid start — The mechanics described are accurate: _deadline_urgent builds the deadline with now.replace(hour, minute) on the calendar day, and once now >= deadline it returns True as long as force_started is False. My scratch repro confirms that at day_start_hour=9, deadline 07:00, runtime 240, muss_heute armed at 20:00, the device goes through update() and is switched on with reason deadline_forced and force_started=True.

It is still not a bug, for four reasons.

1. day_start_hour does not cause it. With day_start_hour=0 the same config armed at 20:00 is also urgent=True, the identical immediate start (repro test_urgent_at_20_with_dsh0). The scenario is really "the user arms the must-run-today switch in the evening, meaning tomorrow morning". The design does not support that for any reset hour.

2. The documented meaning is calendar "today". day_start_hour is described only as the hour when "this device's runtime/energy counters reset" (strings.json/en.json/de.json:182, README:121). Its documented use is cheap_grid top-up overnight, not deadlines. The deadline is "Time by which the device must have run (e.g. 18:00)" (README:118). muss_heute is "Force device on today" (README:295). The Adviso

---

# Gap-Analyse: Was müssen solche Systeme können?

## Stärken von AURUM
- Explainability is better than anything else in the HA/OSS space. sensor.aurum_current_decision gives a stable, machine-readable reason code per device and is usable in automations. The sidebar panel shows the same reasons localised. The attributes are deliberately free of fast-changing values, so they don't bloat the recorder. Solar Optimizer only has card badges and PVEC only has status text; neither offers a reason sensor that automations can read.
- Startup detection for program appliances is power-based and close to unique. AURUM keeps the plug on in standby, detects a program start, pauses it, resumes it on PV surplus, falls back to the grid at a deadline and preempts lower-priority devices. Among the compared systems only SMA does something similar, and SMA needs SEMP/EEBus appliances for it.
- Onboarding needs no YAML: a config flow with unit validation and a check that rejects a 0–1 SOC fraction, a built-in panel that adapts to the configured devices, and auto-created override / must-run / disable switches. It is in the HACS default store, ready for the HA 2026.11 Marketplace, and translated EN/DE. This directly answers the top complaint about EMHASS, Predbat and PVEC, which is setup complexity.
- Battery gating is layered cleanly. There are three global modes, a per-device SOC threshold that falls back to grid-export-only surplus below the threshold, and a battery_priority toggle. Three explicit price modes exist, including cheap_grid_soc. An SOC outage holds the last value (audit fix #10 is intact). After v1.15.1 the budget cap and the price grant use the same _price_grant predicate.
- The anti-flapping toolkit is complete for a rule engine: asymmetric EMA for turn-on and raw values for turn-off, hysteresis and debounce in both directions, min on/off times, a relay switch-penalty multiplier, and priority shedding with a minimal-victim second pass. Unavailable price data holds the current state (tri-state should_run_on_grid) instead of oscillating.
- PV-forecast budget: remaining forecast, in-day correction, weather learning, trajectory multiplier and a persisted safety factor. pv_power_threshold is an explicit escape hatch, and stop_after_runtime, day_start_hour and run conditions cover real community use cases (pool pump, water heater).
- Manual-control semantics are explicit and kept. The README table distinguishes override from manually-on. The disable kill-switch wins over everything. The override is honoured even in the battery emergency. Sliders and deadlines are RestoreNumber/RestoreEntity. On restore, persistence cross-checks against the real switch state.
- Engineering hygiene: the decision core is pure Python behind an HA bridge, so it runs without HA. There are 227 tests, including full-day 15-second simulations. Diagnostics can be downloaded. Everything runs locally with no cloud and no vendor lock-in. I re-checked audit fixes #2–7, #10–12, #14, #15, #17 and #18; all are still in place, so no regression was found.

## Positionierung

AURUM belongs to the rule- and priority-cascade class, alongside Hanergy, openWB SmartHome and PVEC's real-time controller. It is not an optimiser: EMHASS, HAEO, Predbat and the evcc optimizer belong to that class, and AURUM should not chase them. Field data in report B (MPC gains of 0.8–2.5 % measured vs 6–16 % simulated) supports this choice.

Within its class AURUM leads on three things: explainability, power-based handling of washing machines and dishwashers, and zero-YAML onboarding with a built-in panel. It also has forecast budgeting and battery gating, which Solar Optimizer and Hanergy lack.

PVEC is the closest competitor. It has all of AURUM's basics plus a 24 h planner, export-limit management, discharge protection, EV current control, analytics and 1,289 tests. Against PVEC, AURUM is leaner and more transparent but behind on look-ahead, export and negative-price handling, variable-power devices and cost reporting.

Solar Optimizer is ahead only on variable-power devices and global packing. It has no forecast and no battery logic, and its 5-minute cycle is slow.

evcc owns EV charging and should be treated as a partner AURUM coexists with, not as a target.

The defensible position is 'the explainable, fail-safe, zero-YAML surplus and cheap-hour router for on/off household loads that also tells you when it will run'. To hold it, AURUM needs four things:
- the verified correctness fixes;
- fail-safe inputs;
- a negative-price / export rule;
- cost reporting and a light cheapest-slot planner.

Variable-power devices are the one place where the on/off-only constraint itself is the gap; a minimal number-entity sink for heating rods would cover the most common case without taking on EV complexity.

The HELIOS ideas that would work generically:
- the watchdog checks (stale grid sensor, power-balance plausibility, command vs reality);
- the economics tracker;
- negative-price window handling;
- percentile-based price thresholds and grid-fee windows from pricing.py;
- a p10-plus-load-profile reserve.

The rest of HELIOS is hardware-bound and out of scope.

## Top-Empfehlungen
- 1. Ship a bug-fix release (v1.15.4, every item effort S) for the verified defects. (a) A deadline force-start ends when its remaining runtime is done, and the deadline window accounts for runtime already accrued; today a must-run device can run on grid from the deadline window until 00:10. (b) Keep _scheduling_reason across the daily reset and across a restart, so cheap-grid and PV-gate devices are not shed and restarted at midnight or after a reboot. (c) Normalise units (kW to W, Wh to kWh, EUR to ct), which also defuses the documented price trap. (d) Make program_done reachable, and decide explicitly whether the battery emergency may switch off non-interruptible devices. (e) Let the PV gate work on installs without a battery. Every item has a reproducing probe in <local path> and should become a regression test.
- 2. Fail-safe inputs (v1.16). Detect a stale or unavailable grid meter via last_reported and apply a defined safe state: no new starts, release surplus-only devices after a timeout, keep programs and deadline jobs running. Stay in startup mode until SOC is fresh instead of falling into charging mode. Stop sending turn_on to unavailable switches. Surface all of this as Advisor reasons and HA repair issues. This closes report B's #1 failure mode: a device runs for hours on a frozen meter.
- 3. Make priority and shutdown behave as the README promises. A higher-priority regular device should displace running lower-priority devices, with a dwell to prevent ping-pong. Apply the switch penalty to turn-on only, bound the off tolerance by energy, and add a settle window after each switch. Today a priority-30 pump can block a priority-90 heater all day, and a flapping device can draw from the grid for 30 minutes.
- 4. Harden the price path and add a negative-price rule; both are cheap and worth a lot in Germany. Hold a price grant for at least one slot, start one device per cycle with a random offset, add an optional cap on grid import (which can later serve §14a), match price levels case-insensitively, and let all flexible devices absorb power when price <= 0 or <= the export value. This prepares AURUM for 15-minute prices, the Solarspitzengesetz and the end of Dutch net metering.
- 5. Make the PV budget honest and explainable. Stop the 0.85 combined floor from neutralising the safety factor and the in-day correction. Feed the consumption profile from AURUM's own house-load value. Publish the effective factor, and offer Solcast p10 as an option. Add the Advisor reasons budget_reserved_for_battery, price_not_cheap, starting_soon and cooldown, so 'waiting_surplus' stops hiding the most confusing state.
- 6. Build cost and savings reporting from the roadmap: per-device solar kWh vs grid kWh, € at the actual price, feed-in value forgone, and autarky. It is cheap because the data already exists, and no HA tool offers this breakdown. Port the generic parts of HELIOS.
- 7. Make a look-ahead planner the v2.0 headline. For devices with a deadline and runtime, pick the cheapest quarter-hours before the deadline, net of the expected PV, and show the planned window in the Advisor and panel. Build it on timezone-aware timestamps and treat an empty 'tomorrow' as unknown. This closes the largest gap to PVEC, evcc, SMA and clever-PV without turning AURUM into an LP optimiser; field data shows rule engines with a predictive layer capture most of the value.
- 8. Later and optional, in roughly this order: device-type presets with compressor defaults (S); time windows and binary run conditions (S); a dry-run mode (S); a vendor-neutral discharge-block entity (M); a §14a / grid-limit input reusing the import cap (M); a modulating device type for heating rods and number entities (L). Leave EV charging to evcc and battery arbitrage or LP to Predbat and EMHASS, and document how AURUM coexists with them.

## Lücken

| Fähigkeit | AURUM | Fit | Aufwand |
|---|---|---|---|
| [BUG, verified] A deadline force-start ends when the job is done | partial | high | S |
| [BUG, verified] A running device keeps its context across the daily reset and an HA restart | partial | high | S |
| [BUG, verified] Units are normalised: W/kW, Wh/kWh, ct/EUR | partial | high | S |
| [BUG, verified] Higher priority actually wins: running lower-priority devices are displaced | partial | high | M |
| Fail-safe behaviour on stale or missing inputs (grid meter, SOC) | missing | high | M |
| Handling loss of device control (offline plug, satisfied thermostat) | missing | high | S |
| [BUG/doc, verified] Documented contracts hold: program_done and non-interruptible devices | partial | high | S |
| An honest, adaptive PV budget: load profile, pessimistic PV, visible factors | partial | high | M |
| Look-ahead price scheduling to a deadline, with a forward view | missing | high | L |
| Negative-price, export-value and feed-in-cap awareness, including surplus hidden by curtailment | partial | high | M |
| Price-path hardening: hysteresis on price edges, staggered starts, import cap | partial | high | S |
| Faster shutdown when importing from the grid | partial | high | S |
| Complete reason codes in the Advisor | partial | high | S |
| Cost, savings and solar-share reporting | missing | high | M |
| Battery discharge protection during grid-priced runs | partial | medium | M |
| Variable-power (modulating) devices | missing | medium | L |
| §14a EnWG / external grid-limit input | missing | medium | M |
| Device-type presets, including compressor protection | partial | high | S |
| Allowed time windows, schedules and device dependencies | partial | high | S |
| Advisory / dry-run mode | missing | high | S |
| PV gate on installs without a battery (known asymmetry; the consequence is new) | partial | high | S |
| HA quality-scale and test hygiene: repair issues, redaction, DST and trace tests | partial | medium | M |

### [BUG, verified] A deadline force-start ends when the job is done
Status **partial** · Fit **high** · Aufwand **S** · Vorbilder: evcc plans, openWB Zielladen, SMA Muss windows, PVEC deadlines, clever-PV Sollzeiten

**Warum:** Take a device with must-run-today, a deadline and an estimated runtime, with stop_after_runtime left at its default (off). It is force-started on grid and then never stopped by AURUM until the daily reset, because force_started makes it immune to shedding. The trigger also ignores runtime already done on solar. In the probe, a device that had already run 3 h on PV (deadline 18:00, 60 min) went ON at 16:55 and OFF at 00:10 the next day: about 7 h on grid, roughly 14 kWh at 2 kW. With stop_after_runtime on and 50 of 60 min already done, it still starts 65 min before the deadline. Every competitor with deadlines stops when the target is reached.

**AURUM heute:** custom_components/aurum/modules/devices.py:401-411 (force start), 674-676 (force_started means never shed), 1161-1206 (_deadline_urgent ignores runtime_today_s; the window uses the full estimated_runtime). _reset_muss_heute is called only at 341 (stop_after_runtime path) and 995 (SD finish). CHANGELOG 1.8.2 claims muss_heute auto-resets at the runtime target, which is only true with stop_after_runtime. Probe: <local path> (S1, S1b)

**Vorschlag:** _deadline_urgent returns False once runtime_today_s >= estimated_runtime, and sizes the window from the remaining runtime (estimated_runtime - runtime_today). Treat a forced start as a job: once the remaining runtime is done and min_on_time is honoured, turn off with reason runtime_target_reached and reset muss_heute, whether or not stop_after_runtime is set. Add S1 as a regression test.

### [BUG, verified] A running device keeps its context across the daily reset and an HA restart
Status **partial** · Fit **high** · Aufwand **S** · Vorbilder: Solar Optimizer (forced activation survives restart), report B 2.13 restart safety

**Warum:** _reset_device_counters sets _scheduling_reason=None even on devices that are ON, and persistence does not save the reason. A cheap_grid device running across midnight (the typical Tibber night window) or across a restart therefore loses its cheap-grid hold. It is shed after debounce_off and restarted a minute later (probe: OFF 00:10, ON 00:11; after a restart the same off/on). PV-gate devices lose their solar_pv hold at their day_start_hour in the same way. 'Restart toggles devices' is a classic failure listed in report B.

**AURUM heute:** custom_components/aurum/modules/devices.py:1424-1437 (_reset_device_counters clears _scheduling_reason); custom_components/aurum/modules/persistence.py:24-27 (_VALUE_FIELDS lacks _scheduling_reason). Probes: <local path> (S2), <local path> (S3)

**Vorschlag:** Clear _scheduling_reason only for devices that are off. Persist _scheduling_reason, and restore it only if the switch is still on. Add regression tests for the midnight case and the restart case.

### [BUG, verified] Units are normalised: W/kW, Wh/kWh, ct/EUR
Status **partial** · Fit **high** · Aufwand **S** · Vorbilder: report B 2.2 (normalise from unit_of_measurement); EMHASS and PVEC users hit W/kW and sign issues

**Warum:** Config validation accepts kW/mW/MW power sensors and Wh/MWh forecast sensors, but the runtime treats every power value as W and the remaining forecast as kWh. A grid sensor reporting -2.5 kW is read as 2.5 W of surplus, so nothing ever starts, silently. The documented EUR vs ct trap for price_entity (known, not reported as a finding) has the same root cause, so one normaliser fixes all of them. Unit and sign traps are among the most frequent complaints across products.

**AURUM heute:** custom_components/aurum/config_flow.py:121-122,155 (kW, mW, MW, Wh, MWh accepted); custom_components/aurum/modules/energy.py:43,61,93-97 and devices.py:1113-1118 (no conversion); budget.py:171,267 (remaining forecast assumed kWh, whereas _get_pv_today_kwh at 580-613 does auto-detect Wh); pricing.py:88-92 (price passed through, known). Probe: <local path> (S7)

**Vorschlag:** Add helpers get_power_w / get_energy_kwh / get_price_ct that read unit_of_measurement (cached per entity) and scale. For price: EUR/kWh or €/kWh is multiplied by 100; an unknown unit is passed through with a one-time warning. This also defuses the known EUR/ct trap. Until the helpers exist, reject kW and MWh in validation. Raise a repair issue on a mismatch.

### [BUG, verified] Higher priority actually wins: running lower-priority devices are displaced
Status **partial** · Fit **high** · Aufwand **M** · Vorbilder: PVEC (priorities 1-1000 with shedding), SMA priorities, Solar Optimizer (global optimisation), openWB

**Warum:** Only startup-detection devices can preempt. A regular high-priority device has to fit into whatever surplus is left after lower-priority devices that are already running, so whichever device starts first keeps the power. In the probe, a pool pump (800 W, priority 30) started at 1500 W surplus. Surplus then rose to 2600 W for 3 h, and a water heater (2000 W, priority 90) never started. The README promises 'Higher priority devices get power first'. Report B 2.6 calls this priority inversion.

**AURUM heute:** custom_components/aurum/modules/devices.py:394-466 (turn-on uses measured excess, which already includes the lower device's draw); _preempt_for_sd at 1015-1102 is only called from the SD WAITING branch (942); README.md:50. Probe: <local path>

**Vorschlag:** In the regular turn-on path, when should_on fails only on power, add up the power of running lower-priority devices that are interruptible, managed and past min_on_time, reusing the candidate and victim selection of _preempt_for_sd. If surplus plus that power covers the requirement for debounce_on, shed those devices and start the higher-priority one. Add an anti-ping-pong dwell, a notification, and the Advisor reason preempted_by_<name>.

### Fail-safe behaviour on stale or missing inputs (grid meter, SOC)
Status **missing** · Fit **high** · Aufwand **M** · Vorbilder: PVEC (pauses on an unavailable sensor), evcc, the HELIOS watchdog (grid_sensor_stale, power-balance plausibility), report B 2.2

**Warum:** The grid meter is read with a default of 0 W. When it goes unavailable, or freezes at a valid value (cloud meters, Tibber Pulse), the surplus reads 0 W, which neither starts nor stops anything. Devices running on surplus then stay on indefinitely: in the probe the device was still on after 3 h with no battery power sensors configured. There is no age check anywhere. An SOC sensor that is still unavailable after the 90 s grace is treated as 0 %, which means charging mode, every device off, and an Advisor that blames the battery. Report B ranks stale-data detection as the #1 check; PVEC pauses on unavailable sensors.

**AURUM heute:** custom_components/aurum/modules/energy.py:43 (get_float(..., 0)); coordinator.py:155-180 (readiness is checked only during the first 6 cycles); no last_reported or last_updated use in the codebase; energy.py:66-83 (SOC hold falls back to 0.0 when there is no previous value). Probes: <local path> (S6a, S6b)

**Vorschlag:** Track the freshness of each input via state.last_reported, falling back to last_updated. A grid meter always fluctuates, so a value frozen for more than N minutes is a reliable stale signal. Define the safe state: with a stale grid reading, no new turn-ons, and after a timeout release surplus-only devices; keep SD programs, deadline jobs and cheap-grid holds running. If SOC is unavailable at start, stay in startup mode instead of charging mode. Add an Advisor reason sensor_stale, log once on loss and once on recovery, and raise an HA repair issue after N minutes. Port the HELIOS watchdog's power-balance plausibility check in generic form.

### Handling loss of device control (offline plug, satisfied thermostat)
Status **missing** · Fit **high** · Aufwand **S** · Vorbilder: report B 2.2 (device control loss), the PVEC v0.2.3 state deny-list fix, the HELIOS watchdog (command vs reality)

**Warum:** An unavailable switch reads as off. AURUM therefore re-sends turn_on every 5-10 minutes, counts phantom switches, and reserves the device's nominal power in those cycles. In the probe, an offline 1500 W plug at priority 90 received 7 ON commands in an hour, and a 1000 W lower-priority device that would have fitted the 2000 W surplus never started in that hour. Separately, a device that is switched on but draws about 0 W (thermostat satisfied) still accrues runtime, which corrupts stop_after_runtime and deadline accounting.

**AURUM heute:** custom_components/aurum/modules/devices.py:1108-1111 (unavailable is treated as off), 1120-1139 (_turn_on does not verify the result), 279-282 and 1208-1215 (runtime is counted whenever the switch is on, regardless of power). Probe: <local path>

**Vorschlag:** Skip a device whose switch is unavailable: Advisor reason switch_unavailable, no power allocated. After a turn_on, expect the state to be on within 2 cycles; otherwise mark the device not_responding and back off. When a power sensor exists, count runtime only above a small threshold and publish a 'satisfied' reason.

### [BUG/doc, verified] Documented contracts hold: program_done and non-interruptible devices
Status **partial** · Fit **high** · Aufwand **S** · Vorbilder: n/a (correctness and user trust)

**Warum:** After a program finishes, an SD device returns to standby; SD_STATE_DONE is never set. The Advisor reason program_done, which appears in the README reason table and in the README automation example 'has the washing machine finished today?', can therefore never be true. In the probe, after a smart finish the state is standby and the reason is program_standby. Separately, the battery emergency (SOC <= min_soc) switches off non-interruptible devices, although the README says AURUM will not turn them off mid-cycle. Running SD programs are exempt from the emergency; plain non-interruptible devices are not.

**AURUM heute:** custom_components/aurum/modules/devices.py:980-996 and 1003-1013 (finish calls _sd_reset, which sets STANDBY); const.py:155 (SD_STATE_DONE is never assigned by any producer); advisor.py:152; README.md:356,393; devices.py:241-266 (emergency loop does not check interruptible); README.md:117. Probes: <local path> (S4, S5)

**Vorschlag:** Set a program_done_today flag on smart_finish or max_runtime, clear it at the daily reset or on the next detection, and publish it; the Advisor returns program_done while the device is in standby with the flag set. For the emergency, decide explicitly: either skip non-interruptible devices as SD RUNNING programs are skipped, or document that battery protection overrides 'interruptible'.

### An honest, adaptive PV budget: load profile, pessimistic PV, visible factors
Status **partial** · Fit **high** · Aufwand **M** · Vorbilder: Predbat (pv_metric10, Load ML), EMHASS (mlforecaster), SMA (load learning), Victron DESS, clever-PV

**Warum:** These are new findings, not regressions of audit items #5-7. Two of the budget's adaptive layers have no effect. (a) budget_combined_floor = 0.85 clamps weather x safety x in-day. As a result the adaptive safety factor, whose range is 0.55-0.85, never changes the budget, and an in-day correction of 0.5 (only half the forecast PV materialised) is ignored. In the probe, safety factors 0.55, 0.70 and 0.85 all gave the same 3357 W budget, and in-day 0.5 changed nothing. The default factor of 0.70 is therefore never applied, while sensor.aurum_safety_factor shows 70 %. (b) update_consumption_profile reads shared['hourly_consumption_w'], which nothing writes, so household load is a flat 500 W for every hour and cannot be configured. Competitors learn the load (SMA, EMHASS, Predbat, DESS) and weight a pessimistic PV case (Predbat p10).

**AURUM heute:** custom_components/aurum/modules/budget.py:79 and 278-282 (floor), 75 (safety min 0.55), 615-643 (in-day correction), 65 and 112 (flat 500 W), 477 (hourly_consumption_w has no producer anywhere). Probe: <local path>

**Vorschlag:** Apply the floor to the weather factor only, or lower it to about 0.5, so the safety factor and in-day correction can act; publish the effective combined factor. Feed an hourly profile from AURUM's own house-consumption value minus managed-device power (sensor.py already computes house consumption), and expose avg_consumption_w in the options. Optionally use Solcast pv_estimate10 for the battery-target term: p10 for 'must reach target', p50 for optional loads. HELIOS already combine p10 with a load profile in the same way.

### Look-ahead price scheduling to a deadline, with a forward view
Status **missing** · Fit **high** · Aufwand **L** · Vorbilder: evcc plans, openWB Zielladen, clever-PV Sollzeiten, SMA Muss windows, EMHASS, Predbat, PVEC 24 h planner

**Warum:** This is the biggest functional gap to the field. AURUM only asks 'is it cheap right now'. It cannot place a device's runtime in the cheapest quarter-hours before its deadline, and it cannot tell the user when a device will run. Most compared systems do this (see who has it).

**AURUM heute:** custom_components/aurum/modules/pricing.py reads only the current price, level and cheap-period flag (lines 88-128); no today/tomorrow array parsing anywhere in the code; the Advisor publishes current state only

**Vorschlag:** A v1 is about effort M. Write a price-array normaliser for common shapes: native Tibber and tibber_prices today/tomorrow lists with start/total, Nordpool raw_today/raw_tomorrow, and EPEX. Key everything on timezone-aware timestamps, not 'HH:MM' keys, which break on 92- and 100-slot DST days (HELIOS is the cautionary example). For devices with a deadline and estimated runtime, reserve the cheapest slots for the remaining runtime, minus hours in which the hourly PV forecast already covers the device. Treat an empty 'tomorrow' as unknown, never as cheap. Show 'planned 02:15-03:15' in the Advisor and panel. A relative threshold such as 'cheapest X % of the remaining known slots'  needs no unit, so it also sidesteps the EUR/ct trap on that path.

### Negative-price, export-value and feed-in-cap awareness, including surplus hidden by curtailment
Status **partial** · Fit **high** · Aufwand **M** · Vorbilder: PVEC (export limit management), evcc (feed-in priority, §9 EEG), Victron DESS, SMA (dynamic active-power control), E3/DC, EMHASS

**Warum:** Under the Solarspitzengesetz, export from new German systems can be worth 0 € or less. Many German systems are capped at 60 % feed-in, and the draft EEG 2027 proposes 50 %. In the Netherlands, net metering ends in 2027. AURUM treats all export as free surplus. It also cannot see surplus that the inverter curtails at the cap or under zero-export, where the grid meter reads about 0 W.

**AURUM heute:** No export, feed-in, curtailment or negative-price logic anywhere in the codebase (grep). pv_power_threshold (custom_components/aurum/modules/devices.py:582-597, 634-647) is the only partial workaround. solar_only devices never look at the price (pricing.py:124-126).

**Vorschlag:** (a) A global rule: when the current price is <= 0, or <= a configurable export value, every flexible device may run as if it had surplus, whatever its price_mode, still respecting run conditions and the battery floor. This is the generic part of the HELIOS idea. (b) An optional feed-in cap in W or % of kWp: when export >= cap - margin, treat surplus as saturated and use PV power minus house load (the PV-gate logic) as headroom, probing one device at a time.

### Price-path hardening: hysteresis on price edges, staggered starts, import cap
Status **partial** · Fit **high** · Aufwand **S** · Vorbilder: evcc (load management, plan merging), report B 2.3 and 2.6, UK Smart Charge Points Regulations reg. 11

**Warum:** A price grant starts a device immediately and stops it immediately, with no hysteresis and no switch penalty. In the probe, quarter-hour prices alternating around max_price switched a cheap_grid boiler 8 times in 2 h. All cheap-grid devices also start in the same cycle at a slot edge (probe: 3 x 3 kW at 00:00:00, a 9 kW step) with no cap on import. That matters for the main fuse, the Flanders capacity tariff, §14a, and synchronised steps across many installs (UK rules require up to 600 s random delay). Price-level matching is case-sensitive, so a source that reports 'CHEAP' is silently ignored.

**AURUM heute:** custom_components/aurum/modules/devices.py:630-632 (grant without debounce), 690-693 (immediate off), 774-790 (switch penalty only on surplus paths); pricing.py:101 (raw in _LEVEL_ORDER, no lower()). Probe: <local path>

**Vorschlag:** Hold a price grant for at least one full slot plus min_on_time, and apply the switch penalty to price starts too. Start at most one price-driven device per cycle, with an optional random 0-120 s offset. Add an optional 'max grid import for price-driven devices (W)'; the §14a gap below can reuse it. Lower-case price levels before matching.

### Faster shutdown when importing from the grid
Status **partial** · Fit **high** · Aufwand **S** · Vorbilder: evcc (enable 1 min / disable 3 min), report B 2.3, PVEC user complaints

**Warum:** The default debounce_off is 600 s, and the switch penalty multiplies it by up to 3. A device that has been flapping can therefore draw from the grid or the battery for up to 30 min before it is shed. The turn-on EMA also reacts fast to rising surplus and slowly to falling surplus. Practice and user complaints point the other way: switch off fast on import and start slowly. PVEC's 30-minute window drew the complaint 'drains my battery'; evcc defaults to 1 min on / 3 min off.

**AURUM heute:** custom_components/aurum/const.py:128-129 (debounce 300 s on / 600 s off); modules/devices.py:756-768 (penalty applied to the off debounce); helpers.py ema_update_asymmetric with alpha_down 0.7 / alpha_up 0.2 (energy.py:33-35)

**Vorschlag:** Apply the switch penalty to the turn-on debounce only; that is what protects relays. Bound the off tolerance by energy (for example at most 50 Wh of import per device), not only by time, and consider a lower default debounce_off of 180-300 s alongside the existing hysteresis. After any turn-on, add a settle window: skip k cycles or shift the EMA by the nominal power just switched. Without that, debounce_on values below about 60 s, which the config allows, can start two devices on the same surplus.

### Complete reason codes in the Advisor
Status **partial** · Fit **high** · Aufwand **S** · Vorbilder: PVEC status messages ('Insufficient excess (-19W < 180W needed)'), Solar Optimizer badges, report B 2.10

**Warum:** The Advisor is AURUM's differentiator, but the most confusing states all fall into waiting_surplus. A device held back by the PV budget reports waiting_surplus while sensor.aurum_excess_power shows several kW (probe: 4000 W surplus, 500 W budget, reason waiting_surplus). The same catch-all hides min-off cooldown, a pending debounce, a price that is not cheap, a stale sensor and an unavailable switch.

**AURUM heute:** custom_components/aurum/modules/devices.py:439-447 (budget cap, not published), 1241-1262 (published flags); advisor.py:145-168 (fallback to waiting_surplus). Probe: <local path> (S8)

**Vorschlag:** Publish budget_capped, price_ok, cooldown and debounce-pending flags from DeviceManager. Use coarse buckets rather than live seconds so the recorder stays quiet. Add the reasons budget_reserved_for_battery, price_not_cheap, starting_soon, cooldown, sensor_stale and switch_unavailable, with EN/DE labels in the panel.

### Cost, savings and solar-share reporting
Status **missing** · Fit **high** · Aufwand **M** · Vorbilder: Predbat, PVEC, evcc (sessions), clever-PV, SMA, Solar Manager, E3/DC; HELIOS

**Warum:** It is already on the roadmap, and most of the field reports money. No HA tool breaks out the solar share per device together with € saved and feed-in revenue forgone, so it is a cheap differentiator. For a hobby project it is also the strongest driver of retention and donations.

**AURUM heute:** Only kWh per device per day (custom_components/aurum/sensor.py:292-330); the README roadmap item 'Cost tracking' is unchecked

**Vorschlag:** Each device cycle, split a device's measured draw into a solar part and a grid part. The grid part is min(draw, max(0, grid import)), shared across running devices by priority or proportionally. Accumulate solar kWh, grid kWh, € at the current price, and a configurable feed-in value forgone. Expose daily and total TOTAL_INCREASING sensors plus system autarky and self-consumption. Port the generic parts of HELIOS.

### Battery discharge protection during grid-priced runs
Status **partial** · Fit **medium** · Aufwand **M** · Vorbilder: PVEC (discharge protection), evcc (discharge lock), Predbat (car_charging_from_battery)

**Warum:** Battery behaviour that contradicts the user's settings is the most common complaint across all products. In cheap_grid mode the home battery usually discharges into the device unless the inverter is told otherwise, so a 'cheap' run quietly empties the battery. AURUM exposes binary_sensor.aurum_cheap_grid_active for exactly this, but users have to build the automation themselves.

**AURUM heute:** binary_sensor.aurum_cheap_grid_active (custom_components/aurum/modules/devices.py:1268-1276, CHANGELOG 1.7.7); cheap_grid_soc as a battery floor; no native action

**Vorschlag:** Add an optional, vendor-neutral 'discharge block' entity (a switch, input_boolean, or select plus option) that AURUM sets while any cheap-grid device runs and restores afterwards; document who owns it. Ship a blueprint first (effort S) and build it natively later.

### Variable-power (modulating) devices
Status **missing** · Fit **medium** · Aufwand **L** · Vorbilder: Solar Optimizer, PVEC, evcc, openWB, Fronius Ohmpilot, E3/DC, clever-PV, Solar Manager, EMHASS

**Warum:** The largest flexible loads in a house, a heating rod with a power setpoint and an EV, cannot follow surplus with on/off switching. 8 of the 14 compared systems support setpoints. Here AURUM's on/off-only design constraint is itself the gap.

**AURUM heute:** custom_components/aurum/config_flow.py:114-115 (switch entity selector limited to switch and input_boolean); DeviceManager allocates nominal_power on/off only

**Vorschlag:** Add an optional device kind 'modulating' that writes a number entity (W or A) with min/max/step and a minimum time between steps. It receives the surplus left after the on/off devices and acts as the filler sink. Keep EV specifics (phases, vehicle SoC) out of scope and document coexistence with evcc, with AURUM yielding while evcc is charging.

### §14a EnWG / external grid-limit input
Status **missing** · Fit **medium** · Aufwand **M** · Vorbilder: evcc, SMA, openWB, E3/DC

**Warum:** If AURUM switches a heat pump, wallbox or heating rod above 4.2 kW and the grid operator dims, the EMS must keep their combined draw under the setpoint and must not start cheap-grid runs. evcc, SMA, openWB and E3/DC handle this; no HA surplus tool does.

**AURUM heute:** No §14a or grid-limit code anywhere (grep)

**Vorschlag:** Add an optional 'grid limit active' binary_sensor plus a limit in W. While the limit is active: cap the sum of measured managed-device power by shedding in priority order, block price starts, log every event, and set an Advisor reason grid_limit_active. Reuse the import cap from the price-path hardening gap. State in the docs that AURUM is not a certified control box.

### Device-type presets, including compressor protection
Status **partial** · Fit **high** · Aufwand **S** · Vorbilder: evcc (SG-Ready), SMA (min switch-on time guidance), Solar Manager (CTA heat-pump notes), BWP SG-Ready label

**Warum:** Every device gets the same defaults: min_off 60 s and min_on 600 s. The QUICKSTART recommends a heat pump on a smart plug at priority 70 without any warning, yet a compressor needs at least about 10 min off, and SG-Ready requires at least 10 min per signal. There is no cap on starts per hour.

**AURUM heute:** custom_components/aurum/const.py:130-131; docs/QUICKSTART.md ('Wärmepumpe (Smart-Plug-gesteuert): 70'); the switch penalty only lengthens debounce (modules/devices.py:774-790)

**Vorschlag:** Add a 'device type' select (resistive heater, compressor/heat pump, program appliance, pump, generic) that only pre-fills defaults. For a compressor: min_on 15 min, min_off 10 min, at most 3 starts per hour, non-interruptible. Add a QUICKSTART warning to prefer the SG-Ready boost relay over cutting power.

### Allowed time windows, schedules and device dependencies
Status **partial** · Fit **high** · Aufwand **S** · Vorbilder: SMA (time windows), PVEC (time windows, dependencies), EMHASS (start/end timesteps), clever-PV (weekday plans), Solar Optimizer (templates)

**Warum:** The only time controls are a deadline and day_start_hour. There is no 'not before 08:00' (noise at night) and no weekday plan. The run condition only accepts a numeric sensor compared below or above a value, so it cannot express 'only while the pool pump is on'.

**AURUM heute:** custom_components/aurum/config_flow.py:422-444 (condition selector limited to the sensor domain, numeric value); modules/devices.py:530-548

**Vorschlag:** Add optional earliest_start / latest_end times per device that block all non-forced starts outside the window. Allow condition_entity to be a binary_sensor, switch or input_boolean with an 'is on / is off' test.

### Advisory / dry-run mode
Status **missing** · Fit **high** · Aufwand **S** · Vorbilder: Predbat (Monitor, set_read_only), evcc optimizer (recommendations only), HAEO, PVEC (requested)

**Warum:** It builds trust during onboarding: users can watch for a day what AURUM would do before letting it switch anything. Predbat and evcc offer this, and PVEC users have asked for it.

**AURUM heute:** The bridge's turn_on and turn_off always act (custom_components/aurum/hass_bridge.py:55-69)

**Vorschlag:** Add a global 'simulate only' switch. The bridge records the intended actions instead of calling services, device states are tracked virtually, and the Advisor shows 'would turn on/off'. SD devices need the plug on during standby, so either exclude them or simulate them as well.

### PV gate on installs without a battery (known asymmetry; the consequence is new)
Status **partial** · Fit **high** · Aufwand **S** · Vorbilder: n/a

**Warum:** The asymmetry itself is known and pinned in tests/test_cheap_grid_soc.py. What is not named there: since audit fix #10, an unavailable SOC sensor never produces SOC < 0 (energy.py holds the last value or 0 %). The < 0 branch in _pv_gate_ok is therefore reached only when no battery is configured, so pv_power_threshold can never fire on battery-less installs, although the device form offers it. In my view the choice is wrong now: -1 means 'no battery', there is nothing to protect, and both gates should allow the start.

**AURUM heute:** custom_components/aurum/modules/devices.py:595 (battery_soc < 0 returns False); modules/energy.py:66-85; tests/test_cheap_grid_soc.py:72-83

**Vorschlag:** In _pv_gate_ok, treat battery_soc == -1 (no battery configured) as SOC OK, and update the pinned test and the comment. A genuinely unavailable SOC stays fail-closed upstream, as it is today.

### HA quality-scale and test hygiene: repair issues, redaction, DST and trace tests
Status **partial** · Fit **medium** · Aufwand **M** · Vorbilder: HA integration quality scale; DST bugs reported against EMHASS and Victron DESS

**Warum:** Report B lists the HA quality-scale expectations: repair issues for problems the user can fix, redacted diagnostics (Gold), log-once on connection loss and recovery (Silver), and invariant tests for DST days with 92/100 slots, stale inputs and a restart in the middle of a min-on period, plus trace replay. AURUM has 227 tests including full-day simulations, but none of these categories.

**AURUM heute:** No issue_registry use (grep); custom_components/aurum/diagnostics.py:11 ('nothing is redacted', while notify_service is included); budget.py calls datetime.now() internally at 444, 564 and 663, so the clock cannot be injected in tests; no DST test cases

**Vorschlag:** Raise repair issues for a unit mismatch, a wrong grid sign (never negative on a sunny day when PV exceeds house load) and a stale sensor. Redact notify_service from diagnostics. Inject 'now' into the budget helpers. Add invariant tests for DST days, a restart mid-min-on and stale inputs, plus a CSV trace-replay harness fed from aurum_actions.csv and recorder exports.

## Coverage-Kritiker: nicht oder kaum geprüft

- custom_components/aurum/sensor.py: AurumExcessSensor, AurumBatteryModeSensor, AurumCycleSensor, AurumGridPowerSensor, AurumPVPowerSensor, AurumBatteryChargeSensor, AurumBatteryDischargeSensor and _device_icon. None of the six reviewers listed these. I read them: they are pass-throughs of shared keys. They publish a made-up 0 W into MEASUREMENT statistics during the startup early return and whenever an input is unavailable, instead of going unavailable. Battery Mode is a free-text state with no ENUM device_class or translation_key. Low risk, presentation and statistics only.
- custom_components/aurum/diagnostics.py: async_get_config_entry_diagnostics. Only ha-lifecycle listed it; entities-config and advisor-panel did not review it. It reports cfg target_soc/min_soc rather than the live coordinator.battery.target_soc/min_soc set by the RestoreNumber sliders, so support data contradicts what the controller actually uses. It also leaves out price_mode, max_price, pv_power_threshold, day_start_hour, the run-condition fields and budget_info. Low risk.
- custom_components/aurum/modules/devices.py: the commanded-versus-actual path of _turn_on/_turn_off/_is_device_on. Everyone read these functions, but nobody tested a switch that does not follow the command. _turn_on records managed_on, total_switches, _switch_times and notifications without checking the result. _deadline_urgent's pre-deadline branch (around lines 1200-1204) has no once-guard; only the post-deadline branch checks force_started. _notify accepts throttle_key/importance but never uses them. I confirmed this with <scratch>/critic_deadline_dead_plug.py: a deadline device (18:00, 90 min) whose plug is offline got 70 ON commands and 70 mobile pushes between 16:00 and 17:00. An existing probe, <scratch>/gap_probe4.py, shows that an offline 1500 W plug is re-commanded 7 times per hour and its phantom allocation keeps a 1000 W lower-priority device off for the whole hour.
- custom_components/aurum/modules/energy.py: EnergyManager.update with the grid sensor unavailable after the startup grace window (coordinator._entities_ready only guards cycles 1-6). get_float(..., 0) makes grid_raw 0 W. With the default legacy battery-power semantics, excess then becomes +charge power. I confirmed this with <scratch>/critic_grid_unavail.py: while the battery is grid-charging at 3 kW and the house imports 3.5 kW, excess_for_devices climbs to +2997 W within 6 cycles. Earlier probes covered only the no-battery case (gap_probe.py S6a) and idle or discharging batteries (grid_unavail_demo.py), not this direction. No input is ever checked for staleness via last_updated or last_reported.
- custom_components/aurum/modules/budget.py: _get_hourly_forecast was checked by only one reviewer, who explicitly did not verify real Solcast or Open-Meteo attribute shapes or whether timestamps are local or UTC. There are no BudgetManager unit tests. _hours_until_sunset uses a fixed 19:00 fallback when there is no hourly data: real sunset is about 16:40 in November and about 21:30 in June, so the budget goes to 0 ('after_sunset') from 19:00 on summer evenings that still produce PV. Core Forecast.Solar exposes no watts/wh_period attributes, so it always hits that fallback. _get_pv_today_kwh guesses the unit (unit None and raw > 500 means Wh), so its reading can flip between kWh and Wh during a day.
- custom_components/aurum/modules/pricing.py: PricingManager.update compares the level string exactly with lowercase keys ('raw in _LEVEL_ORDER'). If a source reports 'CHEAP' and the level entity is the only price source, should_run_on_grid returns None, so the device holds its state forever. Nobody checked this against the real sources the README names (tibber_prices, Nordpool, EPEX, aWATTar). PricingManager.active is trivial and was not listed.
- custom_components/aurum/frontend/aurum-panel.js: every method (_buildDeviceCard and its service calls, _callService, _update, _sync, set hass, connectedCallback) was reviewed by one reviewer only (advisor-panel), from the source. It was never run in a browser or against HA.
- tests/simulation.py, simulation_7day.py, simulation_7day_budget.py and simulation_calibrate_budget.py: pytest does not collect them and no reviewer ran them against v1.15.3. No reviewer ran a full multi-device day through the real coordinator._async_update_data loop (odd/even split, daily_reset, budget, pricing, SD, shedding).
- These are trivial: no reviewer listed them, I read them and found no issue. helpers.ema_update, hass_bridge.HassAccess.log/config_path, config_flow.AurumConfigFlow.async_get_options_flow, binary_sensor.async_setup_entry, and the switch subclass __init__s (AurumManualOverrideSwitch, AurumMussHeuteSwitch, AurumDisableSwitch).
- Dedupe note: an earlier pass in the same scratchpad already probed some of these scenarios: gap_probe.py through gap_probe4.py, written 17:49-17:52 (deadline/runtime, cheap-grid at midnight, restart scheduling reason, priority inversion, alternating quarter-hour prices, offline plug), plus grid_unavail_demo.py, kw_unit.py and unit_kw_check.py from the verifiers. Check whether those already became findings before re-reporting.

---

# Anhang A — Marktrecherche

# Capability catalogue: home energy management and PV-surplus optimisers compared with AURUM (as of 2026-11-05)

**Scope and method.** I used web research only: official docs, release notes, GitHub issues, the HA community and HACF forums, the Victron community, openWB discussions, and vendor datasheets. AURUM's own feature set comes from `<local path>` and `custom_components/aurum/const.py` (v1.15.3).

**How much to trust each source.** For vendor systems (E3/DC, SENEC, Kostal, Solar Manager, clever-PV) I often only had marketing material, and I say so where that applies. Projects that are still moving, such as the evcc optimizer and the PV Excess Control RC, are described at the state their docs or posts give.

**Legend for the matrix:** Y = documented. ~ = partial or indirect. – = not offered or not found. ? = not verified.

---

## 0. Quick matrix (core capabilities)

Abbreviations: SO = Solar Optimizer (jmcollin78) · PVEC = PV Excess Control (InventoCasa) · SMA = Sunny Home Manager 2.0 · SolMgr = Solar Manager · cPV = clever-PV · DESS = Victron Dynamic ESS · Ohmp = Fronius Ohmpilot

| Capability | AURUM | SO | PVEC | evcc | EMHASS | Predbat | openWB | SMA | SolMgr | cPV | DESS | Ohmp | E3/DC | SENEC | Kostal |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| PV forecast used in decisions | Y (budget) | – | Y | ~ (optimizer, experimental) | Y | Y | ~ (in development) | Y (24/48 h) | Y | Y | Y | – | Y | Y | ? |
| Load forecast / learning | – | – | ? | ~ | Y (ML) | Y (history + Load ML) | – | Y (learns recurring loads) | ? | Y (AI) | Y | – | Y ("AI 360°") | ? | ? |
| "Price is cheap now" threshold | Y | ~ (cost in objective, off-peak forcing) | Y | Y | Y | Y | Y | ~ (DE only, FW ≥2.18) | Y | Y | Y | – | Y | Y | ~ |
| Look-ahead scheduling (cheapest slots to a deadline) | – | – | Y (24 h planner) | Y (plans) | Y | Y | Y (Zielladen) | Y (Muss windows) | ~ | Y (Sollzeiten) | Y | – | Y | ? | ? |
| On/off of arbitrary loads | Y | Y | Y | Y (smart switches) | ~ (via user automations) | ~ (iBoost/car only) | Y (SmartHome) | Y | Y | Y | – | ~ (Heater 2 relay) | Y | Y | ? |
| Power modulation / setpoints | – | Y | Y (6–32 A) | Y | Y (continuous loads) | ~ (car) | Y | Y (SEMP/EEBus) | Y | Y | – | Y (0.3–9 kW) | Y | ? | ~ (wallbox) |
| EV specifics (phases, SoC, departure plan) | – | ~ | Y | Y | ~ | Y | Y | Y | Y | Y | – | – | Y | Y | Y |
| SG-Ready heat pump | ~ (as a plain switch) | ~ | ~ | Y (boost + dim) | ~ (thermal model) | – | Y | Y (external relay) | Y | Y | – | Y | Y | Y | Y |
| Battery grid charging / arbitrage | – | – | Y | Y | Y | Y | Y (2.2/2.3) | ~ (time window) | Y | Y | Y | – | Y | Y | ~ |
| Battery discharge lock / protection | ~ (SoC floors) | – | Y | Y | Y | Y | ? | ? | ? | Y | Y | – | Y | ? | ? |
| Negative-price / export-cap handling | – | – | Y | Y | Y | ~ | ? | Y (dynamic active-power control, zero export) | ? | ? | Y | – | Y | ? | ? |
| §14a EnWG dimming | – | – | – | Y | – | – (UK) | Y | Y | ? | ? | – | – | Y | ? | ? |
| Deadlines / minimum daily runtime | Y | Y | Y | Y | Y | Y (car) | Y | Y | Y | Y | – | ~ (minimum temp) | ? | ? | ? |
| Appliance start detection (washer) | Y (power-based) | – | – | – | – | – | – | Y (via SEMP/EEBus appliances) | ~ | ? | – | – | ? | ? | ? |
| Decision explanations | Y (Advisor + panel) | ~ (card badges) | Y (status messages) | Y | ~ | Y (plan view) | ~ | Y ("Handlungsempfehlung") | ? | ~ | ~ (plan graph) | ~ (LEDs) | ? | ? | ? |
| Cost / savings reporting | – (kWh only) | – | Y | Y (sessions) | ~ | Y | Y | Y | Y | Y | ~ | – | Y | Y | Y |
| Works locally without cloud | Y | Y | Y | Y | Y | Y | Y | – (Sunny Portal) | ~ | – | – (falls back to plain ESS) | Y | ~ | – | ~ |

---

## 1. System profiles (current state, late 2026)

### Direct Home Assistant competitors

**Solar Optimizer (jmcollin78), v3.9.0, released 11 Oct 2026** ([releases](https://github.com/jmcollin78/solar_optimizer/releases), [README](https://github.com/jmcollin78/solar_optimizer))
- **Algorithm:** simulated annealing. Each cycle it minimises `a·import + b·export`, where a and b come from buy/sell price sensors. Both prices must be strictly above 0.
- **Cycle time:** about 300 s is recommended because the computation is CPU-heavy.
- **Device types:** on/off devices, and variable-power devices with `power_min`, `power_max` and `power_step`. It can drive switch, climate, water_heater, humidifier, fan, select, light, input_boolean and button entities.
- **Gating and limits:** `check_usable_template`, `check_active_template`, a per-device `battery_soc_threshold`, `duration_min` / `duration_stop_min`, and daily `min_on_time_per_day_min` / `max_on_time_per_day_min`.
- **Off-peak:** `offpeak_time` forcing, plus `offpeak_power` and `max_on_time_offpeak_min`, both new in 3.9.0.
- **Priorities:** 5 levels plus a global "priority weight". Priority is explicitly not absolute.
- **UI and control:** timed forced activation (1/4/12/24 h), an events API, and a bundled Lovelace card with ACTIVE/MANUAL/WAITING/INACTIVE/DISABLED badges and a 24 h history bar.
- **Missing:** no forecast, no battery planning, and only one instance allowed.

**PV Excess Control (InventoCasa)** ([repo](https://github.com/InventoCasa/PV-Excess-Control), [releases](https://github.com/InventoCasa/PV-Excess-Control/releases))
- **History:** it replaced the pyscript blueprint in April 2026. v0.2.0 shipped 9 Apr, the stable v0.2.4 on 28 Apr, and v0.4.0rc1 on 9 Sep 2026.
- **Architecture:** a real-time controller every 30 s and a 24 h forward planner every 15 min. The optimiser is pure logic, tested by 1,289 tests.
- **Appliances:** priorities 1–1000, dependencies between appliances, a per-appliance averaging window, min/max runtime, and time windows.
- **EV:** SoC, connection state, targets and deadlines, dynamic current from 6 to 32 A, and a live phase count.
- **Battery strategies:** Battery First, Appliance First or Balanced. Also a minimum-SoC shed, "discharge protection" (limits battery discharge while large consumers run), and opt-in dynamic battery charging. That last one throttles morning charging when expected curtailment can fill the battery, and follows the cap near the export limit.
- **Tariffs and grid:** Tibber, Awattar, Nordpool, Octopus and generic sensors, with per-appliance cheap-price and battery-charge-price thresholds. It can force the inverter to grid-charge and blocks battery discharge while charging cheaply from grid. It also has export-limit management and "grid supplementation" (a small grid top-up for appliances).
- **Forecasts:** Solcast, Forecast.Solar or generic sensors, with multiple arrays.
- **Other:** analytics (savings, self-consumption), notifications, and per-appliance Enabled / Override / Pause.

**Newer HA entrants worth knowing**
- **Hanergy:** a priority cascade every 10 s with no forecasts and no prices; the free tier covers 2 devices ([blog](https://hanergy-website.pages.dev/blog/hanergy-vs-emhass)).
- **HAEO:** a pure-LP optimiser with a 48 h horizon. It only publishes recommendations and does not drive hardware ([docs](https://ha-energy-optimiser.github.io/haeo), [limitations](https://ha-energy-optimiser.github.io/haeo/reference/limitations)).

### Open-source optimisers

**evcc** ([intro](https://docs.evcc.io/en), [blog index](https://docs.evcc.io/en/blog))
- **2026 milestones:**
  - Browser configuration became production-ready and 15-min price forecasts arrived in January ([post](https://docs.evcc.io/en/blog/2026/01/01/highlights-browser-config-ready)).
  - Charging modes were restructured into **Smart / Always charge**, and a **Solar Share** slider replaced the watt thresholds in September ([blog index](https://docs.evcc.io/en/blog)).
  - The experimental **Optimizer** plans the whole system several days ahead from consumption, production and price forecasts. It optimises multiple charging plans jointly, reports whether a plan is feasible, and accounts for a static export limit. As of the August post it **only shows recommendations and does not control devices yet** ([0.314 post](https://docs.evcc.io/en/blog/2026/08/19/highlights-release-process-optimizer-customize)).
- **Battery** ([DE battery page](https://docs.evcc.io/de/features/battery)):
  - A priority SoC: below it the home battery gets surplus first.
  - "Battery as buffer": the car may use the battery above a buffer SoC, with an optional auto-start SoC.
  - Battery Boost per session.
  - A capacity-weighted average SoC across multiple batteries.
  - A discharge lock during fast, planned or minimum charging.
  - Grid charging below a price or CO₂ limit, with an optional `maxsoc`.
- **Heating** ([heating](https://docs.evcc.io/en/heating)): SG-Ready via relays (a boost relay plus an optional dim relay), vendor APIs, continuously controlled my-PV heaters, and plain smart switches. The status shows "Boost requested…" while the heat pump hasn't reacted yet. The docs say evcc's temperature limits are *not* a safety feature.
- **Grid:** feed-in priority for variable export prices (a per-loadpoint threshold pauses charging in Smart mode) ([page](https://docs.evcc.io/en/features/dynamic-feedin)). §14a dims to minimum power instead of switching off and pauses battery grid charging ([post](https://docs.evcc.io/en/blog/2024/08/17/highlights-14a-enwg-ocpp-loadmanagement-elli)). §9 EEG curtailment works for Goodwe, Fronius Gen24 and Huawei. Load management covers limited connections.
- **Integrations:** HA, MQTT, REST, an MCP server, and Sunny Home Manager.

**EMHASS 0.17.x** ([docs](https://emhass.readthedocs.io/en/stable/), [config](https://emhass.readthedocs.io/en/stable/config.html))
- **Solver:** linear programming on CVXPY, with HiGHS as the default solver.
- **Run types:** day-ahead, naive MPC, and a "perfect" optimisation.
- **Deferrable loads:**
  - nominal power, *or* a fixed power sequence such as a washer program;
  - operating hours, and start/end timesteps;
  - semi-continuous (all-or-nothing) mode, and single-block mode;
  - a startup penalty, and minimum on/off steps;
  - `deferrable_load_max_cost` for optional loads;
  - `deferrable_load_groups` with a shared power budget and mutual exclusion.
- **Battery:** min/max/target SoC, `set_nocharge_from_grid`, `set_nodischarge_to_grid`, wear weights, and SoC deficit/surplus penalties.
- **Grid:** `maximum_power_to_grid`, `capacity_cost_per_kw` (demand charge), and `compute_curtailment`.
- **Forecasts:** PV from open-meteo, solcast, solar.forecast or csv, plus an ML PV correction. Load as typical, naive or `mlforecaster` (skforecast).
- **Thermal:** a thermal model plus a "thermal battery" for heat pumps with temperature-dependent COP ([thermal](https://emhass.readthedocs.io/en/latest/section_thermal.html)).
- **Execution:** it **does not switch anything itself**. It publishes `sensor.p_deferrableX`, and users write automations that act on it ([automations](https://emhass.readthedocs.io/en/latest/automations.html)).

**Predbat** ([docs](https://springfall2008.github.io/batpred/), [customisation](https://springfall2008.github.io/batpred/customisation/)). Battery-centric, mainly for UK and Octopus users. The newest release I found is v9.6.3.
- **Modes:** Monitor, Control SoC only, Control charge, and Control charge & discharge, plus a `set_read_only` switch.
- **Tunables:** `best_soc_keep` (a soft floor that may be undercut when that saves money), `best_soc_min/max`, `metric_battery_cycle` (wear cost in p/kWh), and `pv_metric10_weight` (weight on a pessimistic 10 % PV scenario).
- **iBoost diverter:** solar, charging, or cheapest-slot modes.
- **Car charging:** smart-planned slots with `car_charging_plan_max_price`.
- **Manual and holiday:** manual charge/export/demand/freeze selectors and a holiday mode.
- **Cadence:** replans every 10 min and controls every 5 min.
- **Insight:** a plan card, calibration charts, actual-vs-predicted comparison, savings tracking, and a "What-If" annual payback prediction.
- **v9.x:** Load ML that excludes iBoost energy from training ([v9.6.3](https://newreleases.io/project/github/springfall2008/batpred/release/v9.6.3)) and an AI chat in the web UI ([v8.54.0](https://github.com/springfall2008/batpred/releases/tag/v8.54.0)).

**openWB software 2.x** ([wiki](https://wiki.openwb.de/))
- **Charge modes:** Sofort, PV (Min+PV), Eco (price-based), Zielladen (target time and SoC, picks cheap slots), and Zeitladen, which can run in parallel.
- **Profiles:** per-vehicle charge profiles with prioritisation ([discussion](https://github.com/openWB/core/discussions/3478)).
- **Other:** phase switching, load management, §14a/EEBUS inputs, BiDi, and tenant billing.
- **Speichersteuerung (active battery control):** a PR merged in May 2026 now hands the battery only the remaining surplus after house load ([PR #3382](https://github.com/openWB/core/pull/3382)). A PV-forecast feature based on open-meteo is still under discussion ([#3785](https://github.com/openWB/core/discussions/3785)).
- **SmartHome devices:** Einschaltschwelle / Ausschaltschwelle in W and Mindesteinschaltdauer ([forum](https://forum.openwb.de/viewtopic.php?p=115327)).
- The forum has moved to GitHub Discussions.

### Commercial and vendor systems

**SMA Sunny Home Manager 2.0** ([datasheet HM-20-DS-de-50](https://files.sma.de/downloads/HM-20-DS-de-50.pdf)). The datasheet lists:
- Forecasts for producers and consumers over **24/48 h**, and **learning of recurring loads and their load profiles**.
- Consumer priorities and configurable time windows, with **"Kann" (use PV surplus) vs "Muss" (target must be met)**.
- 24 measurable / 12 controllable devices, over SEMP and EEBUS.
- Smart plugs, washer/dishwasher/dryer, heat pumps (SG-Ready only via an external relay), and EV chargers.
- **Dynamic active-power control** as a percentage, a fixed value, an external setpoint, or zero export.
- Peak shaving, readiness for §14a dimming, and "Visualisierung Handlungsempfehlung" (action recommendations).
- Dynamic tariffs are marked "—" in the 6/2024 datasheet. Later firmware (≥2.18) supports them in Germany, booked through the SMA Energy App ([DynTarif manual](https://files.sma.de/downloads/DynTarif-BA-de-13.pdf)).
- SMA's own guidance: a minimum switch-on time ≤5 min plans well, while >30 min "causes planning difficulties" ([manual](https://manuals.sma.de/HM-20/en-US/index.html)). Must-window loads get excess PV first ([time windows](https://manuals.sma.de/HM-20/en-US/10609313419.html)).

**Solar Manager (CH)** ([dynamic tariffs](https://www.solarmanager.ch/dynamische-stromtarife))
- **Hardware:** Connect 2 / Flux gateways, advertised as compatible with 500+ devices ([Solarserver](https://www.solarserver.de/2024/12/02/solar-manager-bringt-photovoltaik-energiemanagementsystem-connect-2-heraus/)).
- **Tariffs:** 15-min spot prices, a "Gebühren + Abgaben" surcharge field, and a separate feed-in reference price.
- **Device modes:** "Solar only" or "Solar & Tarifoptimiert".
- **Battery:** grid charging under a price limit that takes the solar forecast into account. It needs a battery with Active Control.
- **Other devices:** EV target SoC, washer/dishwasher scheduled into cheap windows, and heat pumps with dynamic setpoint optimisation (AIT), which the vendor says is more precise than SG-Ready ([Solarserver](https://www.solarserver.de/2024/11/29/energiemanagement-fuer-waermepumpen-von-alpha-innotec-und-novelan/)).
- **Pricing:** a subscription model. A 2024 dealer presentation quotes 48 and 72 €/year ([PDF](https://www.zajadacz.de/documents/AZ_DB_20_2024_SolarManager_Vorstellung_DEHA.pdf)).

**clever-PV** (cloud-to-cloud) ([features](https://clever-pv.com/en/?p=1484))
- Drag-and-drop priorities.
- **Sollzeiten:** a minimum runtime placed at the cheapest times.
- A price threshold per device.
- SG-Ready / PV-Ready heat pumps, heating rods, and a wallbox with phase switching.
- **Battery:** SoC planner, Eco-Offset, Boost, and discharge into the car.
- **AI battery grid charging:** forecasts PV and household load and weighs efficiency, wear and calendar ageing ([ess-news](https://www.ess-news.com/?p=3664)).
- An EV charge planner with recurring weekday plans.
- A PV forecast with a learning phase of about 10 days, and a daily push of the expected yield ([appgefahren](https://www.appgefahren.de/clever-pv-integriert-intelligente-pv-prognose-als-beta-372698.html)).
- Statistics on autarky, self-consumption and costs.
- Subscription tiers (Starter and Clever, from 4 and 6 €/month as of Jan 2025).

**Victron ESS / Dynamic ESS** ([DESS doc](https://www.victronenergy.com/live/drafts:dynamic_ess), last modified 2026-09-04)
- **What it does:** the VRM cloud builds a charge/discharge schedule from day-ahead prices, the PV forecast and the consumption pattern.
- **Modes:** Green (keep battery energy for self-use) and Trade.
- **Battery cost:** entered in €/kWh as purchase cost divided by (cycles × capacity), plus a system efficiency setting.
- **Restrictions:** block battery export, time-based restrictions, and AC import/export current limits on the GX device.
- **"Disable solar at low buy prices":** curtails PV when the buy price drops below a threshold.
- **Negative prices:** an option to treat them as 0, set separately for buy and sell ([announcement](https://community.victronenergy.com/t/vrm-feature-announcement-manage-negative-energy-prices-in-dynamic-ess/1532)).
- **Fallback:** if VRM is unreachable for more than 12 h, the schedule runs out and the system **falls back to plain ESS**.

**Fronius Ohmpilot** ([manual](https://manuals.fronius.com/html/4204260538/en-US.html))
- **Power control:** stepless PWM from 0.3 to 3 kW on one phase. Three-phase goes up to 9 kW: L1 modulated, L2/L3 switched in 3 kW steps.
- **Heater 2:** a second rod, a heat pump via an SG-Ready relay, or an external source. It is used only once Heater 1 hits its maximum temperature.
- **Temperature functions:** minimum water temperature with a PT1000 sensor (may draw grid power), and legionella heating to 60 °C on an interval.
- **Other:** a day curve, Boost (4 h at full power), temperature limiting, and a circulation-pump relay.

**E3/DC (Hager)** ([2026 "Vorteils-Checkliste" PDF](https://www.e3dc.com/wp-data/uploads/2026/03/Vorteils-Checkliste-2026-1.pdf); this is vendor marketing). It lists:
- Wallbox load management for up to 7 wallboxes, with solar- and price-optimised control (Sonnenmodus, charge strategies).
- Automatic phase switching, car charging from the battery with an adjustable SoC discharge threshold, and V2H with the edsn bidirectional charger.
- Heat pumps via SG-Ready, Modbus SunSpec or smart home, and stepless heating rods such as my-PV.
- Dynamic tariffs "via AI 360° or individual price thresholds", a self-learning AI for heat-pump and battery price optimisation, and forecast-based battery charging.
- §14a compliance including modules 1 and 3, readiness for the Solarspitzengesetz ("zeitversetzte Einspeisung", i.e. time-shifted feed-in), an adjustable backup-power reserve, and black start.
- Smart-home links to KNX, Loxone and HA.

**SENEC.** The PowerPilot HEMS was rebuilt for June 2026. The vendor claims 700+ devices and dynamic tariffs. Home P4 and E4 gained forecast-based charging and dynamic tariff support, and SENEC has cooperated with Buderus on heat pumps since June 2026 ([Solarserver](https://www.solarserver.de/2026/06/23/ees-europe-2026-neue-batteriespeicher-generation-von-senec/), [PowerPilot one-pager](https://senec.com/sites/default/files/2025-05/OnePager_PowerPilot.pdf)). evcc's docs say SENEC battery control supports only grid charging, with no discharge lock ([evcc](https://docs.evcc.io/en/meters/senec-home)).

**Kostal.** The energy management here is thin:
- PLENTICORE G3 is "prepared for dynamic tariffs" through AutoUpdate ([page](https://www.kostal-solar-electric.com/en/dynamic-electricity-tariffs/plenticore-equipped-for-dynamic-electricity-tariffs/)).
- SG-Ready and Modbus TCP control are listed in the PLENTICORE comparison sheet ([PDF](https://www.kostal-solar-electric.com/fileadmin/downloadcenter/kse/FS_KOSTAL_PLENTICORE_Versionsvergleich_de.pdf)).
- Wallbox surplus charging needs an external energy manager or the Smart Energy Meter ([PDF](https://www.kostal-solar-electric.com/fileadmin/downloadcenter/kse/Wallbox-mit-Wechselrichter-kombinieren.pdf)).
- Multi-Device-Control and the ENECTOR G2 wallbox were shown at Intersolar 2026 ([solarmagazine](https://solarmagazine.nl/nieuws-zonne-energie/i43813/kostal-presenteert-nieuwe-omvormer-voor-batterijen-en-laadpalen)).

---

## 2. Capability catalogue by category

### 2.1 Forecasting

| Capability | How it works (concrete) | Who has it | AURUM |
|---|---|---|---|
| PV forecast | External sources: Solcast, Forecast.Solar, open-meteo, or the vendor's own weather model. clever-PV calibrates against actual yield during a ~10-day learning phase. EMHASS has an optional ML correction (`set_use_adjusted_pv`). | PVEC, EMHASS, Predbat, evcc (optimizer), SMA, SolMgr, cPV, DESS, E3/DC, SENEC; openWB still in discussion | Y. Solcast/Open-Meteo remaining-energy budget with a persisted safety factor; hourly attribute, with a 19:00 sunset fallback |
| Pessimistic / scenario PV | Predbat blends in a 10 % pessimistic case (`pv_metric10_weight`, default 0.15) and shows a "10 % scenario" cost | Predbat | ~ (safety factor) |
| Load forecast | EMHASS `mlforecaster` (skforecast). Predbat history plus Load ML. SMA "learns recurring loads and their load profiles". DESS consumption pattern. clever-PV and E3/DC "AI". | EMHASS, Predbat, SMA, DESS, cPV, E3/DC | – |
| Price forecast / horizon | evcc 15-min forecasts (0.300). DESS shows the next day's plan from about 3 PM. Solar Manager 15-min spot prices plus a surcharge field. EMHASS via csv or runtime injection. | evcc, DESS, SolMgr, Predbat, EMHASS, PVEC, openWB, cPV | ~ (reads current price, level, and a cheap-period binary only) |

**What users report:**
- Forecast errors are the top DESS complaint: consumption forecasts with zero hours, PV forecasts that disappear or come out 2–6× too high ([PV forecast broken](https://community.victronenergy.com/t/dynamic-ess-pv-forecast-broken/4572), [archive](https://communityarchive.victronenergy.com/articles/245772/dynamic-ess-on-beta-vrm-part-3%EF%B9%96childToView=248325.html)).
- PVEC users report Solcast tomorrow = 0 (#42) ([issues](https://github.com/InventoCasa/PV-Excess-Control/issues)).
- Predbat users ask to exclude unusual, price-driven consumption from load learning ([issues](https://github.com/springfall2008/batpred/issues)).
- Late next-day prices break plans: in openWB, Tibber prices arrived late and Zielladen planned wrongly ([#3703](https://github.com/openWB/core/issues/3703)). DESS has "Delayed import of purchase prices" ([tag](https://community.victronenergy.com/tag/dess)).
- DST and timezone bugs hit EMHASS ("Mixed timezones detected", issue #769, twice a year) ([forum p.189](https://community.home-assistant.io/t/emhass-an-energy-management-for-home-assistant/338126?page=189)) and DESS (a 2 h schedule offset, forecast problems after the DST change) ([tag](https://community.victronenergy.com/tag/dess)).

### 2.2 Optimisation approach

| Approach | Systems | Notes |
|---|---|---|
| Rule / priority cascade (reactive) | AURUM, Hanergy, openWB SmartHome, Ohmpilot, evcc (non-optimizer), PVEC controller | Fast (10–30 s) and explainable, but has no look-ahead |
| Stochastic search over the current state | Solar Optimizer (simulated annealing: T0 1000, cooling 0.95, 1000 iterations) | Globally better packing of mixed loads; CPU-heavy, so ~5-min cycles |
| Rules plus a forward planner | PVEC (30 s controller + 15-min 24 h planner), SMA (24/48 h planning of Kann/Muss loads), evcc plans, openWB Zielladen, clever-PV Sollzeiten | The hybrid that is becoming the standard |
| LP / MILP or MPC | EMHASS (CVXPY/HiGHS, MPC mode), HAEO (pure LP, 48 h), evcc Optimizer (experimental, recommendations only) | Most powerful; hardest to set up; actuation is left to the user (EMHASS) or not yet built (evcc, HAEO) |
| Custom cost-model search | Predbat (cost metric with wear, pessimism, min-improvement thresholds) | Battery and export focused |
| Cloud-computed schedule | DESS, clever-PV, Solar Manager, E3/DC "AI 360°", SENEC | Needs an offline fallback (DESS reverts to plain ESS after 12 h) |

**What users report:**
- **Loop period matters a lot.** Solar Optimizer's 300 s cycle leaves loads on for about 5 min of grid draw at dawn and dusk. Users ask for it to be removed, and complain that loads start while export is still too small ([HACF p.16](https://forum.hacf.fr/t/solaroptimizer-optimisez-votre-consommation-solaire/59665?page=16)).
- PVEC's default 30-min averaging window plus a 600 s minimum switch interval kept a pool heater on, "drains my battery" ([HA thread](https://community.home-assistant.io/t/pv-excess-control-solar-excess-optimizer-as-a-hacs-integration-successor-of-the-pyscript-blueprint/1003122)).
- PVEC's dynamic current reacts so often that it exhausts monthly cloud API quotas (#41).
- The Hanergy vs EMHASS comparison is vendor-written, but its point holds: an LP schedule is static between runs, while a cascade misses global optima ([Hanergy](https://hanergy-website.pages.dev/blog/hanergy-vs-emhass)).

### 2.3 Device control types

| Type | Concrete mechanism | Who |
|---|---|---|
| On/off relay or plug | Switch domains; evcc "smart switches"; SMA smart plugs; openWB Shelly | All except DESS |
| Variable power / setpoint | SO `power_min/max/step` writing to number/select/climate; PVEC writable current entity 6–32 A; evcc phase-aware current down to mA (openWB 2.x); my-PV/Ohmpilot PWM 0.3–3 kW; E3/DC stepless heating rod | SO, PVEC, evcc, openWB, Ohmpilot, E3/DC, cPV, SolMgr, SMA (EEBus/SEMP), EMHASS (continuous loads) |
| 1p/3p phase switching | Charging can start at 1.4 kW instead of 4.1 kW (evcc); live phase count (PVEC rc); E3/DC and clever-PV automatic | evcc, openWB, cPV, E3/DC, PVEC (requested: automatic switching) |
| SG-Ready heat pump | Two relays: boost (encouraged/ordered) and dim (§14a or grid constraint); the heat pump may ignore the request | evcc, SMA (external), Ohmpilot Heater 2, openWB, E3/DC, Kostal, cPV, SolMgr |
| Heat-pump API / setpoint | evcc vendor templates; Solar Manager AIT dynamic setpoint; Buderus MX400 local | evcc, SolMgr, E3/DC |
| Heating rod with temperature logic | Ohmpilot minimum temperature, legionella interval, max-temp limiting; evcc "temperature limits are not a safety feature" | Ohmpilot, evcc, my-PV |
| Program appliances (washer, dishwasher) | SMA SEMP/EEBus with BSH/Miele: the appliance announces its program and the manager sets the start; EMHASS power-sequence profile; Solar Manager cheap-window scheduling | SMA, EMHASS, SolMgr, **AURUM (power-based startup detection)** |
| Batteries | Mode, setpoint or SoC writes (Predbat, evcc, DESS, openWB, PVEC) | see 2.4 |
| Coupled / dependent devices | PVEC "appliance dependencies"; EMHASS `deferrable_load_groups` (shared budget, mutual exclusion) | PVEC, EMHASS. SO explicitly lacks it ("no link between devices" ([HACF](https://forum.hacf.fr/t/solaroptimizer-optimisez-votre-consommation-solaire/59665?page=16))) |

**What users report:**
- Device-specific state detection is fragile: Daikin climate entities report "off" while idle, which PVEC fixed in v0.2.3 by switching from an on-state allow-list to an off-state deny-list.
- The Easee integration lacks a usable current entity.
- openWB heating rods pulsed instead of throttling while the car charged ([forum](https://forum.openwb.de/viewtopic.php?p=115327)).
- SO users ask for a documented minimum time between power steps, to protect heat pumps.

### 2.4 Battery handling

| Feature | How | Who |
|---|---|---|
| Battery-first vs device-first | evcc priority SoC; PVEC Battery First / Appliance First / Balanced | evcc, PVEC, AURUM (global battery-priority toggle) |
| Battery as buffer for loads | evcc buffer SoC plus auto-start SoC; E3/DC car charging from battery with an SoC threshold; clever-PV "discharge into the car" | evcc, E3/DC, cPV |
| Discharge protection | PVEC limits discharge rate while big loads run; evcc discharge lock during fast/planned charging; Predbat `car_charging_from_battery=off` holds the battery | PVEC, evcc, Predbat |
| Soft and hard reserve | Predbat `best_soc_keep` (soft) / `best_soc_min` (hard); E3/DC adjustable backup reserve; DESS minimum SoC | Predbat, E3/DC, DESS, EMHASS |
| Grid charging under a price threshold | evcc price/CO₂ limit plus `maxsoc`; Solar Manager "Tarifoptimiert"; PVEC forced grid charge; clever-PV AI charging | evcc, SolMgr, PVEC, cPV, DESS, Predbat, EMHASS, E3/DC, SENEC |
| Arbitrage / export trading | DESS Trade mode; Predbat forced export with `metric_min_improvement_export` | DESS, Predbat, EMHASS |
| Wear cost | DESS €/kWh; Predbat `metric_battery_cycle`; EMHASS weights; clever-PV ageing model | DESS, Predbat, EMHASS, cPV |
| Forecast-based charge throttling (avoid curtailment) | E3/DC SmartCharge; SMA forecast-based charging; PVEC dynamic battery charging | E3/DC, SMA, PVEC, SENEC |

**What users report:** battery behaviour that contradicts the settings is the dominant complaint across products.
- PVEC: battery not prioritised with battery-first on (#44); "Shed imminent" never sheds, so appliances run on battery for hours (#57) ([issues](https://github.com/InventoCasa/PV-Excess-Control/issues)).
- DESS: Green mode still sells battery energy to the grid on FW v3.80 (Sept–Oct 2026), and users disagree about what Green mode is supposed to do ([thread](https://community.victronenergy.com/t/switching-from-trade-to-green-mode-still-drains-battery-to-grid/63147)). Other threads: "ESS ignores grid setpoint, feed-in limit and Min SOC", "DESS using battery instead of grid during low price" ([tag](https://community.victronenergy.com/tag/dess)).
- EMHASS: the forecast still discharges to the grid with "no discharge to grid" set ([forum](https://community.home-assistant.io/t/emhass-an-energy-management-for-home-assistant/338126?page=189)).
- openWB: PV mode drew from the home battery ([forum](https://forum.openwb.de/viewtopic.php?p=129059)). Eco mode can drain the home battery if the storage system doesn't know the price too ([discussion](https://github.com/openWB/core/discussions/4151)).
- Predbat: inverter writes that revert or never land on GivEnergy, Solis, Sigenergy, Fox and Sunsynk, and "slots flagged Planned Charge are not actually charging" (406 open issues) ([issues](https://github.com/springfall2008/batpred/issues)).

### 2.5 Tariffs

| Feature | Who | Notes |
|---|---|---|
| Spot / dynamic import price | most | evcc, SolMgr and DESS natively. HA tools read sensors from Tibber, Nordpool, aWATTar, Octopus or EPEX. |
| Per-device price threshold | AURUM (`max_price`), PVEC, cPV, evcc (per loadpoint), E3/DC | Basic, expected feature |
| Price + SoC gating | AURUM `cheap_grid_soc`; PVEC battery-charge-price thresholds | AURUM's version is clean |
| Cheapest-N-slots before a deadline | evcc plans, openWB Zielladen, cPV Sollzeiten, SMA Muss windows, EMHASS, Predbat car, PVEC planner | **AURUM missing** (it only asks "is it cheap now") |
| Variable feed-in price / opportunity cost | evcc feed-in priority; PVEC opportunity cost; SO export price in objective; DESS sell formula; EMHASS | AURUM treats all export as free surplus |
| Negative prices | DESS treat-as-zero option and "disable solar at low buy prices"; EMHASS ignores negative prices in startup cost | Matters more under the Solarspitzengesetz (below) |
| Grid fees / surcharges / time-variable network fees | evcc `chargesZones` (§14a module 3); Solar Manager "Gebühren + Abgaben"; DESS buy formula | Matters for §14a module 3 time-variable network fees |
| Demand / capacity charge | EMHASS `capacity_cost_per_kw`; SMA peak shaving; DESS capacity-tariff thread | BE/SE capacity tariffs |

**Unit and sign traps are a recurring theme:** EMHASS mixes W and kW and needs template sensors; AlphaESS reports import as positive, and the inverted template sensor went unavailable, which paused PVEC ([HA p.3](https://community.home-assistant.io/t/pv-excess-control-solar-excess-optimizer-as-a-hacs-integration-successor-of-the-pyscript-blueprint/1003122?page=3)); AURUM has its own EUR-vs-ct trap in `price_entity`.

### 2.6 Grid constraints

- **§14a EnWG.** Since 1 Jan 2024, controllable consumers above 4.2 kW may be dimmed but not switched off. The guaranteed minimum is 4.2 kW, with aggregation formulas for several devices, signalled through an FNN control box and a smart-meter gateway ([42watt](https://42watt.de/magazin/paragraph-14a-enwg)).
  - Implemented by evcc (dim to minimum, pause battery grid charging), SMA, openWB (EEBUS inputs) and E3/DC (modules 1 and 3).
  - **No HA surplus tool (AURUM, SO, PVEC) handles it.**
- **Solarspitzengesetz (Feb 2025).** New systems without a smart meter are capped at 60 % feed-in, and new systems get no remuneration during negative-price hours ([Rödl](https://www.roedl.com/insights/das-solarspitzengesetz-zweitausendfuenfundzwanzig-wichtige-aenderungen-fuer-erneuerbare-energie-anlagen/), [pv magazine](https://www.pv-magazine.de/2025/12/22/keine-angst-vor-dem-solarspitzengesetz-wir-erlaeutern-die-neue-erloessituation/)). This makes absorbing would-be-curtailed power the main value driver.
  - PVEC: "Export limit management" plus a cap-follower for the battery.
  - evcc: a static export limit in the optimizer, and §9 EEG curtailment.
  - SMA: dynamic active-power control and zero export.
  - DESS: AC export limits and PV curtailment.
  - E3/DC: "zeitversetzte Einspeisung" (time-shifted feed-in).
  - EMHASS: `maximum_power_to_grid` and `compute_curtailment`.
- **Curtailed or zero-export systems hide surplus.** When the inverter throttles, the grid meter shows ~0 W even though more PV is available.
  - evcc: "Systems with regulated zero export do not work with solar surplus charging" ([solar charging](https://docs.evcc.io/en/features/solar-charging)).
  - PVEC: a Deye in no-export mode never starts appliances ("Insufficient excess (-19W < 180W needed)") and issue #21. One user forked PVEC to detect unused production from string voltage.
  - Victron: "October Fronius software update silently breaks Victron solar output throttling" ([tag](https://community.victronenergy.com/tag/dess)).
  - **AURUM has the same blind spot.** Its PV power gate (`pv_power_threshold`) is a partial workaround.
- **Load management / main fuse.** evcc circuits and openWB load management are wallbox-centric. E3/DC manages up to 7 wallboxes.

### 2.7 User interaction

| Feature | Who |
|---|---|
| Manual override, force on for X hours | SO `start_device` (1/4/12/24 h, survives restart); PVEC Enabled / Override / Pause; Predbat manual charge/export/freeze selectors; evcc mode per loadpoint; AURUM override plus "must run today" |
| Deadlines / departure time + target | evcc plans (late-charging window 15 min–2 h); openWB Zielladen; Predbat `car_charging_plan_time`; PVEC deadlines; AURUM deadline + estimated runtime |
| Recurring schedules | clever-PV weekday plans; SMA time windows; openWB Zeitladen |
| Allowed time windows (earliest start / latest end) | SMA, PVEC, EMHASS start/end timesteps, SO via template | **AURUM: only a deadline and daily reset hour, no "not before" window** |
| Daily min/max runtime | SO, PVEC, cPV Sollzeiten, EMHASS operating hours, AURUM (deadline, `stop_after_runtime`) |
| Holiday / away mode | Predbat holiday mode (load scaling 0.7) |
| Advisory / dry-run mode | Predbat Monitor + `set_read_only`; HAEO and the evcc Optimizer are recommendation-only; requested for PVEC ("indicator-only mode", Aug 2026) ([HA p.3](https://community.home-assistant.io/t/pv-excess-control-solar-excess-optimizer-as-a-hacs-integration-successor-of-the-pyscript-blueprint/1003122?page=3)) |
| Mobile app, widgets, remote access | evcc (iOS/Android, iOS widgets, remote access 2026), clever-PV, Solar Manager, SMA Energy App, E3/DC |
| Presets / "solar share" | evcc Solar Share slider (100 % = full minimum power from PV, 0 % = any surplus); PVEC grid supplementation |

Setup complexity is the biggest complaint about the LP and battery tools. Predbat's apps.yaml needs per-inverter templates and a file editor, and users ask for working examples ([HA](https://community.home-assistant.io/t/predbat-anyone-have-a-working-apps-yaml-example-for-fox-kh7-inverter/1015045)). EMHASS needs user-written automations per load. PVEC users can't find the setup wizard after installing from HACS, or don't understand "Battery discharge override: 500".

### 2.8 Transparency and explanations

- **Plan visualisation:** the Predbat plan card shows SoC, rates, slots and the 10 % scenario, plus calibration charts. DESS graphs the price and plan in VRM. evcc's battery page and optimizer page show recommendations and feasibility ("can all goals be met?"). SMA has "Handlungsempfehlung". The PVEC dashboard has a plan timeline, which is reported broken in #20.
- **Live state reasons:** SO card badges (ACTIVE/MANUAL/WAITING…) with attributes such as `next_date_available` and `is_usable`. evcc shows "Boost requested…". PVEC writes per-appliance status messages, e.g. "Insufficient excess (-19W < 180W needed)", "excess calculation paused".
- **AURUM is above par here.** A single Advisor sensor gives the "current decision" with localised per-device reasons, published as attributes for automations, plus a self-adapting sidebar panel. None of the HA competitors has a reason sensor that automations can use. The missing piece is the forward view (§4).

### 2.9 Safety and fallbacks

- **Offline fallback:** DESS reverts to plain ESS when VRM is unreachable for more than 12 h or prices are missing. The local OSS tools don't depend on a cloud.
- **Fail-open vs fail-closed sensors:** PVEC pauses all excess calculation when a required sensor is unavailable. AURUM's run condition fails open on an unavailable sensor; that is documented, but users should be aware of it for a water heater.
- **Thermal safety:** evcc and Ohmpilot both stress that the hardware thermostat stays the safety element; evcc's limits are explicitly "not a safety feature".
- **Anti-cycling:** minimum on/off times are universal (SO `duration_min/stop_min`, EMHASS `def_minimum_on_time`, openWB Mindesteinschaltdauer, SMA minimum switch-on time). SMA advises keeping it ≤5 min for plannability, and Solar Manager tells CTA heat-pump owners not to shorten delays ([PDF](https://www.solarmanager.ch/wp-content/uploads/2025/08/SolarManager_Geraeteuebersicht_CTA_AH.pdf)).
- **Read-only / kill switch:** Predbat `set_read_only`, which resets the inverter to native settings. PVEC Master Control, though #71 reports that disabling it turns off always-on devices. SO per-device enable switch.
- **Protect the plan from manual interference:** Predbat issue "doesn't recover from lost/reverted inverter writes". PVEC "fewer redundant charger commands" (rc). In general, re-asserting state every cycle can fight the user; AURUM's "manually-on vs override" table handles this explicitly.
- **External controllers conflicting:** Tibber Grid Rewards vs PVEC ("2 captains on 1 ship??"). evcc docs warn that active battery control overrides E3/DC SmartPower settings ([evcc E3/DC](https://docs.evcc.io/de/meters/e3-dc)).

### 2.10 Reporting

- **Savings and costs:**
  - Predbat: savings tracking and the What-If payback.
  - PVEC: savings, self-consumption ratio, and persistent daily runtime/energy/activation counters (rc).
  - evcc: sessions with costs, charge added and estimated range; time-based statistics (July 2026).
  - clever-PV: autarky, self-consumption, costs.
  - SMA, Solar Manager, E3/DC: portals.
- **Per-device energy:** AURUM kWh/day (Energy Dashboard compatible); SO on-time today.
- **AURUM gap:** cost and autarky per device is still an open roadmap item. Nobody in the HA space breaks out "solar share per device" plus "€ saved vs grid price" plus "feed-in revenue forgone", and that is a cheap differentiator.

### 2.11 Ecosystem and integrations

- **evcc** is the hub: MQTT, REST, MCP, HA, ioBroker, Homey, openHAB, Garmin, and a white-label UI. Many commercial wallboxes and my-PV heaters need a **sponsor token** ([sponsorship](https://docs.evcc.io/en/sponsorship)).
- **SMA** speaks SEMP and EEBUS. Third-party devices such as SmartApplianceEnabler and BSH appliances plug in as SEMP devices, and SEMP is off by default on the charger side ([SMA EVC](https://manuals.sma.de/EVCxx20/en-US/15906683019.html)).
- **Solar Manager** has a community HA integration via the gateway's local REST API, with no cloud account needed ([HA](https://community.home-assistant.io/t/solar-manager-integration-solar-manager-ch-local-sensor-polling-full-device-control/1017665)).
- **E3/DC** exposes RSCP and Modbus; **Victron** exposes Node-RED and the DESS API.

---

## 3. Cross-cutting praise and complaints

**Praised:**
1. **"Set and forget after an afternoon."** A Predbat user on Octopus Agile: "It took an afternoon to configure, but it has been running hands-off since" ([blog](https://livesolar-wales.pages.dev/blog/why-i-switched-to-octopus-agile)).
2. **Ease of use** in clever-PV, recommended by colleagues in renewable-energy research as "easy to use" ([GoingElectric](https://www.goingelectric.de/forum/viewtopic.php?p=1984913)).
3. **Responsive maintainers:** PVEC fixed bugs within days (v0.2.3), and jmcollin78 answers on HACF with calculations.
4. **Vendor neutrality and local control** for evcc and HA tools.
5. **Visible plans:** Predbat, DESS VRM, evcc.

**Complained about** (most frequent first):
1. **Battery behaviour contradicting settings:** DESS, PVEC #44/#57, EMHASS, openWB Eco, Predbat.
2. **Flapping vs sluggishness:** SO's 5-min loop vs PVEC's 30-min averaging vs openWB rod pulsing. Users want fast shutdown on import and slow, damped startup.
3. **The plan diverges from reality,** usually because of forecast errors or late price data.
4. **Setup complexity and unclear parameters:** Predbat apps.yaml, EMHASS automations, PVEC "discharge override".
5. **Sign and unit conventions:** W vs kW, import sign, EUR vs ct.
6. **Hidden surplus** with zero-export or curtailed inverters.
7. **DST and timezone bugs:** EMHASS, DESS.
8. **Paywalls, subscriptions and cloud:**
   - evcc sponsor token for OCPP and commercial wallboxes, plus a licence check at startup ([energiesparhaus](https://www.energiesparhaus.at/forum/76331_3)).
   - Solar Manager subscription split into Basic and Premium.
   - clever-PV premium tiers.
   - SMA's Sunny Portal → ennexOS migration ([SMA](https://www.sma.de/en/products/energy-management/sunny-portal/sunny-home-manager-migration)), and firmware 2.17.2.R broke HA data for one user ([simon42](https://community.simon42.com/t/sma-sunny-home-manager-2-0-liefert-nach-firmwareupdate-keine-daten-mehr/59888)).
9. **Device-specific integration gaps:** Easee current entity, climate state detection, Fox export registers in EMHASS.
10. **Cloud API rate limits** from aggressive control (PVEC #41).

---

## 4. What such systems must be able to do, and where AURUM should improve

**Baseline every serious system now has. AURUM already meets it:**
- surplus detection with hysteresis and debounce
- priorities
- SoC floors
- minimum on/off times
- manual override
- a price threshold
- deadline / minimum runtime
- PV-forecast awareness
- notifications
- persistence across restarts

AURUM's **Advisor** (explanations for every decision) and its **power-based startup detection** for program appliances are genuine differentiators. In the HA/OSS space, only SMA does washer/dishwasher handling, and that needs SEMP/EEBus appliances.

**Gaps, ranked by user demand and competitive pressure:**

1. **Variable-power devices.** SO, PVEC, evcc, openWB, Ohmpilot, E3/DC, clever-PV and Solar Manager all have them. AURUM is on/off only, so EV chargers and heating rods can't follow surplus.
   - Proposal: an optional "variable" device type that writes a `number` (W or A) with min/max/step, plus an optional phase-count entity. Allocate it the *remaining* surplus after the on/off devices, with a minimum time between steps; SO users explicitly asked for that.
2. **Look-ahead price scheduling to a deadline.** evcc, openWB, clever-PV, SMA, EMHASS, Predbat and PVEC do this; AURUM only asks "is it cheap now".
   - Proposal: read price forecast attributes (Tibber Prices / Nordpool today+tomorrow).
   - For each device with `deadline` + `estimated_runtime`, choose the cheapest slots, net of expected PV surplus from the hourly forecast AURUM already reads.
   - Expose the planned slots in the Advisor and panel, so the user sees *when* a device will run, not only why it is or isn't running now.
3. **Negative-price and export-cap handling.** The Solarspitzengesetz and §51 EEG make this a German must-have; competitors with it are PVEC, evcc, DESS, SMA, E3/DC and EMHASS.
   - Proposal: a global "price ≤ 0 → treat as surplus for all flexible devices" rule, independent of `price_mode`.
   - Plus an optional feed-in cap (W or % of kWp) and a PV-power signal, so that AURUM starts loads *before* the inverter curtails. That also fixes the hidden-surplus problem with zero-export setups (generalise `pv_power_threshold`).
4. **Battery discharge protection for devices.** PVEC "discharge protection", evcc discharge lock, Predbat `car_charging_from_battery`.
   - Proposal: a per-device or global "max battery discharge attributable to devices (W)", using the battery power sensors AURUM already reads.
   - Plus an optional user-supplied "discharge block" switch or number that AURUM sets while a device runs in `cheap_grid` mode, so a grid-priced run doesn't silently empty the battery. This is the behaviour users complain about most across all products.
5. **Cost and savings reporting** (already on the roadmap).
   - Per device: solar kWh vs grid kWh, € at the actual price, and feed-in revenue forgone.
   - System-wide: autarky and self-consumption.
   - Cheap for AURUM because the per-device kWh and the price sensor are already there.
6. **Advisory / dry-run mode.** Predbat Monitor and evcc recommendations offer it; PVEC users asked for it. A global switch would let the Advisor say what it *would* do without switching anything. Good for onboarding and trust.
7. **Device dependencies and allowed time windows.**
   - Run condition on a binary or switch state ("only if pool pump is on").
   - An optional "not before HH:MM" window (SMA, PVEC, EMHASS start timesteps), e.g. for noise-sensitive appliances at night.
8. **SG-Ready and §14a.**
   - A heat-pump device type with a boost relay and an optional dim relay (evcc model).
   - A global §14a binary sensor that caps total managed load at the guaranteed minimum and blocks cheap-grid starts while active (evcc's approach).
9. **Robustness lessons from competitors' bug trackers:**
   - Validate sign and units at config time: AURUM could detect EUR/kWh and convert, warn when grid power is never negative during daylight, and so on.
   - Make DST-safe daily resets and deadlines explicit tests.
   - Treat late or missing next-day prices as "unknown, not cheap".
   - Keep shutdown on import fast while startup stays damped; SO's 5-min lag and PVEC's 30-min window are the anti-patterns.
10. **Pessimistic PV weighting and load learning** (Predbat, EMHASS, SMA). AURUM's budget safety factor is a simple form of this; an optional weighting toward a low-PV scenario would cut cases where the battery misses its target SOC.

**Not worth chasing for a lean, generic tool:** full LP/MPC (EMHASS and HAEO already own it, and users complain about the complexity), battery arbitrage/export trading (Predbat, DESS), and inverter-specific battery control (Predbat's issue tracker shows how costly that is).

# Anhang B — Anforderungen & Regulatorik

# Home energy manager and PV-surplus controller requirements in 2026: regulation, tariffs and engineering

*Research report, as of 5 Nov 2026. Main use case: Germany, Tibber dynamic tariff, PV, home battery, EV, water heater and heat-pump-like loads. AURUM itself is used internationally. Sources are linked inline. Where sources disagree or only secondary sources were available, the text says so.*

---

## 0. Summary

1. **Exported energy is now often worth nothing, and sometimes worth less than nothing.** Since 25 Feb 2025, new German PV systems get no feed-in payment for negative-price periods once a smart meter is installed. Until then, feed-in is capped at 60 % of installed power. A draft EEG 2027, still in parliament, would abolish the fixed feed-in tariff for new small systems and make a 50 % cap permanent. For a controller, putting surplus into a load is worth more than exporting it.
2. **Prices come in 15-minute slots.** The EU day-ahead market has been quarter-hourly since 1 Oct 2025, and Tibber's API delivers `QUARTER_HOURLY`. The Home Assistant core Tibber `get_prices` action is still documented as hourly. Controllers must handle 96 slots per day (92 or 100 on DST changeover days), late publication of next-day prices, and the difference between the spot price and the all-in price.
3. **§14a EnWG makes the EMS legally responsible.** If controllable devices (heat pump, private wallbox, battery charging, AC above 4.2 kW) are run through an EMS, the EMS must keep their combined grid draw below the grid operator's setpoint. A controller that starts loads on cheap prices needs a "grid limit active" input.
4. **Rule-based surplus controllers fail in the same few ways in practice:**
   - Flapping.
   - Not adding back the controlled device's own load.
   - Surplus that is hidden because the inverter is curtailing.
   - Stale meter values.
   - Two control loops fighting each other (battery inverter vs. EMS).
   - Compressor short-cycling.
   - Restart side-effects.
   - DST and time-zone bugs.
5. **Optimisation (MPC) beats rules on paper by 6–16 % in simulations, but measured field gains are much smaller (0.8–2.5 % in one test).** A well-built rule engine with forecast and price awareness is a defensible design. Robustness, explainability and fail-safes matter more than optimality.

---

## 1. Regulation and tariffs

### 1.1 §14a EnWG: controllable consumers ("SteuVE") and dimming

**Scope.** It applies to devices above 4.2 kW connection power:
- private wallboxes,
- heat pumps, including heating rods,
- air conditioners,
- battery storage, for the charging direction only.

Several small devices of the same kind (heat pumps among themselves, or AC units among themselves) are added together. Public charge points are excluded. Night storage heaters stay unchanged until 31 Dec 2028. ([BNetzA](https://www.bundesnetzagentur.de/DE/Vportal/Energie/SteuerbareVBE/start.html))

**Dimming rules**
- The grid operator may reduce grid draw only to prevent a concrete overload, and never below a guaranteed minimum (Pmin).
- With **direct control**, Pmin is 4.2 kW per device.
- If the sum of all heat pumps (or all AC units) exceeds 11 kW, Pmin = 0.4 × that sum. ([BNetzA](https://www.bundesnetzagentur.de/DE/Vportal/Energie/SteuerbareVBE/BetroffeneAnlagen_table.html?nn=859060), [e-netz Südhessen TAB](https://www.e-netz-suedhessen.de/fileadmin/download/Technische_Mindestanforderungen_14a.pdf))
- With **EMS control**, the grid operator sends one combined setpoint for all SteuVE behind the EMS. Pmin = 4.2 kW + (n − 1) × GZF × 4.2 kW, where GZF is a simultaneity factor:

  | Number of SteuVE | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9+ |
  |---|---|---|---|---|---|---|---|---|
  | GZF | 0.8 | 0.75 | 0.7 | 0.65 | 0.6 | 0.55 | 0.5 | 0.45 |

  Several heat pumps count as one device. ([dena factsheet](https://www.dena.de/fileadmin/dena/Publikationen/PDFs/2024/240205_KEDi_Factsheet____14a_Web.pdf); BNetzA called these values provisional.)
- **The EMS must make sure that the sum of all SteuVE draw at the grid connection point stays below the setpoint.** It may split the allowance freely between devices, and it may use its own PV or battery discharge to stay compliant. ([e-netz Südhessen TAB §3.1](https://www.e-netz-suedhessen.de/fileadmin/download/Technische_Mindestanforderungen_14a.pdf))
- If a device cannot technically reach the setpoint, it must drop to the next lower possible value, which may be zero. ([same TAB](https://www.e-netz-suedhessen.de/fileadmin/download/Technische_Mindestanforderungen_14a.pdf))
- Feed-in and PV are never dimmed under §14a. Only grid draw is.
- **Preventive dimming** (before the grid operator has proper sensors) is limited to 2 h per day and ends at the latest 24 months after the first preventive use in that grid area. ([BNetzA](https://www.bundesnetzagentur.de/DE/Vportal/Energie/SteuerbareVBE/start.html))
- The grid operator must document control actions and publish them per grid area on vnbdigital.de. ([dena](https://www.dena.de/fileadmin/dena/Publikationen/PDFs/2024/240205_KEDi_Factsheet____14a_Web.pdf))
- The device operator must carry out a command "unverzüglich" (without delay). One secondary source gives a 5-minute reaction time. ([envelio](https://envelio.com/de/paragraph-14a-enwg-ueberblick))

**How the signal reaches the house.** The signal goes from the smart meter gateway to a control box (FNN Steuerbox), and from there to the device or EMS. The interface is either relay contacts or digital. One grid operator's technical rules require VDE-AR-E 2829-6-1 (EEBus) for the digital interface and say BNetzA recommends EEBus as the minimum standard. Old control technology was allowed only until 31 Dec 2025. Devices commissioned before 2024 with an existing control agreement have a transition period until 31 Dec 2028. ([BNetzA](https://www.bundesnetzagentur.de/DE/Vportal/Energie/SteuerbareVBE/start.html), [e-netz TAB](https://www.e-netz-suedhessen.de/fileadmin/download/Technische_Mindestanforderungen_14a.pdf))

**Grid-fee modules**

| Module | What it is | Conditions |
|---|---|---|
| Module 1 | Flat reduction per metering point, roughly 110–190 €/yr (2023 estimate) | Default if the operator chooses nothing |
| Module 2 | Grid-fee energy price cut to 40 % (a 60 % reduction), no grid-fee base charge | Separate meter required |
| Module 3 | Time-variable grid fee with three tiers (HT/ST/NT), windows fixed per grid operator for a calendar year, applied in at least two quarters | Since 1 Apr 2025; only together with Module 1; needs a smart meter (iMSys) |

([BNetzA](https://www.bundesnetzagentur.de/DE/Vportal/Energie/SteuerbareVBE/start.html), [Finanztip](https://finanztip.de/stromtarife/steuerbare-verbrauchseinrichtungen-14a-enwg/))

Forum reports say Tibber passes Module 3 gross prices through and corrects them on the monthly bill, but this varies by grid operator and is not confirmed by Tibber. ([akkudoktor](https://akkudoktor.net/t/modul-3-was-ist-das/35963), [ioBroker forum](https://forum.iobroker.net/topic/67668/tibberlink-adapter/631))

**What a controller should do**
- Accept a "§14a active" input (relay contact via a binary sensor, or EEBus LPC via an add-on such as evcc) and a power limit.
- While the limit is active, cap the summed draw of controllable loads and block cheap-grid starts. evcc pauses battery grid charging during §14a dimming and resumes it afterwards. ([evcc battery docs](https://docs.evcc.io/en/features/battery))
- Log every dimming event.

### 1.2 Solarspitzengesetz (in force 25 Feb 2025)

**No payment at negative prices (§51 EEG).** "For periods in which the spot market price is negative, the payment rate falls to zero." Exceptions:
- systems under 100 kW, until the end of the calendar year in which a smart meter is installed;
- systems under 2 kW, until a later BNetzA determination.

([§51 EEG](https://www.gesetze-im-internet.de/eeg_2014/__51.html)) The old 3–4 hour grace period no longer applies to new systems. Since spot prices are quarter-hourly, secondary sources say the first negative quarter-hour already counts. ([reduco](https://reduco.ai/blog/solar/solarspitzengesetz-60-prozent-regel))

Lost periods are added after the 20-year support term (§51a), with one secondary source saying they are valued at 50 % of rated power. ([co2online](https://www.co2online.de/modernisieren-und-bauen/photovoltaik/solarspitzengesetz/), [j3l7h](https://j3l7h.de/blogmaterial/Solarspitzengesetz.pdf)) Existing systems can opt in voluntarily and get +0.6 ct/kWh. ([BSW](https://www.solarwirtschaft.de/datawall/uploads/2025/01/250131_Bundestag-glaettet-Solarstrom-Spitzen.pdf))

**60 % feed-in cap (§9 (2) EEG).** Until a smart meter plus control unit is installed and successfully tested, systems on feed-in tariff below 100 kW must limit feed-in to 60 % of installed power. Plug-in solar up to 2 kW / 800 VA is exempt. ([§9 EEG](https://www.gesetze-im-internet.de/eeg_2014/__9.html)) The cap is on power at the grid connection, not on energy, so self-consumption can absorb the rest. HTW Berlin estimates losses of 1.1 % (east-west) to 9 % (south) for full-feed-in systems without storage. ([vzhh](https://www.vzhh.de/themen/bauen-immobilien-energie/erneuerbare-energien/solarspitzen-foerdergelder-neue-regeln-fuer-photovoltaikanlagen))

**Consequences for a controller**
1. During negative-price slots, the export is worth 0 €/kWh, or negative under direct marketing. Moving surplus into loads, or deliberately shifting it there, becomes the objective.
2. **Curtailment hides surplus.** Under a 60 % cap, zero-export setups, or a full battery, the inverter curtails, so the grid meter shows export pinned at the cap, or zero. A controller that only reads the grid meter sees no headroom even though PV could deliver more. Practitioners call this out explicitly. ([akkudoktor thread](https://akkudoktor.net/t/pv-ueberschuss-control-fuer-home-assistant/41564)) Ways to handle it:
   - Treat "export ≥ cap − margin" as saturated.
   - Estimate available PV from a forecast or from the inverter's available power.
   - Probe: switch on a load and check whether export stays pinned.
3. **Battery timing.** Filling the battery in the morning wastes it as a buffer for the midday cap. Forecast-based delayed charging is the usual answer.

### 1.3 EEG 2027 draft (not law yet; check status)

- Cabinet approved the draft on 29 Jul 2026. First reading was on 24 Sep 2026 (Drucksache 21/7867). As of mid-October 2026 it was still being debated. It needs Bundesrat passage and EU state-aid approval, and the state-aid approval for the current EEG expires at the end of 2026. ([pv magazine 29 Jul](https://www.pv-magazine.de/2026/07/29/kabinett-beschliesst-entwuerfe-zu-eeg-2027-und-netzpaket/), [pv magazine 14 Sep](https://www.pv-magazine.de/2026/09/14/erste-lesung-von-eeg-novelle-und-netzpaket-auf-der-tagesordnung-des-bundestags/))
- Proposed:
  - end of the fixed feed-in tariff for new systems below 25 kW;
  - mandatory direct marketing;
  - a 50 % feed-in cap for small rooftop systems (70 % for ground-mounted).
- Reports differ on whether the 50 % cap applies only to systems without storage, on transition payments (one draft: 5.2 ct/kWh for at most 36 months), and on end dates. ([pv magazine](https://www.pv-magazine.de/2026/07/29/kabinett-beschliesst-entwuerfe-zu-eeg-2027-und-netzpaket/), [Bitkom position paper](https://www.bitkom.org/sites/main/files/2026-08/bitkom-positionspapier-eeg-flexibilitaet-ermoeglichen-statt-einspeisung-pauschal-begrenzen.pdf), [vdiv](https://vdiv.de/news-details/eeg-novelle-kleine-photovoltaikanlagen-vor-einem-grundlegenden-systemwechsel))
- **Direction for product planning:** feed-in is losing value, and both self-consumption and the ability to absorb peaks are gaining value.

### 1.4 Dynamic tariffs and the price signal

- **Obligation to offer.** Since 1 Jan 2025, every electricity supplier must offer at least one dynamic tariff to customers with a smart meter (iMSys). ([§41a EnWG](https://www.gesetze-im-internet.de/enwg_2005/__41a.html)) At EU level, Directive 2024/1711 gives smart-meter customers the right to request a dynamic contract. ([EU 2024/1711 text](https://www.apren.pt/contents/legislation/directive-eu-2024-1711-en.pdf), [EP summary](https://oeil.europarl.europa.eu/oeil/en/document-summary?id=1785839))
- **15-minute day-ahead.** SDAC/EPEX moved to 15-minute trading units for delivery from 1 Oct 2025. ([EPEX](https://www.epexspot.com/en/news/15-minute-products-live-epex-spot-day-ahead-markets), [pv magazine](https://www.pv-magazine.com/2025/10/01/european-electricity-spot-market-shifts-to-15-minute-trading-blocks))
  - Tibber's GraphQL `priceInfo(resolution: QUARTER_HOURLY)` delivers 15-minute data; HOURLY is the default. ([openHAB community](https://community.openhab.org/t/tibber-and-quarterly-prices/163574/17), [PSTibber](https://www.powershellgallery.com/packages/PSTibber/0.6.4/Content/functions%5CGet-TibberPriceInfo.ps1))
  - The HA core Tibber integration documents `get_prices` as "hourly" and gives no price unit. ([HA Tibber docs](https://www.home-assistant.io/integrations/tibber/))
  - Community integrations (`hass.tibber_prices`, `tibber_adv`) expose 15-minute data. ([hass.tibber_prices](https://github.com/jpawlowski/hass.tibber_prices), [HA forum](https://community.home-assistant.io/t/tibber-advanced-enhanced-tibber-integration-with-quarter-hourly-prices/945403))
- **Publication timing.** Tomorrow's prices usually appear around 13:00 local time. The auction can slip into the afternoon or evening, and on rare auction failures the prices never arrive. Before publication, an empty "tomorrow" is normal and not an error. ([hass.tibber_prices docs](https://jpawlowski.github.io/hass.tibber_prices/user/next/data-actions), [Victron community](https://community.victronenergy.com/t/no-prices-for-tomorrow/6719))
- **Spot price vs all-in price.** Taxes and levies were about 32 % of the household price and grid fees about 28 % (March 2025). A negative spot price therefore usually still gives a positive end-customer price. Negative net prices (down to about −12 ct/kWh) have occurred only in low-grid-fee areas during deeply negative spot hours. ([pv magazine](https://www.pv-magazine.com/2025/05/14/net-electricity-prices-for-end-customers-fall-below-zero/), [zfk](https://www.zfk.de/energie/strom/negativpreise-und-dynamische-tarife-kunden-erhalten-erstmals-geld-zurueck), [energiemarie](https://energiemarie.de/smart-meter/negative-strompreise))
  - Controllers should state which price they compare against.
  - The units trap is real (EUR/kWh vs ct/kWh).
- **How often prices are negative.** Germany had 301 negative hours in 2023, 457 in 2024 and 573 in 2025. 2026 had 242 hours by the end of May. ([Berliner Zeitung](https://www.berliner-zeitung.de/article/573-stunden-minus-deutschlands-strompreise-erreichen-neuen-rekord-10012800), [zfk](https://www.zfk.de/unternehmen/nachrichten/negative-preise-2026-auf-dem-weg-zum-rekordjahr))

### 1.5 Smart meter rollout (MsbG)

- **Mandatory groups:** consumption above 6,000 kWh/yr, a §14a agreement, or generation above 7 kW. ([42watt](https://42watt.de/magazin/smart-meter), [Gleiss Lutz](https://www.gleisslutz.com/en/know-how/smart-meter-rollout-legislative-changes-and-current-installation-trends))
- **Quota:** the 20 % target for end-2025 was widely missed. The federal government reported 434 proceedings against metering operators. ([Bundestag hib 718/2026](https://www.bundestag.de/presse/hib/kurzmeldungen-1216244))
- **Coverage:** about 16 % of mandatory cases were equipped in mid-2025 ([Gleiss Lutz](https://www.gleisslutz.com/en/know-how/smart-meter-rollout-legislative-changes-and-current-installation-trends)) and about 26 % in mid-2026 ([42watt](https://42watt.de/magazin/smart-meter)).
- **Why it matters:** many German users still have no iMSys. That means 60 % cap active, no dynamic-tariff entitlement, and no Module 3. The controller must work in both worlds.

### 1.6 MiSpeL (BNetzA, 1 Oct 2026): mixed grid and PV use of storage

- Home batteries and bidirectional chargers can now charge from the grid (dynamic tariff) and store PV without losing EEG support for the PV share. Re-fed grid power is netted against levies and grid fees.
- Two options:
  - Allocation option: usually two meters.
  - Flat-rate option: households up to 30 kWp, one meter; needs EU state-aid approval first.
- Until the end of September 2027, applying it needs the consent of the grid operator and the metering operator. ([BNetzA press release](https://www.bundesnetzagentur.de/SharedDocs/Pressemitteilungen/DE/2026/20261001_Mispel.html), [BNetzA MiSpeL page](https://www.bundesnetzagentur.de/DE/Fachthemen/ElektrizitaetundGas/ErneuerbareEnergien/EEG_Aufsicht/MiSpeL/start.html))
- **Implication:** price-driven grid charging of the battery becomes legally clean. A controller that coordinates battery grid charging with load shifting becomes more valuable.

### 1.7 Energy sharing (§42c EnWG)

Applies since 1 Jun 2026 within a grid operator's balancing area, and across areas from 2028. Full grid fees still apply, suppliers are not obliged to offer it, and the BNetzA implementing rules were still pending in June 2026. ([Görg](https://www.goerg.de/de/aktuelles/veroeffentlichungen/13-04-2026/bald-strom-mit-nachbarn-teilen-ein-ausblick-auf-das-ab-1-juni-2026-geltende-energy-sharing-gemaess-ss-42c-enwg-chancen-und-grenzen), [cleanthinking](https://www.cleanthinking.de/energy-sharing-deutschland/)) It has little direct controller impact today.

### 1.8 Interface and planning standards

- **EEBus (VDE-AR-E 2829-6 series, IEC 63380 per secondary sources).** These are the use cases for §14a and §9 EEG.
  - **LPC** (Limitation of Power Consumption) and **LPP** (Limitation of Power Production).
  - Failsafe consumption and production limits apply when the control box heartbeat is lost.
  - Failsafe duration is at least 2 h and at most 24 h; evcc defaults to 2 h, and the box overwrites local defaults.
  
  ([evcc FNN Steuerbox](https://docs.evcc.io/en/external-limit/fnn-steuerbox-via-eebus-lpcandlpp-ss-14a-enwg-ss-9-eeg), [enbility eebus-go](https://deepwiki.com/enbility/eebus-go/3.2-energy-guard-(eg)-use-cases), [Bender](https://www.bender.de/docs/charge-controller/hcc/Load-Management/eebus/), [VDE Verlag](https://vde-verlag.de/standards/0800840/vde-ar-e-2829-6-1-anwendungsregel-2022-12.html))
  - **Pattern worth copying:** an explicit failsafe value and failsafe duration whenever the commanding party goes silent.
- **SG Ready (BWP label).**
  - Interface 1.0 has four states. A full lock may last at most 2 h and may be switched at most 3 times per day.
  - Interface 1.1 has three states for heating heat pumps: limited power (configurable, 0 kW or a positive value; BWP recommends the §14a values), normal, and boosted.
  - Every lock or boost signal must stay active for **at least 10 minutes** and may be reactivated no sooner than 10 minutes after it drops.
  - An "SG Ready Novelle 2026" exists. One secondary source claims a migration deadline of 31 Dec 2026 for 1.1; this is unverified.
  
  ([BWP SG Ready](https://www.waermepumpe.de/normen-technik/sg-ready/), [reduco](https://reduco.ai/blog/heizung/sg-ready-waermepumpe-pv-ueberschuss))
- **EN 50491-12-2 "S2"** (being adopted as IEC 63402-2-2). This is a CEM-to-device protocol with five control types:
  - Power Envelope (PEBC),
  - Power Profile (PPBC),
  - Operation Mode (OMBC),
  - Fill Rate (FRBC, for buffers such as tanks or batteries),
  - Demand Driven (DDBC).
  
  It is a good taxonomy for "device classes" in a generic controller. ([s2-ws-json](https://github.com/flexiblepower/s2-ws-json/), [ELAAD/TNO slides](https://elaad.nl/wp-content/uploads/downloads/S2-Current-state-and-future-developments-Res-Flex-Feb-2026.pdf))
- **SMA SEMP.** Each device declares EarliestStart, LatestEnd, MinRunningTime and MaxRunningTime. The difference between Max and Min is optional energy that the EMS hands out only when cheap or surplus power exists. Min = 0 means all of it is optional. evcc exposes a SEMP endpoint. ([openHAB SEMP](https://community.openhab.org/t/new-service-sma-semp-protocol-addons-io/59852), [SMA manual](https://manuals.sma.de/EVCxx20/en-US/15906683019.html), [evcc SHM](https://docs.evcc.io/en/integrations/sma-sunny-home-manager.md))
- **VDI 4657 Sheet 3 (2023-08).** Covers planning and sizing of electrical storage in buildings for self-consumption, feed-in, peak shaving, backup and purchase-cost optimisation. It is a planning guideline, not a specification of how a controller should behave. ([VDI](https://vdi.de/en/home/vdi-standards/details/vdi-4657-blatt-3-planning-and-integration-of-energy-storage-systems-in-energy-building-systems-electrical-storage)) I found no VDI guideline that prescribes HEMS switching behaviour. The behaviour-relevant standards are EEBus/VDE-AR-E 2829-6, FNN control box, SG Ready and S2.

### 1.9 Comparable rules elsewhere (relevant because AURUM is used internationally)

- **Netherlands:** net metering (salderingsregeling) ends completely on 1 Jan 2027. Feed-in is then paid around 4 ct/kWh instead of about 32 ct, and suppliers may charge feed-in costs. Self-consumption becomes the main objective. ([Consumentenbond](https://www.consumentenbond.nl/energie-vergelijken/blijft-de-salderingsregeling-toch-bestaan), [Selectra](https://selectra.nl/energie/zonnepanelen/salderingsregeling))
- **Belgium (Flanders):** capacity tariff. The monthly peak is the highest 15-minute average power, billed on a rolling 12-month average with a 2.5 kW minimum. This requires a **peak-import guard**: do not let price-driven loads stack into one quarter-hour. ([VREG](https://www.vlaamsenutsregulator.be/sites/default/files/toolkit/6812_y22_vreg_campagne_nettarieven_scheurblok_210x297_06.pdf), [Stad Gent](https://stad.gent/nl/huisplus/renoveren/het-capaciteitstarief-hoe-zit-dat))
- **Austria:** summer low-price grid tariff (SNAP) from April 2026. The grid energy price is 20 % lower from 10:00 to 16:00, 1 Apr to 30 Sep; it needs a smart meter in opt-in mode with 15-minute metering. This is a fixed time-of-use component that should stack on top of spot prices. ([AK Wien](https://wien.arbeiterkammer.at/service/presse/AK-Guenstigere-Netzkosten-Sommer-Tarif-SNAP.html))
- **UK:**
  - Smart Charge Points Regulations 2021, reg. 11: a **random start delay of up to 600 s** to avoid synchronised load steps when many devices react to the same price or schedule edge. ([legislation.gov.uk](https://www.legislation.gov.uk/uksi/2021/1467/section/11), [gov.uk guidance](https://www.gov.uk/guidance/regulations-electric-vehicle-smart-charge-points))
  - Octopus Agile passes through negative half-hour prices ("plunge pricing"). ([Octopus](https://octopus.energy/Agile))

---

## 2. Engineering requirements

### 2.1 Define the control variable correctly

- **Add back what you already switched on.** Usable surplus = −P_grid + P(devices this controller has switched on), optionally + battery charge power. Without this, the controller oscillates: surplus 0 → device off → surplus appears → device on. ([akkudoktor](https://akkudoktor.net/t/pv-ueberschuss-control-fuer-home-assistant/41564))
- **Use measured power, not nominal power, wherever a power meter exists.** A water heater whose thermostat has opened still has its switch on but draws 0 W. If the controller reserves its nominal power, lower-priority devices starve. Detect this "satisfied" state and release the reserved power.
- **Battery as a surplus sink.** With battery-priority settings, "battery charging at 3 kW" is surplus the battery absorbs, not surplus for loads. Mature tools use explicit levels:
  - evcc `prioritySoc`: the battery charges first up to this level, and the controller holds it there.
  - `bufferSoc`: above it, the battery may support loads.
  - `bufferStartSoc`: start loads at this SoC even without export.
  - Discharge lock while loads run on cheap grid power or on a plan.
  
  ([evcc battery](https://docs.evcc.io/en/features/battery))
- **Self-regulating loads** (e.g. a modulating heating-rod controller) must count as available surplus, not as house load. evcc models them as `meters.aux`. ([evcc site config](https://docs.evcc.io/en/reference/configuration/site))
- **Residual target.** Regulate to a small export offset (evcc `residualPower`, typically 100–300 W with a battery) instead of exactly 0 W, so the controller and the battery inverter don't fight each other. ([evcc site](https://docs.evcc.io/en/reference/configuration/site), [evcc issue #7362](https://github.com/evcc-io/evcc/issues/7362))
- **Curtailment-aware surplus:** see 1.2.

### 2.2 Fail-safe behaviour when sensors or prices are lost

- **Detect stale data, not just "unavailable".** HA's `last_reported` updates on every report even when the value is unchanged; `last_changed` and `last_updated` do not. Use `last_reported` for age checks. ([HA state objects](https://www.home-assistant.io/docs/configuration/state_object/)) Real failures seen:
  - The HA core Tibber Pulse feed stayed stale for hours while still showing a valid number. ([HA forum](https://community.home-assistant.io/t/tibber-update-intervall/594160))
  - A local Pulse bridge should report every 2–5 s; if not, it is unreliable. ([ha-tibber-pulse-local](https://www.github.com/marq24/ha-tibber-pulse-local))
- **Define a safe state per input, explicitly.**
  - Grid power missing or stale: no new turn-ons. After a timeout, release or turn off surplus-only loads. Keep loads that are mid-cycle (washer programme) or that are on a "must-run" plan.
  - SoC missing: hold the last value, or assume low. AURUM already does this.
  - Price missing: never assume "cheap". Fall back to solar-only.
  - Forecast missing: use a conservative budget.
- **Use an explicit failsafe value and duration, like EEBus.** After losing a command source, apply a defined failsafe limit for a minimum time (EEBus: 2–24 h) instead of whatever state happens to be there. ([evcc](https://docs.evcc.io/en/external-limit/fnn-steuerbox-via-eebus-lpcandlpp-ss-14a-enwg-ss-9-eeg))
- **Plausibility checks:**
  - Price unit: EUR/kWh vs ct/kWh. Read `unit_of_measurement` and normalise automatically.
  - Sign convention for grid and battery power.
  - Range checks: e.g. |P_grid| greater than the main fuse rating is impossible.
- **Device control loss.** A device that cannot be read or switched is taken out of control, but its consumption still counts in house load, so surplus is not allocated twice. ([akkudoktor](https://akkudoktor.net/t/pv-ueberschuss-control-fuer-home-assistant/41564)) Follow the HA quality-scale rules too: mark entities `unavailable`, log once when connectivity is lost and once when it returns, and raise repair issues for problems the user can fix. ([HA quality scale](https://contributors.home-assistant.io/core/quality-scale/rules/))

### 2.3 Hysteresis and anti-flapping

**Three standard tools:**
1. Separate on and off thresholds with a dead band.
2. A dwell or debounce time in both directions.
3. Signal smoothing.

**Reference settings:**

| Source | Setting |
|---|---|
| evcc defaults | `enable.delay` 1 min, `disable.delay` 3 min; thresholds measured at the grid point ([evcc loadpoints](https://docs.evcc.io/en/reference/configuration/loadpoints)) |
| HA blueprint (heat pump) | on below −900 W, off above −10 W, 60 s trigger delay ([HA forum](https://community.home-assistant.io/t/pv-surplus-heat-pump-controller/1021110)) |
| HA AC build | −500 W / +500 W, 60 s stability time ([HA forum](https://community.home-assistant.io/t/using-solar-surplus-to-control-an-air-conditioner-with-home-assistant/1021747)) |

**Counter-example.** A commercial smart port switched a 4 kW element about 10 times in 28 minutes on a partly cloudy day. Panel output stayed above the threshold; house-load swings, not clouds, drove the surplus figure. There was no configurable dwell time. ([HA forum, SigenStor](https://community.home-assistant.io/t/title-sigenstor-hws-smart-port-chattering-on-off-in-variable-cloud-anyone-else-seeing-this-found-a-fix/1023588)) **Lesson:** smooth or filter the surplus signal, not only the PV signal.

**Asymmetric filtering** is legitimate: react fast to deficit (import costs money) and slow to surplus. AURUM already does this with its asymmetric EMA.

**Price edges also need debouncing**, especially with 15-minute slots that alternate cheap and expensive. Use a minimum-run window or merge slots before acting.

### 2.4 Minimum on/off times and device protection

- **Compressors (heat pumps, AC, heat-pump water heaters):**
  - Typical anti-short-cycle restart delay is 3–5 min, minimum on-time around 2 min (HVAC manuals). About 6 or more cycles per hour counts as short-cycling. ([HVAC School](https://hvacrschool.com/cycle-rate-settings-a-quick-review), [UK DECC report on cycling](https://assets.publishing.service.gov.uk/government/uploads/system/uploads/attachment_data/file/65695/7389-effects-cycling-heat-pump-performance.pdf))
  - For SG-Ready-controlled heat pumps the binding floor is **at least 10 min per signal and at least 10 min before re-activation**, plus (in 1.0) a full lock of at most 2 h, at most 3 times per day. ([BWP](https://www.waermepumpe.de/normen-technik/sg-ready/))
  - Recommendation: a device-class preset "compressor" with min on ≥ 10–15 min, min off ≥ 10 min, a cap on starts per hour, and preferably SG-Ready **boost** (raise setpoints) instead of hard power cycling.
- **Relays and smart plugs.** A Shelly Plus 1PM is rated 16 A resistive; inductive loads need an RC snubber. Relay life is finite, and every flap at 3–4 kW wears contacts. ([Shelly](https://www.shelly.com/blogs/documentation/shelly-plus-1pm), [HA forum](https://community.home-assistant.io/t/title-sigenstor-hws-smart-port-chattering-on-off-in-variable-cloud-anyone-else-seeing-this-found-a-fix/1023588)) Track switch counts per device.
- **EV:**
  - The minimum charge current of 6 A means 1.4 kW single-phase or 4.1 kW three-phase.
  - Phase switching (1P/3P) lowers the start threshold.
  - Some vehicles refuse to resume after an interruption.
  
  ([evcc solar charging](https://docs.evcc.io/en/features/solar-charging))
- **During a minimum runtime, reserve only the device's minimum power and keep the rest dynamic.** Don't freeze the device's whole allocation. ([akkudoktor](https://akkudoktor.net/t/pv-ueberschuss-control-fuer-home-assistant/41564))
- **Water heaters and legionella.** DVGW W 551 requires at least 60 °C at the outlet for "large" systems (more than 400 l of storage, or more than 3 l of pipe volume). For small single-family systems, the cautious practice is to stay at 60 °C or run a periodic thermal-disinfection boost. Raising a heat-pump water heater from 48 to 60 °C lowered the seasonal performance factor from 3.22 to 2.19 in one vendor's figures. ([Kreis Gütersloh FAQ](https://www.kreis-guetersloh.de/themen/gesundheit/hygiene-trinkwasser-und-umwelt/trinkwasser/legionellen-in-trinkwasserinstallationen/formulare-informationsblaetter-legionellen-in-trinkwasserinstallationen/vorlagen/informationsblatt-faqs-zu-legionellen-in-trinkwasser-installationen.pdf?cid=1exq), [energie-beratung-schmidt](https://energie-beratung-schmidt.de/legionellen-waermepumpe-warmwassertemperatur/)) A controller that lowers setpoints to "store" PV should leave a legionella boost window that must run.

### 2.5 Slow and delayed meter readings

- **Measurement chain latency adds up:** IR reading head → cloud or local bridge → HA state → controller cycle → relay → device ramp-up → next meter reading. Local SML is about 2–3 s; cloud paths are slower and sometimes stale. ([ha-tibber-pulse-local](https://www.github.com/marq24/ha-tibber-pulse-local), [HA forum](https://community.home-assistant.io/t/tibber-update-intervall/594160))
- **After every switch there is a dead time.** Ignore, or flag as "settling", the readings until the new load shows up in the meter. Otherwise the controller switches a second device on the same surplus.
- **One switching action per cycle per direction** is a simple and robust rule for avoiding double allocation.
- **Choose the cycle time against meter latency.** A 15 s cycle on a meter that reports every 60 s in practice acts on repeated stale values. Expose "meter age" in diagnostics.
- **Many inverters behind one controller slow regulation down.** OpenDTU users report regulation dropping from about 5 s to about 20 s steps with four inverters. ([OpenDTU discussion](https://github.com/tbnobody/OpenDTU/discussions/502))

### 2.6 Multiple devices competing for surplus

- **Fixed priority alone is not enough.** Practitioners recommend per-device minimum and maximum power, minimum runtime, deadline, interruptibility, manual override and hysteresis. ([akkudoktor](https://akkudoktor.net/t/pv-ueberschuss-control-fuer-home-assistant/41564)) This matches SEMP's model of minimum and optional energy with an earliest-start / latest-end window.
- **Mixed on/off and modulating loads.**
  - On/off loads are a knapsack problem: which subset fits the surplus.
  - Modulating loads (EV current, PWM heating rod) are "filler" and take the remainder.
  - Typical pattern: first fit the on/off loads by priority, then give the rest to a modulating sink.
- **Priority inversion.** A high-priority large load that doesn't fit should not block a smaller lower-priority load that does. Allow lower priorities to take what's left, and if a higher-priority device becomes eligible, displace them (with dwell times).
- **Pass-through of unused share.** If surplus is split as a percentage, unused share must flow to the next device. ([akkudoktor example: 75/25 split with pass-through](https://akkudoktor.net/t/pv-ueberschuss-control-fuer-home-assistant/41564))
- **Peak guard.** Cap total grid import from price-driven starts: Flanders capacity tariff, §14a setpoint, main fuse.
- **Stagger and randomise starts on price edges** to avoid synchronised fleet steps (UK: up to 600 s random delay). This matters for an integration with many installs reacting to the same Tibber or EPEX slot boundary. ([legislation.gov.uk](https://www.legislation.gov.uk/uksi/2021/1467/section/11))

### 2.7 Forecasting accuracy and correction

- **Expected error.** Day-ahead PV forecasts typically show about 13–22 % nRMSE in daylight hours in recent studies (persistence baselines about 18–22 %). Partly cloudy days are the worst. ([arXiv 2608.02088](https://arxiv.org/pdf/2608.02088), [arXiv 1811.09337](https://arxiv.org/pdf/1811.09337)) Budget logic must treat forecasts as uncertain.
- **Use the forecast range.** Solcast gives p10, p50 and p90 (`estimate10`, `estimate`, `estimate90`), plus manual or automatic hourly **dampening** factors for local shading learned from generation history. Hobbyist accounts are limited to 10 API calls per day. ([ha-solcast-solar](https://github.com/BJReplay/ha-solcast-solar))
  - Use p10 for "must reach battery target" decisions.
  - Use p50 for optional loads.
- **Correct during the day.** Either re-run a rolling-horizon optimisation with measured state, as EMHASS `naive-mpc-optim` does, recommended every 5–30 min ([EMHASS MPC](https://emhass.readthedocs.io/en/latest/study_cases/mpc.html)), or at minimum rescale the remaining forecast by an actual-vs-forecast ratio for today, with bounds and decay. AURUM's persisted "budget safety factor" is a form of this; it should be bounded and explainable.
- **Rules vs optimisation.**
  - Simulations: MPC saves 6–16 % vs about 2–4 % for rule-based control ([Unibz/Applied Thermal Eng.](https://research.unipd.it/retrieve/fce44464-9794-41e6-804e-beee1a4a8db8/1-s2.0-S1359431122006391-main.pdf)); 13.5 % with battery and heat pump ([arXiv 2408.07435](https://arxiv.org/pdf/2408.07435v1)).
  - Field test of a plus-energy building: only 2.5 % (simple predictive) and 0.8 % (PV-optimised rules), with clear gaps between simulation and measurement. ([CLIMA 2022](https://proceedings.open.tudelft.nl/clima2022/article/view/154))
  - Conclusion: a predictive rule layer captures much of the value. Full MPC is optional.

### 2.8 Time and price handling

- **15-minute slots.** Do not assume hourly prices. Handle mixed sources: some sensors are hourly, some quarter-hourly.
- **DST.** Days have 92 or 100 quarter-hours. Real HA bugs have come from DST:
  - the "Cheapest Energy Hours" macro broke at the end of DST;
  - utility meters reset at 23:00 after the changeover;
  - time-based automations stuck on the old offset.
  
  ([HA forum macro](https://community.home-assistant.io/t/cheapest-energy-hours-jinja-macro-for-dynamic-energy-prices/569370), [HA forum utility meter](https://community.home-assistant.io/t/utility-meter-resets-at-2300-after-change-to-daylight-saving/625247), [frankel.ch](https://blog.frankel.ch/home-assistant/9))
  
  Key all scheduling on timezone-aware UTC timestamps. Treat "daily reset hour" and "must-run-today" deadlines carefully on 23- and 25-hour days.
- **Late prices.** Plan with what is known. Treat "tomorrow empty before about 13:00" as normal and keep retrying. Never extrapolate "cheap".
- **Which price.** Be explicit about spot vs all-in, VAT, Module 3 grid-fee windows, Austrian SNAP windows, and the export price (0 € during negative slots for affected German plants).

### 2.9 User overrides

Users need:
- "Leave alone" (full manual): the controller never touches the device.
- "Force on now" (boost), with automatic expiry.
- "Must finish by" (deadline), with minimum energy or runtime.
- "Never on grid", or a per-device SoC floor.

Make the semantics of a device that was switched on by hand explicit, as AURUM's README does. Overrides should expire or be clearly visible so they are not forgotten. Being able to override manually was named as a core requirement by practitioners. ([akkudoktor](https://akkudoktor.net/t/pv-ueberschuss-control-fuer-home-assistant/41564))

### 2.10 Explainability

- **Show a reason code per device:** no surplus, in min-on time, in min-off time, outside hysteresis, waiting for higher priority, budget reserved for battery, price too high, §14a active, sensor stale, override. Practitioners highlight this as the main help for testing and trust. ([akkudoktor](https://akkudoktor.net/t/pv-ueberschuss-control-fuer-home-assistant/41564))
- **Expose the decision inputs** (surplus used, thresholds, timers remaining, price slot used) as attributes, so users can build automations on them. AURUM's Advisor already covers much of this.

### 2.11 Observability and logging

- **Decision log** of state transitions, with the reason and the inputs at that moment.
- **Counters:**
  - switches per device per day (relay and compressor wear);
  - energy per device from surplus vs from grid;
  - avoided export during negative slots;
  - cost (import cost and export value forgone);
  - meter age;
  - forecast error per day.
- **Diagnostics download with redaction**: an HA Gold-tier rule. ([HA quality scale](https://contributors.home-assistant.io/core/quality-scale/rules/))
- **Log a lost connection once and the recovery once** (Silver tier), instead of spamming the log every cycle.

### 2.12 Testability

- Keep the decision core pure and deterministic: inputs plus time in, actions out. Inject the clock.
- **Trace replay:** record real days (grid, PV, SoC, prices, device power) and replay them against the controller to catch regressions in switch counts and energy.
- **Property and invariant tests:**
  - never more than one turn-on per cycle;
  - never violate min on/off times;
  - never exceed the import cap or §14a setpoint;
  - no oscillation for a constant input;
  - DST days (92 and 100 slots);
  - empty or late price arrays;
  - unit mismatch;
  - stale sensors;
  - restart in the middle of a min-on period.
- HA Silver tier requires more than 95 % test coverage per module and full config-flow test coverage. ([HA quality scale](https://contributors.home-assistant.io/core/quality-scale/rules/))

### 2.13 Restart safety

- On HA start, entities are briefly `unavailable` or `unknown`. Use a start-up grace period. Make **no switching decisions until the critical inputs are fresh**.
- Persist and restore:
  - `on_since` and `off_since` timers, so min-on and min-off survive restarts;
  - runtimes and energy counters;
  - override flags;
  - forecast correction factors.
- Cross-check persisted state against the real switch state. AURUM's persistence comment says it does this.
- Do not "correct" devices that are on at start-up just because the first readings say "no surplus". Wait for fresh readings.
- Support unloading and reloading the config entry without a restart (HA Silver tier).

### 2.14 Coexistence with other controllers

Decide clearly which controller owns what:
- the battery inverter's own zero-export or self-consumption loop;
- evcc for the wallbox;
- the heat pump's own SG-Ready logic;
- vendor smart ports.

Otherwise the controllers react to each other and oscillate. ([akkudoktor](https://akkudoktor.net/t/pv-ueberschuss-control-fuer-home-assistant/41564), [evcc issue](https://github.com/evcc-io/evcc/issues/7362)) Mitigations:
- a residual-power target;
- slower dwell times than the inner loop (the outer loop must be clearly slower);
- treating self-regulating loads as aux.

---

## 3. What goes wrong in practice (checklist)

| Failure | Cause | Fix |
|---|---|---|
| On/off oscillation right after start | Controlled device's own load not added back | Surplus + own controlled load |
| Chatter on cloudy or busy-kitchen days | Thresholds without dwell; house-load swings | Dead band + bidirectional dwell + filtered surplus |
| Two devices start on the same surplus | Dead time not respected | One action per cycle; settle window |
| "No surplus" although the sun is bright | Inverter curtails (60 % cap, zero export, full battery) | Saturation detection or probing; forecast-based estimate |
| Controller keeps loads on for hours after a cloud bank | Stale-but-valid grid value (cloud feed frozen) | Age check via `last_reported`; failsafe on timeout |
| Devices run on the grid all night | EUR/kWh vs ct/kWh unit mismatch | Unit normalisation; plausibility bounds |
| Battery drained by loads | SoC sensor dropout read as "no battery", or no SoC floor on the price path | Hold or assume-low SoC; SoC-gated price mode |
| Heat pump short-cycling or error lockouts | No min on/off; hard power cycling | Compressor preset; SG-Ready boost instead of power cut |
| Lower-priority devices starve | Nominal power reserved for a thermostat-satisfied heater | Use measured power; "satisfied" detection |
| Wrong schedule on DST days | Local-time arithmetic, hourly assumptions | UTC slots; 92/100-slot tests |
| Plan made on missing tomorrow prices | Treating empty as zero or cheap | Treat empty as "unknown"; retry; solar-only fallback |
| Spikes at slot boundaries across many homes | Every install switches at :00/:15 | Randomised start offset |
| §14a breach | Cheap-grid starts ignore dimming signal | §14a input caps the sum of controllable loads |
| Controller fights inverter or evcc | Unclear ownership | Residual target; ownership config; slower outer loop |
| Restart toggles devices | Decisions made on `unavailable` start-up states | Start-up grace; restored timers |

---

## 4. Mapping to AURUM

Based on the README and a quick read of `energy.py`, `pricing.py` and `devices.py` (not a code audit):

**Already present**
- 15 s cycle
- asymmetric EMA (fast reaction to deficit)
- hysteresis and debounce
- min on time, plus `min_off_time` (default 60 s)
- priorities
- battery modes and per-device SoC floor
- PV-forecast budget with a persisted safety factor
- price modes (`cheap_grid`, `cheap_grid_soc`)
- holding device state when there is no price data
- holding the last SoC when the SoC sensor is lost
- manual override and must-run-today
- Advisor reason codes
- diagnostics and persistence
- run conditions (e.g. tank temperature)

**Worth checking or adding (rough priority)**
1. **Stale-data detection for grid power.** `energy.py` reads grid power with `get_float(..., 0)`. Unavailable becomes 0 W, and a frozen-but-valid value is not age-checked (no `last_reported` or age logic found in a quick grep). Add a maximum input age with a defined failsafe (no turn-ons; release surplus-only loads after a timeout).
2. **Curtailment-aware surplus** for 60 % / 50 % caps, zero-export systems and a full battery: saturation detection or a forecast or inverter-available-power hint.
3. **Negative-price and export-value awareness.** Run absorbable loads when export is worth 0 or less (new German systems with an iMSys, direct marketing, NL after 2027), not only when import is cheap.
4. **15-minute and DST-safe price handling**, a tolerant path for late prices, and **automatic unit normalisation** from `unit_of_measurement`. This turns the documented EUR vs ct trap into a non-issue.
5. **§14a input:** a binary sensor plus a limit in W that caps the sum of controllable loads and blocks cheap-grid starts, with logging.
6. **Device-class presets** (resistive, compressor, EV, appliance programme), with a compressor default of at least 10 min on and off and a starts-per-hour cap. Optionally a three-state SG-Ready device (lock / normal / boost).
7. **Measured-power allocation** and "satisfied" detection (switch on, about 0 W drawn) to release reserved surplus.
8. **Modulating sinks** (a power setpoint instead of on/off) for heating rods and EV current.
9. **Randomised start offset** for price-triggered starts, and an import-peak cap (Flanders capacity tariff, main fuse).
10. **Observability:** per-device switch counts, cost tracking (already on the roadmap), meter-age and forecast-error sensors, and a decision log.
11. **Tests:** trace replay and the invariant tests from 2.12 (DST, stale inputs, restart in the middle of min-on).

---

*Not verified against primary sources:*
- the BWP SG Ready 1.1 PDF;
- the full BNetzA BK6-22-300 text (GZF values taken from the dena factsheet, which calls them provisional);
- the final EEG 2027 text (still in parliament);
- Tibber's official treatment of Module 3 in the API;
- a manufacturer-specific compressor minimum on/off time.

**Files:**
- Extracted text of the e-netz Südhessen §14a TAB: <local path>
- Extracted text of the dena §14a factsheet: <local path>