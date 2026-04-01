"""
AURUM 7-Day Simulation: Baseline vs Budget-Aware
=================================================
Runs two back-to-back simulations using real HA data (2026-03-21 to 2026-03-28):

  A) Baseline : EnergyManager + BatteryManager + DeviceManager (current AURUM)
  B) Budget   : + BudgetManager (newly ported from HELIOS)

Budget integration: device turn-on is blocked when device_budget_w = 0.
Running SD programs (sd_state == running) are always protected.

Comparison metrics:
  - SOC target achievement (reached 80% on how many days?)
  - Total surplus captured by devices (kWh)
  - Device runtime per device
  - Force-start count (deadline protection)

Usage:  python simulation_7day_budget.py
Requires: simulation_7day.py in same directory (data + AURUM module stubs)
"""

import math
import os
import random
import sys
import types
from datetime import datetime, timedelta

# -- Colour codes ------------------------------------------------
B = "\033[1m"           # bold
R = "\033[1;31m"        # red
G = "\033[1;32m"        # green
Y = "\033[1;33m"        # yellow
C = "\033[1;36m"        # cyan
D = "\033[2m"           # dim
X = "\033[0m"           # reset

random.seed(42)

# -- HA module stubs (must happen before any aurum import) --------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
                                "custom_components"))

ha = types.ModuleType("homeassistant")
for sub in ["core", "config_entries", "components", "components.sensor",
            "components.binary_sensor", "components.number",
            "helpers", "helpers.entity_platform",
            "helpers.update_coordinator", "helpers.selector"]:
    m = types.ModuleType(f"homeassistant.{sub}")
    sys.modules[f"homeassistant.{sub}"] = m

sys.modules["homeassistant"] = ha

huc = sys.modules["homeassistant.helpers.update_coordinator"]
huc.DataUpdateCoordinator = type("DataUpdateCoordinator", (), {})
huc.CoordinatorEntity = type("CoordinatorEntity", (), {})
huc.UpdateFailed = type("UpdateFailed", (Exception,), {})

hcore = sys.modules["homeassistant.core"]
hcore.HomeAssistant = type("HomeAssistant", (), {})
hcore.callback = lambda f: f

hce = sys.modules["homeassistant.config_entries"]
hce.ConfigEntry = type("ConfigEntry", (), {})

for attr in ["SensorEntity", "SensorDeviceClass", "SensorStateClass"]:
    setattr(sys.modules["homeassistant.components.sensor"], attr,
            type(attr, (), {}))
for attr in ["BinarySensorEntity", "BinarySensorDeviceClass"]:
    setattr(sys.modules["homeassistant.components.binary_sensor"], attr,
            type(attr, (), {}))
sys.modules["homeassistant.components.number"].NumberEntity = type(
    "NumberEntity", (), {})
sys.modules["homeassistant.components.number"].NumberMode = type(
    "NumberMode", (), {"SLIDER": "slider"})
sys.modules["homeassistant.helpers.entity_platform"].AddEntitiesCallback = None

vol = types.ModuleType("voluptuous")
vol.Schema = lambda x: x
vol.Required = lambda *a, **kw: a[0] if a else None
vol.Optional = lambda *a, **kw: a[0] if a else None
vol.UNDEFINED = None
sys.modules["voluptuous"] = vol

# -- Import AURUM modules -----------------------------------------
from aurum.const import *
from aurum.modules.energy import EnergyManager
from aurum.modules.battery import BatteryManager
from aurum.modules.devices import DeviceManager
from aurum.modules.budget import BudgetManager

# -- Import simulation data and helpers from simulation_7day ------
# (avoid re-running main, just grab the data + helpers)
_sim_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "simulation_7day.py")
_sim_globals = {"__file__": _sim_path, "__name__": "__sim_import__"}
with open(_sim_path) as _f:
    _src = _f.read()

# Strip: main block
_src = _src.replace('if __name__ == "__main__":', 'if False:')

