"""
Regression tests for the learned household base load (audit #64, #73).

Nothing wrote shared["hourly_consumption_w"], so the 23:55 job and
BudgetManager.update_consumption_profile() never changed anything and the
PV budget always assumed a flat 500 W household load.

- BaseLoadSampler: house minus AURUM's devices, hourly average, health
  gates (PV and battery sensors, input faults, guessed device power),
  coverage, outliers.
- BudgetManager: default until min_samples, then the measured mean;
  the learned profile survives a restart.
- DeviceManager publishes whether a device's power is measured.
- Coordinator end to end: real update cycles learn the hour and keep it
  across a restart.
"""

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.aurum.const import (
    INPUT_STALE,
    INPUT_UNAVAILABLE,
    override_entity_id,
)

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


def _feed(sampler, start, minutes, step_s=15, **kw):
    """Sample every step_s from start; return what the hour boundaries
    handed over."""
    out = []
    for i in range(int(minutes * 60 / step_s)):
        res = sampler.sample(_shared(start + timedelta(seconds=i * step_s),
                                     **kw))
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

    def test_battery_needs_a_battery_power_sensor(self):
        s = _sampler(battery_charge_power_entity=None,
                     battery_discharge_power_entity=None)
        assert s.disabled_reason == "no battery power sensor"
        # One sensor is enough (a signed sensor in one field).
        assert _sampler(battery_discharge_power_entity=None).enabled
        # No battery at all: house = PV + grid.
        assert _sampler(battery_soc_entity=None,
                        battery_charge_power_entity=None,
                        battery_discharge_power_entity=None).enabled

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
        s = _sampler()
        _feed(s, T10, 60)
        # Two register glitches: the plain mean would be about 1190 W.
        s._samples[100] = 65535.0
        s._samples[101] = 65535.0
        assert _close_hour(s) == {10: pytest.approx(650.0)}

    def test_a_short_real_load_still_counts(self):
        # A kettle: 3 min at +2 kW on a 300 W house.
        s = _sampler()
        _feed(s, T10, 60, pv=0.0, grid=300.0, net=0.0, devices=0.0)
        for i in range(12):
            s._samples[i] = 2300.0
        result = _close_hour(s)[10]
        assert 350 < result < 400

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

    def test_no_learning_without_pv_sensor(
            self, monkeypatch, hass, tmp_path, setup):
        setup = {**setup, "pv_power_entity": None}
        coord = _coordinator(monkeypatch, hass, tmp_path, setup)
        start = datetime(2026, 6, 15, 9, 0)
        _run_cycles(coord, start, start + timedelta(hours=2), 300)
        assert coord.budget._consumption_profile == [500] * 24
