"""
Start reserve for a startup-detection program whose heating phase has
not started yet.

A washer takes in water at about 25 W for several minutes and heats at
about 2 kW afterwards. Before the reserve, its surplus looked free right
after its start: a second waiting machine (dishwasher) started on it, and
minutes later both heated from the grid or the battery. Both are
non-interruptible, so shedding could not fix it.

Now a RUNNING program keeps (nominal power - measured power) free until it
has drawn 90 % of its nominal power once, for at most 30 minutes after its
start. Other startup-detection programs and non-interruptible devices do
not start on that surplus; interruptible devices may use it (they are shed
when the heating comes) unless a device of higher priority is held back by
it. While a reserve is held and for 3 minutes after its release, those
starts also check the measured surplus, since the smoothed one lags. A
program held back by a reserve preempts nobody, nor does one in the cycle
another program starts. An unreachable plug keeps the whole reserve.
"""

import ast
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from custom_components.aurum.const import (
    MODE_NORMAL,
    SD_STATE_RUNNING,
    SD_STATE_WAITING,
    muss_heute_entity_id,
)
from custom_components.aurum.modules.advisor import AdvisorManager
from custom_components.aurum.modules.helpers import ema_update_asymmetric
from custom_components.aurum.modules.persistence import PersistenceManager

T0 = datetime(2026, 11, 15, 9, 0, 0)
TICK = 30
ENERGY_TICK = 15           # the grid meter is read every update cycle
INTAKE_S = 9 * 60          # washer water intake at 25 W


def shared(t, excess, soc=80, turn_on=None, charge=0.0):
    """excess: the measured surplus; turn_on: the smoothed one the
    coordinator hands the devices for starts (default: the same).
    charge: battery charge power, counted as surplus but not exported."""
    if turn_on is None:
        turn_on = excess
    return {
        "now": t,
        "excess_for_devices": turn_on,
        "excess_raw_for_devices": excess,
        "grid_power_ema_asym": -(turn_on - charge),
        "grid_power_raw": -(excess - charge),
        "battery_soc": soc,
        "battery_mode": MODE_NORMAL,
        "device_budget_w": None,
    }


def machine(make_device, name, priority, **kw):
    slug = name.lower()
    cfg = dict(name=name, switch_entity=f"switch.{slug}",
               power_entity=f"sensor.{slug}_power", nominal_power=2000,
               priority=priority, startup_detection=True)
    cfg.update(kw)
    return make_device(**cfg)


def hot_wash(elapsed_s):
    """25 W water intake for 9 min, then 2000 W heating."""
    return 25.0 if elapsed_s < INTAKE_S else 2000.0


def by_name(mgr, name):
    return next(d for d in mgr.devices if d["name"] == name)


