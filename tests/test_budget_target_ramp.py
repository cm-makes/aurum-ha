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


def attrs(hass, entity_id):
    hass.attributes = getattr(hass, "attributes", {})
    return hass.attributes.setdefault(entity_id, {})


def sun(hass, state, elevation=None):
    """Set sun.sun; elevation None leaves the attribute out."""
    hass.states["sun.sun"] = state
    a = attrs(hass, "sun.sun")
    a.clear()
    if elevation is not None:
        a["elevation"] = elevation


PV_TODAY = "sensor.pv_today"


def pv_today(hass, kwh):
    hass.states[PV_TODAY] = str(kwh)
    attrs(hass, PV_TODAY)["unit_of_measurement"] = "kWh"


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
        sun(hass, "below_horizon", -40.0)
        tick(bm, clock, day(1), soc=41, excess=5)
        assert bm._trajectory_start_soc is None

        sun(hass, "above_horizon", 15.0)
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


class TestSunFallback:
    """No PV power sensor, no hourly forecast: sunrise alone is too early.

    PV still makes next to nothing in the first hour after sunrise, so a
    battery overshoot then anchored the ramp at a pre-production SOC. The
    sun must stand 10 degrees high, or the PV-today counter must have
    risen 0.05 kWh since midnight.
    """

    def test_november_sunrise_blip_does_not_anchor(self, hass, clock):
        """Review example: sunrise 07:45, export blip right at sunrise, the
        battery drains 41 -> 33 % until PV takes over at 09:00."""
        bm = make_budget(hass)
        for at, soc, excess, state, elevation in [
            (day(1), 48, 5, "below_horizon", -45.0),
            (day(7, 45), 41, 5, "above_horizon", 0.2),   # sunrise blip
            (day(8, 15), 39, 0, "above_horizon", 3.6),
            (day(8, 30), 36, 30, "above_horizon", 5.5),  # sun still low
        ]:
            sun(hass, state, elevation)
            tick(bm, clock, at, soc=soc, excess=excess)
            assert bm._trajectory_start_soc is None, at

        sun(hass, "above_horizon", 10.1)
        sh = tick(bm, clock, day(9), soc=33, excess=350)
        assert bm._trajectory_start_soc == 33
        assert bm._trajectory_start_time == day(9)
        assert sh["budget_info"]["trajectory_multiplier"] == 1.0
        assert sh["device_budget_w"] > 200

        # Anchored at the sunrise blip, the ramp expected the battery to
        # climb from 41 % since 07:45 and cut the same 09:00 budget hard.
        early = make_budget(hass)
        early._trajectory_start_soc = 41
        early._trajectory_start_time = day(7, 45)
        early_w, early_info = early._calculate_budget(33)
        assert early_info["trajectory_multiplier"] < 0.5
        assert early_w < sh["device_budget_w"] / 2

    @pytest.mark.parametrize("elevation", [None, "unknown"])
    def test_missing_elevation_is_no_daylight_signal(
            self, hass, clock, elevation):
        """Above the horizon but no usable elevation: no anchor, the ramp
        stays neutral instead of anchoring at sunrise."""
        bm = make_budget(hass)
        sun(hass, "above_horizon", elevation)
        sh = tick(bm, clock, day(12), soc=50, excess=500)
        assert bm._trajectory_start_soc is None
        assert sh["budget_info"]["trajectory_multiplier"] == 1.0

    def test_pv_counter_rise_anchors_while_the_sun_is_low(self, hass, clock):
        bm = make_budget(hass, pv_actual_today_entity=PV_TODAY)
        sun(hass, "above_horizon", 2.0)
        pv_today(hass, 0.0)
        tick(bm, clock, day(7, 50), soc=39, excess=10)
        assert bm._trajectory_start_soc is None
        sun(hass, "above_horizon", 4.0)
        pv_today(hass, 0.03)
        tick(bm, clock, day(8, 5), soc=38, excess=40)
        assert bm._trajectory_start_soc is None
        sun(hass, "above_horizon", 6.0)
        pv_today(hass, 0.06)
        tick(bm, clock, day(8, 20), soc=37, excess=150)
        assert bm._trajectory_start_soc == 37
        assert bm._trajectory_start_time == day(8, 20)

    def test_counter_holding_yesterday_does_not_count(self, hass, clock):
        """Many inverters show yesterday's daily yield until they wake up
        and reset in the morning. Only the rise from the lowest reading
        since midnight counts."""
        bm = make_budget(hass, pv_actual_today_entity=PV_TODAY)
        pv_today(hass, 12.4)
        sun(hass, "below_horizon", -45.0)
        tick(bm, clock, day(1), soc=48, excess=5)
        assert bm._trajectory_start_soc is None
        sun(hass, "above_horizon", 0.5)
        tick(bm, clock, day(7, 50), soc=41, excess=5)
        assert bm._trajectory_start_soc is None
        pv_today(hass, 0.0)                   # inverter wakes and resets
        sun(hass, "above_horizon", 1.5)
        tick(bm, clock, day(8), soc=40, excess=5)
        assert bm._trajectory_start_soc is None
        pv_today(hass, 0.07)
        sun(hass, "above_horizon", 4.0)
        tick(bm, clock, day(8, 25), soc=38, excess=120)
        assert bm._trajectory_start_soc == 38

    def test_counter_works_without_sun_entity(self, hass, clock):
        bm = make_budget(hass, pv_actual_today_entity=PV_TODAY)
        pv_today(hass, 12.4)                  # held overnight
        tick(bm, clock, day(1), soc=48, excess=5)
        assert bm._trajectory_start_soc is None
        pv_today(hass, 0.0)
        tick(bm, clock, day(8), soc=40, excess=5)
        assert bm._trajectory_start_soc is None
        pv_today(hass, 0.08)
        tick(bm, clock, day(8, 40), soc=38, excess=200)
        assert bm._trajectory_start_soc == 38

    def test_lifetime_counter(self, hass, clock):
        bm = make_budget(hass, pv_actual_today_entity=PV_TODAY)
        sun(hass, "above_horizon", 1.0)
        pv_today(hass, 8123.40)               # midnight snapshot -> 0 today
        tick(bm, clock, day(7, 50), soc=40, excess=10)
        pv_today(hass, 8123.43)
        tick(bm, clock, day(8, 5), soc=39, excess=40)
        assert bm._trajectory_start_soc is None
        pv_today(hass, 8123.47)
        tick(bm, clock, day(8, 20), soc=38, excess=150)
        assert bm._trajectory_start_soc == 38

    def test_below_horizon_vetoes_a_counter_glitch(self, hass, clock):
        bm = make_budget(hass, pv_actual_today_entity=PV_TODAY)
        sun(hass, "below_horizon", -40.0)
        pv_today(hass, 0.0)
        tick(bm, clock, day(0, 30), soc=50, excess=0)
        pv_today(hass, 0.3)
        tick(bm, clock, day(2), soc=47, excess=5)
        assert bm._trajectory_start_soc is None

    def test_daily_reset_clears_the_counter_baseline(self, hass, clock):
        bm = make_budget(hass, pv_actual_today_entity=PV_TODAY)
        pv_today(hass, 0.0)
        tick(bm, clock, day(6), soc=40, excess=0)
        pv_today(hass, 9.2)
        tick(bm, clock, day(18), soc=80, excess=0)
        bm.daily_reset()
        # Next night, no sun entity: yesterday's 9.2 kWh is still shown.
        tick(bm, clock, datetime(2026, 11, 17, 1, 0), soc=60, excess=5)
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


class TestAnchorFromOlderVersion:
    """An anchor saved by 1.16.3 (any export after midnight) must not
    survive the update restart: it would keep the budget at 0 W for the
    rest of the update day."""

    def test_old_anchor_is_dropped_on_restore(self, hass, clock):
        bm = make_budget(hass)
        bm.restore_state({"trajectory_start_soc": 60.0,
                          "trajectory_start_time": "2026-11-16T02:00:00"})
        assert bm._trajectory_start_soc is None
        assert bm._trajectory_start_time is None

    def test_new_anchor_survives_a_restart(self, hass, clock):
        bm = make_budget(hass)
        bm._trajectory_start_soc = 35.0
        bm._trajectory_start_time = datetime(2026, 11, 16, 9, 30)
        again = make_budget(hass)
        again.restore_state(bm.get_state_for_save())
        assert again._trajectory_start_soc == 35.0
        assert again._trajectory_start_time == datetime(2026, 11, 16, 9, 30)