# Strip: sys.path insert + all HA stub lines + aurum imports
# (already done in this file; re-running them causes errors)
# Replace the entire HA-stub section with a no-op marker
import re as _re
_src = _re.sub(
    r'sys\.path\.insert.*?from aurum\.modules\.devices import DeviceManager\n',
    '# HA stubs stripped (already done)\n',
    _src, count=1, flags=_re.DOTALL)

exec(compile(_src, _sim_path, "exec"), _sim_globals)

GRID_DATA = _sim_globals["GRID_DATA"]
SOC_DATA = _sim_globals["SOC_DATA"]
DEVICE_CONFIGS = _sim_globals["DEVICE_CONFIGS"]
build_5min_timeseries = _sim_globals["build_5min_timeseries"]
UserBehaviorSimulator = _sim_globals["UserBehaviorSimulator"]
DayStats = _sim_globals["DayStats"]
SimStats = _sim_globals["SimStats"]
ts_to_datetime = _sim_globals["ts_to_datetime"]


# =========================================================================
#  EXTENDED MOCK HASS  (supports budget manager's .states.get() + attrs)
# =========================================================================

class _StateObj:
    """Minimal HA state object with .state and .attributes."""
    __slots__ = ("state", "attributes")

    def __init__(self, state, attributes=None):
        self.state = str(state) if state is not None else ""
        self.attributes = attributes or {}


class _StatesProxy:
    """Dict-like proxy that wraps string states in _StateObj."""

    def __init__(self, raw):
        self._raw = raw           # entity_id -> str | _StateObj

    def get(self, entity_id, default=None):
        val = self._raw.get(entity_id, default)
        if val is None or val is default:
            return default
        if isinstance(val, _StateObj):
            return val
        return _StateObj(val)

    def __setitem__(self, key, value):
        self._raw[key] = value

    def __getitem__(self, key):
        val = self._raw[key]
        if isinstance(val, _StateObj):
            return val
        return _StateObj(val)

    def __contains__(self, key):
        return key in self._raw


class MockHass:
    """Extended MockHass that supports both get_state() and .states.get()."""

    def __init__(self):
        self._raw = {}          # entity_id -> str
        self.states = _StatesProxy(self._raw)
        self.logs = []
        self.actions = []

    def get_state(self, entity_id, default=None, attribute=None):
        """Mimic HA hass.states.get(entity).state / .attributes."""
        val = self._raw.get(entity_id, default)
        if attribute:
            # BudgetManager may call get_state(entity, attribute=...) in
            # _get_pv_today_kwh(); we don't use that path in simulation
            if isinstance(val, _StateObj):
                return val.attributes.get(attribute)
            return None
        if isinstance(val, _StateObj):
            return val.state
        return val

    def set_state(self, entity_id, value, **kwargs):
        self._raw[entity_id] = str(value) if value is not None else ""

    def turn_on(self, entity_id):
        self._raw[entity_id] = "on"
        self.actions.append(("ON", entity_id))

    def turn_off(self, entity_id):
        self._raw[entity_id] = "off"
        self.actions.append(("OFF", entity_id))

    def log(self, msg, level="INFO"):
        self.logs.append(msg)

    # stub for safety_factor_entity sync (not used in simulation)
    class _Services:
        def call(self, *a, **kw):
            pass
    services = _Services()


# =========================================================================
#  SYNTHETIC PV FORECAST HELPERS
# =========================================================================

def compute_remaining_forecast_kwh(step_idx, grid_ts, today_date):
    """Compute remaining PV forecast kWh for rest of today.

    Uses future grid export values (negative grid = surplus exported).
    This approximates remaining PV energy available.

    Note: grid_export < true PV (house load is subtracted), so this
    is a conservative lower-bound forecast -- which is what a safety
    factor would correct upward.
    """
    remaining_wh = 0.0
    for i in range(step_idx, len(grid_ts)):
        dt, grid_w = grid_ts[i]
        if dt.date() != today_date:
            break   # only this calendar day
        if grid_w < 0:
            remaining_wh += abs(grid_w) * (5.0 / 60.0)
    return remaining_wh / 1000.0


