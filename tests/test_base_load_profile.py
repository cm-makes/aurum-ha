"""
Regression tests for the learned household base load (audit #64, #73).

Nothing wrote shared["hourly_consumption_w"], so the 23:55 job and
BudgetManager.update_consumption_profile() never changed anything and the
PV budget always assumed a flat 500 W household load.

- BaseLoadSampler: house minus AURUM's devices, hourly average, health
  gates (PV and both battery sensors, input faults, guessed device
  power), coverage, a fixed plausibility bound for single samples.
- Skip reasons: diagnostics say why learning is paused, naming the device.
- BudgetManager: default until min_samples, then the measured mean;
  the learned profile survives a restart.
- DeviceManager publishes whether a device's power is measured, and why
  not.
- Coordinator end to end: real update cycles learn the hour and keep it
  across a restart; diagnostics name the device that pauses learning.
- The PV power sensor text asks for the total PV production of all PV
  systems and, with a hybrid inverter, its PV (DC input) power.
"""

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from custom_components.aurum.const import (
    DOMAIN,
    INPUT_STALE,
    INPUT_UNAVAILABLE,
    override_entity_id,
)
from custom_components.aurum.modules.base_load import (
    MAX_PLAUSIBLE_W,
    SKIP_ENERGY_STEP,
    SKIP_IMPLAUSIBLE,
)

REPO = Path(__file__).resolve().parents[1]
UNREACHABLE = "Pool pump: switch unavailable or missing"

GRID = "sensor.grid"
PV = "sensor.pv"
SOC = "sensor.soc"
CHG = "sensor.bat_charge"
DIS = "sensor.bat_discharge"
FC = "sensor.pv_remaining"

T10 = datetime(2026, 6, 15, 10, 0)

FULL_CONFIG = {
    "grid_power_entity": GRID,
    "pv_power_entity": PV,
    "battery_soc_entity": SOC,
    "battery_charge_power_entity": CHG,
    "battery_discharge_power_entity": DIS,
}


class _Clock(datetime):
    """datetime whose now() the test sets."""
    current = T10

    @classmethod
    def now(cls, tz=None):
        return cls.current


def _sampler(**config):
    from custom_components.aurum.modules.base_load import BaseLoadSampler
    return BaseLoadSampler({**FULL_CONFIG, "update_interval": 15, **config})


def _shared(t, pv=3000.0, grid=50.0, net=-1400.0, devices=1000.0,
            measured=True, **extra):
    """One cycle: house = 3000 + 50 - 1400 = 1650 W, AURUM devices 1000 W."""
    shared = {
        "now": t,
        "pv_power": pv,
        "grid_power_raw": grid,
        "battery_power_net": net,
        "device_power_total": devices,
        "surplus_blind": False,
        "input_health": {"grid": "ok", "pv": "ok", "battery_charge": "ok",
                         "battery_discharge": "ok", "soc": "ok"},
        "device_states": [{"name": "Heater", "power": devices,
                           "switch_on": devices > 0,
                           "power_measured": measured}],
    }
    shared.update(extra)
    return shared


def _feed(sampler, start, minutes, step_s=15, special=None, **kw):
    """Sample every step_s from start; return what the hour boundaries
    handed over. special: {cycle index: _shared kwargs for that cycle}."""
    out = []
    for i in range(int(minutes * 60 / step_s)):
        args = {**kw, **(special or {}).get(i, {})}
        res = sampler.sample(_shared(start + timedelta(seconds=i * step_s),
                                     **args))
        if res:
            out.append(res)
    return out


def _close_hour(sampler, t=T10 + timedelta(hours=1)):
    """First cycle of the next hour: returns the finished hour."""
    return sampler.sample(_shared(t))


# ══════════════════════════════════════════════════════════════════
#  BaseLoadSampler
# ══════════════════════════════════════════════════════════════════


