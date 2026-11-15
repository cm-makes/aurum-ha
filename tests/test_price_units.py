"""
Price sensors in a whole currency unit per kWh (or per MWh).

AURUM compares prices in ct/kWh: the hundredth of the currency (cent,
Rappen, öre, pence). Up to 1.16.2 only EUR/kWh and €/kWh were scaled, so a
Swiss price sensor in CHF/kWh (Innostrom, discussion #35) read 0.28 as
0.28 Rappen: with a max_price of 20 every price looked cheap and a
cheap-grid device ran on grid around the clock. Nord Pool and Tibber in
SEK/NOK/DKK had the same problem, and a price per MWh looked 10x too dear.
"""

from datetime import datetime, timedelta

import pytest

from custom_components.aurum.const import MODE_NORMAL
from custom_components.aurum.modules.helpers import get_price_ct
from custom_components.aurum.modules.pricing import PricingManager

PRICE = "sensor.strompreis"
SW = "switch.test_device"
NIGHT = datetime(2026, 11, 15, 23, 0, 0)


def _set_price(hass, value, unit):
    hass.states[PRICE] = value
    hass.attributes = getattr(hass, "attributes", {})
    hass.attributes[PRICE] = (
        {} if unit is None else {"unit_of_measurement": unit})


@pytest.mark.parametrize(("value", "unit", "expected"), [
    # whole currency per kWh -> x100
    ("0.28", "EUR/kWh", 28),
    ("0.28", "€/kWh", 28),
    ("0.28", "CHF/kWh", 28),       # Innostrom
    ("0.28", "CHF / kWh", 28),
    ("0.28", "chf/kwh", 28),
    ("1.25", "SEK/kWh", 125),      # Nord Pool, Tibber
    ("1.25", "NOK/kWh", 125),
    ("1.25", "DKK/kWh", 125),
    ("1.25", "kr/kWh", 125),
    ("0.245", "GBP/kWh", 24.5),    # Octopus
    ("0.245", "£/kWh", 24.5),
    ("0.31", "USD/kWh", 31),
    ("0.31", "$/kWh", 31),
    ("0.31", "AUD/kWh", 31),
    ("0.55", "PLN/kWh", 55),
    # whole currency per MWh -> x0.1
    ("85", "EUR/MWh", 8.5),
    ("120", "CHF/MWh", 12),
    ("-12.5", "EUR/MWh", -1.25),
    # already in the hundredth, or not a known currency -> as-is
    ("28", "ct/kWh", 28),
    ("28", "Rp./kWh", 28),
    ("28", "Rp/kWh", 28),
    ("28", "öre/kWh", 28),
    ("24", "p/kWh", 24),
    ("28", None, 28),
    ("0.28", "", 0.28),
    ("28", "JPY/kWh", 28),
    ("28", "EUR", 28),
    ("28", "EUR/Wh", 28),
])
def test_price_units(hass, value, unit, expected):
    _set_price(hass, value, unit)
    assert get_price_ct(hass, PRICE) == pytest.approx(expected)


def test_scaled_price_has_no_float_noise(hass):
    # 0.28 * 100 = 28.000000000000004 must still equal a max_price of 28.
    _set_price(hass, "0.28", "CHF/kWh")
    assert get_price_ct(hass, PRICE) == 28


def test_unavailable_returns_default_unscaled(hass):
    _set_price(hass, "unavailable", "CHF/kWh")
    assert get_price_ct(hass, PRICE, 7) == 7
    assert get_price_ct(hass, PRICE) is None


class TestInnostromChf:
    """The setup from discussion #35: max_price 20 Rp., price in CHF/kWh."""

    def _pm(self, hass):
        return PricingManager(hass, {"price_entity": PRICE})

    def _price_ok(self, hass, pm, value):
        _set_price(hass, value, "CHF/kWh")
        sh = {"now": NIGHT}
        pm.update(sh)
        pm.snapshot(sh)
        return sh, pm.is_price_ok(
            {"price_mode": "cheap_grid", "max_price": 20})

    def test_expensive_chf_price_is_not_cheap(self, hass):
        sh, ok = self._price_ok(hass, self._pm(hass), "0.28")
        assert sh["current_price"] == 28
        assert ok is False

    def test_cheap_chf_price_is_cheap(self, hass):
        sh, ok = self._price_ok(hass, self._pm(hass), "0.15")
        assert sh["current_price"] == 15
        assert ok is True

    def test_at_the_limit_counts_as_cheap(self, hass):
        _, ok = self._price_ok(hass, self._pm(hass), "0.20")
        assert ok is True


def _night_shared(now):
    """No surplus (importing 500 W), battery fine, no PV budget."""
    return {
        "now": now,
        "excess_for_devices": -500,
        "excess_raw_for_devices": -500,
        "grid_power_ema_asym": 500,
        "battery_soc": 80,
        "battery_mode": MODE_NORMAL,
        "device_budget_w": None,
        "surplus_blind": False,
    }


def _run(mgr, pm, start, minutes, step=30):
    t = start
    end = start + timedelta(minutes=minutes)
    while t <= end:
        sh = _night_shared(t)
        pm.update(sh)
        pm.snapshot(sh)
        mgr.update(sh)
        t += timedelta(seconds=step)
    return t


class TestCheapGridDeviceWithChf:
    """End to end: the device must not run on grid at 28 Rp. > 20 Rp."""

    def _setup(self, hass, make_manager, make_device):
        mgr = make_manager([make_device(price_mode="cheap_grid",
                                        max_price=20)])
        pm = PricingManager(hass, {"price_entity": PRICE})
        mgr.pricing = pm
        return mgr, pm

    def test_stays_off_at_an_expensive_chf_price(
            self, hass, make_manager, make_device):
        mgr, pm = self._setup(hass, make_manager, make_device)
        _set_price(hass, "0.28", "CHF/kWh")
        _run(mgr, pm, NIGHT, 30)
        assert hass.states[SW] == "off"

    def test_starts_at_a_cheap_chf_price(
            self, hass, make_manager, make_device):
        mgr, pm = self._setup(hass, make_manager, make_device)
        _set_price(hass, "0.28", "CHF/kWh")
        t = _run(mgr, pm, NIGHT, 10)
        assert hass.states[SW] == "off"
        _set_price(hass, "0.15", "CHF/kWh")
        _run(mgr, pm, t, 15)
        assert hass.states[SW] == "on"
