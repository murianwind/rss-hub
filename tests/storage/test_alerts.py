from datetime import UTC, datetime, timedelta

import pytest

from rss_hub.storage.alerts import AlertRepository
from rss_hub.storage.database import Database
from tests.fakes.clock import FakeClock


@pytest.fixture
def clock():
    return FakeClock(datetime(2026, 10, 16, 12, 0, tzinfo=UTC))


@pytest.fixture
def alerts(tmp_path, clock):
    return AlertRepository(Database(tmp_path / "rss_hub.db"), clock)


def test_nothing_was_sent_at_first(alerts):
    assert alerts.last_sent("llm_cap") is None


def test_the_latest_send_time_per_kind_is_returned(alerts, clock):
    alerts.record("llm_cap", "첫 알림")
    clock.advance(hours=2)
    alerts.record("llm_cap", "두 번째 알림")
    alerts.record("billing", "다른 종류")
    assert alerts.last_sent("llm_cap") == clock.now()
    assert alerts.last_sent("billing") == clock.now()
    assert alerts.last_sent("other") is None


def test_kinds_do_not_affect_each_other(alerts, clock):
    alerts.record("a", "x")
    clock.advance(hours=1)
    assert alerts.last_sent("b") is None
    assert alerts.last_sent("a") == clock.now() - timedelta(hours=1)
