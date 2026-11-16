"""
Priority reservation: a higher-priority device keeps its claim on the
surplus while it waits out its debounce.

Up to 1.16.4 priority only ordered the devices within one cycle. With a
constant 1900 W surplus, a heater (1500 W, priority 90, Debounce ON 300 s)
lost to a pump (600 W, priority 10, Debounce ON 60 s): the pump started
first, its load pushed the surplus below the heater's need (nominal +
hysteresis_on + residual = 1800 W) and reset the heater's timer, so the
heater never started. Now a lower-priority device sees the surplus minus
what every higher-priority device that is debouncing toward a surplus start
needs for that start (nominal + hysteresis_on + residual_power; a waiting
program: nominal + hysteresis_on), unless that device's start is blocked
for another reason or two of its starts within the hour did not take.
"""

from datetime import timedelta

import pytest

from custom_components.aurum.const import (
    SD_STATE_RUNNING,
    SD_STATE_WAITING,
    disable_entity_id,
    muss_heute_entity_id,
    override_entity_id,
)

from tests.conftest import FakePricing

H_SW = "switch.heater"
L_SW = "switch.pump"
SD_SW = "switch.washer"


def _shared(now, excess, soc=80, grid_export=None, budget=None, pv=0):
    return {
        "now": now,
        "excess_for_devices": excess,
        "excess_raw_for_devices": excess,
        "grid_power_ema_asym": -(excess if grid_export is None
                                 else grid_export),
        "battery_soc": soc,
        "battery_mode": "normal",
        "device_budget_w": budget,
        "pv_power": pv,
        "surplus_blind": False,
    }


def _load(mgr, hass):
    """What the managed devices draw right now (nominal power)."""
    return sum(d["nominal_power"] for d in mgr.devices
               if hass.states.get(d["switch_entity"]) == "on")


def _run(mgr, hass, start, minutes, base, step=30, **kw):
    """Tick every `step` seconds. The measured surplus is `base` (what the
    house exports with every managed device off) minus their load."""
    t = start
    end = start + timedelta(minutes=minutes)
    while t < end:
        mgr.update(_shared(t, base - _load(mgr, hass), **kw))
        t += timedelta(seconds=step)
    return t


def _heater(make_device, **over):
    # Needs 1500 + 200 + 100 = 1800 W to start.
    cfg = dict(name="Heater", switch_entity=H_SW, nominal_power=1500,
               priority=90, debounce_on=300)
    cfg.update(over)
    return make_device(**cfg)


def _pump(make_device, **over):
    # Needs 600 + 200 + 100 = 900 W to start.
    cfg = dict(name="Pump", switch_entity=L_SW, nominal_power=600,
               priority=10, debounce_on=60)
    cfg.update(over)
    return make_device(**cfg)


def _washer(make_device, **over):
    # Startup detection, program waiting for surplus.
    cfg = dict(name="Washer", switch_entity=SD_SW, nominal_power=2000,
               priority=90, debounce_on=300, startup_detection=True)
    cfg.update(over)
    return make_device(**cfg)


def _ever_on(hass, switch):
    return ("ON", switch) in hass.actions


def _first_on(hass, switch):
    return hass.actions.index(("ON", switch))


def _ignore_on(hass, switch, times=None):
    """The switch ignores AURUM's 'on' command (every time, or the first
    `times`): a broken relay or a tripped overpower protection."""
    real_turn_on = hass.turn_on
    left = [times]

    def turn_on(entity_id):
        if entity_id == switch and left[0] != 0:
            if left[0] is not None:
                left[0] -= 1
            hass.actions.append(("ON", entity_id))
            return
        real_turn_on(entity_id)

    hass.turn_on = turn_on


