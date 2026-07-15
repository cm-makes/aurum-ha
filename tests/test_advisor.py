"""
Unit tests for the Advisor (current-decision) module.

The AdvisorManager is a pure function of the coordinator's ``shared`` dict —
conftest.py stubs the Home Assistant imports, so the module imports directly.
These tests pin the aggregate decision codes and the per-device reason
mapping so a change in either surfaces immediately.
"""

from __future__ import annotations

from custom_components.aurum.modules.advisor import (
    DECISION_OPTIONS,
    AdvisorManager,
)


def _advisor():
    return AdvisorManager(hass=None, config={})


def test_idle_no_devices():
    shared = {"battery_mode": "normal", "battery_soc": 90, "device_states": []}
    data = _advisor().update(shared)
    assert data["decision"] == "idle"
    assert data["devices_total"] == 0


def test_startup_emits_minimal_payload():
    """During the grace period no device claims are made: the panel must
    not render '0/0 devices' while sensors are still warming up."""
    shared = {"battery_mode": "startup", "device_states": []}
    data = _advisor().update(shared)
    assert data["decision"] == "startup"
    assert "devices_on" not in data
    assert "devices_total" not in data


def test_running_solar_via_surplus_available():
    """The DEFAULT turn-on reason for non-SD devices is 'surplus_available'
    (devices.py _turn_on) — the flagship case must map to running_solar."""
    shared = {
        "battery_mode": "normal",
        "battery_soc": 85,
        "device_states": [
            {"name": "Pool", "slug": "pool", "state": "on",
             "scheduling_reason": "surplus_available", "power": 500},
        ],
    }
    data = _advisor().update(shared)
    assert data["decision"] == "running_solar"
    assert data["devices"][0]["reason"] == "solar_surplus"


def test_running_solar_takes_precedence():
    shared = {
        "battery_mode": "normal",
        "battery_soc": 85,
        "device_states": [
            {"name": "Pool", "slug": "pool", "state": "on",
             "scheduling_reason": "excess_sufficient", "power": 500},
            {"name": "Heater", "slug": "heater", "state": "on",
             "scheduling_reason": "cheap_grid", "power": 800},
        ],
    }
    data = _advisor().update(shared)
    # solar beats cheap_grid in the headline
    assert data["decision"] == "running_solar"
    assert data["devices_on"] == 2
    reasons = {d["slug"]: d["reason"] for d in data["devices"]}
    assert reasons == {"pool": "solar_surplus", "heater": "cheap_grid"}


def test_running_cheap_grid_only():
    shared = {
        "battery_mode": "normal",
        "device_states": [
            {"name": "Heater", "slug": "heater", "state": "running",
             "scheduling_reason": "cheap_grid", "power": 800},
        ],
    }
    assert _advisor().update(shared)["decision"] == "running_cheap_grid"


def test_battery_charging_blocks():
    shared = {
        "battery_mode": "charging",
        "battery_soc": 8,
        "device_states": [
            {"name": "Pool", "slug": "pool", "state": "off",
             "soc_threshold": 20, "power": 0},
        ],
    }
    data = _advisor().update(shared)
    assert data["decision"] == "battery_charging"
    assert data["devices"][0]["reason"] == "battery_charging"


def test_manual_override_and_forced():
    shared = {
        "battery_mode": "charging",  # override still runs despite charging
        "battery_soc": 8,
        "device_states": [
            {"name": "Boiler", "slug": "boiler", "state": "manual_override",
             "power": 1500},
            {"name": "Wash", "slug": "wash", "state": "on",
             "force_started": True, "scheduling_reason": "excess_sufficient",
             "power": 2000},
        ],
    }
    data = _advisor().update(shared)
    # Devices are running, so the headline reflects that, not charging.
    # Both run for non-solar reasons (override / deadline) → generic "running".
    assert data["decision"] == "running"
    reasons = {d["slug"]: d["reason"] for d in data["devices"]}
    assert reasons["boiler"] == "manual_override"
    assert reasons["wash"] == "forced_deadline"


