"""
Unit tests: the PV budget cap must not block a price-granted start.

The budget module reserves *solar* for battery charging. After sunset it
returns ``device_budget_w = 0`` (a real zero, not ``None``), so the cap in
``DeviceManager.update()`` stayed active all night. A ``cheap_grid`` device
was only exempt via the grid-only fallback (``battery_soc < soc_threshold``,
its OWN threshold) — so a cautious low threshold silently disabled cheap-grid
runs overnight while a high one enabled them. A price-granted start runs on
grid, not on solar, so the budget has no say in it — same exemption
``deadline_forced`` and the PV gate already had.

See ``devices.py``: ``_price_grant`` / ``update()`` budget cap.
Found by @psecker in #25.
"""

from tests.conftest import FakePricing


def _night(shared_state, **over):
    """After-sunset shared state: budget exhausted, no surplus."""
    shared_state.update({"device_budget_w": 0, "excess_for_devices": 0,
                         "excess_raw_for_devices": 0})
    shared_state.update(over)
    return shared_state


# ══════════════════════════════════════════════════════════════════
#  _price_grant: the shared predicate
# ══════════════════════════════════════════════════════════════════


class TestPriceGrant:
    def test_cheap_grid_granted_regardless_of_soc(
            self, make_manager, make_device):
        mgr = make_manager([make_device(price_mode="cheap_grid")])
        mgr.pricing = FakePricing(price_ok=True)
        dev = mgr.devices[0]
        assert mgr._price_grant(dev, 5, 20) is True
        assert mgr._price_grant(dev, 80, 20) is True

    def test_cheap_grid_soc_requires_threshold(
            self, make_manager, make_device):
        mgr = make_manager([make_device(price_mode="cheap_grid_soc")])
        mgr.pricing = FakePricing(price_ok=True)
        dev = mgr.devices[0]
        assert mgr._price_grant(dev, 10, 20) is False
        assert mgr._price_grant(dev, 20, 20) is True
        assert mgr._price_grant(dev, -1, 20) is True  # unknown SOC → OK

    def test_no_grant_when_price_not_cheap(
            self, make_manager, make_device):
        mgr = make_manager([make_device(price_mode="cheap_grid")])
        mgr.pricing = FakePricing(price_ok=False)
        assert mgr._price_grant(mgr.devices[0], 80, 20) is False

    def test_no_grant_when_price_data_unavailable(
            self, make_manager, make_device):
        # should_run_on_grid returns None → hold state, but never *start*.
        mgr = make_manager([make_device(price_mode="cheap_grid")])
        mgr.pricing = FakePricing(price_ok=True, data_available=False)
        assert mgr._price_grant(mgr.devices[0], 80, 20) is False

    def test_no_grant_for_solar_only(self, make_manager, make_device):
        mgr = make_manager([make_device(price_mode="solar_only")])
        mgr.pricing = FakePricing(price_ok=True)
        assert mgr._price_grant(mgr.devices[0], 80, 20) is False

    def test_no_grant_without_pricing_module(
            self, make_manager, make_device):
        mgr = make_manager([make_device(price_mode="cheap_grid")])
        mgr.pricing = None
        assert mgr._price_grant(mgr.devices[0], 80, 20) is False


# ══════════════════════════════════════════════════════════════════
#  update(): the budget cap and the price grant
# ══════════════════════════════════════════════════════════════════


class TestBudgetCapVsPriceGrant:
    def test_cheap_grid_starts_overnight_despite_zero_budget(
            self, make_manager, make_device, shared_state):
        """The bug: SOC 80 >= threshold 20 → not grid-only → capped."""
        mgr = make_manager([make_device(
            switch_entity="switch.pool", price_mode="cheap_grid")])
        mgr.pricing = FakePricing(price_ok=True)
        mgr.update(_night(shared_state, battery_soc=80))
        assert mgr.hass.states.get("switch.pool") == "on"
        assert mgr.devices[0]["_scheduling_reason"] == "cheap_grid"

    def test_low_and_high_threshold_behave_the_same(
            self, make_manager, make_device, shared_state):
        """The inversion @psecker found: at SOC 50, the 60 % device was
        exempt (grid-only) and the 25 % device was capped. Both are on
        cheap_grid — both must start."""
        mgr = make_manager([
            make_device(name="Pump", switch_entity="switch.pump",
                        price_mode="cheap_grid", soc_threshold=25),
            make_device(name="Heater", switch_entity="switch.heater",
                        price_mode="cheap_grid", soc_threshold=60),
        ])
        mgr.pricing = FakePricing(price_ok=True)
        mgr.update(_night(shared_state, battery_soc=50))
        assert mgr.hass.states.get("switch.pump") == "on"
        assert mgr.hass.states.get("switch.heater") == "on"

    def test_cap_still_applies_when_price_not_cheap(
            self, make_manager, make_device, shared_state):
        """Exemption is scoped to a live grant: expensive price + surplus
        under an exhausted daytime budget must stay capped."""
        mgr = make_manager([make_device(
            switch_entity="switch.pool", price_mode="cheap_grid",
            debounce_on=0)])
        mgr.pricing = FakePricing(price_ok=False)
        mgr.devices[0]["excess_since"] = shared_state["now"]
        mgr.update(_night(shared_state, battery_soc=80,
                          excess_for_devices=1500,
                          excess_raw_for_devices=1500))
        assert mgr.hass.states.get("switch.pool") != "on"

    def test_cap_still_applies_to_solar_only(
            self, make_manager, make_device, shared_state):
        mgr = make_manager([make_device(
            switch_entity="switch.pool", price_mode="solar_only",
            debounce_on=0)])
        mgr.pricing = FakePricing(price_ok=True)
        mgr.devices[0]["excess_since"] = shared_state["now"]
        mgr.update(_night(shared_state, battery_soc=80,
                          excess_for_devices=1500,
                          excess_raw_for_devices=1500))
        assert mgr.hass.states.get("switch.pool") != "on"

    def test_cheap_grid_soc_below_threshold_stays_capped(
            self, make_manager, make_device, shared_state):
        """cheap_grid_soc keeps its battery floor: no grant below the
        threshold, so no start — even though the cap alone would have
        let it through via grid-only mode (SOC 10 < 20)."""
        mgr = make_manager([make_device(
            switch_entity="switch.pool", price_mode="cheap_grid_soc")])
        mgr.pricing = FakePricing(price_ok=True)
        mgr.update(_night(shared_state, battery_soc=10))
        assert mgr.hass.states.get("switch.pool") != "on"

    def test_cheap_grid_soc_above_threshold_starts(
            self, make_manager, make_device, shared_state):
        mgr = make_manager([make_device(
            switch_entity="switch.pool", price_mode="cheap_grid_soc")])
        mgr.pricing = FakePricing(price_ok=True)
        mgr.update(_night(shared_state, battery_soc=80))
        assert mgr.hass.states.get("switch.pool") == "on"

    def test_price_data_unavailable_stays_capped(
            self, make_manager, make_device, shared_state):
        mgr = make_manager([make_device(
            switch_entity="switch.pool", price_mode="cheap_grid")])
        mgr.pricing = FakePricing(price_ok=True, data_available=False)
        mgr.update(_night(shared_state, battery_soc=80))
        assert mgr.hass.states.get("switch.pool") != "on"