class TestHigherPriorityKeepsItsClaim:
    def test_higher_device_starts_lower_waits(
            self, hass, make_manager, make_device, now):
        mgr = make_manager([_heater(make_device), _pump(make_device)])
        _run(mgr, hass, now, 10, base=1900)
        assert hass.states[H_SW] == "on"
        assert hass.states[L_SW] == "off"
        assert not _ever_on(hass, L_SW)

    def test_lower_starts_once_higher_runs_and_surplus_remains(
            self, hass, make_manager, make_device, now):
        mgr = make_manager([_heater(make_device), _pump(make_device)])
        t = _run(mgr, hass, now, 6, base=1900)
        assert hass.states[H_SW] == "on"
        assert not _ever_on(hass, L_SW)
        # More sun: 2600 - 1500 = 1100 W left once the heater runs.
        _run(mgr, hass, t, 3, base=2600)
        assert hass.states[H_SW] == "on"
        assert hass.states[L_SW] == "on"

    def test_lower_starts_during_the_wait_when_both_fit(
            self, hass, make_manager, make_device, now):
        # 2800 - 1500 reserved = 1300 W covers the pump: it does not wait.
        mgr = make_manager([_heater(make_device), _pump(make_device)])
        t = _run(mgr, hass, now, 2, base=2800)
        assert hass.states[L_SW] == "on"
        assert hass.states[H_SW] == "off"
        _run(mgr, hass, t, 4, base=2800)
        assert hass.states[H_SW] == "on"
        assert hass.states[L_SW] == "on"

    def test_reservations_add_up(self, hass, make_manager, make_device, now):
        # A and B (1000 W each, need 1300 W) both debounce; C (500 W,
        # needs 800 W) sees 2700 - 2000 = 700 W and waits. Without the
        # reservation C started first, and A's start then left B 1200 W.
        mgr = make_manager([
            make_device(name="A", switch_entity="switch.a", priority=90,
                        nominal_power=1000, debounce_on=300),
            make_device(name="B", switch_entity="switch.b", priority=50,
                        nominal_power=1000, debounce_on=300),
            make_device(name="C", switch_entity="switch.c", priority=10,
                        nominal_power=500, debounce_on=60),
        ])
        _run(mgr, hass, now, 10, base=2700)
        assert hass.states["switch.a"] == "on"
        assert hass.states["switch.b"] == "on"
        assert hass.states["switch.c"] == "off"
        assert not _ever_on(hass, "switch.c")

    @pytest.mark.parametrize("heater_over, pump_over, base", [
        # Heater needs 1500 + 500 + 100 = 2100 W, the pump 900 W.
        (dict(hysteresis_on=500), {}, 2500),
        # Heater needs 1500 + 200 + 300 = 2000 W, the pump 600 + 200 = 800.
        (dict(residual_power=300), dict(residual_power=0), 2400),
    ], ids=["hysteresis_on", "residual_power"])
    def test_lower_device_with_smaller_margin_cannot_overtake(
            self, hass, make_manager, make_device, now,
            heater_over, pump_over, base):
        # The heater reserves its whole start need, so the pump sees 400 W
        # and waits. Reserving only its 1500 W nominal power left the pump
        # 1000 / 900 W: the pump started, the heater then saw 1900 / 1800 W,
        # short of its need, and never started.
        mgr = make_manager([_heater(make_device, **heater_over),
                            _pump(make_device, **pump_over)])
        _run(mgr, hass, now, 10, base=base)
        assert hass.states[H_SW] == "on"
        # Once the heater runs, base - 1500 W still covers the pump.
        assert hass.states[L_SW] == "on"
        assert _first_on(hass, H_SW) < _first_on(hass, L_SW)

    def test_equal_priorities_keep_todays_order(
            self, hass, make_manager, make_device, now):
        # Same priority: no reservation, the shorter debounce wins as
        # before, even though the heater comes first in the list.
        mgr = make_manager([_heater(make_device, priority=50),
                            _pump(make_device, priority=50)])
        _run(mgr, hass, now, 10, base=1900)
        assert hass.states[L_SW] == "on"
        assert hass.states[H_SW] == "off"


