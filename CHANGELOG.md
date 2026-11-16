# Changelog

All notable changes to AURUM will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.17.0] - 2026-11-16

Better control: a second machine no longer starts on the surplus a program still needs for its first heating, priority holds while a device waits, day/night tariffs via a Schedule helper, a thermostat band for the run condition, and a repair issue for configured entities that no longer exist.

### Added
- **Start reserve for programs whose heating has not started yet** – A washer takes in water at about 25 W for several minutes before it heats at about 2 kW, so a second waiting machine used to start on that surplus and both then heated from the grid or the battery. Now a running *Startup detection* program with a power sensor keeps its *Nominal power* minus its measured power free until it has drawn 90 % of its *Nominal power* once, for at most 30 minutes after its start (a cold program releases it then). Other startup-detection programs and non-interruptible devices don't start on that surplus. Interruptible devices may use it and are shed as usual when the heating comes, unless a device of higher priority is held back by the reserve. While a reserve is held and for 3 minutes after its release, these starts are checked against the lower of the smoothed and the current surplus, so a heating that has just begun counts at once. Deadline, cheap-grid and PV-gate starts ignore the reserve. While a reserve is held, or in the update in which another program with a power sensor starts, a waiting program doesn't switch off lower-priority devices for itself. No reserve without a power sensor or while the plug is off; while the plug is unreachable or the power sensor is unavailable, the whole *Nominal power* stays reserved (still at most 30 minutes). A peak already seen survives a restart. The Advisor shows a device held back by a reserve with the new reason `start_reserve` (panel EN/DE), and diagnostics show each program's reserve. Enter the heating power (about 2,000 W for a washer) as *Power consumption (watts)*, the device's nominal power. A paused program needs that much surplus plus *Hysteresis ON* to resume.
- **Day/night tariffs without a price sensor:** the *Cheap period* field now also accepts a Home Assistant **Schedule** helper or a toggle (`input_boolean`), not only a binary sensor. This applies in setup step 2 and in *Configure → Energy & Battery*. Put your cheap hours in a schedule. For NT 22:00–06:00 that is two blocks on every day, 00:00–06:00 and 22:00–24:00, because a block can't cross midnight. Regular devices in *cheap grid* or *cheap grid (SOC-gated)* mode (water heater, heating rod, pool pump) then also run on grid power in those hours. Washers and dishwashers with startup detection don't start in the cheap hours by themselves: AURUM still pauses a program you start, and the program resumes on PV surplus, or on grid in time if you switch on *Must run today* and set a deadline. This works for HT/NT, Economy 7 or the German grid-fee module 3, with no dynamic tariff or template sensor. A schedule or toggle is read exactly like a binary sensor: off means not cheap, and if it is unavailable the current state is held for at most 30 minutes. With a Schedule helper and no countdown sensor, `cheap_period_starts_in_min` (an attribute of each cheap-grid device's `sensor.aurum_{slug}`) is read from the schedule: the minutes until the next cheap block, or 0 while a block is running. A countdown sensor you configured still takes precedence.
- **Restart margin for the run condition (thermostat band).** New optional device setting *Restart margin* in the add and edit device forms, in the sensor's unit. The default 0 keeps the previous behaviour. Once the run-condition sensor has reached its limit, the device is not started again until the reading is back on the allowed side by the margin. Example: with *tank below 55* and margin 3, the water heater switches off at 55 and may start again only below 52. *Above* conditions work the same way in the other direction. The band holds back every start that uses the condition: surplus, PV-gate, cheap-grid and deadline starts, and a program paused by startup detection. A device that is already on inside the band keeps running up to the limit, like a thermostat. This covers a device switched on by hand, one left on when Manual override ends, and one started while the sensor was unavailable. At the limit it stops after its minimum on-time as before; the run condition never stops a non-interruptible device or a running startup-detection program. Inside the band such a device is still shed for lack of surplus like any other, and once it is off, the band keeps it off. Under Manual override AURUM still switches nothing, while the band keeps following the sensor, also at the battery reserve. An unavailable sensor still fails open and leaves the band as it was. The band is kept across restarts and option reloads, and starts over when you change the sensor, the condition or the limit. For a device that is off inside the band, the Advisor shows *run condition not met*.
- **Repair issue for configured entities that no longer exist.** An entity in AURUM's configuration can disappear: renamed (for example with *Recreate entity IDs*), disabled, or removed with its device or integration. AURUM used to carry on without it and say nothing. Without its power measurement, startup detection saw no program start. A run condition stopped applying. A price or forecast sensor gave no data. Now, once Home Assistant is running and AURUM's startup has ended, AURUM checks every 5 minutes that each configured entity exists. That covers the energy, battery, forecast, weather and price sensors, and each device's switch, power measurement and run condition sensor (if a condition limit is set). Entities still missing 10 minutes after a check first missed them are listed in one repair issue, *AURUM: configured entities not found*, with device and field (for example "Washer – Power measurement: `sensor.washer_power`"), and logged once. The issue updates as entities come back and clears itself within 5 minutes once they all exist again. An entity that exists but is unavailable is not listed. A grid meter, battery power sensor or SOC that no longer exists is reported in this issue instead of the *unavailable* one, and does not show as *unavailable* first while the check is still confirming it.
- **Support link in the panel.** A small line below the devices: "AURUM is free. If it saves you money: ☕ Buy me a coffee" (German: "Kaffee spendieren"). It is a plain link that opens in a new tab; nothing is loaded from the site before you click it.

### Fixed
- **Priority now also holds while a device waits out its debounce.** Priority used to order devices only within one control cycle, so a higher-priority device with a long *Debounce ON* could lose a steady surplus to a lower-priority one with a shorter debounce. Example: a 1500 W heater (priority 90, 300 s) and a 600 W pump (priority 10, 60 s) with 1900 W of surplus. The pump started first, its load pushed the surplus below what the heater needed, and the heater's countdown started over every time, so it never ran. Now, while a device (including a washer or dishwasher program waiting for surplus) counts down its *Debounce ON* for a surplus start, the surplus it needs to start is reserved: *Nominal power* + *Hysteresis ON* + *Power reserve*, or *Nominal power* + *Hysteresis ON* for a waiting program. Lower-priority devices, waiting programs included, start on surplus only if what is left after that reservation covers them. The reservation ends as soon as the device starts, or when something other than the surplus blocks its start: run condition, *Minimum OFF time*, runtime target reached, budget cap, SOC threshold, force-off or manual override. After two starts within an hour that the device's switch didn't take (still off on the next check: a broken relay, tripped overpower protection, a switch stuck at `unknown`), the device reserves nothing until its switch is seen on, at most for an hour. Devices with the same priority don't hold each other back, devices that are already on reserve nothing, and cheap-grid, solar-power-threshold and deadline starts work as before. If the surplus keeps dipping just below what the higher-priority device needs, its countdown starts over; after 15 minutes of reserving without a start (or three times its *Debounce ON*, if longer) its claim lapses until it starts or an hour has passed, so the lower-priority device isn't held back all day. Right after a device starts, the smoothed surplus still reads the power it now takes; for 3 minutes after any start, surplus starts therefore use the lower of the smoothed and the current surplus, so a lower-priority device with a short *Debounce ON* doesn't start on surplus that is already gone.
- **A waiting program no longer switches off lower-priority devices it can't use.** A washer or dishwasher waiting for surplus used to switch off lower-priority devices even when all of them together could not free enough power for it to start. The program kept waiting, and the devices came back on and were switched off again each time their *Minimum ON time* ended (about five off/on cycles per hour for a pool pump). Now a program switches them off only when that lets it start. It also no longer switches off a device that runs on the grid on purpose (a cheap-tariff run while its cheap period lasts, such as a night-tariff water heater, or a deadline start): that frees grid power, not surplus (audit #6). Once the cheap period has ended and surplus carries such a device, it may yield as before.
- **Optional entity fields can be emptied in Configure** (audit #27). An emptied field came back with its old value, so an entity that was gone for good could not be removed, and the new *configured entities not found* issue could not be resolved. The current value is now only suggested, and an emptied field is saved as empty.
- **Setup wizard step 2 showed raw keys** for the push-notification, price, price-level, cheap-period and countdown fields. It now shows the same labels and descriptions as *Configure → Energy & Battery*, including the ct/kWh note on the price sensor.

## [1.16.4] - 2026-11-15

Fixes for problems found by comparing AURUM with HELIOS, the author's own, larger installation, and checked against AURUM's code with tests.

### Fixed
- **Manual override no longer backfires on washers and dishwashers** (audit #7, override part). With startup detection, AURUM stopped watching the plug while *Manual* was on, then acted on stale information when you switched back to PV. It cut a paused program you had resumed by hand. It paused mid-cycle a program you had started under *Manual*. After a program had ended, it kept the plug off until the next surplus, followed by phantom "running" and "finished" messages. AURUM still never switches a device while *Manual* is on, but with a power sensor it now keeps reading the power. A program you run meanwhile shows as `running`, and its end is detected as usual, with the *finished* message, even if you switch the plug off once it has gone quiet. Once AURUM has seen it running, it runs to its end untouched after you switch back to PV. A program you start just before switching back is paused like any other start. If you switch the plug off while the program is drawing power, the program is interrupted, not finished: the off time under *Manual* doesn't count as runtime, and the program continues when you switch the plug back on. The *finished* message now reports the runtime AURUM counted for the program, like the runtime sensor, so it no longer includes time the plug was off or Home Assistant was not running. This also works while the battery is at its reserve. Without a power sensor, nothing is tracked under *Manual*. Also, a paused higher-priority program no longer has AURUM switch off another device whose *Manual* override is on to make room.
- **Washing machines and dishwashers that idle at their standby power were never marked finished on time.** Program detection treats a program as finished only while the power stays *below* the *Finish threshold*. That threshold defaulted to the *Standby power* (3 W), and the help text said "Usually same as standby". A machine idling at its standby never drops below it, so only *Max runtime* (3 h) ended the program, and the "finished" push and the *Must run today* reset came hours late. AURUM now uses standby + 1 W in two cases: the finish threshold equals a standby power of 3 W or more, or it is still a default value (the old 3 W or the new 4 W) below a higher standby. Any other value is used as set, including a finish threshold you lowered on purpose for a machine that really idles lower (also as an equal pair below 3 W, such as 2 W / 2 W). A finish threshold above the *Start threshold* is capped at the start threshold, because a finished machine idling between the two was detected as a new program and its plug was switched off. Existing devices are corrected automatically. The setup log names each corrected device, each finish threshold kept below or at standby, and any device whose standby power is not below its start threshold. New devices default to 4 W. The help texts on the add and edit forms now say to set the finish threshold a little above the real idle power and not above the start threshold, and they describe which values AURUM adjusts. If you had set a 3 W or 4 W finish threshold below a higher standby on purpose, the log names the device: lower its *Standby power* below the finish threshold (for example 2.9 W for a 3 W finish threshold) to keep your setting.
- **PV budget no longer holds devices back on good days** (audit #18, #19). On days the battery fills up anyway, and for most of the morning after a short export at night or at sunrise, the forecast budget could stay at 0 W. Regular devices such as pumps, water heaters and heaters now start on surplus that is really there. Budgets rise for many existing users. In detail:
  - The weather-based target only lowers your charge target in bad weather. A learned weather factor above 1 used to raise it by up to 15 points (past 100 %).
  - A charge target below 50 % is no longer lifted to 50 %.
  - The day ramp never aims above 100 %.
  - The day ramp only starts once solar really produces. That means 100 W on your PV power sensor, or, without one, 100 W in your hourly forecast. Without either, the sun must be at least 10° high or your PV-today counter must have risen by 0.05 kWh. Sunrise alone no longer counts. A ramp anchored at night by an older version is dropped when you update.
- **PV budget learns your household load**: Until now the budget subtracted a flat 500 W per hour until sunset. Contrary to the 1.5.0 notes, nothing ever fed the consumption profile. The budget now subtracts what your household actually uses in each hour of the day: house consumption minus AURUM's own devices. Each hour is averaged and handed to the budget when the hour ends. An hour uses the learned value once it has data from 3 days, and learned values survive restarts. Short loads such as a kettle count in full; only single readings beyond ±30 kW are ignored as glitches. Loads AURUM does not switch (a wallbox, a heat pump) count as household load. Learning needs:
  - a PV power sensor that reports the total PV production of all PV systems in the house (every inverter, including a balcony plant). With a hybrid inverter, use its PV (DC input) power, not its AC output, which already includes the battery;
  - with a battery (any battery sensor configured), both its charge and its discharge power sensor.
  Learning pauses while one of these sensors or the grid meter has failed, while a device that is on has no working power sensor, while a device's switch is unavailable or missing, and while AURUM's device control step fails. Diagnostics show the learned profile (`budget` → `consumption_profile`) and whether learning runs and, if not, why, naming the device (`budget` → `consumption_learning`). (audit #64, #73)
- **Devices started by the solar power threshold now stop when the sun drops, even while the battery covers them** (audit #5, solar-threshold part). A device started by *Solar power ≥* stops when PV falls below the threshold minus *Hysteresis off*, or when the battery falls below the device's SOC threshold. That stop only happened while the meter showed grid import, so a pool pump that the battery fed (no battery power sensors configured) kept running. It now acts whatever the meter shows, and its power counts before any other device is shed for a deficit. With a large surplus, the device may be started again a few minutes later as a normal surplus run. Other stop reasons are unchanged: a device whose cheap price has ended keeps running while real surplus covers it.

## [1.16.3] - 2026-11-15

### Changed
- **README** leads with washing machines and dishwashers (startup detection) and with deadlines, and says what AURUM doesn't do: no EV charging, no battery or inverter control.

### Fixed
- **Price sensors in CHF, SEK, NOK, DKK, GBP and other currencies were read 100 times too low** ([#35](https://github.com/cm-makes/aurum-ha/discussions/35)). AURUM compares prices in ct/kWh, the hundredth of the currency, but converted only EUR/kWh and €/kWh. A Swiss price sensor in CHF/kWh (for example from the Innostrom integration) reporting `0.28` was read as 0.28 Rappen, so with a *Maximum price* of 20 every price looked cheap and a cheap-grid device ran on grid around the clock. Nord Pool and the native Tibber integration in SEK, NOK or DKK had the same problem. AURUM now converts a whole currency unit per kWh (EUR, CHF, GBP, SEK, NOK, DKK, kr, PLN, CZK, USD, AUD, NZD, CAD and the symbols €, £, $) by 100 and a price per MWh by 0.1. A sensor already in the hundredth (ct/kWh, Rp./kWh) or without a unit is used as before. *Maximum price* now goes up to 1000 instead of 100, in the setup dialog, as an entity and in the panel, because prices in öre or øre often exceed 100 per kWh.

## [1.16.2] - 2026-11-15

### Added
- **Download count in the Marketplace.** Every release now carries `aurum.zip` (built by the *Release ZIP* workflow from `tools/build_release_zip.py`), and `hacs.json` sets `zip_release`, so the Marketplace installs that file and shows how often it was downloaded. The count is per release: it starts at 0 with every new version. Releases up to 1.16.1 have no ZIP and still install from the source archive.

### Changed
- **README:** installation from the Home Assistant Marketplace (2026.11) with My Home Assistant badges, HACS steps for older versions, a "Why AURUM?" section and a short summary in German.
- **Brand logo** trimmed to the wordmark without empty space and exported at the sizes Home Assistant asks for (`logo.png` 144 px high, new `logo@2x.png`). The Marketplace takes the brand images from the latest release, so the new logo appears there after the next release.
- The brand preview page moved to `tools/brand_preview.html` and no longer ships with the integration; the unused `render_preview.py` is gone.

## [1.16.1] - 2026-11-15

### Fixed
- **Dashboard showed "–" in every tile after the AURUM device was renamed** ([#31](https://github.com/cm-makes/aurum-ha/issues/31)). The panel read the hub sensors and *Current decision* from fixed IDs such as `sensor.aurum_pv_power`. After the AURUM device is renamed, Home Assistant 2026.11's *Recreate entity IDs* (device page → ⋮) gives every entity of the device an ID with the area and the new device name (e.g. `sensor.smarthome_aurumsolopt_pv_power`). AURUM renames the per-device entities back on the next start, but not the hub entities, so the tiles and the decision banner stayed empty while AURUM itself kept working. The panel now looks the hub entities up in the entity registry by their unique ID, so it finds them under any entity ID. Nothing needs to be renamed back.
- **Hub entities now have fixed entity IDs** like the per-device entities, instead of IDs that HA derives from the entity and device name. New installs get the same IDs as before (`sensor.aurum_pv_power`, `number.aurum_target_soc`, `binary_sensor.aurum_cheap_grid_active`, …), and *Recreate entity IDs* keeps them as long as the AURUM device has not been renamed. Existing entity IDs, including renamed ones, are left as they are, so your automations keep working.
- **Device names in the panel** no longer start with the HA device name ("AurumSolOpt AURUM Boiler" is shown as "Boiler"). Since HA 2026.11 the friendly name starts with the device name.
- The start-up entity ID repair now also covers the per-device *PV power threshold* number, so its slider no longer disappears from the panel after *Recreate entity IDs*.

## [1.16.0] - 2026-11-10

Safe mode for failed sensors, and cleaner restarts. From the audit of 2026-11-05 (`docs/CODE_AUDIT_2026-11-05.md`, finding numbers in brackets). Regression tests: `tests/test_failsafe_inputs.py`; the bug tests fail on 1.15.4.

### Added
- **Safe mode when a sensor fails.** AURUM now checks its hub inputs on every cycle. When the grid meter is unavailable for more than about a minute or frozen (no new reading within *Sensor timeout*), or a configured battery power sensor is unavailable for more than about a minute, AURUM starts nothing on surplus and switches off devices it started on surplus after their *Debounce OFF* time. Programs, deadline jobs, cheap-grid and PV-gate runs and devices you switched on yourself keep running. Before, an unavailable meter read as 0 W, so nothing was ever shed (#24, #99); with battery power sensors, a meter outage during grid charging even started devices (#40); and a frozen meter value started one device after another (#41). See README → *When a sensor fails*.
- **Sensor timeout** setting (*Configure → Energy & Battery*, default 10 min, 0 = off) for the frozen-value check of the grid and PV power sensors.
- **Faults are visible** (#44): Advisor decision `input_fault` (grid meter, battery power sensor or SOC failed) with an `input_faults` attribute listing every failed input, per-device reasons `input_fault` and `switch_unavailable`, AURUM's grid, PV, battery charge/discharge and excess sensors go `unavailable` with their source (house consumption too, except for a PV sensor that is merely offline at night, which counts as 0 W), an HA repair issue after 15 minutes (grid meter, battery power sensors, SOC; not PV, which many inverters take offline every night), one log line on loss and one on recovery, and the input health with raw source state and age in the diagnostics.

### Fixed
- **A missing SOC forced the battery-reserve emergency after restarts** (#16) — a SOC sensor still unavailable after the 90 s warm-up was read as 0 %, which switched off non-interruptible, cheap-grid and deadline devices. Startup now waits for the SOC sensor (up to 5 min). A SOC that becomes unknown later (sensor down for more than 30 min) makes new starts treat the battery as low, without the emergency and without switching running devices off.
- **`nan` / `inf` readings poisoned the surplus until the next restart** (#43) — they now count as unavailable, and the smoothing recovers from a bad value.
- **Unavailable device switches were commanded every cycle** (#35 in part, #38, #42) — AURUM read them as off, so it re-sent ON (with a push in the deadline window), reserved their power, which starved lower-priority devices, and inflated the switch penalty. A device whose switch is unavailable is now left alone and shown as `unavailable`; the time it is unreachable is not counted as runtime, and when the switch reports off again the run counts as ended. A switch in state `unknown` is still commanded, as before.
- **Startup detection with an offline plug or power sensor** (#36 in part, #10 in part) — an unavailable plug during a program was read as 0 W, so the program was reported finished, *Must run today* was cleared and the program was cut when the plug came back; an unavailable power sensor made standby look like a program start. Both now hold the state machine until the reading is back, and the finish then needs *Finish time* of observed standby power.
- **Restart with a switch that has not loaded yet** (#71) — AURUM read it as off and later showed its own run as `manual_override`. The saved state is now kept and checked once the switch reports.
- **State was not saved when Home Assistant stops** (#22) — HA does not unload integrations on a restart, so the state file could be 5 minutes old, and a program started in that window was restored as paused and cut. AURUM now saves on stop.
- **Energy Today sensors dropped to 0 after every restart and reload** (#21, #25), so the Energy Dashboard counted today's energy twice. They now start from the restored values, and a failed device cycle keeps the previous values.
- **A restart across midnight restored yesterday's budget anchor** (#23, #63), which could set the budget to 0 W for the whole day. Day values are now reset when the saved state is from an earlier day; learned values are kept.
- **A price outage held a cheap-grid run indefinitely** (#56) — after 30 minutes without price data the price counts as not cheap.
- **Frozen PV power held PV-gate devices on** (#100) — a PV reading above 0 W with no new value within *Sensor timeout* counts as 0 W.
- **The PV gate never started a device whose surplus was short** — its debounce timer was cleared every cycle in which the surplus did not cover the device, so the gate only fired when the plain surplus would have started the device anyway. It now starts the device on PV power alone, as documented (found in the review of this release).
- README: the sign-flip template used `float(0)`, which turns a meter outage into a live 0 W (#102); it now has an `availability` line. The troubleshooting note that a missing SOC sensor means charging mode was wrong (#62).

### Changed
- After a restart, a device you switched on yourself stays yours (`manual_override`). Before, every device found switched on was taken over by AURUM. With the state now saved on stop, the saved owner is reliable. A device AURUM has no saved state for (newly added or renamed) is still taken over when it is found on.
- Startup detection restarts its quiet and standby timers after any time it did not observe: a switch or power sensor gap, the battery-reserve emergency, manual override, the disable switch, and a Home Assistant restart. A finish always needs *Finish time* of observed standby power.

### Upgrade notes
- If your grid meter updates less often than every 10 minutes (some cloud integrations), the Advisor shows *Sensor fault* between updates and surplus starts pause; if the gap is longer than *Sensor timeout* plus *Debounce OFF*, devices running on surplus are also switched off and on again with every update. Raise *Sensor timeout* above the meter's update interval, or set it to 0.
- A device whose switch entity does not exist (renamed or deleted) is now treated as unavailable instead of off: AURUM leaves it alone and shows it as `unavailable`. Pick the new entity in the device settings.

### Known limitations
- A meter that freezes at exactly 0 W is not detected, because zero-export inverters legitimately sit at 0 W.
- Battery power sensors are checked for availability only, not for frozen values (they legitimately sit at 0 W for hours).
- A device that the user switches off during a deadline window is still started again, and an SD plug switched off externally during a program still ends it as finished (#35, #36, unchanged).

## [1.15.4] - 2026-11-06

Fixes from the audit of 2026-11-05 (`docs/CODE_AUDIT_2026-11-05.md`). Every fix has a regression test in `tests/test_audit_2026_11.py`; the bug tests fail on 1.15.3.

### Fixed
- **Deadline force-start ignored the runtime already done and then held the device on grid until midnight** — `_deadline_urgent` sized the start window from the full *Estimated runtime* and never looked at the runtime. A device that had already run its target on PV was still force-started at the deadline, and its force-start immunity only ended at the next daily reset. Without *Stop after runtime* (the default) *Must run today* never reset either, so this repeated every day. Reproduced: a 1.5 kW device that ran 3 h on PV was force-started at 16:55 and ran on grid until 00:10, about 11 kWh. *Must run today* now works as a job for regular devices: the runtime counted is the runtime since the switch was turned on (PV runs count; an earlier load or the previous *Daily reset hour* cycle does not). The deadline window only covers what is still missing; once the job is done, *Must run today* resets (with or without *Stop after runtime*) and the force-start immunity ends, as it does when you switch *Must run today* off. An open job keeps its progress across the daily reset and across a restart. With *Stop after runtime* the daily cap wins: the window covers whichever is smaller, the job or the daily remainder, and a job switched on after today's cap was reached runs in the next daily cycle. Startup-detection devices are unchanged: their deadline is about the pending program.
- **Startup detection paused a program that was still running after a *max runtime* finish** — the default *Max runtime* is 3 h, shorter than many eco programmes. On that finish the device went straight back to standby monitoring with the plug on, saw the still-running program as a new start and switched the plug off mid-cycle. After a *max runtime* finish, detection now waits until the power has stayed at standby for *Finish time* (needs a power sensor; quiet time already seen before the finish counts, and the hold ends if the plug is switched off). After a normal smart finish the next program is detected at once, as before. Not covered: a smart finish that fires too early during a long low-power phase (e.g. a dishwasher's passive drying); set *Finish time* longer than the appliance's longest quiet phase.
- **Battery priority could not see battery discharge, so running devices drained the battery down to minimum SOC** — with *Battery priority* on, only grid power counted. A hybrid inverter holds grid near 0 W by discharging, so a device started on export kept running after sunset until the battery hit `min_soc`. Discharge now counts as a deficit in this mode (charge power still does not count as surplus). Without battery power sensors AURUM still cannot see discharge; the README now says so.
- **A running cheap-grid or PV-gate device lost its scheduling reason at the daily reset and on restart** — the reason was cleared at the daily reset and not persisted, so the device was then treated as a plain surplus run and shed (and possibly restarted). The reason is now kept while the device is on, persisted, and restored only if the switch is still on after the restart. A restart across the daily boundary also no longer restores yesterday's `force_started`.
- **Power, energy and price sensors in other units were read as W / kWh / ct** — the config flow accepted kW, MW, Wh and MWh sensors, but the runtime used the raw number, so a kW grid sensor made the surplus 1000x too small. AURUM now converts by `unit_of_measurement`: kW/MW/mW → W, Wh/MWh → kWh (forecast and PV-today sensors), and **EUR/kWh or €/kWh → ct/kWh** (the native Tibber integration). Sensors without a unit are used as-is, as before.

### Known limitations
- A legacy *Must run today* entity (input_boolean) that is briefly `unavailable` is read as off for that cycle, which restarts the job count.
- A device that is already on when the deadline window opens is still treated as a surplus run until it is shed; it is then force-started (unchanged from 1.15.3).

### Upgrade note
- If you followed the old advice and wrapped your EUR price sensor in a template that multiplies by 100, check the wrapper's unit: with `ct/kWh` (or no unit) nothing changes; if it still says `EUR/kWh`, AURUM now scales it a second time (28 → 2800 ct). Set the unit to `ct/kWh`, or point AURUM at the original EUR/kWh sensor.
- The AURUM price sensor of EUR/kWh users now shows ct (e.g. `28` instead of `0.28`), so its history steps by 100x at the upgrade.

## [1.15.3] - 2026-11-05

### Changed
- **Ready for Home Assistant 2026.11 and the built-in Marketplace** — Nothing in 2026.11 breaks AURUM; this release removes the two things that would otherwise warn or age badly. `manifest.json` now declares `"categories": ["energy.solar_batteries"]`: the Marketplace (HACS is built into HA as of 2026.11) browses integrations by category and warns about a manifest without one. The hub's device info is now built with `DeviceInfo(...)` keyword fields instead of a plain dict: `DeviceInfo` became a dataclass in 2026.11 and dict-style access is slated for deprecation. The keyword form works on every supported HA version (min. 2024.1). No config or behaviour changes.

## [1.15.2] - 2026-11-04

### Fixed
- **Raw translation keys in the options menu and the price-mode dropdown** — The *Configure* menu showed `menu_edit_energy`, `menu_add_device`, … and the device dialog's *Price mode* showed `price_mode_solar_only`, `price_mode_cheap_grid`, `price_mode_cheap_grid_soc` instead of readable text, in every language. HA's frontend looks up select-option translations by the option's *value* (`add_device`, `solar_only`, …), but the `action` and `price_mode` entries in `strings.json` / `en.json` / `de.json` were keyed by the option's *label*, so the lookup missed and the label was shown as-is. `condition_op` was keyed correctly, which is why its dropdown always worked. The translation keys now match the values; no config or behaviour changes. A new test reads every `SelectSelector` from `config_flow.py` and asserts its translation keys equal its option values, in all three files.

## [1.15.1] - 2026-09-05

### Fixed
- **PV budget cap blocked cheap-grid starts overnight** — The budget module returns `device_budget_w = 0` after sunset (a real zero, not `None`), so the cap in `DeviceManager.update()` stayed active all night. It sits *before* `_should_turn_on`, so a `cheap_grid` device never reached its price check unless it was exempt via the grid-only fallback — which is `battery_soc < soc_threshold`, the device's *own* threshold. Result: a water heater at `soc_threshold: 60` was exempt most nights (battery usually below 60 %) and ran on cheap grid as documented, while a pool pump at `soc_threshold: 25` on the identical `cheap_grid` mode was capped and silently never started in a live cheap-tariff window. The cautious setting disabled the feature; the generous one enabled it. Now a live price grant exempts the device from the budget cap — the same treatment `deadline_forced` and the PV gate already had. The budget reserves *solar* for the battery; a price-granted run uses grid, so the budget has no say in it. The exemption is scoped to a live grant: with an expensive price, or unavailable price data, or in `solar_only` mode, the cap applies exactly as before, and `cheap_grid_soc` keeps its battery floor (no grant below the device threshold). The price predicate is now a single helper, `_price_grant`, shared by the grant itself and the cap so the two can't drift. 13 new tests; the three bug tests fail on 1.15.0.

  Found and diagnosed by [@psecker](https://github.com/psecker) in [#25](https://github.com/cm-makes/aurum-ha/pull/25). Thank you.

## [1.15.0] - 2026-08-22

### Added
- **SOC-gated cheap-grid price mode (`cheap_grid_soc`)** — A third per-device `price_mode` alongside `solar_only` and `cheap_grid`. It behaves like `cheap_grid` (runs on PV surplus *or* cheap grid price), except that the price-based start is only granted while battery SOC is at or above that device's `soc_threshold`. Below the threshold the device falls back to `solar_only` behaviour: genuine grid-export surplus can still start it, a cheap price alone cannot. Background: on the plain `cheap_grid` path, `_should_turn_on` returns early on a cheap price *before* any SOC logic runs, so `soc_threshold` is silently never consulted for a price-driven start — a device could run on grid all night with the battery well below its configured reserve. `cheap_grid` is deliberately left unchanged (a water heater that should always take cheap power is a legitimate use case); `cheap_grid_soc` is the opt-in for users who want price-awareness *and* a battery floor. The Max Price number entity and the sensor pricing attributes are created for the new mode too, and the device sensor now reports which of the two price-aware modes is active. EN/DE strings added. Unit-tested.

  Contributed by [@psecker](https://github.com/psecker) in [#21](https://github.com/cm-makes/aurum-ha/pull/21).

### Fixed
- **CI ran only a fraction of the test suite** — the `Unit Tests` workflow step invoked `pytest tests/test_devices.py`, so every other test module (advisor, PV gate, day-start-hour, persistence, stop-after-runtime, i18n, smoke, v1.11 features …) was collected by nobody. Now runs `pytest tests/` — 202 tests instead of 51.

### Changed
- **`max_price` help text** now names both price-aware modes instead of only `cheap_grid` (EN/DE).
- Internal: the `cheap_grid` price-mode literal is replaced by the `PRICE_MODE_CHEAP_GRID` constant in `devices.py`, `number.py` and `sensor.py`, so producer and consumers can no longer drift (same treatment the `SCHED_REASON_*` strings got in 1.14.0).

## [1.14.1] - 2026-07-16

### Fixed
- **Advisor wording: "Charging battery" → "Battery below reserve"** – The `battery_charging` decision/reason labels (EN/DE, sensor state + panel banner + device reason lines) claimed the battery was actively charging. AURUM doesn't measure that: the mode means *SOC is at or below `min_soc`, devices are paused*. The battery may well be idle at that moment (spotted during a live session: BYD at 2 % on a July morning, not charging). The machine-readable codes (`battery_charging`) are unchanged — only display strings; no breaking change for automations.

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