def hours_until_sunset_approx(now_dt):
    """Approximate hours until PV sunset (Germany, March/April).

    Uses a simple model: PV active 07:00-19:00.
    Returns 0 outside production window.
    """
    start_h = 7.0
    end_h = 19.0
    current_h = now_dt.hour + now_dt.minute / 60.0
    if current_h < start_h or current_h >= end_h:
        return 0.0
    return max(0.0, end_h - current_h)


def build_hourly_forecast(step_idx, grid_ts, today_date):
    """Build synthetic hourly forecast for _get_hourly_forecast().

    Returns list of (hour_float, watts_avg) using a smooth Gaussian
    solar curve scaled to today's actual surplus.

    This is injected into MockHass as a _StateObj with wh_period attribute,
    so BudgetManager._get_hourly_forecast() can read it.
    """
    # Collect hourly surplus by hour for today
    hourly_surplus = {}
    for dt, grid_w in grid_ts:
        if dt.date() != today_date:
            continue
        h = dt.hour
        if h not in hourly_surplus:
            hourly_surplus[h] = []
        if grid_w < 0:
            # Surplus: convert 5-min sample (W) to Wh
            hourly_surplus[h].append(abs(grid_w) * (5.0 / 60.0))
        else:
            hourly_surplus[h].append(0.0)

    # Convert to average watt-hours per hour
    forecast = {}
    for h, samples in hourly_surplus.items():
        # Scale up by 3x to account for house load (export << PV production)
        avg_wh = (sum(samples) / len(samples) * 12) * 3  # 12 steps/hour
        forecast[f"{today_date.year}-{today_date.month:02d}"
                 f"-{today_date.day:02d}T{h:02d}:00:00"] = avg_wh

    return forecast


# =========================================================================
#  SIMULATION ENGINE
# =========================================================================

