# AURUM – Solar Surplus Optimizer

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/v/release/Chris0479/aurum-ha?style=flat)](https://github.com/Chris0479/aurum-ha/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2024.1%2B-blue.svg)](https://www.home-assistant.io/)

**AURUM** (*Latin: Gold*) automatically distributes your PV surplus power to household devices — priority-based, battery-aware, and fully configurable through the Home Assistant UI.

> **No coding required.** Install via HACS, add your grid sensor, configure devices through the UI — done.

## Features

- **PV Surplus Steering** – Turns devices on/off based on available excess power
- **Battery-Aware** – Respects battery SOC with configurable target and minimum thresholds
- **Priority-Based** – Higher priority devices get power first
- **Per-Device SOC Threshold** – Each device can have its own minimum battery level
- **Startup Detection** – Recognizes when washing machines or dishwashers start a program and protects the cycle from interruption
- **Hysteresis & Debounce** – Prevents rapid switching with configurable margins
- **State Persistence** – Device runtimes survive restarts
- **No Vendor Lock-In** – Works with any grid meter, any battery, any smart plug

## Requirements

- Home Assistant 2024.1.0+
- A grid power sensor (W) — e.g. Shelly 3EM, Kostal, SMA, Fronius
- Smart switches for your devices — e.g. Shelly Plug, Tasmota, Zigbee plugs
- Optional: Battery SOC sensor, PV power sensor

## Installation

### HACS (recommended)

1. Open HACS → Integrations → ⋮ → Custom repositories
2. Add `https://github.com/Chris0479/aurum-ha` as **Integration**
3. Search for "AURUM" and install
4. Restart Home Assistant

### Manual

1. Copy `custom_components/aurum/` to your `config/custom_components/` directory
2. Restart Home Assistant

## Setup

1. Go to **Settings → Integrations → Add Integration → AURUM**
2. **Step 1:** Select your grid power sensor (and optionally PV + battery SOC)
3. **Step 2:** Set battery capacity, target SOC, minimum SOC, and update interval
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
| **SOC threshold** | Device turns off when battery drops below this |
| **Startup detection** | Enable for appliances with programs (washers, dishwashers) |

## How It Works

```
Every 15 seconds:
  1. Read grid power → calculate excess (negative grid = export = surplus)
  2. Check battery SOC → determine mode (normal / low_soc / charging)
  3. For each device (by priority):
     - Enough surplus + SOC OK? → Turn ON
     - Surplus gone or SOC low? → Turn OFF (respecting min-on-time)
  4. Startup Detection: If a washing machine starts → protect the cycle
```

### Battery Modes

| Mode | Condition | Effect |
|------|-----------|--------|
| **normal** | SOC ≥ target | All devices allowed |
| **low_soc** | min < SOC < target | Only devices whose SOC threshold is met |
| **charging** | SOC ≤ min | All devices off |

## Entities Created

### Global
| Entity | Type | Description |
|--------|------|-------------|
| `sensor.aurum_excess_power` | Sensor | Available surplus (W) |
| `sensor.aurum_battery_mode` | Sensor | Current mode |
| `number.aurum_target_soc` | Number | Target SOC slider |
| `number.aurum_min_soc` | Number | Minimum SOC slider |

### Per Device
| Entity | Type | Description |
|--------|------|-------------|
| `sensor.aurum_{name}` | Sensor | Device state (on/off/running/standby) |
| `sensor.aurum_{name}_power` | Sensor | Current power draw (W) |
| `sensor.aurum_{name}_runtime` | Sensor | Runtime today (min) |
| `binary_sensor.aurum_{name}_active` | Binary | Is device active? |
| `number.aurum_{name}_soc_threshold` | Number | SOC threshold slider |

## Roadmap

- [ ] Price-aware scheduling (dynamic electricity tariffs)
- [ ] Cost tracking (import/export/autarky)
- [ ] Multi-battery support
- [ ] PV forecast-based power budget
- [ ] Push notifications
- [ ] Dashboard cards

## Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

MIT License — see [LICENSE](LICENSE)

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for version history.
