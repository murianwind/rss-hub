from datetime import UTC, datetime, timedelta

from rss_hub.services.clock import SystemClock


def test_system_clock_returns_the_current_time_with_a_timezone():
    now = SystemClock().now()
    assert now.tzinfo is not None
    assert abs(now - datetime.now(UTC)) < timedelta(seconds=5)