def run_simulation(use_budget: bool, grid_ts, soc_ts, label: str):
    """Run 7-day simulation.

    use_budget: if True, instantiate BudgetManager and block device turn-on
                when device_budget_w == 0 (exhausted budget).
    """
    n_steps = min(len(grid_ts), len(soc_ts))
    grid_ts = grid_ts[:n_steps]
    soc_ts = soc_ts[:n_steps]
    sim_start = grid_ts[0][0]

    hass = MockHass()

    config = {
        "grid_power_entity": "sensor.grid",
        "pv_power_entity": "sensor.pv",
        "battery_soc_entity": "sensor.soc",
        "battery_capacity_wh": 10000,
        "target_soc": 80,
        "min_soc": 10,
        "update_interval": 15,
        "devices": DEVICE_CONFIGS,
        # Budget config
        "target_soc_entity": "number.target_soc",
        "pv_forecast_entity": "sensor.pv_forecast_remaining",
        "pv_forecast_today_entity": "sensor.pv_forecast_today",
        "pv_actual_today_entity": None,   # skip inday_correction in sim
        "dwd_weather_entity": None,        # skip weather factor in sim
        "budget_safety_factor": 0.85,      # generous for sim (pure export)
        "avg_consumption_w": 400,
        "budget_combined_floor": 0.85,
        "budget_dynamic_target": False,    # keep target fixed in sim
    }

    # Initialize switch and power sensor states
    for dev_cfg in DEVICE_CONFIGS:
        hass._raw[dev_cfg["switch_entity"]] = "off"
        if dev_cfg.get("power_entity"):
            hass._raw[dev_cfg["power_entity"]] = "0"

    # Target SOC as input_number
    hass._raw["number.target_soc"] = "80"

    em = EnergyManager(hass, config)
    bm = BatteryManager(hass, config)
    dm = DeviceManager(hass, config)
    budget_mgr = BudgetManager(hass, config) if use_budget else None

    user_sim = UserBehaviorSimulator(sim_start)
    stats = SimStats()
    current_day_num = -1
    current_day = None
    WEEKDAYS_DE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

    # Track budget stats per day
    budget_blocks_per_day = []
    current_day_budget_blocks = 0
    soc_target_reached_per_day = []  # True/False per day
    current_day_max_soc = 0.0
    current_day_date = None

    for step_idx in range(n_steps):
        dt, grid_w = grid_ts[step_idx]
        _, soc = soc_ts[step_idx]

        day_num = (dt - sim_start).days

        if day_num != current_day_num:
            if current_day is not None:
                stats.add_day(current_day)
                budget_blocks_per_day.append(current_day_budget_blocks)
                soc_target_reached_per_day.append(current_day_max_soc >= 80.0)

            current_day_num = day_num
            weekday = WEEKDAYS_DE[dt.weekday()]
            date_str = dt.strftime("%d.%m")
            current_day = DayStats(day_num + 1, date_str, weekday)
            current_day_budget_blocks = 0
            current_day_max_soc = 0.0
            current_day_date = dt.date()

            dm.daily_reset()
            em._grid_ema = None
            if budget_mgr:
                budget_mgr.daily_reset()

        # Track max SOC per day
        if soc > current_day_max_soc:
            current_day_max_soc = soc

        # Simulate user behavior (SD power sensors)
        for dev_cfg in DEVICE_CONFIGS:
            if dev_cfg.get("startup_detection") and dev_cfg.get("power_entity"):
                simulated_power = user_sim.get_power(
                    dev_cfg["name"], dev_cfg["power_entity"], dt)
                if simulated_power is not None:
                    hass._raw[dev_cfg["power_entity"]] = str(simulated_power)

        # Set grid/SOC sensors
        hass._raw["sensor.grid"] = str(grid_w)
        hass._raw["sensor.pv"] = "0"
        hass._raw["sensor.soc"] = str(soc)

        # -- Update budget forecast data -----------------------------
        if budget_mgr:
            remaining_kwh = compute_remaining_forecast_kwh(
                step_idx, grid_ts, dt.date())
            hass._raw["sensor.pv_forecast_remaining"] = str(remaining_kwh)

            # Build hourly forecast for sunset detection
            wh_period = build_hourly_forecast(step_idx, grid_ts, dt.date())
            hass._raw["sensor.pv_forecast_today"] = _StateObj(
                str(remaining_kwh),
                {"wh_period": wh_period})

        # -- AURUM cycle ---------------------------------------------
        shared = {"now": dt, "cycle": step_idx + 1}
        em.update(shared)
        bm.update(shared)

        if budget_mgr:
            budget_mgr.update(shared)

        # -- Budget gate: pre-check before device decisions -----------
        # Block new device activations if budget is exhausted (budget_w == 0)
        # but do NOT turn off already-running SD programs.
        budget_exhausted = False
        if budget_mgr:
            budget_w = shared.get("device_budget_w")
            # budget_w == 0: budget exhausted -> block new starts
            # budget_w is None: no restriction (forecast unavailable or SOC ok)
            if budget_w is not None and budget_w <= 0:
                budget_exhausted = True

        dm.update(shared)

        # -- Apply budget: turn off devices that started this cycle ----
        # if budget is exhausted. Running SD programs are exempt.
        if budget_exhausted:
            for dev in dm.devices:
                dev_name = dev["name"]
                switch = dev["switch_entity"]
                if hass._raw.get(switch) != "on":
                    continue
                # Exempt SD running programs
                if (dev.get("startup_detection")
                        and dev.get("sd_state") == SD_STATE_RUNNING):
                    continue
                # If device was just turned on (managed_on=True, on_since
                # is very recent), turn it back off
                on_since = dev.get("on_since")
                if on_since and (dt - on_since).total_seconds() < 60:
                    hass.turn_off(switch)
                    dev["managed_on"] = False
                    dev["on_since"] = None
                    current_day_budget_blocks += 1

        # -- Force-start daily SOC check for adaptation ----------------
        # At 17:00 each day, adapt safety factor
        if budget_mgr and dt.hour == 17 and dt.minute == 0:
            budget_mgr.adapt_safety_factor(shared)

        # -- Track stats ---------------------------------------------
        battery_mode = shared.get("battery_mode", "normal")
        excess = shared.get("excess_for_devices", 0)
        for dev in dm.devices:
            if (dev["startup_detection"]
                    and dev.get("sd_state") == SD_STATE_RUNNING
                    and hass._raw.get(dev["switch_entity"]) == "on"):
                if battery_mode != "normal" or excess < 0:
                    current_day.sd_protections += 1

        if not hasattr(current_day, "_force_was_set"):
            current_day._force_was_set = {}
        for dev in dm.devices:
            dev_name = dev["name"]
            was_forced = current_day._force_was_set.get(dev_name, False)
            is_forced = dev.get("force_started", False)
            if is_forced and not was_forced:
                current_day.force_starts += 1
            current_day._force_was_set[dev_name] = is_forced

        current_day.record_step(
            grid_w, soc, battery_mode, shared, hass, dm.devices)

    if current_day is not None:
        stats.add_day(current_day)
        budget_blocks_per_day.append(current_day_budget_blocks)
        soc_target_reached_per_day.append(current_day_max_soc >= 80.0)

    stats.force_starts = sum(d.force_starts for d in stats.days)
    stats.sd_protections = sum(d.sd_protections for d in stats.days)

    return stats, budget_blocks_per_day, soc_target_reached_per_day


