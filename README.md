# AURUM – Solar Surplus Optimizer

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/v/release/cm-makes/aurum-ha?style=flat)](https://github.com/cm-makes/aurum-ha/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2024.1%2B-blue.svg)](https://www.home-assistant.io/)

**AURUM** (*Latin: Gold*) automatically distributes your PV surplus power to household devices — priority-based, battery-aware, and fully configurable through the Home Assistant UI.

> **No coding required.** Install via HACS, add your grid sensor, configure devices through the UI — done.

---

## Features

- **PV Surplus Steering** – Turns devices on/off based on available excess power
- **Battery-Aware** – Respects battery SOC with configurable target and minimum thresholds
- **Priority-Based** – Higher priority devices get power first
- **Per-Device SOC Threshold** – Each device can have its own minimum battery level
- **Startup Detection** – Recognizes when washing machines or dishwashers start a program and protects the cycle from interruption
- **PV Forecast Budget** – Uses Solcast or Open-Meteo forecast to calculate how much power is available for devices for the rest of the day
- **Manual Override & Muss-heute Switches** – Auto-created per device; override pauses AURUM control, "muss heute" forces the device on regardless of surplus
- **Hysteresis & Debounce** – Prevents rapid switching with configurable margins
- **State Persistence** – Device runtimes and budget safety factor survive restarts
- **HA Diagnostics** – Download a full JSON snapshot of AURUM's internal state for bug reports
- **No Vendor Lock-In** – Works with any grid meter, any battery, any smart plug

---

## Requirements

- Home Assistant 2024.1.0+
- A grid power sensor (W, signed: positive = import, negative = export) — e.g. Shelly 3EM, Kostal, SMA, Fronius
- Smart switches for your devices — e.g. Shelly Plug, Tasmota, Zigbee plugs
- Optional: Battery SOC sensor, PV power sensor, Solcast or Open-Meteo forecast

---

## Installation

### HACS (recommended)

1. Open HACS → Integrations → ⋮ → Custom repositories
2. Add `https://github.com/cm-makes/aurum-ha` as **Integration**
3. Search for "AURUM" and install
4. Restart Home Assistant

### Manual

1. Copy `custom_components/aurum/` to your `config/custom_components/` directory
2. Restart Home Assistant

---

## Setup

1. Go to **Settings → Integrations → Add Integration → AURUM**
2. **Energy & Battery:** Select your grid power sensor (and optionally PV, battery SOC, battery charge/discharge power, PV forecast)
3. **Battery settings:** Set capacity, target SOC, minimum SOC, and update interval
4. After setup: Go to **AURUM → Configure** to add devices

### Adding Devices

In the integration options (Configure), click **Add a device** and fill in:

| Setting | Description |
|---------|-------------|
| **Name** | Display name (e.g. "Washing Machine") |
| **Switch entity** | The switch that controls the device |
| **Power sensor** | Optional: Real-time power measurement |
| **Nominal power** | Expected power draw in watts |
| **Priority** | 1–100, higher = turned on first |
| **SOC threshold** | Device only runs when battery is above this level |
| **Startup detection** | Enable for appliances with programs (washers, dishwashers) |
| **Interruptible** | If disabled, AURUM will not turn the device off mid-cycle |
| **Deadline** | Time by which the device must have run (e.g. `18:00`) |
| **Estimated runtime** | Expected runtime in minutes (used for deadline scheduling) |

### PV Forecast Budget (optional)

AURUM can limit device runtimes based on how much PV energy is forecast for the rest of the day, so the battery reliably reaches its target SOC.

In **Configure → Energy & Battery**:

| Field | What to enter |
|-------|---------------|
| `pv_forecast_entity` | Sensor with **remaining** forecast for today in kWh (e.g. Solcast "Prognose verbleibende Leistung heute") |
| `pv_forecast_today_entity` | Sensor with **hourly forecast data** as attribute (e.g. Solcast "Forecast Today" with `forecast` attribute) |

> If your forecast entity only provides a daily total without hourly data, AURUM uses a fallback sunset estimate (19:00) for budget calculations.

---

## How It Works

```
Every 15 seconds:
  1. Read grid power → calculate excess (negative grid = export = surplus)
  2. Check battery SOC → determine mode (normal / low_soc / charging)
  3. Optional: Calculate PV budget from forecast
  4. For each device (by priority):
     - Enough surplus + SOC OK + budget available? → Turn ON
     - Surplus gone or SOC low? → Turn OFF (respecting min-on-time)
  5. Startup Detection: If a washing machine starts → protect the cycle
```

### Battery Modes

| Mode | Condition | Effect |
|------|-----------|--------|
| **normal** | SOC ≥ target | All devices allowed |
| **low_soc** | min < SOC < target | Devices run if surplus is sufficient; per-device SOC thresholds apply |
| **charging** | SOC ≤ min | All devices off (battery protection) |

### Manual Override vs. Manually-On

| Situation | AURUM behavior |
|-----------|---------------|
| Override switch **ON** | AURUM ignores the device completely — no turn-on, no turn-off |
| Device physically on, override switch **OFF** | AURUM applies normal turn-off logic (e.g. battery protection) |
| AURUM turned the device on | Full management — turns off when surplus drops |

---

## Entities Created

### Global
| Entity | Type | Description |
|--------|------|-------------|
| `sensor.aurum_excess_power` | Sensor | Available surplus (W) |
| `sensor.aurum_battery_soc` | Sensor | Battery SOC (%) |
| `sensor.aurum_battery_mode` | Sensor | Current mode (normal/low_soc/charging) |
| `sensor.aurum_forecast_remaining` | Sensor | PV forecast remaining today (kWh) |
| `sensor.aurum_budget` | Sensor | Device power budget (W) |
| `sensor.aurum_safety_factor` | Sensor | Budget safety factor (0–1) |
| `number.aurum_target_soc` | Number | Target SOC slider |
| `number.aurum_min_soc` | Number | Minimum SOC slider |

### Per Device
| Entity | Type | Description |
|--------|------|-------------|
| `sensor.aurum_{slug}` | Sensor | Device state (on/off/manual_override/running/standby) |
| `sensor.aurum_{slug}_power` | Sensor | Current power draw (W) |
| `sensor.aurum_{slug}_runtime` | Sensor | Runtime today (min) |
| `binary_sensor.aurum_{slug}_active` | Binary | Is device active? |
| `number.aurum_{slug}_soc_threshold` | Number | SOC threshold slider |
| `switch.aurum_{slug}_override` | Switch | Manual override (AURUM hands off) |
| `switch.aurum_{slug}_muss_heute` | Switch | Force device on today |

> `{slug}` is the device name lowercased with spaces replaced by underscores (e.g. "Washing Machine" → `washing_machine`).

---

## Example Dashboard

A ready-to-use Mushroom-based dashboard is included:

📄 **[example_dashboard.yaml](example_dashboard.yaml)**

Copy the contents into **Settings → Dashboards → ⋮ → Raw configuration editor**.

> Requires [Mushroom Cards](https://github.com/piitaya/lovelace-mushroom) (installable via HACS)

---

## Diagnostics

Download a full JSON snapshot of AURUM's internal state for troubleshooting:

**Settings → Devices & Services → AURUM → ⋮ → Download Diagnostics**

The file contains: energy values, battery state, budget info, device states, override switch states, and coordinator health.

---

## Roadmap

- [ ] Price-aware scheduling (dynamic electricity tariffs)
- [ ] Cost tracking (import/export/autarky)
- [ ] Multi-battery support
- [ ] Push notifications
- [ ] Dashboard cards

---

## Support the Project

If AURUM saves you energy and money, consider supporting its development:

[![GitHub Sponsors](https://img.shields.io/badge/Sponsor-GitHub-ea4aaa?logo=github)](https://github.com/sponsors/cm-makes)

Your support helps keep this project alive and growing.

---

## Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

MIT License — see [LICENSE](LICENSE)

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for version history.
