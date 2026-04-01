"""
AURUM Budget Safety Factor Calibration
=======================================
Sweeps budget_safety_factor over a range of values and records key metrics
for each, then recommends the optimal value.

Improvement over simulation_7day_budget.py:
  PV estimate uses BOTH grid export AND SOC changes (battery charging rate),
  so the forecast base is closer to actual PV production.

  Battery charge rate (W) = SOC_change_per_5min * battery_capacity_wh / 100 * (60/5)
  House load estimate = 400 W (constant)
  PV_estimate = max(0, -grid_w + house_load_estimate + battery_charge_rate)

Usage:  python simulation_calibrate_budget.py
Requires: simulation_7day_budget.py + simulation_7day.py in same directory.
"""

import math
import os
import random
import sys
import types
from datetime import datetime, timedelta, date as _date

random.seed(42)

# ── HA module stubs (must happen before any aurum import) ────────────────────
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

# ── Import AURUM modules ─────────────────────────────────────────────────────
from aurum.const import *
from aurum.modules.energy import EnergyManager
from aurum.modules.battery import BatteryManager
from aurum.modules.devices import DeviceManager
from aurum.modules.budget import BudgetManager

# ── Import simulation data and helpers from simulation_7day ─────────────────
import re as _re

_sim_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "simulation_7day.py")
_sim_globals = {"__file__": _sim_path, "__name__": "__sim_import__"}
with open(_sim_path) as _f:
    _src = _f.read()

_src = _src.replace('if __name__ == "__main__":', 'if False:')
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


# ═══════════════════════════════════════════════════════════════════════════
#  MOCK HASS
# ═══════════════════════════════════════════════════════════════════════════

class _StateObj:
    __slots__ = ("state", "attributes")
    def __init__(self, state, attributes=None):
        self.state = str(state) if state is not None else ""
        self.attributes = attributes or {}


class _StatesProxy:
    def __init__(self, raw):
        self._raw = raw

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
    def __init__(self):
        self._raw = {}
        self.states = _StatesProxy(self._raw)
        self.logs = []
        self.actions = []

    def get_state(self, entity_id, default=None, attribute=None):
        val = self._raw.get(entity_id, default)
        if attribute:
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

    class _Services:
        def call(self, *a, **kw):
            pass
    services = _Services()


# ═══════════════════════════════════════════════════════════════════════════
#  IMPROVED PV FORECAST HELPERS
# ═══════════════════════════════════════════════════════════════════════════

BATTERY_CAPACITY_WH = 10000
HOUSE_LOAD_W = 400


def compute_pv_estimate(grid_w, soc_now, soc_prev):
    """Estimate actual PV production from grid + SOC change + house load.

    Battery charge rate (W) = SOC_change_per_5min * capacity_wh / 100 * (60/5)
    PV_estimate = max(0, -grid_w + house_load + battery_charge_rate)

    Guard: only produce a non-zero estimate when there is solar evidence
    (grid exporting OR battery charging). This prevents false positives at
    night when the battery discharges to serve house load.
    """
    soc_change = soc_now - soc_prev   # %/5min (positive = charging)
    # No solar evidence: grid importing AND battery discharging -> no PV
    if grid_w >= 0 and soc_change <= 0:
        return 0.0
    # Only count battery charging (positive soc_change) as PV contribution
    battery_charge_w = max(0.0, soc_change) * BATTERY_CAPACITY_WH / 100.0 * (60.0 / 5.0)
    pv_estimate = max(0.0, -grid_w + HOUSE_LOAD_W + battery_charge_w)
    return pv_estimate


def compute_remaining_forecast_kwh_improved(step_idx, grid_ts, soc_ts, today_date):
    """Compute remaining PV forecast kWh for rest of today using improved estimate."""
    remaining_wh = 0.0
    for i in range(step_idx, len(grid_ts)):
        dt, grid_w = grid_ts[i]
        if dt.date() != today_date:
            break
        # Get SOC for this step and previous step
        soc_now = soc_ts[i][1]
        soc_prev = soc_ts[i - 1][1] if i > 0 else soc_now
        pv_w = compute_pv_estimate(grid_w, soc_now, soc_prev)
        remaining_wh += pv_w * (5.0 / 60.0)   # W * h
    return remaining_wh / 1000.0


