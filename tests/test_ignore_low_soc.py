"""
Tests for the ``ignore_low_soc`` per-device flag.

Motivating bug: a device on ``price_mode=cheap_grid`` is meant to start on
a fixed cheap-tariff window "even at night ... regardless of battery SOC"
(per the config-flow description) — but two independent SOC-driven gates
can silently keep it from ever reaching that price check:

1. The emergency ``MODE_CHARGING`` branch in ``DeviceManager.update()``
   force-stops / skips every device once SOC <= min_soc, before the
   per-device loop (and therefore ``_should_turn_on``) ever runs.
2. The nightly PV budget cap: after sunset ``device_budget_w`` is zeroed
   (not ``None`` — the cap stays active), and a device is only exempt from
   it once ITS OWN SOC falls below ITS OWN ``soc_threshold``. Two devices
   on the same ``cheap_grid`` price_mode can therefore behave very
   differently overnight purely because of unrelated ``soc_threshold``
   values (e.g. a water heater at 60% is exempted most nights, a pool pump
   at 25% rarely is) — even though neither gate has anything to do with
   the price-based grant itself.

``ignore_low_soc=True`` makes a device's schedule fully independent of
SOC by exempting it from both gates, while leaving default (``False``)
devices byte-for-byte on the pre-existing behaviour.
"""

from datetime import timedelta

from custom_components.aurum.const import MODE_CHARGING, MODE_NORMAL
from tests.conftest import FakePricing


def make_shared(now, excess=0, soc=50, budget=None, mode=MODE_NORMAL):
    return {
        "now": now,
        "excess_for_devices": excess,
        "excess_raw_for_devices": excess,
        "grid_power_ema_asym": -excess,
        "battery_soc": soc,
        "battery_mode": mode,
        "device_budget_w": budget,
    }


# ══════════════════════════════════════════════════════════════════
#  Emergency low-SOC shutoff (MODE_CHARGING)
# ══════════════════════════════════════════════════════════════════


class TestEmergencyBypass:
    def test_default_device_force_stopped_during_charging(
            self, make_manager, make_device, hass, now):
        mgr = make_manager([make_device(
            name="Water Heater", switch_entity="switch.wh",
            price_mode="cheap_grid")])
        mgr.pricing = FakePricing(price_ok=True)
        dev = mgr.devices[0]
        hass.set_state("switch.wh", "on")
        dev["managed_on"] = True

        mgr.update(make_shared(now, mode=MODE_CHARGING))

        assert hass.get_state("switch.wh") == "off"
        assert ("OFF", "switch.wh") in hass.actions

    def test_flagged_device_survives_and_can_start_during_charging(
            self, make_manager, make_device, hass, now):
        mgr = make_manager([make_device(
            name="Pool Pump", switch_entity="switch.pool",
            price_mode="cheap_grid", ignore_low_soc=True,
            debounce_on=0)])
        mgr.pricing = FakePricing(price_ok=True)

        mgr.update(make_shared(now, mode=MODE_CHARGING))

        assert hass.get_state("switch.pool") == "on"
        assert ("ON", "switch.pool") in hass.actions

    def test_flagged_device_off_stays_off_when_price_not_ok(
            self, make_manager, make_device, hass, now):
        """The flag removes the SOC gates, not the price gate itself."""
        mgr = make_manager([make_device(
            name="Pool Pump", switch_entity="switch.pool",
            price_mode="cheap_grid", ignore_low_soc=True)])
        mgr.pricing = FakePricing(price_ok=False)
        hass.set_state("switch.pool", "off")

        mgr.update(make_shared(now, excess=0, mode=MODE_CHARGING))

        assert hass.get_state("switch.pool") == "off"
        assert ("ON", "switch.pool") not in hass.actions

    def test_other_devices_still_protected_when_one_is_flagged(
            self, make_manager, make_device, hass, now):
        """Mixed fleet: the emergency loop must still shed a normal
        device even while a flagged sibling is exempted the same cycle."""
        mgr = make_manager([
            make_device(name="Water Heater", switch_entity="switch.wh"),
            make_device(name="Pool Pump", switch_entity="switch.pool",
                        price_mode="cheap_grid", ignore_low_soc=True,
                        debounce_on=0),
        ])
        mgr.pricing = FakePricing(price_ok=True)
        hass.set_state("switch.wh", "on")
        mgr.devices[0]["managed_on"] = True

        mgr.update(make_shared(now, mode=MODE_CHARGING))

        assert hass.get_state("switch.wh") == "off"
        assert hass.get_state("switch.pool") == "on"


# ══════════════════════════════════════════════════════════════════
#  Nightly PV budget cap
# ══════════════════════════════════════════════════════════════════


class TestBudgetCapBypass:
    def test_default_device_blocked_by_zero_budget_despite_cheap_price(
            self, make_manager, make_device, hass, now):
        """Root-cause regression: SOC (50) is above soc_threshold (20),
        so the device is NOT in grid-only mode and the zeroed nightly
        budget blocks it — even though price is cheap and price_mode is
        cheap_grid. This is the exact bug pattern that motivated the
        flag (pool pump vs water heater soc_threshold asymmetry)."""
        mgr = make_manager([make_device(
            name="Pool Pump", switch_entity="switch.pool",
            price_mode="cheap_grid", soc_threshold=20)])
        mgr.pricing = FakePricing(price_ok=True)
        hass.set_state("switch.pool", "off")

        mgr.update(make_shared(now, soc=50, budget=0))

        assert hass.get_state("switch.pool") == "off"
        assert ("ON", "switch.pool") not in hass.actions

    def test_flagged_device_ignores_zero_budget(
            self, make_manager, make_device, hass, now):
        mgr = make_manager([make_device(
            name="Pool Pump", switch_entity="switch.pool",
            price_mode="cheap_grid", soc_threshold=20,
            ignore_low_soc=True)])
        mgr.pricing = FakePricing(price_ok=True)

        mgr.update(make_shared(now, soc=50, budget=0))

        assert hass.get_state("switch.pool") == "on"

    def test_grid_only_mode_already_exempts_without_the_flag(
            self, make_manager, make_device, hass, now):
        """Sanity check on the existing exemption path: SOC below the
        device's own soc_threshold already bypasses the cap today, with
        no flag needed — confirms the bug is specifically about SOC
        sitting ABOVE a low threshold, not the exemption logic itself."""
        mgr = make_manager([make_device(
            name="Pool Pump", switch_entity="switch.pool",
            price_mode="cheap_grid", soc_threshold=20)])
        mgr.pricing = FakePricing(price_ok=True)

        mgr.update(make_shared(now, soc=10, budget=0))

        assert hass.get_state("switch.pool") == "on"


# ══════════════════════════════════════════════════════════════════
#  Diagnostics
# ══════════════════════════════════════════════════════════════════


class TestStatePublished:
    def test_ignore_low_soc_reflected_in_device_states(
            self, make_manager, make_device, now):
        mgr = make_manager([make_device(ignore_low_soc=True)])
        shared = make_shared(now)
        mgr.update(shared)
        assert shared["device_states"][0]["ignore_low_soc"] is True

    def test_defaults_false_when_not_configured(
            self, make_manager, make_device, now):
        mgr = make_manager([make_device()])
        shared = make_shared(now)
        mgr.update(shared)
        assert shared["device_states"][0]["ignore_low_soc"] is False
