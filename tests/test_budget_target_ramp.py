"""
Regression tests for the PV budget holding devices back on good days
(audit 2026-11-05, findings #18 and #19).

- The dynamic target SOC only ever lowers the user's target. A learned
  weather factor above 1 (it is clamped at 1.5) used to raise it, and a
  target below 50 % was lifted to the 50 % floor.
- The SOC day ramp aims at no more than 100 %.
- The day ramp anchors only once PV really produces. A night-time export
  blip (battery overshoot) used to anchor it at a night SOC, and the
  multiplier then held the budget at 0 W until about noon.
"""

from datetime import datetime

import pytest

from custom_components.aurum.modules import budget as budget_mod
from custom_components.aurum.modules.budget import BudgetManager

FC = "sensor.pv_remaining"
WEATHER = "weather.home"


@pytest.fixture
def clock(monkeypatch):
    """Freeze budget.py's wall clock (it reads datetime.now() directly)."""

    class _Clock(datetime):
        current = datetime(2026, 11, 16, 12, 0)

        @classmethod
        def now(cls, tz=None):
            return cls.current

    monkeypatch.setattr(budget_mod, "datetime", _Clock)
    return _Clock


def make_budget(hass, remaining_kwh=15, **cfg):
    config = {"pv_forecast_entity": FC, "target_soc": 80,
              "battery_capacity_wh": 10000}
    config.update(cfg)
    hass.states[FC] = str(remaining_kwh)
    return BudgetManager(hass, config)


def learn(bm, hass, condition, factor):
    """Give the weather entity a learned factor (past min observations)."""
    hass.states[WEATHER] = condition
    bm._weather_learned[condition] = factor
    bm._weather_observations[condition] = 50


def tick(bm, clock, at, soc, excess, pv=0):
    clock.current = at
    sh = {"now": at, "battery_soc": soc, "excess_for_devices": excess,
          "pv_power": pv}
    bm.update(sh)
    return sh


def day(h, m=0):
    return datetime(2026, 11, 16, h, m)


# ── (1) Dynamic target only lowers ───────────────────────────────


class TestDynamicTarget:
    @pytest.mark.parametrize("target, w, expected", [
        (100.0, 1.278, 100.0),   # learned "sunny" above 1: no raise
        (100.0, 1.5, 100.0),     # clamp of the weather learning
        (80.0, 1.3, 80.0),
        (100.0, 0.5, 85.0),      # bad weather still lowers
        (70.0, 0.2, 50.0),       # floor holds
        (40.0, 0.3, 40.0),       # floor never lifts a low target
        (40.0, 1.0, 40.0),
    ])
    def test_never_above_target(self, hass, target, w, expected):
        bm = make_budget(hass)
        assert bm._dynamic_target(target, w) == pytest.approx(expected)

    def test_disabled_returns_target(self, hass):
        bm = make_budget(hass, budget_dynamic_target=False)
        assert bm._dynamic_target(100.0, 0.3) == 100.0

    def test_sunny_learned_factor_keeps_user_target(self, hass, clock):
        """Target 80, learned sunny 1.3: the budget aimed at 89 %."""
        bm = make_budget(hass, weather_entity=WEATHER)
        learn(bm, hass, "sunny", 1.3)
        clock.current = day(10)
        _, info = bm._calculate_budget(60)
        assert info["effective_target_soc"] == 80.0
        assert info["energy_to_target_wh"] == 2000

    def test_target_below_floor_is_kept(self, hass, clock):
        """Target 40 at SOC 30 reserved 2 kWh (to 50 %) instead of 1 kWh."""
        bm = make_budget(hass, target_soc=40)
        clock.current = day(10)
        _, info = bm._calculate_budget(30)
        assert info["effective_target_soc"] == 40.0
        assert info["energy_to_target_wh"] == 1000

    def test_bad_weather_still_lowers_the_budget_target(self, hass, clock):
        bm = make_budget(hass, weather_entity=WEATHER)
        learn(bm, hass, "cloudy", 0.5)
        clock.current = day(10)
        _, info = bm._calculate_budget(60)
        assert info["effective_target_soc"] == 65.0


# ── (2) Ramp target capped at 100 % ──────────────────────────────