class TestSampler:
    def test_hour_average_excludes_aurum_devices(self):
        s = _sampler()
        assert _feed(s, T10, 60) == []
        assert _close_hour(s) == {10: pytest.approx(650.0)}

    def test_each_hour_is_handed_over_once(self):
        s = _sampler()
        _feed(s, T10, 60)
        out = _feed(s, T10 + timedelta(hours=1), 60, devices=500.0)
        assert out == [{10: pytest.approx(650.0)}]
        assert _close_hour(s, T10 + timedelta(hours=2)) == {
            11: pytest.approx(1150.0)}

    def test_needs_a_pv_power_sensor(self):
        # Without PV, grid + battery is about 0 W while PV produces.
        s = _sampler(pv_power_entity=None)
        assert not s.enabled
        assert s.disabled_reason == "no PV power sensor"
        assert _feed(s, T10, 60) == [] and _close_hour(s) is None

    def test_battery_needs_both_battery_power_sensors(self):
        s = _sampler(battery_charge_power_entity=None,
                     battery_discharge_power_entity=None)
        assert s.disabled_reason == "no battery charge or discharge power sensor"
        # The sensors are unsigned: with only the charge sensor a
        # discharging battery is invisible (PV 300 W + battery 500 W
        # would be learned as 300 W), and vice versa.
        only_charge = _sampler(battery_discharge_power_entity=None)
        assert not only_charge.enabled
        assert only_charge.disabled_reason == (
            "no battery discharge power sensor")
        _feed(only_charge, T10, 60)
        assert _close_hour(only_charge) is None
        only_discharge = _sampler(battery_charge_power_entity=None)
        assert only_discharge.disabled_reason == (
            "no battery charge power sensor")
        assert _sampler().enabled
        # No battery at all: house = PV + grid.
        assert _sampler(battery_soc_entity=None,
                        battery_charge_power_entity=None,
                        battery_discharge_power_entity=None).enabled

        # Without a SOC sensor (the config flow allows that) one battery
        # power sensor still means a battery whose other direction goes
        # unseen: PV 300 W + an unseen 500 W discharge would be learned
        # as 300 W (true load 800 W), and those hours would be used once
        # a SOC sensor is added.
        no_soc_charge = _sampler(battery_soc_entity=None,
                                 battery_discharge_power_entity=None)
        assert not no_soc_charge.enabled
        assert no_soc_charge.disabled_reason == (
            "no battery discharge power sensor")
        _feed(no_soc_charge, T10, 60, pv=300.0, grid=0.0, net=0.0,
              devices=0.0, device_states=[])
        assert _close_hour(no_soc_charge) is None
        no_soc_discharge = _sampler(battery_soc_entity=None,
                                    battery_charge_power_entity=None)
        assert no_soc_discharge.disabled_reason == (
            "no battery charge power sensor")
        # Both power sensors without a SOC sensor are enough.
        assert _sampler(battery_soc_entity=None).enabled

    @pytest.mark.parametrize("extra", [
        {"surplus_blind": True},
        {"input_health": {"grid": INPUT_UNAVAILABLE}},
        {"input_health": {"grid": INPUT_STALE}},
        {"input_health": {"pv": INPUT_STALE}},
        # Inverter offline: PV may be producing unseen.
        {"input_health": {"pv": INPUT_UNAVAILABLE}},
        {"input_health": {"battery_charge": INPUT_UNAVAILABLE}},
        {"input_health": {"battery_discharge": INPUT_STALE}},
        # The device step failed this cycle.
        {"device_power_total": None},
        # The energy step failed before it published input health: the
        # powers are missing and would read as 0 W.
        {"input_health": None},
    ])
    def test_unhealthy_cycles_give_no_sample(self, extra):
        s = _sampler()
        _feed(s, T10, 60, **extra)
        assert _close_hour(s) is None

    def test_soc_fault_does_not_stop_learning(self):
        # The SOC is not part of the energy balance.
        s = _sampler()
        _feed(s, T10, 60, input_health={"soc": INPUT_UNAVAILABLE})
        assert _close_hour(s) == {10: pytest.approx(650.0)}

    def test_guessed_device_power_gives_no_sample(self):
        # A device without a power sensor counts its nominal power, which
        # a heating rod at temperature does not draw.
        s = _sampler()
        _feed(s, T10, 60, measured=False)
        assert _close_hour(s) is None

    def test_startup_placeholders_give_no_sample(self):
        s = _sampler()
        _feed(s, T10, 60, device_states=[{"name": "Heater", "power": 0}])
        assert _close_hour(s) is None

    def test_no_devices_is_fine(self):
        s = _sampler()
        _feed(s, T10, 60, devices=0.0, device_states=[])
        assert _close_hour(s) == {10: pytest.approx(1650.0)}

    def test_partial_hour_after_restart_is_not_learned(self):
        late = _sampler()
        _feed(late, T10 + timedelta(minutes=40), 20)
        assert _close_hour(late) is None
        # More than half the hour is enough.
        early = _sampler()
        _feed(early, T10 + timedelta(minutes=25), 35)
        assert _close_hour(early) == {10: pytest.approx(650.0)}

    def test_coverage_follows_the_update_interval(self):
        s = _sampler(update_interval=60)
        assert s.min_samples == 30
        _feed(s, T10 + timedelta(minutes=29), 31, step_s=60)
        assert _close_hour(s) == {10: pytest.approx(650.0)}

    def test_glitch_readings_do_not_drag_the_hour(self):
        # 120 s cycles: 30 samples an hour, so a 2 % trim drops nothing.
        # One 65535 W register glitch would raise the hour by about 2.2 kW.
        s = _sampler(update_interval=120)
        _feed(s, T10, 60, step_s=120, special={7: {"grid": 65535.0}})
        assert _close_hour(s) == {10: pytest.approx(650.0)}
        assert s.last_hour["skipped_cycles"] == {SKIP_IMPLAUSIBLE: 1}

    def test_a_device_power_glitch_does_not_drag_the_hour(self):
        # A glitch in a device's power sensor drives the sample far below
        # 0 W: the plain mean would reject the whole hour as negative.
        s = _sampler(update_interval=120)
        _feed(s, T10, 60, step_s=120, special={7: {"devices": 65535.0}})
        assert _close_hour(s) == {10: pytest.approx(650.0)}

    @pytest.mark.parametrize("watts, kept", [
        (MAX_PLAUSIBLE_W - 1000, True),
        (MAX_PLAUSIBLE_W + 1000, False),
        (-(MAX_PLAUSIBLE_W - 1000), True),
        (-(MAX_PLAUSIBLE_W + 1000), False),
    ])
    def test_plausibility_bound(self, watts, kept):
        from custom_components.aurum.modules.base_load import BaseLoadSampler
        value, reason = BaseLoadSampler.measure(_shared(
            T10, pv=0.0, grid=watts, net=0.0, devices=0.0))
        if kept:
            assert (value, reason) == (watts, None)
        else:
            assert (value, reason) == (None, SKIP_IMPLAUSIBLE)

    def test_a_short_real_load_counts_in_full(self):
        # A kettle: 3 min at +2 kW on a 300 W house (12 of 240 cycles).
        # A 2 % trim at each end dropped most of it (about 369 W).
        s = _sampler()
        _feed(s, T10, 60, pv=0.0, grid=300.0, net=0.0, devices=0.0,
              special={i: {"grid": 2300.0} for i in range(12)})
        assert _close_hour(s) == {10: pytest.approx(400.0)}

    def test_out_of_step_meters_average_out(self):
        # A cloud: PV read late, half the samples 800 W too high and half
        # 800 W too low. No clamp at 0, so the hour stays right.
        s = _sampler()
        _feed(s, T10, 30, pv=0.0, grid=300.0 + 800.0, net=0.0, devices=0.0)
        _feed(s, T10 + timedelta(minutes=30), 30,
              pv=0.0, grid=300.0 - 800.0, net=0.0, devices=0.0)
        assert _close_hour(s) == {10: pytest.approx(300.0)}

    def test_negative_hour_is_rejected(self):
        # AURUM counts more device power than the house uses.
        s = _sampler()
        _feed(s, T10, 60, devices=2200.0)
        assert _close_hour(s) is None
        # A few watts below 0 are tolerance: learned as 0 W.
        s = _sampler()
        _feed(s, T10, 60, devices=1700.0)
        assert _close_hour(s) == {10: 0.0}