def test_below_soc_threshold_reason():
    shared = {
        "battery_mode": "low_soc",
        "battery_soc": 30,
        "device_states": [
            {"name": "Pool", "slug": "pool", "state": "off",
             "soc_threshold": 50, "power": 0},
            {"name": "Fan", "slug": "fan", "state": "off",
             "soc_threshold": 10, "power": 0},
        ],
    }
    data = _advisor().update(shared)
    assert data["decision"] == "waiting"
    reasons = {d["slug"]: d["reason"] for d in data["devices"]}
    assert reasons["pool"] == "below_soc_threshold"   # 30 < 50
    assert reasons["fan"] == "waiting_surplus"         # 30 >= 10


def test_sd_program_states():
    shared = {
        "battery_mode": "normal",
        "battery_soc": 90,
        "device_states": [
            {"name": "Pool", "slug": "pool", "state": "off",
             "runtime_target_reached": True, "power": 0},
            {"name": "Dish", "slug": "dish", "state": "waiting",
             "sd_state": "waiting", "power": 0},
            {"name": "Wash", "slug": "wash", "state": "done",
             "sd_state": "done", "power": 0},
            {"name": "Dryer", "slug": "dryer", "state": "standby",
             "sd_state": "standby", "power": 0},
        ],
    }
    data = _advisor().update(shared)
    assert data["decision"] == "waiting"
    reasons = {d["slug"]: d["reason"] for d in data["devices"]}
    assert reasons["pool"] == "runtime_done"
    assert reasons["dish"] == "program_paused"
    assert reasons["wash"] == "program_done"
    assert reasons["dryer"] == "program_standby"


def test_disabled_beats_everything():
    """Force-off switch: the device must NOT read 'waiting for surplus' —
    it will never start while disabled."""
    shared = {
        "battery_mode": "charging",  # even the charging label loses
        "battery_soc": 5,
        "device_states": [
            {"name": "Pool", "slug": "pool", "state": "off",
             "disabled": True, "soc_threshold": 20, "power": 0},
        ],
    }
    data = _advisor().update(shared)
    assert data["devices"][0]["reason"] == "disabled"


def test_condition_not_met():
    """Run condition (e.g. boiler already hot) must not read as
    'waiting for surplus'."""
    shared = {
        "battery_mode": "normal",
        "battery_soc": 90,
        "device_states": [
            {"name": "Boiler", "slug": "boiler", "state": "off",
             "condition_met": False, "power": 0},
        ],
    }
    data = _advisor().update(shared)
    assert data["devices"][0]["reason"] == "condition_not_met"


def test_no_churn_attributes():
    """Attributes must not carry fast-changing numbers: every attribute
    delta is a recorder write. Watts and timestamps live in the dedicated
    numeric sensors."""
    shared = {
        "battery_mode": "normal",
        "battery_soc": 90,
        "excess": 1234.5,
        "device_states": [
            {"name": "Pool", "slug": "pool", "state": "on",
             "scheduling_reason": "surplus_available", "power": 512.3},
        ],
    }
    data = _advisor().update(shared)
    assert "excess_w" not in data
    assert "last_update" not in data
    assert "battery_soc" not in data
    assert "power" not in data["devices"][0]


def test_price_context_only_when_available():
    base = {"battery_mode": "normal", "battery_soc": 90, "device_states": []}

    no_price = _advisor().update(dict(base))
    assert "price_level" not in no_price

    # shared["current_price"] is already ct/kWh (pricing.py) — pass-through.
    with_price = _advisor().update({
        **base,
        "price_data_available": True,
        "price_level": "cheap",
        "current_price": 18.42,
    })
    assert with_price["price_level"] == "cheap"
    assert with_price["current_price_ct"] == 18.4


def test_decision_options_cover_all_codes():
    """Every decision the aggregate can emit must be a valid ENUM option."""
    from custom_components.aurum.modules import advisor as adv
    emitted = {
        adv.DECISION_STARTUP, adv.DECISION_BATTERY_CHARGING,
        adv.DECISION_RUNNING_SOLAR, adv.DECISION_RUNNING_CHEAP_GRID,
        adv.DECISION_RUNNING, adv.DECISION_WAITING, adv.DECISION_IDLE,
        "unknown",
    }
    assert emitted == set(DECISION_OPTIONS)