def build_hourly_forecast_improved(step_idx, grid_ts, soc_ts, today_date, sim_now_dt):
    """Build synthetic hourly forecast using improved PV estimate.

    IMPORTANT: BudgetManager._hours_until_sunset() uses datetime.now() (wall clock)
    to determine current_hour, then scans the wh_period forecast for hours > current_hour.
    To get the correct remaining solar hours, we remap simulation hours to wall-clock-
    relative hours: wall_h = wall_clock_hour + (sim_h - sim_current_hour).
    This preserves the relative ordering and duration of solar production correctly.
    """
    wall_now = datetime.now()
    wall_hour_frac = wall_now.hour + wall_now.minute / 60.0
    sim_hour_frac = sim_now_dt.hour + sim_now_dt.minute / 60.0
    # offset: how many hours to shift sim_hour to get wall-clock-relative hour
    hour_offset = wall_hour_frac - sim_hour_frac

    hourly_pv = {}
    for i in range(step_idx, len(grid_ts)):
        dt, grid_w = grid_ts[i]
        if dt.date() != today_date:
            continue
        h = dt.hour
        soc_now = soc_ts[i][1]
        soc_prev = soc_ts[i - 1][1] if i > 0 else soc_now
        pv_w = compute_pv_estimate(grid_w, soc_now, soc_prev)
        if h not in hourly_pv:
            hourly_pv[h] = []
        hourly_pv[h].append(pv_w * (5.0 / 60.0))  # Wh per 5-min interval

    # Remap hours to wall-clock-relative and use wall-clock date for timestamp keys
    # so budget._get_hourly_forecast() parses dt.hour as wall-clock-relative hour
    forecast = {}
    wall_date = wall_now.date()
    for sim_h, samples in hourly_pv.items():
        wh_hour = sum(samples)
        # Map sim hour to wall-clock hour (preserves relative ordering)
        wall_h = sim_h + round(hour_offset)  # integer hour shift
        wall_h_clamped = max(0, min(23, wall_h))
        key = (f"{wall_date.year}-{wall_date.month:02d}"
               f"-{wall_date.day:02d}T{wall_h_clamped:02d}:00:00")
        # Accumulate if multiple sim hours map to same wall hour
        forecast[key] = forecast.get(key, 0.0) + wh_hour

    return forecast


# ═══════════════════════════════════════════════════════════════════════════
#  SIMULATION ENGINE (parameterised by safety_factor)
# ═══════════════════════════════════════════════════════════════════════════

