from datetime import UTC, datetime, timedelta

import pytest

from rss_hub.web.ui import until

NOW = datetime(2026, 10, 27, 5, 0, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        (timedelta(seconds=-30), "곧"),
        (timedelta(seconds=3), "곧"),
        (timedelta(seconds=30), "30초 뒤"),
        (timedelta(minutes=5), "5분 뒤"),
        (timedelta(hours=3), "3시간 뒤"),
        (timedelta(days=2), "2일 뒤"),
    ],
)
def test_until_reads_the_remaining_time(delta, expected):
    assert until(NOW + delta, NOW) == expected
