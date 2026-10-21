from datetime import UTC, date, datetime, timedelta

import pytest

from rss_hub.storage.database import Database
from rss_hub.storage.llm_usage import LlmUsageRepository
from tests.fakes.clock import FakeClock
from tests.keywords.store import raw_connection, usage_breakdown


@pytest.fixture
def clock():
    return FakeClock(datetime(2026, 10, 16, 12, 0, tzinfo=UTC))


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "rss_hub.db")


@pytest.fixture
def usage(db, clock):
    return LlmUsageRepository(db, clock)


def test_every_call_is_counted_for_its_utc_day(usage):
    usage.record(model="a", outcome="success", status=200)
    usage.record(model="a", outcome="rate_limited", status=429)
    assert usage.count_day(date(2026, 10, 16)) == 2
    assert usage.count_day(date(2026, 10, 15)) == 0


def test_the_day_is_decided_in_utc_not_local_time(usage, clock):
    clock.set(datetime(2026, 10, 16, 23, 59, tzinfo=UTC))  # 한국 시간으로는 이미 17일
    usage.record(model="a", outcome="success", status=200)
    clock.set(datetime(2026, 10, 17, 0, 0, 1, tzinfo=UTC))
    usage.record(model="a", outcome="success", status=200)
    assert usage.count_day(date(2026, 10, 16)) == 1
    assert usage.count_day(date(2026, 10, 17)) == 1


def test_count_since_covers_a_sliding_window(usage, clock):
    usage.record(model="a", outcome="success", status=200)
    clock.advance(seconds=59)
    usage.record(model="a", outcome="success", status=200)
    clock.advance(seconds=2)  # 첫 호출은 61초 전
    now = clock.now()
    assert usage.count_since(now - timedelta(seconds=60)) == 1
    assert usage.count_since(now - timedelta(seconds=62)) == 2


def test_breakdown_separates_models_and_outcomes(db, usage):
    usage.record(model="a", outcome="success", status=200)
    usage.record(model="a", outcome="success", status=200)
    usage.record(model="a", outcome="unavailable", status=503)
    usage.record(model="b", outcome="success", status=200)
    assert usage_breakdown(db, date(2026, 10, 16)) == {
        "a": {"success": 2, "unavailable": 1},
        "b": {"success": 1},
    }


def test_token_numbers_are_stored_for_later_analysis(usage, tmp_path):

    usage.record(
        model="a",
        outcome="success",
        status=200,
        prompt_tokens=250,
        completion_tokens=100,
        reasoning_tokens=0,
    )
    with raw_connection(tmp_path / "rss_hub.db") as conn:
        row = conn.execute(
            "SELECT prompt_tokens, completion_tokens, reasoning_tokens FROM llm_usage"
        ).fetchone()
    assert tuple(row) == (250, 100, 0)


def test_empty_day_has_an_empty_breakdown(db, usage):
    assert usage_breakdown(db, date(2026, 1, 1)) == {}