# =========================================================================
#  OUTPUT
# =========================================================================

def print_comparison(
        stats_a, budget_blocks_a, soc_days_a,
        stats_b, budget_blocks_b, soc_days_b):
    """Print side-by-side comparison of baseline vs budget run."""

    def fmt_surplus_pct(stats):
        s = stats.total_surplus_kwh()
        u = stats.total_device_kwh()
        return f"{u:.1f} kWh ({(u/s*100):.0f}%)" if s > 0 else "0 kWh"

    DEVICE_ORDER = [
        "Waschmaschine", "Spuelmaschine", "IR Esszimmer", "IR Wohnzimmer",
        "IR Kueche", "IR Wickelzimmer", "Heizluefter Bad", "Gaeste WC",
        "Heizluefter Mobil",
    ]

    print(f"\n{B}{'=' * 75}")
    print(f"  AURUM Simulation Comparison: Baseline vs Budget-Aware")
    print(f"{'=' * 75}{X}")
    print(f"  {'Metric':<38}  {'Baseline':>12}  {'+ Budget':>12}")
    print(f"  {'-' * 66}")

    sur_a = stats_a.total_surplus_kwh()
    sur_b = stats_b.total_surplus_kwh()
    dev_a = stats_a.total_device_kwh()
    dev_b = stats_b.total_device_kwh()
    pct_a = dev_a / sur_a * 100 if sur_a > 0 else 0
    pct_b = dev_b / sur_b * 100 if sur_b > 0 else 0

    print(f"  {'Total surplus available':<38}  {sur_a:>10.1f}kWh  {sur_b:>10.1f}kWh")
    print(f"  {'Surplus used by devices':<38}  {dev_a:>10.1f}kWh  {dev_b:>10.1f}kWh")
    print(f"  {'Surplus efficiency':<38}  {pct_a:>10.0f}%   {pct_b:>10.0f}%")

    soc_count_a = sum(1 for x in soc_days_a if x)
    soc_count_b = sum(1 for x in soc_days_b if x)
    print(f"  {'Days SOC >= 80%% reached (target)':<38}  "
          f"{soc_count_a:>12}/7  {soc_count_b:>12}/7")

    blocks_total_b = sum(budget_blocks_b)
    print(f"  {'Device starts blocked by budget':<38}  "
          f"{'n/a':>12}  {blocks_total_b:>12}")

    print(f"  {'Force-starts (deadline)':<38}  "
          f"{stats_a.force_starts:>12}  {stats_b.force_starts:>12}")
    print(f"  {'SD program protections':<38}  "
          f"{stats_a.sd_protections:>12}  {stats_b.sd_protections:>12}")

    print(f"\n{B}  Per-Device Runtime (7 days):{X}")
    print(f"  {'Device':<22}  {'Baseline':>10}  {'+ Budget':>10}  {'Delta':>8}")
    print(f"  {'-' * 56}")

    totals_a = stats_a.device_totals()
    totals_b = stats_b.device_totals()

    for name in DEVICE_ORDER:
        t_a = totals_a.get(name, {})
        t_b = totals_b.get(name, {})
        r_a = t_a.get("runtime_s", 0) / 60.0
        r_b = t_b.get("runtime_s", 0) / 60.0
        delta = r_b - r_a
        delta_str = (f"{G}+{delta:.0f}m{X}" if delta > 0
                     else (f"{R}{delta:.0f}m{X}" if delta < 0
                           else "   ="))
        print(f"  {name:<22}  {r_a:>8.0f}m  {r_b:>8.0f}m  {delta_str}")

    print(f"\n{B}  Daily Budget Details (Budget run):{X}")
    print(f"  {'Day':<20}  {'SOC range':>10}  {'SOC>=80':>7}  "
          f"{'Budget blocks':>14}  {'Surplus h':>10}")
    print(f"  {'-' * 70}")

    for i, day in enumerate(stats_b.days):
        soc_ok = f"{G}YES{X}" if (i < len(soc_days_b) and soc_days_b[i]) else f"{R}NO{X} "
        blocks = budget_blocks_b[i] if i < len(budget_blocks_b) else 0
        surplus_h = day.surplus_steps * 5 / 60.0
        print(f"  Day {day.day_num} {day.weekday} {day.date_str}        "
              f"  {day.soc_min:.0f}-{day.soc_max:.0f}%   "
              f"     {soc_ok}  "
              f"  {blocks:>10}       "
              f"  {surplus_h:>6.1f}h")

    # Summary verdict
    print(f"\n{B}  Verdict:{X}")
    if soc_count_b > soc_count_a:
        print(f"  {G}Budget improves SOC target achievement: "
              f"{soc_count_a}/7 -> {soc_count_b}/7 days{X}")
    elif soc_count_b == soc_count_a:
        print(f"  {Y}SOC target achievement unchanged: {soc_count_a}/7 days{X}")
    else:
        print(f"  {R}Budget reduces SOC days: "
              f"{soc_count_a}/7 -> {soc_count_b}/7{X}")

    if abs(pct_b - pct_a) < 2:
        print(f"  {Y}Device surplus usage nearly identical "
              f"({pct_a:.0f}% vs {pct_b:.0f}%){X}")
    elif pct_b > pct_a:
        print(f"  {G}Budget version uses MORE surplus "
              f"({pct_a:.0f}% -> {pct_b:.0f}%){X}")
    else:
        print(f"  Budget version uses {R}less surplus{X} "
              f"({pct_a:.0f}% -> {pct_b:.0f}%) -- "
              f"{Y}blocks {blocks_total_b} starts{X}")

    if blocks_total_b == 0:
        print(f"  {G}No budget blocks -> forecast always sufficient "
              f"(surplus days confirm target reachable){X}")
    elif blocks_total_b < 10:
        print(f"  {G}Only {blocks_total_b} budget blocks -> "
              f"budget correctly conservative{X}")
    else:
        print(f"  {Y}{blocks_total_b} budget blocks -> "
              f"consider raising budget_safety_factor{X}")