# ══════════════════════════════════════════════════════════════════
#  Why learning is paused (diagnostics)
# ══════════════════════════════════════════════════════════════════


def _with_unreachable_pump():
    return [
        {"name": "Heater", "power": 1000.0, "switch_on": True,
         "power_measured": True, "power_unmeasured": None},
        {"name": "Pool pump", "power": 0, "switch_on": False,
         "power_measured": False,
         "power_unmeasured": "switch unavailable or missing"},
    ]


class TestSkipReasons:
    """One switch that never comes back blocks all learning: the
    diagnostics must say so instead of 'active'."""

    def test_an_unreachable_switch_is_named(self):
        s = _sampler()
        _feed(s, T10, 60, device_states=_with_unreachable_pump())
        info = s.info()
        assert info["status"] == "paused"
        assert info["reason"] == UNREACHABLE
        assert info["samples_this_hour"] == 0
        assert info["samples_needed_per_hour"] == 120
        assert info["skipped_this_hour"] == {UNREACHABLE: 240}
        assert info["last_skip"] == {"reason": UNREACHABLE,
                                     "at": "2026-06-15T10:59:45"}

        assert _close_hour(s) is None
        info = s.info()
        assert info["last_hour"] == {
            "hour": 10, "samples": 0, "learned_w": None,
            "reason": "too few samples (0 of 120)",
            "skipped_cycles": {UNREACHABLE: 240}}
        # 11:00 the switch is back: active again; the count since start
        # stays.
        assert info["status"] == "active" and info["reason"] is None
        assert info["skipped_this_hour"] == {}
        assert info["skipped_since_start"] == {UNREACHABLE: 240}

    @pytest.mark.parametrize("extra, reason", [
        ({"device_states": [{"name": "Heater", "power": 1000.0,
                             "switch_on": True, "power_measured": False,
                             "power_unmeasured": "on without a power sensor"}]},
         "Heater: on without a power sensor"),
        ({"input_health": {"grid": INPUT_STALE}}, "grid meter stale"),
        ({"input_health": {"pv": INPUT_UNAVAILABLE}},
         "PV power sensor unavailable"),
        ({"input_health": {"battery_discharge": INPUT_UNAVAILABLE}},
         "battery discharge power sensor unavailable"),
        ({"surplus_blind": True}, "surplus blind"),
        ({"device_power_total": None}, "device step failed"),
        # Odd cycle after a failed device step: stale cached device data.
        ({"base_load_device_data_stale": True}, "device step failed"),
        ({"input_health": None}, SKIP_ENERGY_STEP),
        ({"device_states": [{"name": "Heater", "power": 0}]},
         "devices starting up"),
        ({"grid": 65535.0}, SKIP_IMPLAUSIBLE),
    ])
    def test_each_skip_has_a_reason(self, extra, reason):
        s = _sampler()
        s.sample(_shared(T10, **extra))
        info = s.info()
        assert (info["status"], info["reason"]) == ("paused", reason)
        assert info["skipped_since_start"] == {reason: 1}

    def test_off_names_the_missing_sensor(self):
        info = _sampler(pv_power_entity=None).info()
        assert (info["status"], info["reason"]) == (
            "off", "no PV power sensor")

    def test_a_learned_hour_is_reported(self):
        s = _sampler()
        _feed(s, T10, 60)
        _close_hour(s)
        info = s.info()
        assert (info["status"], info["reason"]) == ("active", None)
        assert info["last_hour"] == {"hour": 10, "samples": 240,
                                     "learned_w": 650.0,
                                     "skipped_cycles": {}}


