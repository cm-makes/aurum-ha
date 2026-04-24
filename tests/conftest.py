"""
pytest configuration for AURUM.

Stubs the Home Assistant modules that ``custom_components.aurum`` imports at
package-init time so ``DeviceManager`` can be exercised without a running HA
instance. Also provides a ``MockHass`` fixture and a device-config factory.
"""

import os
import sys
import types
from datetime import datetime, timedelta

import pytest


# ─── HA module stubs (must happen before any aurum import) ───────

_HA_SUBMODULES = [
    "homeassistant",
    "homeassistant.core",
    "homeassistant.config_entries",
    "homeassistant.helpers",
    "homeassistant.helpers.entity_registry",
    "homeassistant.helpers.entity_platform",
    "homeassistant.helpers.update_coordinator",
    "homeassistant.helpers.selector",
    "homeassistant.components",
    "homeassistant.components.sensor",
    "homeassistant.components.binary_sensor",
    "homeassistant.components.number",
    "homeassistant.components.switch",
    "homeassistant.components.time",
]

for mod_name in _HA_SUBMODULES:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = types.ModuleType(mod_name)

# Minimum attributes the aurum package touches at import time.
sys.modules["homeassistant.core"].HomeAssistant = type("HomeAssistant", (), {})
sys.modules["homeassistant.core"].callback = lambda f: f
sys.modules["homeassistant.config_entries"].ConfigEntry = type("ConfigEntry", (), {})

huc = sys.modules["homeassistant.helpers.update_coordinator"]
huc.DataUpdateCoordinator = type("DataUpdateCoordinator", (), {})
huc.CoordinatorEntity = type("CoordinatorEntity", (), {})
huc.UpdateFailed = type("UpdateFailed", (Exception,), {})

# Add the repo root so ``custom_components.aurum...`` imports resolve.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# ─── MockHass ────────────────────────────────────────────────────


class MockHass:
    """Minimal stand-in for the hass object DeviceManager uses."""

    def __init__(self):
        self.states = {}
        self.logs = []
        self.actions = []          # list of (action, entity_id)
        self.services = []         # list of (service, kwargs)

    def get_state(self, entity_id, default=None):
        return self.states.get(entity_id, default)

    def set_state(self, entity_id, value):
        self.states[entity_id] = value

    def turn_on(self, entity_id):
        self.states[entity_id] = "on"
        self.actions.append(("ON", entity_id))

    def turn_off(self, entity_id):
        self.states[entity_id] = "off"
        self.actions.append(("OFF", entity_id))

    def log(self, msg, level="INFO"):
        self.logs.append(msg)

    def call_service(self, service, **kwargs):
        self.services.append((service, kwargs))


# ─── Fake pricing ────────────────────────────────────────────────


class FakePricing:
    """Pricing stub with a toggleable ``is_price_ok`` result."""

    def __init__(self, price_ok=True):
        self.price_ok = price_ok
        self.calls = 0

    def is_price_ok(self, dev):
        self.calls += 1
        return self.price_ok


# ─── Fixtures ────────────────────────────────────────────────────


@pytest.fixture
def hass():
    return MockHass()


@pytest.fixture
def now():
    """Fixed reference datetime (noon, sunny day)."""
    return datetime(2026, 4, 24, 12, 0, 0)


@pytest.fixture
def make_device():
    """Factory that produces a minimal device-config dict.

    Defaults are sane; override per test with ``make_device(name=..., priority=...)``.
    """

    def _factory(**overrides):
        base = {
            "name": "Test Device",
            "switch_entity": "switch.test_device",
            "power_entity": None,
            "nominal_power": 1000,
            "priority": 50,
            "soc_threshold": 20,
            "hysteresis_on": 200,
            "hysteresis_off": 100,
            "debounce_on": 300,
            "debounce_off": 600,
            "min_on_time": 600,
            "min_off_time": 60,
            "interruptible": True,
            "residual_power": 100,
            "price_mode": "solar_only",
            "max_price": 0,
            "startup_detection": False,
        }
        base.update(overrides)
        return base

    return _factory


@pytest.fixture
def make_manager(hass, make_device):
    """Factory that builds a DeviceManager with a list of device-configs."""

    from custom_components.aurum.modules.devices import DeviceManager

    def _factory(device_configs=None, **global_config):
        cfg = {"devices": device_configs or []}
        cfg.update(global_config)
        return DeviceManager(hass, cfg)

    return _factory


@pytest.fixture
def shared_state(now):
    """Baseline ``shared`` dict passed to DeviceManager.update()."""
    return {
        "now": now,
        "excess_for_devices": 0,
        "excess_raw_for_devices": 0,
        "grid_power_ema_asym": 0,
        "battery_soc": 80,
        "battery_mode": "normal",
        "device_budget_w": None,
    }