class House:
    """PV surplus before any AURUM device, and what each device draws.

    A startup-detection machine reads 1 W in standby, 25 W once its Start
    button was pressed (until AURUM pauses it), 0 W with the plug off, and
    its program profile (seconds since the run started -> W) while
    RUNNING. A regular device draws its nominal power while on.

    ema=True reads the grid like the coordinator: every 15 s into the
    asymmetric EMA (alpha 0.7 while the surplus rises, 0.2 while it
    falls), and the devices are controlled every second cycle on that EMA
    (starts) and the raw reading (stops). Otherwise both are the raw
    surplus, every 30 s.

    A device in `offline` keeps running (a relay keeps its state during a
    WiFi dropout), but its switch and power sensor read unavailable.

    charge: a battery charging at constant power. It counts as surplus
    (battery power sensors without battery priority) but is not exported.
    """

    def __init__(self, mgr, hass, pv, profiles, ema=False):
        self.mgr = mgr
        self.hass = hass
        self.pv = pv
        self.profiles = profiles
        self.ema = ema
        self.grid_ema = None
        self.cycle = 0
        self.soc = 80
        self.charge = 0.0
        self.pressed = set()
        self.offline = set()
        self.started = {}         # name -> first time seen RUNNING
        self.min_excess = None
        self.shared = None

    def draw(self, dev, t):
        if (self.hass.states.get(dev["switch_entity"]) != "on"
                and dev["name"] not in self.offline):
            return 0.0
        if not dev["startup_detection"]:
            return float(dev["nominal_power"])
        if dev["sd_state"] == SD_STATE_RUNNING and dev["sd_running_since"]:
            elapsed = (t - dev["sd_running_since"]).total_seconds()
            return self.profiles[dev["name"]](elapsed)
        return 25.0 if dev["name"] in self.pressed else 1.0

    def run(self, t, seconds):
        step = ENERGY_TICK if self.ema else TICK
        end = t + timedelta(seconds=seconds)
        while t < end:
            total = 0.0
            for dev in self.mgr.devices:
                watts = self.draw(dev, t)
                total += watts
                if dev["name"] in self.offline:
                    self.hass.states[dev["switch_entity"]] = "unavailable"
                    if dev["power_entity"]:
                        self.hass.states[dev["power_entity"]] = "unavailable"
                elif dev["power_entity"]:
                    self.hass.states[dev["power_entity"]] = str(watts)
            export = self.pv - total - self.charge
            excess = export + self.charge
            if self.min_excess is None or excess < self.min_excess:
                self.min_excess = excess
            turn_on = None
            if self.ema:
                self.grid_ema = ema_update_asymmetric(
                    self.grid_ema, -export, 0.7, 0.2)
                turn_on = -self.grid_ema + self.charge
            if self.cycle % (TICK // step) == 0:
                self.shared = shared(t, excess, soc=self.soc,
                                     turn_on=turn_on, charge=self.charge)
                self.mgr.update(self.shared)
                for dev in self.mgr.devices:
                    if dev.get("sd_state") == SD_STATE_RUNNING:
                        self.started.setdefault(dev["name"], t)
            self.cycle += 1
            t += timedelta(seconds=step)
        return t

    def reasons(self):
        view = AdvisorManager(self.hass, {}).update(self.shared)
        return {d["name"]: d["reason"] for d in view["devices"]}


def two_waiting_machines(make_manager, make_device, hass, pv, profiles,
                         extra=(), ema=False, **kw):
    """Washer (priority 60) and dishwasher (50), both paused in WAITING
    with no surplus. kw: settings of both machines. Returns the house and
    the time."""
    mgr = make_manager([machine(make_device, "Washer", 60, **kw),
                        machine(make_device, "Dishwasher", 50, **kw),
                        *extra])
    house = House(mgr, hass, 0, profiles, ema=ema)
    t = house.run(T0, 60)                     # plugs on, standby
    house.pressed |= {"Washer", "Dishwasher"}
    t = house.run(t, 60)                      # Start pressed, paused
    for name in ("Washer", "Dishwasher"):
        assert by_name(mgr, name)["sd_state"] == SD_STATE_WAITING
    house.pressed.clear()
    house.pv = pv
    return house, t


class TestTwoMachinesOnOneSurplus:
    def test_only_one_machine_starts(self, hass, make_manager, make_device):
        house, t = two_waiting_machines(
            make_manager, make_device, hass, 2500,
            {"Washer": hot_wash, "Dishwasher": hot_wash})
        house.min_excess = None
        t = house.run(t, 40 * 60)

        washer = by_name(house.mgr, "Washer")
        dish = by_name(house.mgr, "Dishwasher")
        assert washer["sd_state"] == SD_STATE_RUNNING
        assert dish["sd_state"] == SD_STATE_WAITING
        assert hass.states[dish["switch_entity"]] == "off"
        assert "Dishwasher" not in house.started
        # The washer's heating came from the surplus, not the grid.
        assert house.min_excess >= 0

    def test_advisor_names_the_reserve(self, hass, make_manager, make_device):
        house, t = two_waiting_machines(
            make_manager, make_device, hass, 2500,
            {"Washer": hot_wash, "Dishwasher": hot_wash})
        t = house.run(t, 6 * 60)                 # washer in its intake
        assert "Washer" in house.started
        assert house.reasons()["Dishwasher"] == "start_reserve"
        ds = next(d for d in house.shared["device_states"]
                  if d["name"] == "Dishwasher")
        assert ds["start_reserve_hold"] is True

        # The washer heats: the surplus really is short now.
        t = house.run(t, INTAKE_S)
        assert house.reasons()["Dishwasher"] == "program_paused"

    def test_heating_counts_at_once_despite_the_smoothed_surplus(
            self, hass, make_manager, make_device):
        # The start check uses the smoothed surplus, which falls by only
        # 20 % of a drop per reading. When the washer began to heat, its
        # reserve went at once while the smoothed surplus still read about
        # 3,000 W, so with a short debounce the dishwasher started 30 s
        # into the heating (true free surplus 1,500 W, 2,200 W needed) and
        # both heated: -500 W.
        house, t = two_waiting_machines(
            make_manager, make_device, hass, 3500,
            {"Washer": hot_wash, "Dishwasher": hot_wash},
            ema=True, debounce_on=30)
        house.min_excess = None
        t = house.run(t, 40 * 60)

        dish = by_name(house.mgr, "Dishwasher")
        assert "Washer" in house.started
        assert "Dishwasher" not in house.started
        assert dish["sd_state"] == SD_STATE_WAITING
        assert house.min_excess >= 0

    def test_no_preemption_in_the_cycle_another_program_starts(
            self, hass, make_manager, make_device):
        # Both machines finish their debounce in the same cycle. The
        # washer starts; the dishwasher used to switch the pump off for
        # itself right away, although from the next cycle on the washer's
        # reserve holds it: the pump came back and was switched off again
        # once the reserve was released.
        pump = make_device(name="Pump", switch_entity="switch.pump",
                           nominal_power=800, priority=10)
        house, t = two_waiting_machines(
            make_manager, make_device, hass, 3800,
            {"Washer": hot_wash, "Dishwasher": hot_wash}, extra=(pump,))
        p = by_name(house.mgr, "Pump")
        hass.states["switch.pump"] = "on"
        p.update(managed_on=True, on_since=t - timedelta(hours=1))
        hass.actions.clear()

        t = house.run(t, 12 * 60)                # washer still in intake
        assert "Washer" in house.started
        assert t < house.started["Washer"] + timedelta(seconds=INTAKE_S)
        assert ("OFF", "switch.pump") not in hass.actions
        assert hass.states["switch.pump"] == "on"
        assert by_name(house.mgr, "Dishwasher")["sd_state"] == (
            SD_STATE_WAITING)


class TestReserveRelease:
    def test_cold_wash_releases_after_30_minutes(
            self, hass, make_manager, make_device):
        house, t = two_waiting_machines(
            make_manager, make_device, hass, 3000,
            {"Washer": lambda s: 300.0, "Dishwasher": hot_wash})
        t = house.run(t, 6 * 60)
        washer_start = house.started["Washer"]
        dish = by_name(house.mgr, "Dishwasher")

        # 2700 W of surplus, but 1700 W stay reserved for the heating.
        t = house.run(t, (washer_start + timedelta(minutes=29, seconds=30)
                          - t).total_seconds())
        assert dish["sd_state"] == SD_STATE_WAITING
        assert by_name(house.mgr, "Washer")["_sd_start_reserve_w"] == 1700

        # 30 min after its start the washer releases it; the dishwasher
        # starts after its debounce.
        t = house.run(t, 7 * 60)
        assert dish["sd_state"] == SD_STATE_RUNNING
        assert house.started["Dishwasher"] >= washer_start + timedelta(
            minutes=30)

    def test_reaching_the_peak_releases_at_once(
            self, hass, make_manager, make_device):
        # Intake, a short 1900 W heating (>= 90 % of 2000 W), then 300 W.
        def short_heat(s):
            if s < INTAKE_S:
                return 25.0
            return 1900.0 if s < INTAKE_S + 180 else 300.0

        house, t = two_waiting_machines(
            make_manager, make_device, hass, 3000,
            {"Washer": short_heat, "Dishwasher": hot_wash})
        t = house.run(t, 6 * 60)
        washer_start = house.started["Washer"]
        dish = by_name(house.mgr, "Dishwasher")

        t = house.run(t, (washer_start + timedelta(seconds=INTAKE_S - 30)
                          - t).total_seconds())
        assert dish["sd_state"] == SD_STATE_WAITING      # held in intake

        # The peak has been seen once: back at 300 W the reserve stays
        # released, long before the 30 min are up.
        t = house.run(t, 12 * 60)
        washer = by_name(house.mgr, "Washer")
        assert washer["_sd_start_reserve_w"] == 0
        assert washer["sd_peak_run"] == washer["sd_running_since"]
        assert dish["sd_state"] == SD_STATE_RUNNING
        assert house.started["Dishwasher"] < washer_start + timedelta(
            minutes=30)


def running_washer(mgr, hass, t, watts=25, **kw):
    """Put the washer into a RUNNING program started at t (as after a
    surplus start), drawing `watts`."""
    dev = by_name(mgr, "Washer")
    hass.states[dev["switch_entity"]] = "on"
    if dev["power_entity"]:
        hass.states[dev["power_entity"]] = str(watts)
    dev.update(sd_state=SD_STATE_RUNNING, sd_running_since=t,
               sd_run_runtime_s=0, managed_on=True, on_since=t,
               sd_lockout_until=t + timedelta(hours=3), **kw)
    return dev


def waiting_dishwasher(mgr, hass, t):
    dev = by_name(mgr, "Dishwasher")
    hass.states[dev["switch_entity"]] = "off"
    dev.update(sd_state=SD_STATE_WAITING, sd_waiting_since=t)
    return dev


class TestReserveValue:
    def test_reserve_rules(self, hass, make_manager, make_device):
        mgr = make_manager([machine(make_device, "Washer", 60)])
        dev = running_washer(mgr, hass, T0, watts=25)
        pw = dev["power_entity"]
        t = T0 + timedelta(minutes=5)
        assert mgr._sd_start_reserve_w(dev, t) == 1975

        hass.states[pw] = "unavailable"          # nothing seen: all of it
        assert mgr._sd_start_reserve_w(dev, t) == 2000

        hass.states[pw] = "25"
        hass.states[dev["switch_entity"]] = "off"   # plug off: nothing
        assert mgr._sd_start_reserve_w(dev, t) == 0
        # Unreachable plug: the relay keeps its state and the program
        # goes on, so all of it stays reserved (still at most 30 min).
        hass.states[dev["switch_entity"]] = "unavailable"
        assert mgr._sd_start_reserve_w(dev, t) == 2000
        assert mgr._sd_start_reserve_w(
            dev, T0 + timedelta(minutes=30)) == 0
        hass.states[dev["switch_entity"]] = "on"

        assert mgr._sd_start_reserve_w(
            dev, T0 + timedelta(minutes=30)) == 0   # window over

        hass.states[pw] = "1800"                 # 90 % of 2000 W
        assert mgr._sd_start_reserve_w(dev, t) == 0
        hass.states[pw] = "25"
        assert mgr._sd_start_reserve_w(dev, t) == 0  # seen once is enough

        # A new run holds a reserve again.
        dev["sd_running_since"] = t
        assert mgr._sd_start_reserve_w(dev, t) == 1975

    def test_unreachable_plug_keeps_the_reserve(
            self, hass, make_manager, make_device):
        # A WiFi dropout of the washer's plug and power sensor during its
        # intake used to release the reserve: the dishwasher started and
        # both heated from the grid.
        house, t = two_waiting_machines(
            make_manager, make_device, hass, 3000,
            {"Washer": hot_wash, "Dishwasher": hot_wash})
        t = house.run(t, 6 * 60)
        washer_start = house.started["Washer"]
        washer = by_name(house.mgr, "Washer")

        t = house.run(t, (washer_start + timedelta(minutes=1)
                          - t).total_seconds())
        house.offline.add("Washer")
        house.min_excess = None
        t = house.run(t, 7 * 60)
        assert washer["_sd_start_reserve_w"] == 2000
        house.offline.clear()
        hass.states[washer["switch_entity"]] = "on"
        t = house.run(t, 30 * 60)

        assert "Dishwasher" not in house.started
        assert washer["sd_state"] == SD_STATE_RUNNING
        assert house.min_excess >= 0

    def test_no_power_sensor_no_reserve(
            self, hass, make_manager, make_device):
        mgr = make_manager([
            machine(make_device, "Washer", 60, power_entity=None),
            machine(make_device, "Dishwasher", 50)])
        running_washer(mgr, hass, T0)
        dish = waiting_dishwasher(mgr, hass, T0)
        t = T0
        for _ in range(12):
            t += timedelta(seconds=TICK)
            mgr.update(shared(t, 2500))
        assert dish["sd_state"] == SD_STATE_RUNNING

    def test_deadline_start_ignores_the_reserve(
            self, hass, make_manager, make_device):
        mgr = make_manager([
            machine(make_device, "Washer", 60),
            machine(make_device, "Dishwasher", 50, deadline="12:00",
                    estimated_runtime=120)])
        running_washer(mgr, hass, T0 + timedelta(hours=2))
        dish = waiting_dishwasher(mgr, hass, T0)
        hass.states[muss_heute_entity_id("dishwasher")] = "on"
        mgr.update(shared(T0 + timedelta(hours=2, minutes=1), 2500))
        assert dish["sd_state"] == SD_STATE_RUNNING
        assert dish["force_started"] is True


class TestOtherDevices:
    def test_non_interruptible_device_waits(
            self, hass, make_manager, make_device):
        boiler = make_device(name="Boiler", switch_entity="switch.boiler",
                             nominal_power=1500, priority=40,
                             interruptible=False)
        mgr = make_manager([machine(make_device, "Washer", 60), boiler])
        running_washer(mgr, hass, T0)
        t = T0
        sh = None
        for _ in range(20):                     # 10 min, washer in intake
            t += timedelta(seconds=TICK)
            sh = shared(t, 2475)
            mgr.update(sh)
        assert hass.states["switch.boiler"] == "off"
        view = AdvisorManager(hass, {}).update(sh)
        reasons = {d["name"]: d["reason"] for d in view["devices"]}
        assert reasons["Boiler"] == "start_reserve"

    def test_interruptible_device_may_use_the_reserved_surplus(
            self, hass, make_manager, make_device):
        # Shed like any other device once the heating comes; holding it
        # back would strand the surplus for up to 30 min after a cold wash.
        pump = make_device(name="Pump", switch_entity="switch.pump",
                           nominal_power=800, priority=40)
        mgr = make_manager([machine(make_device, "Washer", 60), pump])
        running_washer(mgr, hass, T0)
        t = T0
        for _ in range(12):
            t += timedelta(seconds=TICK)
            mgr.update(shared(t, 2475))
        assert hass.states["switch.pump"] == "on"

    def test_lower_priority_device_does_not_take_a_held_back_claim(
            self, hass, make_manager, make_device):
        # The boiler (priority 90) is held back by the washer's reserve.
        # The pump (priority 10) used to take the reserved surplus, and
        # since nobody preempts it, the boiler never started: after the
        # release 2,500 - 300 - 800 = 1,400 W were left against 1,800 W.
        boiler = make_device(name="Boiler", switch_entity="switch.boiler",
                             nominal_power=1500, priority=90,
                             interruptible=False)
        pump = make_device(name="Pump", switch_entity="switch.pump",
                           nominal_power=800, priority=10)
        mgr = make_manager([machine(make_device, "Washer", 60), boiler,
                            pump])
        house = House(mgr, hass, 2500, {"Washer": lambda s: 300.0})
        running_washer(mgr, hass, T0, watts=300)       # a cold program
        t = house.run(T0, 25 * 60)
        assert hass.states["switch.pump"] == "off"
        assert hass.states["switch.boiler"] == "off"
        reasons = house.reasons()
        assert reasons["Boiler"] == "start_reserve"
        assert reasons["Pump"] == "start_reserve"

        # Released after 30 min: the boiler starts by priority.
        t = house.run(t, 15 * 60)
        assert hass.states["switch.boiler"] == "on"
        assert hass.states["switch.pump"] == "off"

    def test_interruptible_device_uses_the_reserve_if_nobody_above_could(
            self, hass, make_manager, make_device):
        # The boiler is blocked by its run condition, not by the reserve:
        # the pump may still use the reserved surplus.
        boiler = make_device(name="Boiler", switch_entity="switch.boiler",
                             nominal_power=1500, priority=90,
                             interruptible=False,
                             condition_entity="sensor.boiler_temp",
                             condition_op="below", condition_value=55)
        pump = make_device(name="Pump", switch_entity="switch.pump",
                           nominal_power=800, priority=10)
        mgr = make_manager([machine(make_device, "Washer", 60), boiler,
                            pump])
        hass.states["sensor.boiler_temp"] = "60"
        house = House(mgr, hass, 2500, {"Washer": lambda s: 300.0})
        running_washer(mgr, hass, T0, watts=300)
        house.run(T0, 10 * 60)
        assert hass.states["switch.pump"] == "on"
        assert hass.states["switch.boiler"] == "off"

    @pytest.mark.parametrize("soc, charge", [(80, 0), (10, 2000)])
    def test_non_interruptible_start_counts_the_heating_at_once(
            self, hass, make_manager, make_device, soc, charge):
        # As for a waiting program: right after the washer began to heat,
        # the smoothed surplus still covered the boiler's 1,800 W, so with
        # a 30 s debounce it started on 1,400 W of true surplus. The same
        # for the grid export a device checks below its SOC threshold
        # (here the battery charges at 2,000 W, which the surplus counts).
        boiler = make_device(name="Boiler", switch_entity="switch.boiler",
                             nominal_power=1500, priority=40,
                             interruptible=False, debounce_on=30)
        mgr = make_manager([machine(make_device, "Washer", 60), boiler])
        house = House(mgr, hass, 3400 + charge, {"Washer": hot_wash},
                      ema=True)
        house.soc = soc
        house.charge = charge
        running_washer(mgr, hass, T0)
        house.run(T0, 20 * 60)
        assert ("ON", "switch.boiler") not in hass.actions
        assert house.min_excess - charge >= 0

    def test_held_program_preempts_nobody(
            self, hass, make_manager, make_device):
        # True surplus 3000 W; the washer's coming 1975 W plus the
        # dishwasher's 2200 W cannot both fit, so switching the pump off
        # would only hand its power to the washer's heating.
        pump = make_device(name="Pump", switch_entity="switch.pump",
                           nominal_power=800, priority=10)
        mgr = make_manager([machine(make_device, "Washer", 60),
                            machine(make_device, "Dishwasher", 80), pump])
        running_washer(mgr, hass, T0)
        dish = waiting_dishwasher(mgr, hass, T0)
        p = by_name(mgr, "Pump")
        hass.states["switch.pump"] = "on"
        p.update(managed_on=True, on_since=T0 - timedelta(hours=1))
        t = T0
        for _ in range(10):
            t += timedelta(seconds=TICK)
            mgr.update(shared(t, 3000 - 25 - 800))
        assert hass.states["switch.pump"] == "on"
        assert ("OFF", "switch.pump") not in hass.actions
        assert dish["sd_state"] == SD_STATE_WAITING


class TestRestart:
    def test_seen_peak_survives_a_restart(
            self, hass, make_manager, make_device, tmp_path):
        sf = str(tmp_path / "state.json")
        cfg = [machine(make_device, "Washer", 60)]
        mgr = make_manager(cfg)
        t = datetime.now().replace(microsecond=0) - timedelta(minutes=10)
        dev = running_washer(mgr, hass, t, watts=2000)
        mgr.update(shared(t + timedelta(minutes=9), 0))
        assert dev["sd_peak_run"] == t
        PersistenceManager(hass, {"state_file": sf}).save(mgr)

        mgr2 = make_manager(cfg)
        PersistenceManager(hass, {"state_file": sf}).restore(mgr2)
        dev2 = by_name(mgr2, "Washer")
        hass.states[dev2["power_entity"]] = "300"
        assert mgr2._sd_start_reserve_w(dev2, t + timedelta(minutes=10)) == 0


COMP = Path(__file__).resolve().parents[1] / "custom_components" / "aurum"


def _advisor_reasons():
    """String codes _device_reason can return."""
    tree = ast.parse((COMP / "modules" / "advisor.py").read_text(
        encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_device_reason")
    return {n.value.value for n in ast.walk(fn)
            if isinstance(n, ast.Return) and isinstance(n.value, ast.Constant)
            and isinstance(n.value.value, str)}


def _panel_keys(lang):
    src = (COMP / "frontend" / "aurum-panel.js").read_text(encoding="utf-8")
    m = re.search(r"\n  " + lang + r": \{(.*?)\n  \},", src, re.S)
    assert m, f"STRINGS.{lang} not found"
    return set(re.findall(r"(\w+):\s*\"", m.group(1)))


class TestAdvisorReasonTexts:
    def test_every_reason_has_en_and_de_panel_text(self):
        reasons = _advisor_reasons()
        assert "start_reserve" in reasons
        for lang in ("en", "de"):
            keys = _panel_keys(lang)
            missing = {r for r in reasons if f"reason_{r}" not in keys}
            assert not missing, f"{lang}: {missing}"