# ══════════════════════════════════════════════════════════════════
#  BudgetManager consumption profile
# ══════════════════════════════════════════════════════════════════


def _budget(hass, **config):
    from custom_components.aurum.modules.budget import BudgetManager
    return BudgetManager(hass, {"pv_forecast_entity": FC, **config})


class TestBudgetProfile:
    @pytest.fixture(autouse=True)
    def _clock(self, monkeypatch):
        from custom_components.aurum.modules import budget as budget_mod
        monkeypatch.setattr(budget_mod, "datetime", _Clock)
        _Clock.current = T10

    def test_default_until_min_samples_then_the_measured_mean(self, hass):
        bm = _budget(hass)
        feed = {"hourly_consumption_w": {10: 250.0}}
        bm.update_consumption_profile(feed)
        bm.update_consumption_profile(feed)
        # Two days are not enough: the flat default.
        assert bm._estimate_consumption_wh(1.0) == pytest.approx(500.0)
        bm.update_consumption_profile(feed)
        # Day 3: the measured average, not 0.3 * 250 + 0.7 * 500 = 425.
        assert bm._estimate_consumption_wh(1.0) == pytest.approx(250.0)
        # Then the EMA.
        bm.update_consumption_profile({"hourly_consumption_w": {10: 350.0}})
        assert bm._estimate_consumption_wh(1.0) == pytest.approx(280.0)

    def test_unlearned_hours_keep_the_default(self, hass):
        bm = _budget(hass, avg_consumption_w=400)
        for _ in range(3):
            bm.update_consumption_profile(
                {"hourly_consumption_w": {"10": 250.0}})
        # 10:00-12:00: hour 10 learned, hour 11 still the default.
        assert bm._estimate_consumption_wh(2.0) == pytest.approx(650.0)
        info = bm.consumption_profile_info()
        assert info["watts"][10] == 250 and info["watts"][11] == 400
        assert info["samples"][10] == 3 and info["default_w"] == 400

    def test_learned_profile_survives_a_restart(self, hass):
        bm = _budget(hass)
        for _ in range(3):
            bm.update_consumption_profile(
                {"hourly_consumption_w": {10: 250.0}})
        saved = bm.get_state_for_save()
        fresh = _budget(hass)
        fresh.restore_state(saved)
        assert fresh._estimate_consumption_wh(1.0) == pytest.approx(250.0)
        assert fresh.consumption_profile_info() == (
            bm.consumption_profile_info())


