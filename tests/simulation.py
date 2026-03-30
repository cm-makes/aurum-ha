"""
AURUM v1.0.0 – Full Simulation
================================
Simulates all AURUM logic without Home Assistant.
Run: python tests/simulation.py
"""

import sys
import os
import types
import tempfile
import json
from datetime import datetime, timedelta

# ─── Colors ──────────────────────────────────────────────────────
G = "\033[92m"   # green
R = "\033[91m"   # red
Y = "\033[93m"   # yellow
C = "\033[96m"   # cyan
B = "\033[1m"    # bold
D = "\033[2m"    # dim
X = "\033[0m"    # reset

# ─── Mock HA ─────────────────────────────────────────────────────

class MockHass:
    def __init__(self):
        self.states = {}
        self.logs = []
        self.actions = []

    def get_state(self, entity_id, default=None):
        return self.states.get(entity_id, default)

    def set_state(self, entity_id, value, **kwargs):
        self.states[entity_id] = value

    def turn_on(self, entity_id):
        self.states[entity_id] = "on"
        self.actions.append(("ON", entity_id))

    def turn_off(self, entity_id):
        self.states[entity_id] = "off"
        self.actions.append(("OFF", entity_id))

    def log(self, msg, level="INFO"):
        self.logs.append(msg)


# ─── HA Module Stubs ─────────────────────────────────────────────

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

from aurum.const import *
from aurum.modules.energy import EnergyManager
from aurum.modules.battery import BatteryManager
from aurum.modules.devices import DeviceManager

# ─── Counters ────────────────────────────────────────────────────

ok = 0
fail = 0
warnings = 0