class TestStartupDetection:
    def test_waiting_program_reserves_against_lower_device(
            self, hass, make_manager, make_device, now):
        # Washer needs 2000 + 200 = 2200 W; the pump sees 400 W and waits
        # instead of starting and being preempted later.
        mgr = make_manager([_washer(make_device), _pump(make_device)])
        mgr.devices[0]["sd_state"] = SD_STATE_WAITING
        _run(mgr, hass, now, 6, base=2400)
        assert mgr.devices[0]["sd_state"] == SD_STATE_RUNNING
        assert hass.states[SD_SW] == "on"
        assert not _ever_on(hass, L_SW)

    def test_lower_waiting_program_respects_higher_reservation(
            self, hass, make_manager, make_device, now):
        # The program (600 W, needs 800 W) sees 1900 - 1500 = 400 W. Once
        # started it could not be cut, so the heater would never start.
        mgr = make_manager([
            _heater(make_device),
            _washer(make_device, nominal_power=600, priority=50,
                    debounce_on=60),
        ])
        washer = next(d for d in mgr.devices if d["name"] == "Washer")
        washer["sd_state"] = SD_STATE_WAITING
        _run(mgr, hass, now, 10, base=1900)
        assert hass.states[H_SW] == "on"
        assert washer["sd_state"] == SD_STATE_WAITING
        assert not _ever_on(hass, SD_SW)

    def test_lower_waiting_program_with_bigger_margin_cannot_overtake(
            self, hass, make_manager, make_device, now):
        # The heater (needs 1800 W) reserves its start need: the washer
        # (2000 W, needs 2200 W) sees 3750 - 1800 = 1950 W and waits. With
        # only the heater's 1500 W reserved it saw 2250 W and started, and
        # the heater then saw 1750 W for the whole program and never ran.
        mgr = make_manager([
            _heater(make_device),
            _washer(make_device, priority=50, debounce_on=60),
        ])
        washer = next(d for d in mgr.devices if d["name"] == "Washer")
        washer["sd_state"] = SD_STATE_WAITING
        _run(mgr, hass, now, 10, base=3750)
        assert hass.states[H_SW] == "on"
        # 3750 - 1500 = 2250 W once the heater runs: the program starts.
        assert washer["sd_state"] == SD_STATE_RUNNING
        assert _first_on(hass, H_SW) < _first_on(hass, SD_SW)

    def test_waiting_program_reserves_what_its_own_test_needs(
            self, hass, make_manager, make_device, now):
        # A waiting program's start test is nominal + hysteresis_on (no
        # residual_power): the washer reserves 2200 W, so the pump (needs
        # 900 W) sees 3100 - 2200 = 900 W and may start during the wait.
        mgr = make_manager([_washer(make_device), _pump(make_device)])
        mgr.devices[0]["sd_state"] = SD_STATE_WAITING
        t = _run(mgr, hass, now, 2, base=3100)
        assert hass.states[L_SW] == "on"
        assert not _ever_on(hass, SD_SW)
        # 3100 - 600 = 2500 W still covers the program.
        _run(mgr, hass, t, 5, base=3100)
        assert mgr.devices[0]["sd_state"] == SD_STATE_RUNNING

    def test_program_short_of_surplus_neither_sheds_nor_reserves(
            self, hass, make_manager, make_device, now):
        # The washer (needs 2200 W) sees 1400 W. The 600 W pump cannot
        # cover the 800 W deficit, so it is not shed (it used to be, and
        # came back on minutes later). The washer's old timer is cleared
        # and it does not hold back the fan (300 W, needs 600 W), which
        # starts after its own 60 s debounce.
        mgr = make_manager([
            _washer(make_device),
            _pump(make_device, priority=50),
            make_device(name="Fan", switch_entity="switch.fan",
                        nominal_power=300, priority=5, debounce_on=60),
        ])
        washer, pump, _fan = mgr.devices
        washer["sd_state"] = SD_STATE_WAITING
        washer["excess_since"] = now - timedelta(seconds=60)
        hass.states[L_SW] = "on"
        pump.update(managed_on=True, _cached_on=True,
                    on_since=now - timedelta(hours=1))
        _run(mgr, hass, now, 1.5, base=2000)   # ticks at 0, 30 and 60 s
        assert ("OFF", L_SW) not in hass.actions
        assert washer["excess_since"] is None
        assert hass.states["switch.fan"] == "on"

    @pytest.mark.parametrize("base", [3000, 3600])
    def test_no_pump_churn_for_a_program_that_cannot_fit(
            self, hass, make_manager, make_device, now, base):
        # Heater (priority 90) starts first, the waiting washer (priority
        # 50, needs 2200 W) never fits next to it, even with the pump off.
        # It used to shed the running 600 W pump anyway, each time the
        # pump's min_on_time ended: 5 off/on per hour. Now the pump keeps
        # running.
        mgr = make_manager([
            _heater(make_device),
            _washer(make_device, priority=50, debounce_on=60),
            _pump(make_device),
        ])
        washer = next(d for d in mgr.devices if d["name"] == "Washer")
        pump = next(d for d in mgr.devices if d["name"] == "Pump")
        washer["sd_state"] = SD_STATE_WAITING
        hass.states[L_SW] = "on"
        pump.update(managed_on=True, _cached_on=True,
                    on_since=now - timedelta(hours=1))
        _run(mgr, hass, now, 60, base=base)
        assert hass.states[H_SW] == "on"
        assert washer["sd_state"] == SD_STATE_WAITING
        assert ("OFF", L_SW) not in hass.actions
        assert hass.states[L_SW] == "on"