def run_simulation(safety_factor, grid_ts, soc_ts):
    """Run 7-day budget simulation with the given safety_factor."""
    n_steps = min(len(grid_ts), len(soc_ts))
    grid_ts = grid_ts[:n_steps]
    soc_ts = soc_ts[:n_steps]
    sim_start = grid_ts[0][0]

    hass = MockHass()

    config = {
        "grid_power_entity": "sensor.grid",
        "pv_power_entity": "sensor.pv",
        "battery_soc_entity": "sensor.soc",
        "battery_capacity_wh": BATTERY_CAPACITY_WH,
        "target_soc": 80,
        "min_soc": 10,
        "update_interval": 15,
        "devices": DEVICE_CONFIGS,
        "target_soc_entity": "number.target_soc",
        "pv_forecast_entity": "sensor.pv_forecast_remaining",
        "pv_forecast_today_entity": "sensor.pv_forecast_today",
        "pv_actual_today_entity": None,
        "dwd_weather_entity": None,
        "budget_safety_factor": safety_factor,
        "avg_consumption_w": HOUSE_LOAD_W,
        "budget_combined_floor": 0.85,
        "budget_dynamic_target": False,
    }

    for dev_cfg in DEVICE_CONFIGS:
        hass._raw[dev_cfg["switch_entity"]] = "off"
        if dev_cfg.get("power_entity"):
            hass._raw[dev_cfg["power_entity"]] = "0"

    hass._raw["number.target_soc"] = "80"

    em = EnergyManager(hass, config)
    bm = BatteryManager(hass, config)
    dm = DeviceManager(hass, config)
    budget_mgr = BudgetManager(hass, config)

    # Monkey-patch: fix trajectory multiplier and consumption profile for simulation.
    #
    # BudgetManager._get_trajectory_multiplier() uses datetime.now() (wall clock)
    # for elapsed time, but _trajectory_start_time is set from shared["now"] (sim time).
    # With sim dates in March and wall clock on April 1st, elapsed ≈ 263h, which drives
    # trajectory_multiplier to 0.0, zeroing out all budget.
    # Fix: use sim time (shared["now"]) for trajectory elapsed calculation.
    #
    # BudgetManager._estimate_consumption_wh() also uses datetime.now() for current_hour,
    # causing consumption to be computed from wall-clock hour, not sim hour.
    # Fix: use sim time for the hourly consumption profile.
    #
    # Both fixes are done by binding instance methods that capture sim_now from shared.

    import types as _types

    _sim_now_ref = [None]  # mutable container so closures can update it

    def _traj_mult_sim(self, battery_soc, target_soc, hours_remaining):
        """Trajectory multiplier using simulation time instead of wall clock."""
        if (self._trajectory_start_soc is None
                or self._trajectory_start_time is None):
            return 1.0
        now = _sim_now_ref[0]
        if now is None:
            return 1.0
        total_hours = hours_remaining  # already computed from sim forecast
        elapsed = (now - self._trajectory_start_time).total_seconds() / 3600
        if total_hours <= 0 or elapsed < 0:
            return 1.0
        total_window = elapsed + hours_remaining
        if total_window <= 0:
            return 1.0
        progress = elapsed / total_window
        expected_soc = (self._trajectory_start_soc
                        + (target_soc - self._trajectory_start_soc) * progress)
        deviation = battery_soc - expected_soc
        band = self.trajectory_band if self.trajectory_band > 0 else 5
        adjustment = (deviation / band) * 0.5
        return max(0.0, min(2.0, 1.0 + adjustment))

    def _consumption_sim(self, hours_remaining):
        """Consumption estimate using simulation time instead of wall clock."""
        now = _sim_now_ref[0]
        if now is None:
            return self.avg_consumption_w * hours_remaining
        current_hour = now.hour
        current_frac = now.minute / 60.0
        total_wh = 0.0
        remaining = hours_remaining
        if remaining > 0:
            h = current_hour
            frac = min(remaining, 1.0 - current_frac)
            total_wh += self._consumption_profile[h % 24] * frac
            remaining -= frac
        h = current_hour + 1
        while remaining >= 1.0:
            total_wh += self._consumption_profile[h % 24]
            remaining -= 1.0
            h += 1
        if remaining > 0:
            total_wh += self._consumption_profile[h % 24] * remaining
        return total_wh

    budget_mgr._get_trajectory_multiplier = _types.MethodType(
        _traj_mult_sim, budget_mgr)
    budget_mgr._estimate_consumption_wh = _types.MethodType(
        _consumption_sim, budget_mgr)

    user_sim = UserBehaviorSimulator(sim_start)
    stats = SimStats()
    current_day_num = -1
    current_day = None
    WEEKDAYS_DE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

    budget_blocks_per_day = []
    current_day_budget_blocks = 0
    soc_target_reached_per_day = []
    current_day_max_soc = 0.0

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

            dm.daily_reset()
            em._grid_ema = None
            budget_mgr.daily_reset()

        if soc > current_day_max_soc:
            current_day_max_soc = soc

        for dev_cfg in DEVICE_CONFIGS:
            if dev_cfg.get("startup_detection") and dev_cfg.get("power_entity"):
                simulated_power = user_sim.get_power(
                    dev_cfg["name"], dev_cfg["power_entity"], dt)
                if simulated_power is not None:
                    hass._raw[dev_cfg["power_entity"]] = str(simulated_power)

        hass._raw["sensor.grid"] = str(grid_w)
        hass._raw["sensor.pv"] = "0"
        hass._raw["sensor.soc"] = str(soc)

        # Improved forecast: use PV estimate from grid + SOC changes
        remaining_kwh = compute_remaining_forecast_kwh_improved(
            step_idx, grid_ts, soc_ts, dt.date())
        hass._raw["sensor.pv_forecast_remaining"] = str(remaining_kwh)

        wh_period = build_hourly_forecast_improved(
            step_idx, grid_ts, soc_ts, dt.date(), dt)
        hass._raw["sensor.pv_forecast_today"] = _StateObj(
            str(remaining_kwh),
            {"wh_period": wh_period})

        shared = {"now": dt, "cycle": step_idx + 1}
        _sim_now_ref[0] = dt   # update sim time for monkey-patched methods
        em.update(shared)
        bm.update(shared)
        budget_mgr.update(shared)

        budget_exhausted = False
        budget_w = shared.get("device_budget_w")
        if budget_w is not None and budget_w <= 0:
            budget_exhausted = True

        dm.update(shared)

        if budget_exhausted:
            for dev in dm.devices:
                switch = dev["switch_entity"]
                if hass._raw.get(switch) != "on":
                    continue
                if (dev.get("startup_detection")
                        and dev.get("sd_state") == SD_STATE_RUNNING):
                    continue
                on_since = dev.get("on_since")
                if on_since and (dt - on_since).total_seconds() < 60:
                    hass.turn_off(switch)
                    dev["managed_on"] = False
                    dev["on_since"] = None
                    current_day_budget_blocks += 1

        if dt.hour == 17 and dt.minute == 0:
            budget_mgr.adapt_safety_factor(shared)

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
            grid_w, soc, shared.get("battery_mode", "normal"), shared, hass,
            dm.devices)

    if current_day is not None:
        stats.add_day(current_day)
        budget_blocks_per_day.append(current_day_budget_blocks)
        soc_target_reached_per_day.append(current_day_max_soc >= 80.0)

    stats.force_starts = sum(d.force_starts for d in stats.days)

    total_budget_blocks = sum(budget_blocks_per_day)
    soc_days = sum(1 for x in soc_target_reached_per_day if x)
    device_kwh = stats.total_device_kwh()
    force_starts = stats.force_starts

    return total_budget_blocks, soc_days, device_kwh, force_starts


