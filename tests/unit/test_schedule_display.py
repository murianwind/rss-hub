"""피드마다 실제로 배정된 수집 주기(활동량에 따라 자동으로 달라지는 값)를 보여 주는 규칙."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from rss_hub.domain.schedule import (
    Activity,
    FeedRef,
    build_schedule,
    describe_cycle,
    feed_cycles,
    next_check,
)

SEOUL = ZoneInfo("Asia/Seoul")
QUIET, WEEKLY, TODAY, BUSY = Activity(0, 0), Activity(2, 0), Activity(0, 1), Activity(10, 3)


def cycles(activity, *, interval=5, batch=15):
    keys = list(activity)
    schedule = build_schedule([FeedRef(k) for k in keys], activity, interval, batch)
    return feed_cycles(schedule, interval, activity, keys)


def test_a_quiet_feed_is_checked_once_an_hour_and_a_busy_one_up_to_three_times():
    found = cycles({"quiet": QUIET, "weekly": WEEKLY, "today": TODAY, "busy": BUSY})
    assert [found[k].checks_per_hour for k in ("quiet", "weekly", "today", "busy")] == [1, 2, 2, 3]
    assert [found[k].wanted for k in ("quiet", "weekly", "today", "busy")] == [1, 2, 2, 3]


def test_the_minutes_are_the_real_slot_times_in_order_and_never_repeat():
    found = cycles({"busy": BUSY, "quiet": QUIET})
    for cycle in found.values():
        assert (
            list(cycle.minutes) == sorted(set(cycle.minutes))
            and len(cycle.minutes) == cycle.checks_per_hour
        )
        assert all(m % 5 == 0 and 0 <= m < 60 for m in cycle.minutes)


def test_the_minutes_follow_the_collection_interval():
    found = cycles({"a": BUSY}, interval=15)
    assert all(m in (0, 15, 30, 45) for m in found["a"].minutes)


def test_when_the_capacity_is_short_a_busy_feed_gets_fewer_checks_than_it_wanted():
    # 슬롯당 1개, 주기 30분(슬롯 2개)이면 피드 두 개가 한 번씩 점검하면 용량이 다 찬다
    found = cycles({"a": BUSY, "b": BUSY}, interval=30, batch=1)
    assert [found[k].checks_per_hour for k in ("a", "b")] == [1, 1]
    assert [found[k].wanted for k in ("a", "b")] == [3, 3]


def test_a_feed_that_is_not_in_the_schedule_has_no_cycle():
    schedule = build_schedule([FeedRef("a")], {}, 5)
    assert "ghost" not in feed_cycles(schedule, 5, {}, ["a", "ghost"])


@pytest.mark.parametrize(
    ("minutes", "wanted", "text"),
    [
        ((0,), 1, "시간당 1회(약 60분마다)"),
        ((0, 30), 2, "시간당 2회(약 30분마다)"),
        ((0, 20, 40), 3, "시간당 3회(약 20분마다)"),
        ((5, 25), 3, "시간당 2회(약 30분마다)"),
    ],
)
def test_the_cycle_is_described_in_plain_korean(minutes, wanted, text):
    from rss_hub.domain.schedule import FeedCycle

    assert describe_cycle(FeedCycle(len(minutes), minutes, wanted)) == text


@pytest.mark.parametrize(
    ("now", "minutes", "expected"),
    [
        (
            datetime(2026, 10, 20, 14, 7, 20, tzinfo=SEOUL),
            (5, 35),
            datetime(2026, 10, 20, 14, 35, tzinfo=SEOUL),
        ),
        (
            datetime(2026, 10, 20, 14, 40, 0, tzinfo=SEOUL),
            (5, 35),
            datetime(2026, 10, 20, 15, 5, tzinfo=SEOUL),
        ),
        (
            datetime(2026, 10, 20, 14, 35, 10, tzinfo=SEOUL),
            (5, 35),
            datetime(2026, 10, 20, 15, 5, tzinfo=SEOUL),
        ),
        (
            datetime(2026, 10, 20, 23, 59, 0, tzinfo=SEOUL),
            (10,),
            datetime(2026, 10, 21, 0, 10, tzinfo=SEOUL),
        ),
    ],
)
def test_the_next_check_is_the_next_scheduled_minute_even_across_the_hour_and_the_day(
    now, minutes, expected
):
    assert next_check(now, minutes) == expected


def test_there_is_no_next_check_without_minutes():
    assert next_check(datetime(2026, 10, 20, 14, 0, tzinfo=SEOUL), ()) is None