# ══════════════════════════════════════════════════════════════════
#  DeviceManager: measured or guessed device power
# ══════════════════════════════════════════════════════════════════


class TestPowerMeasured:
    def test_flag_per_device(self, hass, make_manager, make_device, now):
        mgr = make_manager([
            make_device(name="Metered", switch_entity="switch.a",
                        power_entity="sensor.a_power"),
            make_device(name="Plain", switch_entity="switch.b"),
            make_device(name="Broken", switch_entity="switch.c",
                        power_entity="sensor.c_power"),
            make_device(name="Off", switch_entity="switch.d"),
            make_device(name="Gone", switch_entity="switch.e",
                        power_entity="sensor.e_power"),
        ])
        hass.states.update({
            "switch.a": "on", "sensor.a_power": "420",
            "switch.b": "on",
            "switch.c": "on", "sensor.c_power": "unavailable",
            "switch.d": "off",
            "switch.e": "unavailable", "sensor.e_power": "800",
        })
        shared = {"now": now}
        mgr._publish_device_states(shared, 80)
        flags = {d["name"]: d["power_measured"]
                 for d in shared["device_states"]}
        assert flags == {"Metered": True, "Plain": False, "Broken": False,
                         "Off": True, "Gone": False}
        # Why not, for the diagnostics.
        reasons = {d["name"]: d["power_unmeasured"]
                   for d in shared["device_states"]}
        assert reasons == {
            "Metered": None,
            "Plain": "on without a power sensor",
            "Broken": "on, power sensor unavailable",
            "Off": None,
            "Gone": "switch unavailable or missing",
        }
        # The power figures themselves are unchanged.
        assert shared["device_power_total"] == 420 + 1000 + 1000


# ══════════════════════════════════════════════════════════════════
#  Coordinator end to end
# ══════════════════════════════════════════════════════════════════


def _coordinator(monkeypatch, hass, tmp_path, config):
    from custom_components.aurum import coordinator as coord_mod
    from custom_components.aurum.modules import budget as budget_mod

    monkeypatch.setattr(
        coord_mod.DataUpdateCoordinator, "__init__",
        lambda self, hass, *a, **k: setattr(self, "hass", hass))
    monkeypatch.setattr(coord_mod, "HassAccess", lambda h: h)
    monkeypatch.setattr(coord_mod, "datetime", _Clock)
    monkeypatch.setattr(budget_mod, "datetime", _Clock)

    async def _executor(func, *args):
        return func(*args)

    hass.async_add_executor_job = _executor
    hass.config = SimpleNamespace(path=lambda name: str(tmp_path / name))
    entry = SimpleNamespace(data=config, options={}, entry_id="test")
    coord = coord_mod.AurumCoordinator(hass, entry)
    asyncio.run(coord.async_setup())
    return coord