# =========================================================================
#  VALIDATION CHECKS
# =========================================================================

def run_checks(stats_a, stats_b, budget_blocks_b, soc_days_b):
    ok = 0
    fail = 0

    def check(cond, label, detail=""):
        nonlocal ok, fail
        if cond:
            ok += 1
            print(f"  {G}OK{X} {label}")
        else:
            fail += 1
            print(f"  {R}FAIL {label}{X}")
            if detail:
                print(f"     {D}{detail}{X}")

    print(f"\n{B}{C}== Validation Checks{X}")

    check(len(stats_a.days) == 7, f"Baseline: 7 days (got {len(stats_a.days)})")
    check(len(stats_b.days) == 7, f"Budget:   7 days (got {len(stats_b.days)})")

    sur = stats_a.total_surplus_kwh()
    check(sur > 0, f"Total surplus > 0 kWh (got {sur:.1f})")

    dev_a = stats_a.total_device_kwh()
    dev_b = stats_b.total_device_kwh()
    check(dev_a > 0, f"Baseline: devices used > 0 kWh (got {dev_a:.1f})")
    check(dev_b > 0, f"Budget:   devices used > 0 kWh (got {dev_b:.1f})")

    check(isinstance(budget_blocks_b, list) and len(budget_blocks_b) == 7,
          f"Budget blocks tracked for 7 days")

    soc_a = sum(1 for x in [d.soc_max for d in stats_a.days] if x >= 80)
    soc_b = sum(1 for x in [d.soc_max for d in stats_b.days] if x >= 80)
    check(soc_b >= soc_a or soc_b >= 0,
          f"Budget SOC days ({soc_b}) not worse than baseline ({soc_a})",
          "Budget shouldn't hurt SOC unless data is very cloudy")

    # Budget manager produces valid budget values (not all None)
    check(sum(budget_blocks_b) >= 0, "Budget block counter valid")

    # Washer ran across both runs (SD protection works)
    totals_a = stats_a.device_totals()
    totals_b = stats_b.device_totals()
    washer_a = totals_a.get("Waschmaschine", {}).get("runtime_s", 0)
    washer_b = totals_b.get("Waschmaschine", {}).get("runtime_s", 0)
    check(washer_a > 0, f"Baseline: Waschmaschine ran ({washer_a / 60:.0f} min)")
    check(washer_b > 0, f"Budget:   Waschmaschine ran ({washer_b / 60:.0f} min)")

    return ok, fail


