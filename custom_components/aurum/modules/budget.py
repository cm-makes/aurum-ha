"""
AURUM – Budget Manager
=======================
PV surplus budget: determines how much power can be used for managed devices
while still reaching the target battery SOC by end of solar production.

1:1 port of HELIOS BudgetManager (budget.py), adapted for AURUM:
- Output: shared["device_budget_w"] instead of shared["heating_budget_w"]
- Logging via _LOGGER (Python logging) instead of hass.log()
- HA service calls use hass.services.call() instead of hass.call_service()
- Module docstring and naming adapted for AURUM context

Core algorithm unchanged (multiplicative correction chain):
  usable_pv = forecast * weather_factor * safety_factor * inday_correction
  budget_w  = (usable_pv - energy_to_target - consumption) / hours
  budget_w *= trajectory_multiplier

Budget states:
  > 0   : devices allowed up to this wattage total
  = 0   : no budget
  None  : feature disabled or data unavailable (no restriction)

Source: HELIOS BudgetManager (v1.3.2) -> 1:1 port
"""

import logging
from datetime import datetime

from .helpers import get_float

_LOGGER = logging.getLogger(__name__)


class BudgetManager:
    """PV surplus budget based on forecast and SOC trajectory.

    Multiplicative correction chain:
      usable_pv = forecast * weather_factor * safety_factor * inday_correction
      budget_w  = (usable_pv - energy_to_target - consumption) / hours
      budget_w *= trajectory_multiplier

    Budget states:
      > 0   : devices allowed up to this wattage total
      = 0   : no budget, only pure-grid excess
      None  : feature disabled / data unavailable (no restriction)
    """

    def __init__(self, hass, config):
        self.hass = hass
        self._number_values = None  # set by coordinator

        # ── Entity IDs ──────────────────────────────────────────────
        self.target_soc_entity = config.get("target_soc_entity")
        self.battery_soc_entity = config.get(
            "battery_soc_entity",
            config.get("combined_soc_entity", "sensor.batterie_soc_gesamt"))
        self.pv_forecast_entity = config.get(
            "pv_forecast_entity",
            "sensor.solcast_pv_forecast_prognose_verbleibende_leistung_heute")
        self.pv_forecast_today_entity = config.get(
            "pv_forecast_today_entity",
            "sensor.solcast_pv_forecast_prognose_heute")
        self.pv_actual_today_entity = config.get(
            "pv_actual_today_entity",
            "sensor.evcc_pv_energy")
        self.dwd_weather_entity = config.get(
            "dwd_weather_entity",
            "weather.openweathermap")
        self.safety_factor_entity = config.get("safety_factor_entity")

        # ── Capacity / consumption ──────────────────────────────────
        self.battery_capacity_wh = config.get("battery_capacity_wh", 10960)
        self.avg_consumption_w = config.get("avg_consumption_w", 500)

        # ── Safety factor ───────────────────────────────────────────
        self.budget_safety_factor = config.get("budget_safety_factor", 0.7)
        self.budget_safety_step_up = config.get(
            "budget_safety_step_up",
            config.get("budget_safety_step", 0.10))
        self.budget_safety_step_down = config.get(
            "budget_safety_step_down",
            config.get("budget_safety_step", 0.03))
        self.budget_safety_min = config.get("budget_safety_min", 0.55)
        self.budget_safety_max = config.get("budget_safety_max", 1.0)

        # ── Budget combined floor (prevents over-restriction in bad weather)
        self.budget_combined_floor = config.get("budget_combined_floor", 0.85)

        # ── Dynamic target SOC (lower target in bad weather) ────────
        self.budget_dynamic_target = config.get("budget_dynamic_target", True)
        self.budget_dynamic_target_max_reduction = config.get(
            "budget_dynamic_target_max_reduction", 30)
        self.budget_dynamic_target_min = config.get(
            "budget_dynamic_target_min", 50)

        # ── Grid export override ────────────────────────────────────
        self.grid_export_override_w = config.get("grid_export_override_w", 50)

        # ── Residual power ──────────────────────────────────────────
        self.residual_power = config.get("residual_power", 100)

        # ── SOC trajectory tracking ─────────────────────────────────
        self.trajectory_band = config.get("trajectory_band", 5)
        self._trajectory_start_soc = None
        self._trajectory_start_time = None

        # ── PV total midnight snapshot (for daily calc) ─────────────
        self._pv_total_midnight = None

        # ── Weather factor EMA ──────────────────────────────────────
        self._weather_factor_ema = None

        # ── Adaptive consumption profile (hourly EMA) ───────────────
        self._consumption_profile = [self.avg_consumption_w] * 24
        self._consumption_samples = [0] * 24
        self._consumption_ema_alpha = config.get("consumption_ema_alpha", 0.3)
        self._consumption_min_samples = config.get("consumption_min_samples", 3)

        # ── Learned weather factor (per-condition EMA) ───────────────
        self._weather_learned = {
            "sunny": 1.0, "clear-night": 1.0,
            "partlycloudy": 0.8, "cloudy": 0.5,
            "fog": 0.4, "rainy": 0.3, "pouring": 0.2,
            "snowy": 0.2, "snowy-rainy": 0.25,
            "hail": 0.2, "lightning": 0.3,
            "lightning-rainy": 0.25, "windy": 0.9,
            "windy-variant": 0.7, "exceptional": 0.5,
        }
        self._weather_observations = {}
        self._weather_learn_alpha = config.get("weather_learn_alpha", 0.2)
        self._weather_learn_min_obs = config.get("weather_learn_min_obs", 5)

        # ── Bayesian safety factor (Beta-Binomial) ───────────────────
        self.bayesian_safety = config.get("bayesian_safety", False)
        self._sf_alpha = config.get("sf_beta_alpha", 7.0)
        self._sf_beta = config.get("sf_beta_beta", 3.0)
        self._sf_decay = config.get("sf_beta_decay", 0.95)

        # ── Cycle counter (for periodic logging) ────────────────────
        self._cycle_count = 0

    # ══════════════════════════════════════════════════════════════
    #  MAIN UPDATE
    # ══════════════════════════════════════════════════════════════

    def update(self, shared):
        """Calculate device budget and fill shared state.

        Called every cycle by coordinator. Reads battery_soc from shared.
        Fills: device_budget_w, budget_info, safety_factor,
               pv_forecast_remaining_kwh, hours_until_sunset,
               hourly_forecast, weather_factor, outdoor_temp,
               pv_actual_today_kwh

        1:1 port of HELIOS BudgetManager.update() with output key renamed:
        heating_budget_w -> device_budget_w
        """
        self._cycle_count += 1
        now = shared.get("now", datetime.now())

        battery_soc = shared.get("battery_soc",
                                 shared.get("combined_soc"))
        if battery_soc is None:
            battery_soc = get_float(
                self.hass, self.battery_soc_entity, default=None)

        # ── Read supporting data for shared state ──────────────────
        outdoor_temp = self._get_outdoor_temp()
        weather_factor = self._get_smoothed_weather_factor()
        hours_remaining = self._hours_until_sunset()
        hourly_forecast = self._get_hourly_forecast()
        pv_actual_kwh = self._get_pv_today_kwh()

        remaining_kwh = get_float(
            self.hass, self.pv_forecast_entity, default=None)

        # Fill shared state (always, even if budget disabled)
        shared["weather_factor"] = weather_factor
        shared["outdoor_temp"] = outdoor_temp
        shared["hours_until_sunset"] = hours_remaining
        shared["hourly_forecast"] = hourly_forecast
        shared["pv_actual_today_kwh"] = pv_actual_kwh
        shared["pv_forecast_remaining_kwh"] = remaining_kwh
        shared["safety_factor"] = round(self.budget_safety_factor, 2)

        # ── SOC trajectory start detection ─────────────────────────
        excess = shared.get("excess_for_devices", 0)
        if (self._trajectory_start_soc is None
                and excess > 0 and self.target_soc_entity
                and battery_soc is not None):
            self._trajectory_start_soc = battery_soc
            self._trajectory_start_time = now
            _LOGGER.debug(
                "AURUM Budget: trajectory start SOC=%.1f%% at %s",
                battery_soc, now.strftime("%H:%M"))

        # ── Calculate budget ────────────────────────────────────────
        budget_w, info = self._calculate_budget(battery_soc)

        shared["device_budget_w"] = budget_w
        shared["budget_info"] = info

        # Cache for odd-cycle reads
        self.last_budget_w = budget_w
        self.last_info = info

    def _calculate_budget(self, battery_soc):
        """Core budget calculation.

        Returns (budget_w, info_dict) where budget_w is:
          > 0   : devices allowed up to this wattage total
          = 0   : no budget, only grid-only excess
          None  : feature disabled or data unavailable (no restriction)

        1:1 port of HELIOS BudgetManager._calculate_budget()
        """
        if (not self.target_soc_entity
                and not (self._number_values
                         and "target_soc" in self._number_values)):
            return None, {}

        target_soc = self._get_target_soc()
        if target_soc is None:
            return None, {}

        if battery_soc is None:
            return None, {}

        info = {
            "target_soc": target_soc,
            "current_soc": round(battery_soc, 1),
            "safety_factor": round(self.budget_safety_factor, 2),
        }

        # Already at or above target -> unlimited devices
        if battery_soc >= target_soc:
            info["reason"] = "soc_above_target"
            return None, info

        # Get remaining PV forecast
        remaining_kwh = get_float(
            self.hass, self.pv_forecast_entity, default=None)
        if remaining_kwh is None:
            info["reason"] = "no_forecast"
            return None, info

        remaining_wh = remaining_kwh * 1000

        # ── Multiplicative correction chain ────────────────────────
        weather_factor = self._get_smoothed_weather_factor()
        inday_correction = self._get_inday_correction()
        combined = (weather_factor
                    * self.budget_safety_factor
                    * inday_correction)
        combined = max(self.budget_combined_floor, combined)
        usable_wh = remaining_wh * combined

        # Dynamic target SOC: lower target in bad weather
        effective_target = target_soc
        if self.budget_dynamic_target:
            reduction = ((1.0 - weather_factor)
                         * self.budget_dynamic_target_max_reduction)
            effective_target = max(
                self.budget_dynamic_target_min,
                target_soc - reduction)

        # Energy needed to reach target SOC
        energy_to_target = (max(0, effective_target - battery_soc) / 100
                            * self.battery_capacity_wh)

        # Hours until end of solar production
        hours_remaining = self._hours_until_sunset()
        if hours_remaining <= 0:
            info["reason"] = "after_sunset"
            return 0, info

        # Estimated household consumption
        consumption_wh = self._estimate_consumption_wh(hours_remaining)

        # Calculate base budget
        budget_wh = usable_wh - energy_to_target - consumption_wh
        budget_w = budget_wh / hours_remaining if hours_remaining > 0 else 0

        # ── SOC trajectory multiplier ───────────────────────────────
        trajectory_mult = self._get_trajectory_multiplier(
            battery_soc, effective_target, hours_remaining)
        budget_w_adjusted = budget_w * trajectory_mult

        info.update({
            "remaining_pv_wh": round(remaining_wh, 0),
            "weather_factor": weather_factor,
            "inday_correction": round(inday_correction, 2),
            "combined_factor": round(combined, 2),
            "effective_target_soc": round(effective_target, 1),
            "usable_pv_wh": round(usable_wh, 0),
            "energy_to_target_wh": round(energy_to_target, 0),
            "consumption_wh": round(consumption_wh, 0),
            "budget_wh": round(budget_wh, 0),
            "budget_w_raw": round(budget_w, 0),
            "trajectory_multiplier": round(trajectory_mult, 2),
            "budget_w": round(budget_w_adjusted, 0),
            "hours_remaining": round(hours_remaining, 1),
            "reason": ("budget_ok" if budget_w_adjusted > 0
                       else "budget_exhausted"),
        })

        # Periodic budget logging (every ~5min at 30s interval)
        if self._cycle_count % 10 == 0:
            _LOGGER.debug(
                "AURUM BUDGET: target=%.0f%% SOC=%.0f%% | "
                "PV=%.0fWh x%.2f (w=%.2f s=%.2f i=%.2f floor=%s)"
                "=%.0fWh | need: SOC=%.0fWh + cons=%.0fWh | "
                "budget=%.0fWh -> %.0fW (x%.2f traj)",
                effective_target, battery_soc,
                remaining_wh, combined,
                weather_factor, self.budget_safety_factor, inday_correction,
                self.budget_combined_floor,
                usable_wh, energy_to_target, consumption_wh,
                budget_wh, budget_w_adjusted, trajectory_mult)

        return max(0, budget_w_adjusted), info

    # ══════════════════════════════════════════════════════════════
    #  WEATHER FACTOR
    # ══════════════════════════════════════════════════════════════

    def _get_weather_factor(self):
        """Get PV forecast correction factor from weather condition.

        Maps HA weather conditions to PV correction factor.
        1:1 port of HELIOS BudgetManager._get_weather_factor()
        """
        if not self.dwd_weather_entity:
            return 1.0

        condition = self.hass.get_state(self.dwd_weather_entity)
        if not condition or condition in ("unavailable", "unknown"):
            return 1.0

        factors = {
            "sunny": 1.0,
            "clear-night": 1.0,
            "partlycloudy": 0.8,
            "cloudy": 0.5,
            "fog": 0.4,
            "rainy": 0.3,
            "pouring": 0.2,
            "snowy": 0.2,
            "snowy-rainy": 0.25,
            "hail": 0.2,
            "lightning": 0.3,
            "lightning-rainy": 0.25,
            "windy": 0.9,
            "windy-variant": 0.7,
            "exceptional": 0.5,
        }
        obs_count = self._weather_observations.get(condition, 0)
        if obs_count >= self._weather_learn_min_obs:
            return self._weather_learned.get(
                condition, factors.get(condition, 0.7))
        return factors.get(condition, 0.7)

    def _get_current_condition(self):
        """Read current weather condition string."""
        if not self.dwd_weather_entity:
            return None
        condition = self.hass.get_state(self.dwd_weather_entity)
        if not condition or condition in ("unavailable", "unknown"):
            return None
        return condition

    def _get_target_soc(self):
        """Read target SOC: number_values first, fallback to entity."""
        if self._number_values and "target_soc" in self._number_values:
            return float(self._number_values["target_soc"])
        return get_float(self.hass, self.target_soc_entity, default=None)

    def _get_smoothed_weather_factor(self):
        """EMA-smoothed weather factor to prevent budget jumps.

        alpha=0.1 -> ~10 cycles (5min) for 63% adaptation.
        1:1 port of HELIOS BudgetManager._get_smoothed_weather_factor()
        """
        raw = self._get_weather_factor()
        if self._weather_factor_ema is None:
            self._weather_factor_ema = raw
            return raw
        alpha = 0.1
        self._weather_factor_ema = (alpha * raw
                                    + (1 - alpha) * self._weather_factor_ema)
        return self._weather_factor_ema

    # ══════════════════════════════════════════════════════════════
    #  ADAPTIVE CONSUMPTION PROFILE
    # ══════════════════════════════════════════════════════════════

    def _estimate_consumption_wh(self, hours_remaining):
        """Estimate consumption in Wh for remaining solar hours.

        Uses hourly consumption profile if calibrated, otherwise
        falls back to avg_consumption_w.
        1:1 port of HELIOS BudgetManager._estimate_consumption_wh()
        """
        now = datetime.now()
        current_hour = now.hour
        current_frac = now.minute / 60.0

        total_wh = 0.0
        remaining = hours_remaining

        # First partial hour
        if remaining > 0:
            h = current_hour
            frac = min(remaining, 1.0 - current_frac)
            total_wh += self._consumption_profile[h % 24] * frac
            remaining -= frac

        # Full hours
        h = current_hour + 1
        while remaining >= 1.0:
            total_wh += self._consumption_profile[h % 24]
            remaining -= 1.0
            h += 1

        # Last partial hour
        if remaining > 0:
            total_wh += self._consumption_profile[h % 24] * remaining

        return total_wh

    def update_consumption_profile(self, shared):
        """Update hourly consumption profile from today's data.

        Call daily (e.g. 23:55). Reads hourly averages from shared.
        1:1 port of HELIOS BudgetManager.update_consumption_profile()
        """
        hourly_data = shared.get("hourly_consumption_w")
        if not hourly_data:
            return

        updated = []
        alpha = self._consumption_ema_alpha
        min_s = self._consumption_min_samples

        for hour_str, avg_w in hourly_data.items():
            try:
                h = int(hour_str)
                if not (0 <= h <= 23) or avg_w is None:
                    continue
                avg_w = float(avg_w)
                if avg_w < 0:
                    continue

                self._consumption_samples[h] += 1
                if self._consumption_samples[h] >= min_s:
                    self._consumption_profile[h] = (
                        alpha * avg_w
                        + (1 - alpha) * self._consumption_profile[h])
                    updated.append(h)
            except (ValueError, TypeError):
                continue

        if updated:
            _LOGGER.debug(
                "AURUM Budget: consumption profile updated for hours %s, "
                "range %.0f-%.0fW",
                sorted(updated),
                min(self._consumption_profile),
                max(self._consumption_profile))

    # ══════════════════════════════════════════════════════════════
    #  LEARNED WEATHER FACTOR
    # ══════════════════════════════════════════════════════════════

    def update_weather_learning(self, shared):
        """Update weather factor learning from PV actual vs forecast.

        Call hourly during daytime.
        1:1 port of HELIOS BudgetManager.update_weather_learning()
        """
        condition = self._get_current_condition()
        if not condition:
            return

        actual_kwh = shared.get("pv_actual_hour_kwh")
        forecast_kwh = shared.get("pv_forecast_hour_kwh")

        if (actual_kwh is None or forecast_kwh is None
                or forecast_kwh < 0.05):
            return

        try:
            ratio = float(actual_kwh) / float(forecast_kwh)
            ratio = max(0.1, min(1.5, ratio))

            count = self._weather_observations.get(condition, 0) + 1
            self._weather_observations[condition] = count

            if count >= self._weather_learn_min_obs:
                alpha = self._weather_learn_alpha
                old = self._weather_learned.get(condition, 0.7)
                new_val = alpha * ratio + (1 - alpha) * old
                self._weather_learned[condition] = round(new_val, 3)
                _LOGGER.debug(
                    "AURUM Budget: weather learning %s ratio=%.2f "
                    "-> factor=%.3f (%d obs)",
                    condition, ratio, new_val, count)
        except (ValueError, TypeError, ZeroDivisionError):
            pass

    # ══════════════════════════════════════════════════════════════
    #  PV FORECAST / SUNSET
    # ══════════════════════════════════════════════════════════════

    def _hours_until_sunset(self):
        """Calculate hours until end of PV production from forecast.

        1:1 port of HELIOS BudgetManager._hours_until_sunset()
        """
        forecast = self._get_hourly_forecast()
        if not forecast:
            return 0

        now = datetime.now()
        current_hour = now.hour + now.minute / 60.0

        last_production_hour = current_hour
        for hour, watts in forecast:
            if watts > 50 and hour > current_hour:
                last_production_hour = hour

        return max(0, last_production_hour - current_hour)

    def _get_pv_today_kwh(self):
        """Get today's PV production in kWh.

        Supports daily-reset sensors and total/lifetime counters.
        Auto-detects Wh vs kWh from unit_of_measurement.
        1:1 port of HELIOS BudgetManager._get_pv_today_kwh()
        """
        if not self.pv_actual_today_entity:
            return None

        raw = get_float(self.hass, self.pv_actual_today_entity, default=None)
        if raw is None:
            return None

        unit = self.hass.get_state(
            self.pv_actual_today_entity, attribute="unit_of_measurement")
        is_wh = (unit == "Wh" or (unit is None and raw > 500))

        if self._pv_total_midnight is not None:
            daily_val = raw - self._pv_total_midnight
            if daily_val < 0:
                self._pv_total_midnight = raw
                daily_val = 0
            return (daily_val / 1000.0) if is_wh else daily_val
        else:
            if (is_wh and raw > 100_000) or (not is_wh and raw > 100):
                self._pv_total_midnight = raw
                _LOGGER.debug(
                    "AURUM Budget: PV total counter detected: %.0f %s – "
                    "midnight snapshot saved",
                    raw, "Wh" if is_wh else "kWh")
                return 0.0
            else:
                return (raw / 1000.0) if is_wh else raw

    def _get_inday_correction(self):
        """Compare actual PV production today vs forecast prediction.

        If morning production was only 60% of predicted, the remaining
        forecast is corrected by 0.6. Clamped to [0.3, 1.5].
        1:1 port of HELIOS BudgetManager._get_inday_correction()
        """
        if not self.pv_actual_today_entity:
            return 1.0
        if not self.pv_forecast_today_entity:
            return 1.0

        actual_kwh = self._get_pv_today_kwh()
        if actual_kwh is None or actual_kwh < 0.1:
            return 1.0

        total_forecast_kwh = get_float(
            self.hass, self.pv_forecast_today_entity, default=None)
        remaining_kwh = get_float(
            self.hass, self.pv_forecast_entity, default=None)
        if total_forecast_kwh is None or remaining_kwh is None:
            return 1.0

        predicted_so_far_kwh = total_forecast_kwh - remaining_kwh
        if predicted_so_far_kwh < 0.1:
            return 1.0

        correction = actual_kwh / predicted_so_far_kwh
        return max(0.3, min(1.5, correction))

    # ══════════════════════════════════════════════════════════════
    #  SOC TRAJECTORY
    # ══════════════════════════════════════════════════════════════

    def _get_trajectory_multiplier(self, battery_soc, target_soc,
                                   hours_remaining):
        """Compare actual SOC vs expected linear ramp.

        Returns multiplier 0.0-2.0:
          Ahead of schedule -> >1.0 (allow more devices)
          Behind schedule   -> <1.0 (restrict devices)

        1:1 port of HELIOS BudgetManager._get_trajectory_multiplier()
        """
        if (self._trajectory_start_soc is None
                or self._trajectory_start_time is None):
            return 1.0

        now = datetime.now()
        total_hours = self._hours_until_sunset()
        elapsed = (now - self._trajectory_start_time).total_seconds() / 3600

        if total_hours <= 0 or elapsed <= 0:
            return 1.0

        total_window = elapsed + hours_remaining
        if total_window <= 0:
            return 1.0

        progress = elapsed / total_window
        expected_soc = (self._trajectory_start_soc
                        + (target_soc - self._trajectory_start_soc)
                        * progress)

        deviation = battery_soc - expected_soc  # positive = ahead

        band = self.trajectory_band if self.trajectory_band > 0 else 5
        adjustment = (deviation / band) * 0.5
        multiplier = max(0.0, min(2.0, 1.0 + adjustment))

        return multiplier

    # ══════════════════════════════════════════════════════════════
    #  ADAPTIVE SAFETY FACTOR (daily at 17:00)
    # ══════════════════════════════════════════════════════════════

    def adapt_safety_factor(self, shared):
        """Daily evaluation: did we reach target SOC?

        Supports two modes:
        1. Bayesian (Beta-Binomial): posterior mean = safety factor.
        2. Classic: asymmetric step-up/step-down.

        Public method, called daily at 17:00 by coordinator.
        1:1 port of HELIOS BudgetManager.adapt_safety_factor()
        """
        if not self.target_soc_entity:
            return

        current_soc = get_float(
            self.hass, self.battery_soc_entity, default=None)
        target_soc = self._get_target_soc()
        if current_soc is None or target_soc is None:
            return

        old_factor = self.budget_safety_factor
        success = current_soc >= target_soc

        if self.bayesian_safety:
            self._sf_alpha *= self._sf_decay
            self._sf_beta *= self._sf_decay

            if success:
                self._sf_alpha += 1
            else:
                self._sf_beta += 1

            posterior_mean = self._sf_alpha / (
                self._sf_alpha + self._sf_beta)
            self.budget_safety_factor = max(
                self.budget_safety_min,
                min(self.budget_safety_max, posterior_mean))

            _LOGGER.info(
                "AURUM Budget safety factor [Bayesian]: %.2f -> %.2f "
                "(%s: SOC=%.0f%% vs target=%.0f%%) "
                "alpha=%.1f beta=%.1f",
                old_factor, self.budget_safety_factor,
                "SUCCESS" if success else "MISS",
                current_soc, target_soc,
                self._sf_alpha, self._sf_beta)
        else:
            if success:
                self.budget_safety_factor = min(
                    self.budget_safety_max,
                    self.budget_safety_factor
                    + self.budget_safety_step_up)
                _LOGGER.info(
                    "AURUM Budget safety factor +%.2f -> %.2f "
                    "(target reached: SOC=%.0f%% >= %.0f%%)",
                    self.budget_safety_step_up,
                    self.budget_safety_factor,
                    current_soc, target_soc)
            else:
                self.budget_safety_factor = max(
                    self.budget_safety_min,
                    self.budget_safety_factor
                    - self.budget_safety_step_down)
                _LOGGER.info(
                    "AURUM Budget safety factor -%.2f -> %.2f "
                    "(target missed: SOC=%.0f%% < %.0f%%)",
                    self.budget_safety_step_down,
                    self.budget_safety_factor,
                    current_soc, target_soc)

        # Sync to input_number if configured
        if self.safety_factor_entity:
            try:
                self.hass.call_service(
                    "input_number/set_value",
                    entity_id=self.safety_factor_entity,
                    value=round(self.budget_safety_factor, 2))
            except Exception as e:
                _LOGGER.warning(
                    "AURUM Budget: could not update %s: %s",
                    self.safety_factor_entity, e)

    # ══════════════════════════════════════════════════════════════
    #  HOURLY FORECAST
    # ══════════════════════════════════════════════════════════════

    def _get_hourly_forecast(self):
        """Read PV forecast as list of (hour_float, watts).

        Supports Open-Meteo (watts/wh_period attributes) and
        Solcast (forecast attribute) formats.
        1:1 port of HELIOS BudgetManager._get_hourly_forecast()
        """
        entity = self.pv_forecast_today_entity
        if not entity:
            return None
        try:
            full_state = self.hass.get_state(entity, attribute="all")
            if not full_state:
                return None
            attrs = full_state.get("attributes", {})

            # ── Option 1: Open-Meteo "watts" attribute ──────────────
            watts_data = attrs.get("watts")
            if watts_data and isinstance(watts_data, dict):
                hourly = {}
                for ts_str, watts_val in watts_data.items():
                    try:
                        dt = datetime.fromisoformat(str(ts_str))
                        hour = dt.hour
                        if hour not in hourly:
                            hourly[hour] = []
                        hourly[hour].append(float(watts_val))
                    except (ValueError, TypeError):
                        continue
                if hourly:
                    forecast = []
                    for hour in sorted(hourly.keys()):
                        avg_watts = sum(hourly[hour]) / len(hourly[hour])
                        forecast.append((float(hour), avg_watts))
                    return forecast if forecast else None

            # ── Option 2: Open-Meteo "wh_period" attribute ──────────
            wh_data = attrs.get("wh_period")
            if wh_data and isinstance(wh_data, dict):
                forecast = []
                for ts_str, wh_val in wh_data.items():
                    try:
                        dt = datetime.fromisoformat(str(ts_str))
                        hour = dt.hour + dt.minute / 60.0
                        forecast.append((hour, float(wh_val)))
                    except (ValueError, TypeError):
                        continue
                return forecast if forecast else None

            # ── Option 3: Solcast "forecast" attribute ───────────────
            forecast_data = None
            for attr_name in ("forecast", "detailedForecast",
                              "detailedHourly"):
                if attr_name in attrs:
                    forecast_data = attrs[attr_name]
                    break

            if forecast_data and isinstance(forecast_data, list):
                forecast = []
                for entry in forecast_data:
                    if "period_start" not in entry:
                        continue
                    try:
                        dt = datetime.fromisoformat(
                            str(entry["period_start"]))
                        hour = dt.hour + dt.minute / 60.0
                        watts = float(
                            entry.get("pv_estimate", 0)) * 1000
                        forecast.append((hour, watts))
                    except (ValueError, TypeError, KeyError):
                        continue
                return forecast if forecast else None

            return None
        except Exception:
            return None

    # ══════════════════════════════════════════════════════════════
    #  OUTDOOR TEMPERATURE
    # ══════════════════════════════════════════════════════════════

    def _get_outdoor_temp(self):
        """Read outdoor temperature from weather entity.

        1:1 port of HELIOS BudgetManager._get_outdoor_temp()
        """
        if not self.dwd_weather_entity:
            return None
        try:
            full_state = self.hass.get_state(
                self.dwd_weather_entity, attribute="all")
            if not full_state:
                return None
            attrs = full_state.get("attributes", {})
            val = attrs.get("temperature")
            if val in (None, "unavailable", "unknown", ""):
                return None
            return float(val)
        except (ValueError, TypeError):
            return None

    # ══════════════════════════════════════════════════════════════
    #  DAILY RESET
    # ══════════════════════════════════════════════════════════════

    def daily_reset(self):
        """Reset trajectory tracking at midnight.

        Called by coordinator in its daily_reset callback.
        1:1 port of HELIOS BudgetManager.daily_reset()
        """
        self._trajectory_start_soc = None
        self._trajectory_start_time = None
        self._pv_total_midnight = None
        self._weather_factor_ema = None

    # ══════════════════════════════════════════════════════════════
    #  STATE PERSISTENCE
    # ══════════════════════════════════════════════════════════════

    def get_state_for_save(self):
        """Return dict of state that should be persisted.

        1:1 port of HELIOS BudgetManager.get_state_for_save()
        """
        return {
            "budget_safety_factor": self.budget_safety_factor,
            "trajectory_start_soc": self._trajectory_start_soc,
            "trajectory_start_time": (
                self._trajectory_start_time.isoformat()
                if self._trajectory_start_time else None),
            "pv_total_midnight": self._pv_total_midnight,
            "consumption_profile": self._consumption_profile,
            "consumption_samples": self._consumption_samples,
            "weather_learned": self._weather_learned,
            "weather_observations": self._weather_observations,
            "sf_alpha": self._sf_alpha,
            "sf_beta": self._sf_beta,
        }

    def restore_state(self, saved):
        """Restore state from persistence dict.

        Prefers input_number entity over saved JSON value for safety factor.
        1:1 port of HELIOS BudgetManager.restore_state()
        """
        if not saved:
            return

        sf_restored = False
        if self.safety_factor_entity:
            ha_sf = get_float(
                self.hass, self.safety_factor_entity, default=None)
            if ha_sf is not None:
                self.budget_safety_factor = ha_sf
                _LOGGER.info(
                    "AURUM Budget: safety factor from HA entity: %.2f",
                    self.budget_safety_factor)
                sf_restored = True
        if not sf_restored:
            saved_factor = saved.get("budget_safety_factor")
            if saved_factor is not None:
                self.budget_safety_factor = float(saved_factor)
                _LOGGER.info(
                    "AURUM Budget: safety factor restored from state: %.2f",
                    self.budget_safety_factor)

        traj_soc = saved.get("trajectory_start_soc")
        traj_time = saved.get("trajectory_start_time")
        if traj_soc is not None and traj_time is not None:
            self._trajectory_start_soc = float(traj_soc)
            try:
                self._trajectory_start_time = datetime.fromisoformat(
                    traj_time)
            except (ValueError, TypeError):
                self._trajectory_start_time = None

        pv_mid = saved.get("pv_total_midnight")
        if pv_mid is not None:
            self._pv_total_midnight = float(pv_mid)
            _LOGGER.debug(
                "AURUM Budget: PV midnight snapshot restored: %.0f",
                self._pv_total_midnight)

        cp = saved.get("consumption_profile")
        if cp and isinstance(cp, list) and len(cp) == 24:
            self._consumption_profile = [float(v) for v in cp]
            _LOGGER.debug(
                "AURUM Budget: consumption profile restored: %.0f-%.0fW",
                min(self._consumption_profile),
                max(self._consumption_profile))
        cs = saved.get("consumption_samples")
        if cs and isinstance(cs, list) and len(cs) == 24:
            self._consumption_samples = [int(v) for v in cs]

        wl = saved.get("weather_learned")
        if wl and isinstance(wl, dict):
            self._weather_learned.update(wl)
            _LOGGER.debug(
                "AURUM Budget: weather learning restored: %d conditions",
                len(wl))
        wo = saved.get("weather_observations")
        if wo and isinstance(wo, dict):
            self._weather_observations = {
                k: int(v) for k, v in wo.items()}

        sf_a = saved.get("sf_alpha")
        sf_b = saved.get("sf_beta")
        if sf_a is not None and sf_b is not None:
            self._sf_alpha = float(sf_a)
            self._sf_beta = float(sf_b)
            if self.bayesian_safety:
                _LOGGER.debug(
                    "AURUM Budget: Bayesian SF restored: "
                    "alpha=%.1f beta=%.1f",
                    self._sf_alpha, self._sf_beta)