def _run_cycles(coord, start, end, step_s):
    async def _go():
        t = start
        while t <= end:
            _Clock.current = t
            await coord._async_update_data()
            t += timedelta(seconds=step_s)
    asyncio.run(_go())


class TestCoordinator:
    @pytest.fixture
    def setup(self, hass, make_device, tmp_path):
        config = {
            **FULL_CONFIG,
            "pv_forecast_entity": FC,
            "target_soc": 80,
            "update_interval": 300,
            "consumption_min_samples": 1,
            "state_file": str(tmp_path / "aurum_state.json"),
            "devices": [make_device(
                name="Heater", switch_entity="switch.heater",
                power_entity="sensor.heater_power")],
        }
        # House 3000 + 50 - 1400 = 1650 W, of which the heater 1000 W.
        # Manual override: AURUM leaves the heater on.
        hass.states.update({
            GRID: "50", PV: "3000", SOC: "50", CHG: "1400", DIS: "0",
            FC: "10", "switch.heater": "on",
            "sensor.heater_power": "1000",
            override_entity_id("heater"): "on",
        })
        return config

    def test_update_cycles_learn_the_hour_and_keep_it(
            self, monkeypatch, hass, tmp_path, setup):
        coord = _coordinator(monkeypatch, hass, tmp_path, setup)
        start = datetime(2026, 6, 15, 9, 0)
        _run_cycles(coord, start, start + timedelta(hours=2), 300)

        assert hass.states["switch.heater"] == "on"
        profile = coord.budget._consumption_profile
        # 10:00-11:00: the house without AURUM's heater.
        assert profile[10] == pytest.approx(650.0)
        # 09:00-10:00 was half startup: not learned.
        assert profile[9] == pytest.approx(500.0)

        # Restart: the learned hour comes back from the state file.
        asyncio.run(coord.async_save_state())
        again = _coordinator(monkeypatch, hass, tmp_path, setup)
        assert again.budget._consumption_profile[10] == pytest.approx(650.0)
        assert again.budget.consumption_profile_info()["samples"][10] == 1

    def test_failing_device_step_learns_nothing_from_the_stale_cache(
            self, monkeypatch, hass, tmp_path, setup):
        # The device step raises from 10:00 on while the heater's real draw
        # changes: odd cycles must not learn from the cache of 09:xx.
        coord = _coordinator(monkeypatch, hass, tmp_path, setup)
        start = datetime(2026, 6, 15, 9, 0)
        _run_cycles(coord, start, start + timedelta(minutes=55), 300)

        def _boom(_shared):
            raise RuntimeError("device step broken")
        monkeypatch.setattr(coord.devices, "update", _boom)
        hass.states["sensor.heater_power"] = "2000"
        _run_cycles(coord, start + timedelta(hours=1),
                    start + timedelta(hours=2), 300)
        assert coord.budget._consumption_profile[10] == pytest.approx(500.0)

    def test_no_learning_without_pv_sensor(
            self, monkeypatch, hass, tmp_path, setup):
        setup = {**setup, "pv_power_entity": None}
        coord = _coordinator(monkeypatch, hass, tmp_path, setup)
        start = datetime(2026, 6, 15, 9, 0)
        _run_cycles(coord, start, start + timedelta(hours=2), 300)
        assert coord.budget._consumption_profile == [500] * 24

    def test_diagnostics_name_the_device_that_pauses_learning(
            self, monkeypatch, hass, tmp_path, setup, make_device):
        # A seasonal plug unplugged for the winter: its switch entity is
        # gone, so no cycle gives a sample and no hour is learned.
        setup = {**setup, "devices": setup["devices"] + [make_device(
            name="Pool pump", switch_entity="switch.pool_pump",
            power_entity="sensor.pool_pump_power")]}
        coord = _coordinator(monkeypatch, hass, tmp_path, setup)
        start = datetime(2026, 6, 15, 9, 0)
        _run_cycles(coord, start, start + timedelta(hours=2), 300)
        assert coord.budget._consumption_profile[10] == pytest.approx(500.0)

        from custom_components.aurum import diagnostics
        coord.data = {}
        coord.last_update_success = True
        diag_hass = SimpleNamespace(
            data={DOMAIN: {"test": {"coordinator": coord}}},
            states=SimpleNamespace(get=lambda entity_id: None))
        result = asyncio.run(diagnostics.async_get_config_entry_diagnostics(
            diag_hass, SimpleNamespace(entry_id="test")))
        learning = result["budget"]["consumption_learning"]
        assert learning["status"] == "paused"
        assert learning["reason"] == UNREACHABLE
        assert learning["last_hour"]["hour"] == 10
        assert learning["last_hour"]["learned_w"] is None
        assert learning["last_hour"]["skipped_cycles"] == {UNREACHABLE: 12}

    def test_failed_energy_step_learns_nothing(
            self, monkeypatch, hass, tmp_path, setup):
        # EnergyManager.update raises before it publishes its readings:
        # PV, grid and battery are missing. With no AURUM device drawing
        # power, every cycle would read as a 0 W house and the hour would
        # be learned as 0 W, which inflates the budget.
        setup = {**setup, "devices": []}
        coord = _coordinator(monkeypatch, hass, tmp_path, setup)

        def _broken(shared):
            raise RuntimeError("energy step broke")

        monkeypatch.setattr(coord.energy, "update", _broken)
        start = datetime(2026, 6, 15, 9, 0)
        _run_cycles(coord, start, start + timedelta(hours=2), 300)
        assert coord.budget._consumption_profile[10] == pytest.approx(500.0)
        info = coord.base_load.info()
        assert info["last_hour"]["hour"] == 10
        assert info["last_hour"]["skipped_cycles"] == {SKIP_ENERGY_STEP: 12}