def _block_run_condition(hass, mgr):
    hass.states["sensor.tank"] = "60"
    return {}


def _block_runtime_target(hass, mgr):
    mgr.devices[0]["runtime_today_s"] = 3600
    return {}


def _block_disabled(hass, mgr):
    hass.states[disable_entity_id("heater")] = "on"
    return {}


def _block_override(hass, mgr):
    hass.states[override_entity_id("heater")] = "on"
    return {}


def _block_budget_cap(hass, mgr):
    # 1000 W budget: too small for the heater, enough for the pump.
    return {"budget": 1000}


def _block_soc(hass, mgr):
    # Below the heater's SOC threshold only grid export counts for it, and
    # the battery takes all of the surplus.
    return {"soc": 30, "grid_export": 0}


class TestBlockedDeviceDoesNotReserve:
    @pytest.mark.parametrize("block", [
        _block_run_condition,
        _block_runtime_target,
        _block_disabled,
        _block_override,
        _block_budget_cap,
        _block_soc,
    ], ids=lambda f: f.__name__.replace("_block_", ""))
    def test_reservation_ends_when_the_start_is_blocked(
            self, hass, make_manager, make_device, now, block):
        mgr = make_manager([
            _heater(make_device, condition_entity="sensor.tank",
                    condition_op="below", condition_value=55,
                    stop_after_runtime=True, estimated_runtime=60,
                    soc_threshold=50),
            _pump(make_device),
        ])
        hass.states["sensor.tank"] = "40"
        t = _run(mgr, hass, now, 2, base=1900)
        assert not _ever_on(hass, L_SW)      # the heater reserves
        kw = block(hass, mgr)
        _run(mgr, hass, t, 3, base=1900, **kw)
        assert hass.states[H_SW] == "off"
        assert hass.states[L_SW] == "on"

    def test_min_off_time_blocks_the_reservation(
            self, hass, make_manager, make_device, now):
        # Even with a debounce timer left over, a heater inside its
        # min_off_time cannot start and must not hold the pump back.
        mgr = make_manager([_heater(make_device, min_off_time=1800),
                            _pump(make_device)])
        heater = mgr.devices[0]
        heater["last_off"] = now - timedelta(seconds=30)
        heater["excess_since"] = now - timedelta(seconds=120)
        _run(mgr, hass, now, 3, base=1900)
        assert hass.states[H_SW] == "off"
        assert hass.states[L_SW] == "on"