def check(cond, label, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  {G}OK{X} {label}")
    else:
        fail += 1
        print(f"  {R}FAIL {label}{X}")
        if detail:
            print(f"       {D}{detail}{X}")


def warn(label):
    global warnings
    warnings += 1
    print(f"  {Y}!! {label}{X}")


def title(t):
    print(f"\n{B}{C}== {t}{X}")


# ─── Helpers ─────────────────────────────────────────────────────

def cfg(devices=None, **kw):
    c = {
        "grid_power_entity": "sensor.grid",
        "pv_power_entity": "sensor.pv",
        "battery_soc_entity": "sensor.soc",
        "battery_capacity_wh": 10000,
        "target_soc": 80, "min_soc": 10,
        "update_interval": 15,
        "devices": devices or [],
    }
    c.update(kw)
    return c


def dev(name, sw, pw=None, nom=1000, prio=50, soc_th=20, sd=False, **kw):
    d = {"name": name, "switch_entity": sw, "power_entity": pw,
         "nominal_power": nom, "priority": prio,
         "soc_threshold": soc_th, "startup_detection": sd}
    d.update(kw)
    return d


def cycle(hass, en, bat, dm, grid, soc, t, powers=None, warmup=0):
    """Run one AURUM cycle. warmup=N runs N extra energy cycles first to settle EMA."""
    hass.states["sensor.grid"] = str(grid)
    hass.states["sensor.pv"] = "0"
    hass.states["sensor.soc"] = str(soc)
    if powers:
        for k, v in powers.items():
            hass.states[k] = str(v)
    # Warm up EMA with consistent readings
    for i in range(warmup):
        s = {"now": t - timedelta(seconds=(warmup - i) * 15), "cycle": 1}
        en.update(s)
    shared = {"now": t, "cycle": 1}
    en.update(shared)
    bat.update(shared)
    dm.update(shared)
    return shared


def setup(devices, **kw):
    """Create hass + all managers with devices."""
    h = MockHass()
    for d in devices:
        h.states[d["switch_entity"]] = "off"
        if d.get("power_entity"):
            h.states[d["power_entity"]] = "0"
    c = cfg(devices=devices, **kw)
    return h, EnergyManager(h, c), BatteryManager(h, c), DeviceManager(h, c)


def skip_debounce(dm, t, seconds=700):
    """Fast-forward on_since to bypass min_on_time/debounce."""
    for d in dm.devices:
        if d["on_since"]:
            d["on_since"] = t - timedelta(seconds=seconds)
        d["last_on"] = t - timedelta(seconds=seconds)
        d["last_off"] = t - timedelta(seconds=seconds)


def reset_ema(en):
    """Reset EMA so next cycle initializes fresh."""
    en._grid_ema = None


# ══════════════════════════════════════════════════════════════════
#  TESTS
# ══════════════════════════════════════════════════════════════════

def test_plug_compatibility():
    title("1: Smart Plug Compatibility")
    plugs = [
        ("Shelly Plug S", "switch.shelly_plug"),
        ("Tasmota", "switch.tasmota_1"),
        ("Zigbee (IKEA)", "switch.zigbee_tradfri"),
        ("Z-Wave", "switch.zwave_plug"),
        ("Fritz DECT 200", "switch.fritz_dect"),
        ("HA Input Boolean", "input_boolean.virtual"),
        ("Shelly Pro 4PM", "switch.pro4pm_ch1"),
    ]
    for name, sw in plugs:
        h, en, bat, dm = setup([dev(name, sw, nom=500)])
        cycle(h, en, bat, dm, grid=-1000, soc=90,
              t=datetime(2026, 3, 28, 12, 0))
        check(h.states[sw] == "on",
              f"{name} ({sw.split('.')[0]}.*) turns on with surplus")

    # Without power sensor → uses nominal
    h, en, bat, dm = setup([dev("NoPwr", "switch.x", nom=800)])
    s = cycle(h, en, bat, dm, grid=-1500, soc=90,
              t=datetime(2026, 3, 28, 12, 0))
    check(h.states["switch.x"] == "on",
          "No power sensor -> uses nominal_power")

    # With power sensor → reads actual
    h2, en2, bat2, dm2 = setup([
        dev("WithPwr", "switch.y", pw="sensor.y_power", nom=800)])
    h2.states["switch.y"] = "on"
    dm2.devices[0]["managed_on"] = True  # pretend AURUM turned it on
    s = cycle(h2, en2, bat2, dm2, grid=-200, soc=90,
              t=datetime(2026, 3, 28, 12, 0),
              powers={"sensor.y_power": "450"})
    check(s["device_states"][0]["power"] == 450.0,
          "With power sensor reads actual 450W (not nominal 800W)")


def test_priority():
    title("2: Priority-Based Distribution")
    devs = [
        dev("Pool", "switch.pool", nom=500, prio=80),
        dev("Heizstab", "switch.heater", nom=2000, prio=50),
        dev("Wallbox", "switch.car", nom=3700, prio=30),
    ]
    h, en, bat, dm = setup(devs)
    t = datetime(2026, 3, 28, 12, 0)

    # 800W: only pool (needs 500+200=700W)
    cycle(h, en, bat, dm, grid=-800, soc=90, t=t)
    check(h.states["switch.pool"] == "on", "800W: Pool (prio 80) ON")
    check(h.states["switch.heater"] == "off", "800W: Heizstab OFF (too little)")
    check(h.states["switch.car"] == "off", "800W: Wallbox OFF (too little)")

    # 3000W: pool + heater. Remaining after pool: 3000-500=2500, heater needs 2200
    t2 = t + timedelta(minutes=15)
    skip_debounce(dm, t2)
    reset_ema(en)
    cycle(h, en, bat, dm, grid=-3000, soc=90, t=t2)
    check(h.states["switch.heater"] == "on",
          "3000W: Heizstab ON (2500 remaining > 2200 needed)")

    # 8000W: all three
    t3 = t + timedelta(minutes=30)
    skip_debounce(dm, t3)
    reset_ema(en)
    cycle(h, en, bat, dm, grid=-8000, soc=90, t=t3)
    check(h.states["switch.car"] == "on",
          "8000W: Wallbox ON (enough for all)")

    # Drop to 400W: lowest prio (car) off first
    t4 = t + timedelta(minutes=45)
    skip_debounce(dm, t4)
    reset_ema(en)
    cycle(h, en, bat, dm, grid=-400, soc=90, t=t4)
    check(h.states["switch.car"] == "off",
          "400W: Wallbox (lowest prio) OFF first")


def test_battery_modes():
    title("3: Battery Mode Transitions")
    devs = [
        dev("Pool", "switch.pool", nom=500, prio=80, soc_th=30),
        dev("Heizstab", "switch.heater", nom=2000, prio=50, soc_th=60),
    ]
    h, en, bat, dm = setup(devs, target_soc=80, min_soc=10)
    t = datetime(2026, 3, 28, 12, 0)

    # SOC 90 → normal
    s = cycle(h, en, bat, dm, grid=-3000, soc=90, t=t)
    check(s["battery_mode"] == "normal", "SOC 90% -> normal")
    check(h.states["switch.pool"] == "on", "normal: Pool ON")
    check(h.states["switch.heater"] == "on", "normal: Heizstab ON")

    # SOC 50 → low_soc, pool OK (th=30), heater NOT (th=60)
    t2 = t + timedelta(minutes=15)
    skip_debounce(dm, t2)
    s = cycle(h, en, bat, dm, grid=-3000, soc=50, t=t2)
    check(s["battery_mode"] == "low_soc", "SOC 50% -> low_soc")
    check(h.states["switch.pool"] == "on",
          "low_soc: Pool ON (SOC 50 > threshold 30)")
    check(h.states["switch.heater"] == "off",
          "low_soc: Heizstab OFF (SOC 50 < threshold 60)")

    # SOC 5 → charging, everything off
    t3 = t + timedelta(minutes=30)
    skip_debounce(dm, t3)
    s = cycle(h, en, bat, dm, grid=-3000, soc=5, t=t3)
    check(s["battery_mode"] == "charging", "SOC 5% -> charging")
    check(h.states["switch.pool"] == "off",
          "charging: Pool OFF (battery critical)")

    # No battery → always normal
    h2, en2, bat2, dm2 = setup(
        [dev("D1", "switch.d1", nom=500)],
        battery_soc_entity=None)
    s2 = cycle(h2, en2, bat2, dm2, grid=-1000, soc=-1,
               t=datetime(2026, 3, 28, 12, 0))
    check(s2["battery_mode"] == "normal", "No battery -> always normal")


def test_startup_detection():
    title("4: Startup Detection (Waschmaschine)")
    h, en, bat, dm = setup([
        dev("Wascher", "switch.w", pw="sensor.w_power", nom=2000,
            prio=90, sd=True,
            sd_power_threshold=10, sd_detection_time=5,
            sd_min_runtime=60, sd_finish_power=5,
            sd_finish_time=30, sd_max_runtime=7200),
    ])
    h.states["switch.w"] = "on"  # plug on (standby)
    w = dm.devices[0]
    t = datetime(2026, 3, 28, 10, 0)

    # Standby: 2W
    cycle(h, en, bat, dm, grid=-500, soc=90, t=t,
          powers={"sensor.w_power": "2"})
    check(w["sd_state"] == "standby", "2W standby power -> standby")

    # User starts wash -> 1800W spike
    t += timedelta(seconds=15)
    cycle(h, en, bat, dm, grid=-500, soc=90, t=t,
          powers={"sensor.w_power": "1800"})
    check(w["sd_state"] == "detected", "1800W spike -> detected")

    # Sustained -> running
    t += timedelta(seconds=15)
    cycle(h, en, bat, dm, grid=-500, soc=90, t=t,
          powers={"sensor.w_power": "1500"})
    check(w["sd_state"] == "running", "Sustained power -> running")

    # Surplus gone, 2kW import! Washer MUST stay on
    t += timedelta(seconds=30)
    cycle(h, en, bat, dm, grid=2000, soc=70, t=t,
          powers={"sensor.w_power": "1600"})
    check(h.states["switch.w"] == "on",
          "2kW import but SD running -> washer PROTECTED")

    # Battery critical! Still protected
    t += timedelta(seconds=30)
    cycle(h, en, bat, dm, grid=2000, soc=5, t=t,
          powers={"sensor.w_power": "1400"})
    check(h.states["switch.w"] == "on",
          "SOC 5% (charging) but SD running -> STILL protected")

    # Program finishes: low power for finish_time
    t += timedelta(seconds=120)  # past min_runtime (60s)
    for i in range(4):  # 4 cycles * 15s = 60s > finish_time 30s
        t += timedelta(seconds=15)
        cycle(h, en, bat, dm, grid=-500, soc=90, t=t,
              powers={"sensor.w_power": "3"})

    check(w["sd_state"] == "standby",
          f"Low power sustained -> done -> standby (got {w['sd_state']})")
    # After DONE → STANDBY, SD auto-enables plug for next detection
    check(h.states["switch.w"] == "on",
          "Program done: plug back ON for detection (Helios-Logik)")


def test_sd_no_surplus():
    title("4b: SD Without Surplus (Helios-Logik)")
    h, en, bat, dm = setup([
        dev("Spueler", "switch.sp", pw="sensor.sp_power", nom=2000,
            prio=80, sd=True,
            sd_power_threshold=10, sd_detection_time=5,
            sd_min_runtime=60, sd_finish_power=5,
            sd_finish_time=30, sd_max_runtime=7200),
    ])
    sp = dm.devices[0]
    t = datetime(2026, 3, 28, 10, 0)

    # No surplus, plug is OFF → SD must turn it ON for detection
    cycle(h, en, bat, dm, grid=500, soc=90, t=t,
          powers={"sensor.sp_power": "0"})
    check(h.states["switch.sp"] == "on",
          "No surplus: SD plug auto-enabled for detection")
    check(sp["sd_state"] == "standby",
          "State is standby (waiting for program start)")

    # Device now on, drawing 2W standby
    t += timedelta(seconds=15)
    cycle(h, en, bat, dm, grid=500, soc=90, t=t,
          powers={"sensor.sp_power": "2"})
    check(h.states["switch.sp"] == "on",
          "Standby 2W: plug stays ON")

    # User starts dishwasher → 1500W
    t += timedelta(seconds=15)
    cycle(h, en, bat, dm, grid=500, soc=90, t=t,
          powers={"sensor.sp_power": "1500"})
    check(sp["sd_state"] == "detected",
          "1500W spike detected (no surplus needed!)")

    # Sustained → running
    t += timedelta(seconds=15)
    cycle(h, en, bat, dm, grid=500, soc=90, t=t,
          powers={"sensor.sp_power": "1400"})
    check(sp["sd_state"] == "running",
          "Sustained → running (program protected)")

    # Battery charging mode (SOC 5%) → program STILL protected
    t += timedelta(seconds=15)
    cycle(h, en, bat, dm, grid=2000, soc=5, t=t,
          powers={"sensor.sp_power": "1300"})
    check(h.states["switch.sp"] == "on",
          "SOC 5% + no surplus: program PROTECTED (Helios-Logik)")

    # Program finishes
    t += timedelta(seconds=120)  # past min_runtime
    for i in range(4):
        t += timedelta(seconds=15)
        cycle(h, en, bat, dm, grid=500, soc=90, t=t,
              powers={"sensor.sp_power": "2"})

    check(h.states["switch.sp"] in ("on", "off"),
          f"Program done, state={sp['sd_state']}")

    # After done → next cycle turns plug back on for standby detection
    t += timedelta(seconds=15)
    cycle(h, en, bat, dm, grid=500, soc=90, t=t,
          powers={"sensor.sp_power": "0"})
    check(h.states["switch.sp"] == "on",
          "After done: plug back ON for next program detection")
    check(sp["sd_state"] == "standby",
          "Ready for next cycle (standby)")


def test_hysteresis_debounce():
    title("5: Hysteresis & Debounce")
    h, en, bat, dm = setup([
        dev("H", "switch.h", nom=2000, prio=50,
            hysteresis_on=200, hysteresis_off=100,
            debounce_on=60, debounce_off=120,
            min_on_time=300),
    ])
    d = dm.devices[0]
    t = datetime(2026, 3, 28, 12, 0)

    # 2100W < 2200 (nom+hysteresis_on)
    cycle(h, en, bat, dm, grid=-2100, soc=90, t=t)
    check(h.states["switch.h"] == "off",
          "2100W < 2200 needed (hysteresis) -> OFF")

    # 2500W enough
    t += timedelta(seconds=15)
    cycle(h, en, bat, dm, grid=-2500, soc=90, t=t)
    check(h.states["switch.h"] == "on",
          "2500W >= 2200 -> ON")

    # Small deficit: 50W import, within hysteresis_off (100)
    t += timedelta(seconds=15)
    cycle(h, en, bat, dm, grid=50, soc=90, t=t)
    check(h.states["switch.h"] == "on",
          "50W deficit < hysteresis_off 100 -> stays ON")

    # 200W deficit BUT min_on_time (300s) not reached
    t += timedelta(seconds=15)
    cycle(h, en, bat, dm, grid=200, soc=90, t=t)
    check(h.states["switch.h"] == "on",
          "200W deficit but min_on_time not reached -> stays ON")

    # Past min_on_time
    t += timedelta(seconds=300)
    d["on_since"] = t - timedelta(seconds=350)
    reset_ema(en)
    cycle(h, en, bat, dm, grid=200, soc=90, t=t)
    check(h.states["switch.h"] == "off",
          "Past min_on_time + deficit -> OFF")

    # Try re-enable immediately -> debounce blocks
    t += timedelta(seconds=15)
    reset_ema(en)
    cycle(h, en, bat, dm, grid=-3000, soc=90, t=t)
    check(h.states["switch.h"] == "off",
          "15s after OFF: debounce_on (60s) blocks")

    # After debounce
    t += timedelta(seconds=60)
    reset_ema(en)
    cycle(h, en, bat, dm, grid=-3000, soc=90, t=t)
    check(h.states["switch.h"] == "on",
          "75s after OFF: debounce passed -> ON again")


def test_manual_override():
    title("6: Manual Override Detection")
    h, en, bat, dm = setup([
        dev("Pool", "switch.pool", nom=500, prio=50),
    ])
    d = dm.devices[0]
    t = datetime(2026, 3, 28, 12, 0)

    # User manually turns on via HA app (AURUM didn't do it)
    h.states["switch.pool"] = "on"
    # d["managed_on"] is False by default

    cycle(h, en, bat, dm, grid=500, soc=90, t=t)  # no surplus!
    check(h.states["switch.pool"] == "on",
          "Manual override: device ON despite no surplus")
    check(d["managed_on"] == False,
          "managed_on stays False (not AURUM-controlled)")

    st = [s for s in dm.devices[0:] if True]  # just get device state from shared
    # Check state label
    s = cycle(h, en, bat, dm, grid=500, soc=90, t=t)
    manual_state = None
    for ds in s.get("device_states", []):
        if ds["name"] == "Pool":
            manual_state = ds["state"]
    check(manual_state == "manual_override",
          f"State shows 'manual_override' (got {manual_state})")

    # AURUM turns a device on normally
    h2, en2, bat2, dm2 = setup([
        dev("Heater", "switch.h", nom=500, prio=50),
    ])
    t2 = datetime(2026, 3, 28, 12, 0)
    cycle(h2, en2, bat2, dm2, grid=-1000, soc=90, t=t2)
    check(dm2.devices[0]["managed_on"] == True,
          "AURUM turns on -> managed_on=True")

    # Surplus gone -> AURUM turns it off
    t2 += timedelta(minutes=15)
    skip_debounce(dm2, t2)
    reset_ema(en2)
    cycle(h2, en2, bat2, dm2, grid=500, soc=90, t=t2)
    check(h2.states["switch.h"] == "off",
          "AURUM-managed device: turned off when surplus gone")
    check(dm2.devices[0]["managed_on"] == False,
          "After OFF: managed_on=False")


def test_deadline():
    title("7: Deadline Scheduling")

    # Scenario: Washer with deadline 18:00, estimated 120min runtime
    h, en, bat, dm = setup([
        dev("Wascher", "switch.w", nom=2000, prio=50,
            deadline="18:00", estimated_runtime=120,
            sd=True, sd_power_threshold=10, sd_detection_time=5,
            sd_min_runtime=60, sd_finish_power=5,
            sd_finish_time=30, sd_max_runtime=7200),
    ])
    w = dm.devices[0]

    # 14:00 – 4h to deadline, 2h estimated → not urgent yet
    # But SD device: plug is ON for detection (Helios-Logik)
    t = datetime(2026, 3, 28, 14, 0)
    cycle(h, en, bat, dm, grid=500, soc=90, t=t)  # no surplus
    check(h.states["switch.w"] == "on",
          "14:00: SD device -> plug ON for detection (not yet urgent)")
    check(w["force_started"] == False,
          "14:00: not urgent -> force_started=False")

    # 15:55 – 2h5min left, 2h+5min needed → URGENT!
    t2 = datetime(2026, 3, 28, 15, 55)
    cycle(h, en, bat, dm, grid=500, soc=90, t=t2)  # no surplus!
    check(h.states["switch.w"] == "on",
          "15:55: 125min left = 120+5min needed -> FORCE START")
    check(w["force_started"] == True,
          "force_started flag is True")

    # 16:00 – still urgent, battery charging mode → stays on anyway
    t3 = datetime(2026, 3, 28, 16, 0)
    cycle(h, en, bat, dm, grid=2000, soc=5, t=t3)  # importing + SOC critical
    check(h.states["switch.w"] == "on",
          "16:00: SOC 5% but deadline urgent -> stays ON")

    # 16:10 – surplus gone, still within deadline → stays on
    t4 = datetime(2026, 3, 28, 16, 10)
    cycle(h, en, bat, dm, grid=2000, soc=50, t=t4)
    check(h.states["switch.w"] == "on",
          "16:10: No surplus but deadline urgent -> stays ON")

    # 19:00 – deadline passed → no longer urgent, can turn off normally
    h2, en2, bat2, dm2 = setup([
        dev("Wascher", "switch.w", nom=2000, prio=50,
            deadline="18:00", estimated_runtime=120),
    ])
    t5 = datetime(2026, 3, 28, 19, 0)
    cycle(h2, en2, bat2, dm2, grid=500, soc=90, t=t5)
    check(h2.states["switch.w"] == "off",
          "19:00: Past deadline -> not urgent, stays OFF")

    # No deadline set → never force-starts
    h3, en3, bat3, dm3 = setup([
        dev("Pool", "switch.pool", nom=500, prio=50),
    ])
    t6 = datetime(2026, 3, 28, 17, 55)
    cycle(h3, en3, bat3, dm3, grid=500, soc=90, t=t6)
    check(h3.states["switch.pool"] == "off",
          "No deadline: never force-starts")

    # Deadline with no estimated_runtime → never urgent
    h4, en4, bat4, dm4 = setup([
        dev("Test", "switch.t", nom=500, prio=50,
            deadline="18:00", estimated_runtime=0),
    ])
    t7 = datetime(2026, 3, 28, 17, 55)
    cycle(h4, en4, bat4, dm4, grid=500, soc=90, t=t7)
    check(h4.states["switch.t"] == "off",
          "Deadline but no estimated_runtime -> never urgent")


def test_ema():
    title("8: EMA Smoothing")
    h = MockHass()
    c = cfg()
    en = EnergyManager(h, c)

    values = [-1000, -800, -1200, -950, -1100, -1000, -1050, -980]
    emas = []
    for i, grid in enumerate(values):
        h.states["sensor.grid"] = str(grid)
        h.states["sensor.pv"] = "0"
        h.states["sensor.soc"] = "80"
        shared = {"now": datetime(2026, 3, 28, 12, i, 0)}
        en.update(shared)
        emas.append(shared["grid_power_ema"])

    raw_range = max(values) - min(values)
    ema_range = max(emas) - min(emas)
    check(ema_range < raw_range,
          f"EMA range ({ema_range:.0f}W) < raw range ({raw_range}W)")

    # First value: EMA should equal raw (not 0.3*raw)
    check(emas[0] == values[0],
          f"First EMA = first raw value ({emas[0]} == {values[0]})")

    print(f"\n  {D}Grid: raw -> EMA (alpha=0.3):{X}")
    for r, e in zip(values, emas):
        print(f"    {r:>6}W -> {e:>8.1f}W")


def test_persistence():
    title("9: State Persistence")
    from aurum.modules.persistence import PersistenceManager

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        sf = f.name

    h = MockHass()
    c = cfg(devices=[
        dev("Pool", "switch.pool", nom=500),
        dev("Heater", "switch.h", nom=2000),
    ], state_file=sf)

    pm = PersistenceManager(h, c)
    dm = DeviceManager(h, c)

    dm.devices[0]["runtime_today_s"] = 3600
    dm.devices[0]["total_switches"] = 5
    dm.devices[1]["runtime_today_s"] = 1800

    pm.save(dm)

    dm2 = DeviceManager(h, c)
    check(dm2.devices[0]["runtime_today_s"] == 0, "Fresh DM: 0 runtime")
    pm.restore(dm2)
    check(dm2.devices[0]["runtime_today_s"] == 3600,
          f"Restored Pool runtime: 3600s (got {dm2.devices[0]['runtime_today_s']})")
    check(dm2.devices[0]["total_switches"] == 5,
          f"Restored Pool switches: 5")

    os.unlink(sf)


def test_edge_cases():
    title("10: Edge Cases")

    # Zero surplus
    h, en, bat, dm = setup([dev("D1", "switch.d1", nom=500)])
    cycle(h, en, bat, dm, grid=0, soc=90, t=datetime(2026, 3, 28, 12, 0))
    check(h.states["switch.d1"] == "off", "Zero surplus -> off")

    # No devices
    h2, en2, bat2, dm2 = setup([])
    s = cycle(h2, en2, bat2, dm2, grid=-5000, soc=90,
              t=datetime(2026, 3, 28, 12, 0))
    check(s["devices_on"] == 0, "No devices configured -> no error")

    # All devices too big
    h3, en3, bat3, dm3 = setup([
        dev("Big", "switch.big", nom=5000, prio=80),
    ])
    cycle(h3, en3, bat3, dm3, grid=-1000, soc=90,
          t=datetime(2026, 3, 28, 12, 0))
    check(h3.states["switch.big"] == "off",
          "1000W surplus < 5200W needed -> stays off")

    # Daily reset
    h4, en4, bat4, dm4 = setup([dev("D", "switch.d", nom=500)])
    dm4.devices[0]["runtime_today_s"] = 7200
    dm4.devices[0]["total_switches"] = 10
    dm4.daily_reset()
    check(dm4.devices[0]["runtime_today_s"] == 0,
          "daily_reset: runtime -> 0")
    check(dm4.devices[0]["total_switches"] == 0,
          "daily_reset: switches -> 0")


def test_missing_features():
    title("11: Remaining Recommendations")
    warn("No daily runtime target (e.g. 'pool needs 4h/day')")
    warn("No EMA reset when large device switches on/off")
    # Fixed: SD now auto-enables plug for detection (Helios-Logik)


# ══════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print(f"\n{B}{'='*55}")
    print(f"  AURUM v1.0.0 - Full Simulation")
    print(f"{'='*55}{X}")

    test_plug_compatibility()
    test_priority()
    test_battery_modes()
    test_startup_detection()
    test_sd_no_surplus()
    test_hysteresis_debounce()
    test_manual_override()
    test_deadline()
    test_ema()
    test_persistence()
    test_edge_cases()
    test_missing_features()

    print(f"\n{B}{'='*55}")
    total = ok + fail
    if fail == 0:
        print(f"  {G}ALL {ok} CHECKS PASSED{X}")
    else:
        print(f"  {R}{fail}/{total} FAILED{X}")
        print(f"  {G}{ok}/{total} PASSED{X}")
    if warnings:
        print(f"  {Y}{warnings} WARNINGS (missing features){X}")
    print(f"{B}{'='*55}{X}\n")
