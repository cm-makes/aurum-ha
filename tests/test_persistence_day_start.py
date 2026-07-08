"""
Round-trip tests for day_start_hour-aware persistence restore (v1.12.1).

Regression guard for the debt left by the v1.12.0 day_start_hour feature:
persistence used to zero counters on the calendar day, which could wrongly
wipe runtime accrued before midnight on a day_start_hour>0 device restarted
in the pre-boundary window.
"""

import json
from datetime import datetime

import pytest

from custom_components.aurum.modules.devices import DeviceManager
from custom_components.aurum.modules.persistence import PersistenceManager


def _write_state(path, dev_name, saved_at, runtime_s=330):
    state = {
        "_meta": {"saved_at": saved_at.isoformat(),
                  "saved_date": saved_at.strftime("%Y-%m-%d"),
                  "version": "1.1.0"},
        dev_name: {
            "runtime_today_s": runtime_s, "energy_today_wh": 1000.0,
            "total_switches": 3, "sd_state": "", "managed_on": False,
            "force_started": False,
            "on_since": None, "last_on": None, "last_off": None,
        },
    }
    with open(path, "w") as f:
        json.dump(state, f)


def _mgr(hass, **dev):
    base = {"name": "Pool Pump", "switch_entity": "switch.pool",
            "nominal_power": 1000, "priority": 50}
    base.update(dev)
    return DeviceManager(hass, {"devices": [base]})


class TestDayAwareRestore:
    def test_offset_device_kept_when_still_in_cycle(self, hass, tmp_path):
        # day_start_hour=9. Runtime accrued after midnight (03:00), device
        # restarted at 06:00 — same 09:00→09:00 cycle, must NOT be zeroed.
        sf = str(tmp_path / "state.json")
        mgr = _mgr(hass, day_start_hour=9)
        _write_state(sf, "Pool Pump", datetime(2026, 7, 9, 3, 0, 0))
        pm = PersistenceManager(hass, {"state_file": sf})
        # Freeze "now" to 06:00 on the same day.
        import custom_components.aurum.modules.persistence as P
        real = P.datetime
        P.datetime = _FrozenNow(datetime(2026, 7, 9, 6, 0, 0), real)
        try:
            pm.restore(mgr)
        finally:
            P.datetime = real
        assert mgr.devices[0]["runtime_today_s"] == 330  # preserved
        assert mgr.devices[0]["_last_reset"] == datetime(2026, 7, 9, 9, 0, 0) \
            or mgr.devices[0]["_last_reset"] == datetime(2026, 7, 8, 9, 0, 0)

    def test_offset_device_reset_after_boundary(self, hass, tmp_path):
        # Saved before the boundary, restarted after 09:00 → cycle rolled
        # over → counters zeroed.
        sf = str(tmp_path / "state.json")
        mgr = _mgr(hass, day_start_hour=9)
        _write_state(sf, "Pool Pump", datetime(2026, 7, 9, 5, 0, 0))
        pm = PersistenceManager(hass, {"state_file": sf})
        import custom_components.aurum.modules.persistence as P
        real = P.datetime
        P.datetime = _FrozenNow(datetime(2026, 7, 9, 10, 0, 0), real)
        try:
            pm.restore(mgr)
        finally:
            P.datetime = real
        assert mgr.devices[0]["runtime_today_s"] == 0  # rolled over

    def test_default_midnight_still_zeroes_previous_day(self, hass, tmp_path):
        # day_start_hour=0 (default): saved yesterday, restored today → zero
        # (unchanged legacy behaviour).
        sf = str(tmp_path / "state.json")
        mgr = _mgr(hass)  # day_start_hour default 0
        _write_state(sf, "Pool Pump", datetime(2026, 7, 8, 22, 0, 0))
        pm = PersistenceManager(hass, {"state_file": sf})
        import custom_components.aurum.modules.persistence as P
        real = P.datetime
        P.datetime = _FrozenNow(datetime(2026, 7, 9, 7, 0, 0), real)
        try:
            pm.restore(mgr)
        finally:
            P.datetime = real
        assert mgr.devices[0]["runtime_today_s"] == 0

    def test_default_midnight_keeps_same_day(self, hass, tmp_path):
        sf = str(tmp_path / "state.json")
        mgr = _mgr(hass)
        _write_state(sf, "Pool Pump", datetime(2026, 7, 9, 8, 0, 0))
        pm = PersistenceManager(hass, {"state_file": sf})
        import custom_components.aurum.modules.persistence as P
        real = P.datetime
        P.datetime = _FrozenNow(datetime(2026, 7, 9, 10, 0, 0), real)
        try:
            pm.restore(mgr)
        finally:
            P.datetime = real
        assert mgr.devices[0]["runtime_today_s"] == 330  # preserved


class _FrozenNow:
    """datetime shim: fixed now(), everything else delegates to the real
    datetime class (fromisoformat, replace via instances, etc.)."""

    def __init__(self, fixed, real):
        self._fixed = fixed
        self._real = real

    def now(self, tz=None):
        return self._fixed

    def __getattr__(self, name):
        return getattr(self._real, name)