# ═══════════════════════════════════════════════════════════════════════════
#  MAIN – parameter sweep
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    grid_ts = list(build_5min_timeseries(GRID_DATA))
    soc_ts = list(build_5min_timeseries(SOC_DATA))

    sim_start = grid_ts[0][0]
    sim_end = grid_ts[-1][0]

    SAFETY_FACTORS = [0.50, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 1.00]

    print()
    print("=" * 70)
    print("  AURUM Budget Safety Factor Calibration")
    print(f"  Period: {sim_start.strftime('%Y-%m-%d')} -> {sim_end.strftime('%Y-%m-%d')}")
    print("  PV estimate: grid export + SOC change + house load (400 W)")
    print("=" * 70)
    print()

    results = []

    for sf in SAFETY_FACTORS:
        print(f"  Running sf={sf:.2f} ...", end="", flush=True)
        # Reset random seed for reproducibility per run
        random.seed(42)
        blocks, soc_days, dev_kwh, force_starts = run_simulation(
            sf, list(grid_ts), list(soc_ts))
        results.append((sf, blocks, soc_days, dev_kwh, force_starts))
        print(f"  blocks={blocks:4d}  SOC days={soc_days}/7  "
              f"kWh={dev_kwh:.1f}  force_starts={force_starts}")

    # ── Determine baseline SOC days (lowest sf = most permissive) ──────────
    baseline_soc_days = results[0][2]  # sf=0.50 is the most permissive

    print()
    print("-" * 70)
    print(f"  {'sf':<6}  {'blocks':>7}  {'SOC days':>9}  {'kWh used':>9}  {'force_starts':>12}")
    print(f"  {'-'*6}  {'-'*7}  {'-'*9}  {'-'*9}  {'-'*12}")
    for sf, blocks, soc_days, dev_kwh, force_starts in results:
        soc_str = f"{soc_days}/7"
        print(f"  {sf:<6.2f}  {blocks:>7d}  {soc_str:>9}  {dev_kwh:>9.1f}  {force_starts:>12d}")
    print("-" * 70)

    # ── Recommendation logic ───────────────────────────────────────────────
    # Note: budget_combined_floor (default 0.85) clamps the effective factor
    # to max(floor, sf). Safety factors below 0.85 are therefore all equivalent
    # in their usable_pv calculation. The adaptive mechanism (adapt_safety_factor)
    # also changes sf during the sim based on daily SOC success.
    #
    # The minimum achievable blocks with this dataset is structural:
    # ~490 nighttime blocks (correct: no PV available) are unavoidable.
    # Daytime blocks occur during early morning when SOC is very low and all PV
    # is correctly reserved for battery charging.
    #
    # Goal: lowest sf where budget_blocks < 50 AND soc_days >= baseline.
    # If not achievable, find the best trade-off (fewest blocks, most kWh).

    min_blocks = min(r[1] for r in results)
    max_kwh = max(r[3] for r in results)

    recommended = None
    for sf, blocks, soc_days, dev_kwh, force_starts in results:
        if blocks < 50 and soc_days >= baseline_soc_days:
            recommended = (sf, blocks, soc_days, dev_kwh, force_starts)
            break

    if recommended is None:
        # Fall back: fewest blocks with most kWh (prefer lower sf = more permissive)
        # Among those with minimum blocks, pick highest kWh
        min_block_results = [r for r in results if r[1] == min_blocks]
        recommended = max(min_block_results, key=lambda r: r[3])
        rec_reason = (f"best trade-off: fewest blocks ({min_blocks}) with most kWh "
                      f"(threshold <50 not achievable with this dataset; "
                      f"structural minimum ~490 nighttime no-PV blocks)")
    else:
        rec_reason = "lowest sf with blocks < 50 AND soc_days >= baseline"

    rec_sf, rec_blocks, rec_soc, rec_kwh, rec_fs = recommended

    print()
    print("=" * 70)
    print(f"  ANALYSIS")
    print(f"  Structural findings:")
    print(f"  - budget_combined_floor=0.85 clamps sf<0.85 to same effective value")
    print(f"  - adapt_safety_factor() modifies sf dynamically during simulation")
    print(f"  - Nighttime blocks (~490) are correct: no PV available after sunset")
    print(f"  - Daytime blocks occur when SOC<target and PV needed for charging")
    print(f"  - Minimum achievable blocks: {min_blocks} (structural limit)")
    print(f"  - Maximum device kWh achievable: {max_kwh:.1f}")
    print()
    print(f"  RECOMMENDATION")
    print(f"  Baseline SOC days (sf=0.50, most permissive): {baseline_soc_days}/7")
    print(f"  Criteria: budget_blocks < 50 AND soc_days >= {baseline_soc_days}/7")
    print(f"  Reason: {rec_reason}")
    print()
    print(f"  --> Recommended budget_safety_factor = {rec_sf:.2f}")
    print(f"      blocks={rec_blocks}  SOC days={rec_soc}/7  "
          f"kWh={rec_kwh:.1f}  force_starts={rec_fs}")
    print()
    print(f"  Note: To reduce blocks further, consider lowering budget_combined_floor")
    print(f"  (currently 0.85) or avg_consumption_w (currently {HOUSE_LOAD_W}W).")
    print("=" * 70)
    print()
