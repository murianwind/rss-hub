from datetime import UTC, datetime, timedelta, timezone

import pytest

from rss_hub.domain.jobs import SLOT_GRACE_SECONDS, due_slot, interval_due, latest_slot_start

KST = timezone(timedelta(hours=9))


def at(hour, minute, second=0):
    return datetime(2026, 10, 16, hour, minute, second, tzinfo=KST)


@pytest.mark.parametrize(
    ("now", "interval", "expected"),
    [
        (at(14, 0), 5, at(14, 0)),
        (at(14, 4, 59), 5, at(14, 0)),
        (at(14, 5), 5, at(14, 5)),
        (at(14, 22, 31), 5, at(14, 20)),
        (at(14, 59, 59), 15, at(14, 45)),
        (at(14, 37), 1, at(14, 37)),
        (at(14, 37), 60, at(14, 0)),
    ],
)
def test_the_latest_slot_start(now, interval, expected):
    assert latest_slot_start(now, interval) == expected


def test_a_slot_that_has_not_run_is_due_right_when_it_starts():
    assert due_slot(at(14, 20), at(14, 15), 5) == at(14, 20)


def test_a_slot_is_due_until_the_grace_period_ends():
    assert due_slot(at(14, 20, SLOT_GRACE_SECONDS - 1), at(14, 15), 5) == at(14, 20)
    assert due_slot(at(14, 21, 0), at(14, 15), 5) is None  # 5분 슬롯의 20분 시작에서 60초가 지났다


def test_a_slot_that_already_ran_is_not_due_again():
    assert due_slot(at(14, 20, 30), at(14, 20), 5) is None


def test_slots_missed_while_the_service_was_down_are_not_caught_up():
    # 14:00~14:20에 꺼져 있다가 14:20에 시작: 14:20 슬롯만 실행하고 14:05~14:15는 실행하지 않는다
    assert due_slot(at(14, 20, 5), at(14, 0), 5) == at(14, 20)
    # 14:23에 시작했다면 놓친 14:20 슬롯은 건너뛴다
    assert due_slot(at(14, 23), at(14, 0), 5) is None


def test_the_first_ever_run_happens_at_a_slot_start_and_not_in_the_middle_of_one():
    assert due_slot(at(14, 20, 3), None, 5) == at(14, 20)
    assert due_slot(at(14, 22), None, 5) is None


def test_a_slot_older_than_the_last_one_that_ran_is_ignored():
    assert due_slot(at(14, 20, 5), at(14, 25), 5) is None


@pytest.mark.parametrize(
    ("elapsed", "due"), [(None, True), (0, False), (59, False), (60, True), (61, True)]
)
def test_interval_jobs_run_when_the_interval_has_passed(elapsed, due):
    now = datetime(2026, 10, 16, 5, 0, tzinfo=UTC)
    last = None if elapsed is None else now - timedelta(seconds=elapsed)
    assert interval_due(now, last, 60) is due
