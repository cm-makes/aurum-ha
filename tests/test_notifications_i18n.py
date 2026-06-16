"""
Tests for runtime-notification localization (issue follow-up: some
notifications were hardcoded German). DeviceManager picks EN/DE from
the HA UI language and falls back to English.
"""

import pytest

from custom_components.aurum.modules.devices import (
    DeviceManager,
    _NOTIFY_STRINGS,
)


def _mgr(hass, make_device, lang=None):
    if lang is not None:
        hass.language = lang
    return DeviceManager(hass, {"devices": [make_device()]})


class TestLanguageSelection:
    def test_defaults_to_english_when_no_language(
            self, hass, make_device):
        # MockHass has no `language` attribute → fallback "en".
        mgr = _mgr(hass, make_device)
        assert mgr.lang == "en"

    def test_reads_language_from_hass(self, hass, make_device):
        mgr = _mgr(hass, make_device, lang="de")
        assert mgr.lang == "de"

    def test_empty_language_falls_back_to_english(self, hass, make_device):
        mgr = _mgr(hass, make_device, lang="")
        assert mgr.lang == "en"


class TestTranslationHelper:
    def test_english_message_formatted(self, hass, make_device):
        mgr = _mgr(hass, make_device, lang="en")
        msg = mgr._t("runtime_target_reached", name="Pool", minutes=400)
        assert msg == "⏱️ Pool: daily runtime reached (400 min) – switched off"
        assert "Tageslaufzeit" not in msg

    def test_german_message_formatted(self, hass, make_device):
        mgr = _mgr(hass, make_device, lang="de")
        msg = mgr._t("runtime_target_reached", name="Pool", minutes=400)
        assert msg == "⏱️ Pool: Tageslaufzeit erreicht (400 min) – ausgeschaltet"

    def test_unknown_language_falls_back_to_english(
            self, hass, make_device):
        mgr = _mgr(hass, make_device, lang="fr")
        msg = mgr._t("sd_running", name="Dishwasher")
        assert msg == "▶️ Dishwasher is running now (PV surplus)"

    def test_unknown_key_returns_key(self, hass, make_device):
        mgr = _mgr(hass, make_device, lang="en")
        assert mgr._t("does_not_exist", name="X") == "does_not_exist"

    def test_missing_placeholder_does_not_raise(self, hass, make_device):
        mgr = _mgr(hass, make_device, lang="en")
        # omit `minutes` → returns the raw template instead of raising
        out = mgr._t("runtime_target_reached", name="Pool")
        assert "{minutes}" in out


class TestTableIntegrity:
    @pytest.mark.parametrize("key", list(_NOTIFY_STRINGS))
    def test_every_key_has_en_and_de(self, key):
        variants = _NOTIFY_STRINGS[key]
        assert "en" in variants and "de" in variants

    @pytest.mark.parametrize("key", list(_NOTIFY_STRINGS))
    def test_en_and_de_share_placeholders(self, key):
        import re
        en = set(re.findall(r"\{(\w+)\}", _NOTIFY_STRINGS[key]["en"]))
        de = set(re.findall(r"\{(\w+)\}", _NOTIFY_STRINGS[key]["de"]))
        assert en == de, f"{key}: placeholder mismatch {en} vs {de}"


class TestEndToEndNotification:
    def test_runtime_stop_notification_is_english_by_default(
            self, hass, make_device, now):
        from datetime import timedelta

        mgr = DeviceManager(hass, {"devices": [make_device(
            stop_after_runtime=True, estimated_runtime=400)]})
        dev = mgr.devices[0]
        hass.set_state(dev["switch_entity"], "on")
        dev["managed_on"] = True
        dev["on_since"] = now - timedelta(hours=2)
        dev["_runtime_tick"] = now
        dev["runtime_today_s"] = 400 * 60
        mgr.update({
            "now": now, "excess_for_devices": 5000,
            "excess_raw_for_devices": 5000, "grid_power_ema_asym": -5000,
            "battery_soc": 80, "battery_mode": "normal",
            "device_budget_w": None})
        # The persistent notification service was called with English text.
        notes = [kw.get("message", "")
                 for svc, kw in hass.services
                 if svc == "persistent_notification/create"]
        assert any("daily runtime reached" in m for m in notes)
        assert all("Tageslaufzeit" not in m for m in notes)
