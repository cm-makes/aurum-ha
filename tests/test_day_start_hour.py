"""
Unit tests for the per-device day_start_hour daily-reset boundary (v1.12.0,
community discussion #11).
"""

from datetime import datetime, timedelta


def _at(h, m=0):
    return datetime(2026, 7, 8, h, m, 0)


class TestDayStartHour:
    def test_no_arg_resets_all_unconditionally(
            self, make_manager, make_device):
        mgr = make_manager([make_device()])
        dev = mgr.devices[0]
        dev["runtime_today_s"] = 1234
        dev["force_started"] = True
        mgr.daily_reset()  # legacy call form (tests/simulations)
        assert dev["runtime_today_s"] == 0
        assert dev["force_started"] is False

    def test_first_call_records_boundary_without_reset(
            self, make_manager, make_device):
        mgr = make_manager([make_device()])
        dev = mgr.devices[0]
        dev["runtime_today_s"] = 900
        mgr.daily_reset(_at(12))
        # First call only anchors the boundary — no reset, no data loss.
        assert dev["runtime_today_s"] == 900
        assert dev["_last_reset"] is not None

    def test_midnight_default_resets_after_day_rollover(
            self, make_manager, make_device):
        mgr = make_manager([make_device(day_start_hour=0)])
        dev = mgr.devices[0]
        mgr.daily_reset(_at(23, 55))       # anchor to today 00:00
        dev["runtime_today_s"] = 600
        mgr.daily_reset(_at(23, 59))       # same day → no reset
        assert dev["runtime_today_s"] == 600
        # Next calendar day, 00:01 → crosses midnight boundary → reset
        nextday = datetime(2026, 7, 9, 0, 1, 0)
        mgr.daily_reset(nextday)
        assert dev["runtime_today_s"] == 0

    def test_day_start_hour_9_resets_at_9_not_midnight(
            self, make_manager, make_device):
        mgr = make_manager([make_device(day_start_hour=9)])
        dev = mgr.devices[0]
        # Anchor at 10:00 → boundary = today 09:00
        mgr.daily_reset(_at(10))
        dev["runtime_today_s"] = 330  # 5.5 h of overnight-ish runtime
        # Crossing midnight does NOT reset a 09:00 device
        mgr.daily_reset(datetime(2026, 7, 9, 0, 30, 0))
        assert dev["runtime_today_s"] == 330
        # Just before 09:00 next day → still not reset
        mgr.daily_reset(datetime(2026, 7, 9, 8, 59, 0))
        assert dev["runtime_today_s"] == 330
        # At 09:01 → crosses the 09:00 boundary → reset
        mgr.daily_reset(datetime(2026, 7, 9, 9, 1, 0))
        assert dev["runtime_today_s"] == 0

    def test_before_start_hour_anchors_to_previous_day(
            self, make_manager, make_device):
        mgr = make_manager([make_device(day_start_hour=9)])
        dev = mgr.devices[0]
        # First call at 03:00 (before 09:00) → boundary = yesterday 09:00
        mgr.daily_reset(_at(3))
        assert dev["_last_reset"] == datetime(2026, 7, 7, 9, 0, 0)
        dev["runtime_today_s"] = 200
        # Reaching 09:00 today → reset
        mgr.daily_reset(_at(9, 2))
        assert dev["runtime_today_s"] == 0

    def test_devices_reset_independently(
            self, make_manager, make_device):
        mgr = make_manager([
            make_device(name="Midnight Dev", switch_entity="switch.a",
                        day_start_hour=0),
            make_device(name="Nine Dev", switch_entity="switch.b",
                        day_start_hour=9),
        ])
        a, b = mgr.devices
        mgr.daily_reset(_at(10))  # anchor both
        a["runtime_today_s"] = 100
        b["runtime_today_s"] = 100
        # Cross midnight: only the day_start_hour=0 device resets
        mgr.daily_reset(datetime(2026, 7, 9, 0, 5, 0))
        assert a["runtime_today_s"] == 0
        assert b["runtime_today_s"] == 100