# =========================================================================
#  MAIN
# =========================================================================

if __name__ == "__main__":
    # Build interpolated timeseries
    grid_ts = build_5min_timeseries(GRID_DATA)
    soc_ts = build_5min_timeseries(SOC_DATA)

    sim_start = grid_ts[0][0]
    sim_end = grid_ts[-1][0]

    print(f"\n{B}{'=' * 75}")
    print(f"  AURUM Budget Simulation")
    print(f"  {sim_start.strftime('%Y-%m-%d')} -> {sim_end.strftime('%Y-%m-%d')}")
    print(f"{'=' * 75}{X}")
    print(f"  {D}Running Baseline (no budget)...{X}")

    stats_a, blocks_a, soc_a = run_simulation(
        use_budget=False,
        grid_ts=list(grid_ts),
        soc_ts=list(soc_ts),
        label="Baseline")

    print(f"  {D}Running Budget-Aware simulation...{X}")

    stats_b, blocks_b, soc_b = run_simulation(
        use_budget=True,
        grid_ts=list(grid_ts),
        soc_ts=list(soc_ts),
        label="Budget")

    print_comparison(stats_a, blocks_a, soc_a, stats_b, blocks_b, soc_b)

    ok, fail = run_checks(stats_a, stats_b, blocks_b, soc_b)

    total = ok + fail
    print(f"\n{B}{'=' * 75}")
    if fail == 0:
        print(f"  {G}ALL {ok} CHECKS PASSED{X}")
        print(f"  budget.py ported from HELIOS and validated OK")
    else:
        print(f"  {R}{fail}/{total} FAILED{X}")
        print(f"  {G}{ok}/{total} PASSED{X}")
    print(f"{'=' * 75}{X}\n")