class TestRampTargetCap:
    def _anchored(self, bm):
        bm._trajectory_start_soc = 30.0
        bm._trajectory_start_time = day(8)

    def test_ramp_never_aims_above_100(self, hass, clock, monkeypatch):
        """Guard: whatever the target, the ramp compares against <= 100 %."""
        bm = make_budget(hass, target_soc=110, budget_dynamic_target=False)
        self._anchored(bm)
        seen = []
        real = bm._get_trajectory_multiplier

        def spy(soc, target, hours):
            seen.append(target)
            return real(soc, target, hours)

        monkeypatch.setattr(bm, "_get_trajectory_multiplier", spy)
        clock.current = day(15)
        _, info = bm._calculate_budget(72)
        assert seen == [100.0]
        # 08:00 30 % -> 19:00 100 %: 74.5 % expected at 15:00, 72 % is close.
        assert info["trajectory_multiplier"] > 0.7

    def test_sunny_day_budget_not_zeroed(self, hass, clock):
        """Target 100, learned sunny 1.5: the ramp aimed at 115 % and the
        multiplier clamped to 0 although the battery was nearly on track."""
        bm = make_budget(hass, remaining_kwh=8, target_soc=100,
                         weather_entity=WEATHER)
        learn(bm, hass, "sunny", 1.5)
        self._anchored(bm)
        clock.current = day(15)
        budget_w, info = bm._calculate_budget(72)
        assert info["effective_target_soc"] == 100.0
        assert info["trajectory_multiplier"] > 0.7
        assert budget_w > 500


# ── (3) Day ramp anchored only on real PV ────────────────────────


class TestRampAnchor:
    def test_night_export_blip_does_not_zero_the_morning(self, hass, clock):
        """Audit #18: grid-only surplus, 5 W export at 01:00 at SOC 41 %."""
        bm = make_budget(hass)
        hass.states["sun.sun"] = "below_horizon"
        tick(bm, clock, day(1), soc=41, excess=5)
        assert bm._trajectory_start_soc is None

        hass.states["sun.sun"] = "above_horizon"
        sh = tick(bm, clock, day(10), soc=35, excess=400)
        assert bm._trajectory_start_soc == 35
        assert bm._trajectory_start_time == day(10)
        assert sh["budget_info"]["trajectory_multiplier"] == 1.0
        assert sh["device_budget_w"] > 0

    def test_pv_sensor_decides(self, hass, clock):
        bm = make_budget(hass, pv_power_entity="sensor.pv")
        # The sun entity is ignored once a PV power sensor is configured.
        hass.states["sun.sun"] = "above_horizon"
        tick(bm, clock, day(1), soc=41, excess=5, pv=0)
        assert bm._trajectory_start_soc is None
        tick(bm, clock, day(7, 40), soc=38, excess=20, pv=60)  # dawn noise
        assert bm._trajectory_start_soc is None
        tick(bm, clock, day(8, 30), soc=37, excess=150, pv=800)
        assert bm._trajectory_start_soc == 37
        assert bm._trajectory_start_time == day(8, 30)

    def test_without_pv_sensor_the_forecast_slot_decides(
            self, hass, clock, monkeypatch):
        bm = make_budget(hass, pv_forecast_today_entity="sensor.pv_hourly")
        forecast = [(7.0, 0.0), (8.0, 350.0), (9.0, 900.0), (12.0, 2500.0),
                    (16.0, 120.0), (17.0, 0.0)]
        monkeypatch.setattr(bm, "_get_hourly_forecast", lambda: forecast)
        hass.states["sun.sun"] = "above_horizon"
        tick(bm, clock, day(1), soc=41, excess=5)
        assert bm._trajectory_start_soc is None
        tick(bm, clock, day(7, 30), soc=38, excess=10)   # slot 07:00: 0 W
        assert bm._trajectory_start_soc is None
        tick(bm, clock, day(8, 15), soc=37, excess=200)  # slot 08:00: 350 W
        assert bm._trajectory_start_soc == 37

    def test_no_daylight_signal_leaves_the_ramp_neutral(self, hass, clock):
        """No PV sensor, no hourly forecast, no sun entity: never anchor."""
        bm = make_budget(hass)
        sh = tick(bm, clock, day(12), soc=50, excess=500)
        assert bm._trajectory_start_soc is None
        assert sh["budget_info"]["trajectory_multiplier"] == 1.0

    def test_still_needs_excess(self, hass, clock):
        bm = make_budget(hass, pv_power_entity="sensor.pv")
        tick(bm, clock, day(9), soc=40, excess=-300, pv=1500)
        assert bm._trajectory_start_soc is None


class TestForecastSlot:
    def test_current_slot(self):
        fc = [(8.0, 50.0), (8.5, 300.0), (9.0, 700.0)]
        assert BudgetManager._forecast_w_now(fc, day(8, 10)) == 50.0
        assert BudgetManager._forecast_w_now(fc, day(8, 40)) == 300.0
        assert BudgetManager._forecast_w_now(fc, day(7, 59)) == 0.0

    def test_repeated_hours_from_several_days(self):
        fc = [(10.0, 80.0), (11.0, 400.0), (10.0, 900.0)]
        assert BudgetManager._forecast_w_now(fc, day(10, 30)) == 900.0
