"""
Unit tests for the SOC-gated cheap-grid price mode (``cheap_grid_soc``).

The mode behaves like ``cheap_grid`` except that the price-based start is
only granted while battery SOC is at or above the device ``soc_threshold``.
Below it the device falls back to ``solar_only`` behaviour: genuine grid
export can still run it, a cheap price alone cannot.

See ``devices.py``: ``_should_turn_on`` / ``_should_turn_off``.
Introduced in #21 by @psecker.
"""

from datetime import timedelta

from tests.conftest import FakePricing


# ══════════════════════════════════════════════════════════════════
#  Turn-on: the SOC gate on the price path
# ══════════════════════════════════════════════════════════════════


class TestCheapGridSocTurnOn:
    def test_price_start_granted_when_soc_ok(
            self, make_manager, make_device, now):
        mgr = make_manager([make_device(price_mode="cheap_grid_soc")])
        mgr.pricing = FakePricing(price_ok=True)
        dev = mgr.devices[0]
        # SOC 80 >= threshold 20 → price alone starts the device.
        assert mgr._should_turn_on(dev, 0, 0, 80, 20, now) is True
        assert dev["_scheduling_reason"] == "cheap_grid"

    def test_price_start_blocked_when_soc_below(
            self, make_manager, make_device, now):
        mgr = make_manager([make_device(price_mode="cheap_grid_soc")])
        mgr.pricing = FakePricing(price_ok=True)
        dev = mgr.devices[0]
        # SOC 10 < threshold 20 and no surplus → the cheap price is ignored.
        assert mgr._should_turn_on(dev, 0, 0, 10, 20, now) is False

    def test_soc_at_threshold_is_enough(
            self, make_manager, make_device, now):
        mgr = make_manager([make_device(price_mode="cheap_grid_soc")])
        mgr.pricing = FakePricing(price_ok=True)
        dev = mgr.devices[0]
        # Boundary: ">= threshold", not "> threshold".
        assert mgr._should_turn_on(dev, 0, 0, 20, 20, now) is True

    def test_below_soc_still_starts_on_grid_export(
            self, make_manager, make_device, now):
        """Fallback is solar_only, not "off": real export still starts it."""
        mgr = make_manager([make_device(
            price_mode="cheap_grid_soc", debounce_on=0)])
        mgr.pricing = FakePricing(price_ok=True)
        dev = mgr.devices[0]
        dev["excess_since"] = now - timedelta(seconds=1)
        # Below threshold the device may only use grid export, so the
        # surplus decision is taken on available_grid_excess (2000 W)
        # against needed = 1000 + 200 + 100 = 1300 W.
        assert mgr._should_turn_on(dev, 5000, 2000, 10, 20, now) is True

    def test_below_soc_ignores_battery_backed_excess(
            self, make_manager, make_device, now):
        mgr = make_manager([make_device(
            price_mode="cheap_grid_soc", debounce_on=0)])
        mgr.pricing = FakePricing(price_ok=True)
        dev = mgr.devices[0]
        dev["excess_since"] = now - timedelta(seconds=1)
        # Plenty of computed excess but no real export → stays off.
        assert mgr._should_turn_on(dev, 5000, 500, 10, 20, now) is False

    def test_unknown_soc_grants_price_start(
            self, make_manager, make_device, now):
        """SOC unavailable (<0) is currently permissive on the price path.

        Note the asymmetry with ``_pv_gate_ok``, which fails *safe* (gate
        closed) on an unknown SOC. Encoded here so a future change to
        either side is a deliberate decision rather than a silent drift.
        """
        mgr = make_manager([make_device(price_mode="cheap_grid_soc")])
        mgr.pricing = FakePricing(price_ok=True)
        dev = mgr.devices[0]
        assert mgr._should_turn_on(dev, 0, 0, -1, 20, now) is True

    def test_price_not_ok_falls_back_to_solar_logic(
            self, make_manager, make_device, now):
        mgr = make_manager([make_device(price_mode="cheap_grid_soc")])
        mgr.pricing = FakePricing(price_ok=False)
        dev = mgr.devices[0]
        assert mgr._should_turn_on(dev, 0, 0, 80, 20, now) is False


class TestPlainCheapGridUnchanged:
    """Regression guard: #21 must not alter existing ``cheap_grid``."""

    def test_price_start_ignores_soc(self, make_manager, make_device, now):
        mgr = make_manager([make_device(price_mode="cheap_grid")])
        mgr.pricing = FakePricing(price_ok=True)
        dev = mgr.devices[0]
        # SOC far below threshold — plain cheap_grid still starts.
        assert mgr._should_turn_on(dev, 0, 0, 5, 50, now) is True
        assert dev["_scheduling_reason"] == "cheap_grid"

    def test_solar_only_never_uses_price_path(
            self, make_manager, make_device, now):
        mgr = make_manager([make_device(price_mode="solar_only")])
        mgr.pricing = FakePricing(price_ok=True)
        dev = mgr.devices[0]
        assert mgr._should_turn_on(dev, 0, 0, 80, 20, now) is False


# ══════════════════════════════════════════════════════════════════
#  Turn-off
# ══════════════════════════════════════════════════════════════════


class TestCheapGridSocTurnOff:
    def _running(self, mgr, now):
        dev = mgr.devices[0]
        dev["on_since"] = now - timedelta(hours=1)
        dev["_scheduling_reason"] = "cheap_grid"
        return dev

    def test_holds_during_deficit_while_soc_ok(
            self, make_manager, make_device, now):
        mgr = make_manager([make_device(price_mode="cheap_grid_soc")])
        mgr.pricing = FakePricing(price_ok=True)
        dev = self._running(mgr, now)
        # Deep deficit but price cheap and SOC healthy → intentional grid use.
        assert mgr._should_turn_off(dev, -9999, 80, 20, now) is None

    def test_soc_deficit_stops_it_below_threshold(
            self, make_manager, make_device, now):
        """Below threshold the generic SOC guard reclaims the device.

        This guard predates #21 and fires for *both* price-aware modes —
        which is exactly why the plain ``cheap_grid`` path could cycle:
        the SOC guard switched the device off, and the ungated price path
        switched it straight back on after ``min_off_time``. Gating the
        turn-on side is what actually breaks that cycle.
        """
        mgr = make_manager([make_device(price_mode="cheap_grid_soc")])
        mgr.pricing = FakePricing(price_ok=True)
        dev = self._running(mgr, now)
        dev["_soc_grid_deficit_since"] = now - timedelta(seconds=700)
        assert mgr._should_turn_off(
            dev, -9999, 10, 20, now) == "soc_grid_deficit"

    def test_expensive_price_still_releases_immediately(
            self, make_manager, make_device, now):
        mgr = make_manager([make_device(price_mode="cheap_grid_soc")])
        mgr.pricing = FakePricing(price_ok=False)
        dev = self._running(mgr, now)
        assert mgr._should_turn_off(
            dev, 500, 80, 20, now) == "price_no_longer_cheap"

    def test_holds_when_price_data_unavailable(
            self, make_manager, make_device, now):
        mgr = make_manager([make_device(price_mode="cheap_grid_soc")])
        mgr.pricing = FakePricing(price_ok=False, data_available=False)
        dev = self._running(mgr, now)
        assert mgr._should_turn_off(dev, -9999, 80, 20, now) is None