class TestStartThatDoesNotTake:
    @pytest.mark.parametrize("fault", ["relay", "unknown"])
    def test_reservation_ends_after_two_starts_that_did_not_take(
            self, hass, make_manager, make_device, now, fault):
        # The heater's switch never turns on: a broken relay, or a
        # non-optimistic MQTT switch stuck at 'unknown'. It kept re-arming
        # and reserved forever, so the pump never ran. Now it is commanded
        # at 300 s and 630 s, seen off after each, and the pump starts
        # after its own 60 s debounce from then on.
        mgr = make_manager([_heater(make_device), _pump(make_device)])
        if fault == "relay":
            _ignore_on(hass, H_SW)
        else:
            hass.states[H_SW] = "unknown"
        _run(mgr, hass, now, 20, base=1900)
        assert hass.actions.count(("ON", H_SW)) == 2
        assert hass.states[L_SW] == "on"

    def test_one_lost_command_keeps_the_reservation(
            self, hass, make_manager, make_device, now):
        # A single 'on' that does not arrive is not enough: the heater
        # keeps its claim, starts on the next attempt, and the failure is
        # forgotten once it is seen on.
        mgr = make_manager([_heater(make_device), _pump(make_device)])
        _ignore_on(hass, H_SW, times=1)
        _run(mgr, hass, now, 20, base=1900)
        assert hass.states[H_SW] == "on"
        assert not _ever_on(hass, L_SW)
        assert mgr.devices[0]["_failed_starts"] == []

    def test_failed_starts_stay_bounded(
            self, hass, make_manager, make_device, now):
        # A cheap-grid start is retried every cycle: a broken relay must
        # not grow the list of failed starts without end.
        mgr = make_manager([_pump(make_device, price_mode="cheap_grid")])
        mgr.pricing = FakePricing(price_ok=True)
        _ignore_on(hass, L_SW)
        _run(mgr, hass, now, 30, base=0)
        assert hass.actions.count(("ON", L_SW)) == 60
        assert len(mgr.devices[0]["_failed_starts"]) == 2

    @pytest.mark.parametrize("age_min, pump_waits", [
        (10, False),    # two recent failures: no reservation
        (61, True),     # older than an hour: the heater reserves again
    ])
    def test_failed_starts_count_for_an_hour(
            self, hass, make_manager, make_device, now, age_min, pump_waits):
        mgr = make_manager([_heater(make_device), _pump(make_device)])
        mgr.devices[0]["_failed_starts"] = [
            now - timedelta(minutes=age_min)] * 2
        _run(mgr, hass, now, 3, base=1900)
        assert _ever_on(hass, L_SW) is not pump_waits


class TestOtherStartPathsUnchanged:
    def test_pv_gate_wait_does_not_reserve(
            self, hass, make_manager, make_device, now):
        # The PV gate starts the heater on raw PV whatever the surplus, so
        # the pump's load cannot reset it: no reservation, both run.
        mgr = make_manager([_heater(make_device, pv_power_threshold=1000),
                            _pump(make_device)])
        t = _run(mgr, hass, now, 2, base=1900, pv=3000)
        assert hass.states[L_SW] == "on"
        _run(mgr, hass, t, 4, base=1900, pv=3000)
        assert hass.states[H_SW] == "on"

    def test_lower_cheap_grid_start_ignores_reservation(
            self, hass, make_manager, make_device, now):
        mgr = make_manager([_heater(make_device),
                            _pump(make_device, price_mode="cheap_grid")])
        mgr.pricing = FakePricing(price_ok=True)
        _run(mgr, hass, now, 0.5, base=1900)
        assert hass.states[L_SW] == "on"

    def test_lower_deadline_start_ignores_reservation(
            self, hass, make_manager, make_device, now):
        mgr = make_manager([_heater(make_device),
                            _pump(make_device, deadline="12:30",
                                  estimated_runtime=60)])
        hass.states[muss_heute_entity_id("pump")] = "on"
        _run(mgr, hass, now, 0.5, base=1900)
        assert hass.states[L_SW] == "on"
        assert mgr.devices[1]["force_started"] is True