# ══════════════════════════════════════════════════════════════════
#  The PV power sensor must cover all PV production
# ══════════════════════════════════════════════════════════════════


def _pv_descriptions(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    return [step["data_description"]["pv_power_entity"]
            for section in ("config", "options")
            for step in data[section]["step"].values()
            if "pv_power_entity" in step.get("data_description", {})]


_EN_PHRASES = (
    "the total PV production of all PV systems in the house (every "
    "inverter, including a balcony plant)",
    "With a hybrid inverter, use its PV (DC input) power, not its AC "
    "output",
)


class TestPvSensorText:
    """An unmetered balcony plant or a second inverter is missing from
    the house consumption, so the learned load comes out too low: the
    field and the README ask for the total PV production. A hybrid
    inverter's AC output already includes the battery (PV 3000 W DC,
    charging 1500 W: AC 1500 W), so the battery would count twice: they
    ask for its PV (DC input) power, never for an AC output."""

    @pytest.mark.parametrize("path, phrases", [
        ("custom_components/aurum/strings.json", _EN_PHRASES),
        ("custom_components/aurum/translations/en.json", _EN_PHRASES),
        ("custom_components/aurum/translations/de.json", (
            "die gesamte PV-Erzeugung aller PV-Anlagen im Haus",
            "(alle Wechselrichter, auch ein Balkonkraftwerk)",
            "Bei einem Hybrid-Wechselrichter nimm dessen PV-Leistung "
            "(DC-Eingang), nicht die AC-Leistung",
        )),
    ])
    def test_field_description(self, path, phrases):
        texts = _pv_descriptions(REPO / path)
        assert len(texts) == 2      # setup and options
        for text in texts:
            for phrase in phrases:
                assert phrase in text
            # The AC output is only named as what not to use.
            assert "total AC output" not in text
            assert "gesamte AC-Leistung" not in text

    def test_readme(self):
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        assert ("PV **power** sensor that reports the total PV production "
                "of all PV systems in the house (every inverter, including "
                "a balcony plant)") in readme
        assert ("With a hybrid inverter, use its PV (DC input) power, not "
                "its AC output") in readme
        assert "total AC output" not in readme
