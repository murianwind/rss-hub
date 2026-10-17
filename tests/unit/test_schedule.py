from collections import Counter

import pytest

from rss_hub.domain.schedule import (
    PRIORITY_EVERY_SLOT,
    PRIORITY_NORMAL,
    Activity,
    FeedRef,
    activity_score,
    build_schedule,
    desired_checks,
    run_minutes,
    schedule_fingerprint,
    slot_for,
    slots_per_hour,
)


def normal_feeds(count, prefix="f"):
    return [FeedRef(key=f"{prefix}{i:03d}") for i in range(count)]


def occurrences(schedule):
    return Counter(key for batch in schedule.batches for key in batch)


# ---------- 슬롯과 실행 시각 ----------


@pytest.mark.parametrize(
    ("interval", "slots"), [(1, 60), (2, 30), (5, 12), (10, 6), (15, 4), (30, 2), (60, 1)]
)
def test_slots_per_hour(interval, slots):
    assert slots_per_hour(interval) == slots


@pytest.mark.parametrize("interval", [0, -5, 7, 8, 9, 11, 25, 61, 120])
def test_slots_per_hour_rejects_intervals_that_do_not_divide_an_hour(interval):
    with pytest.raises(ValueError, match="60"):
        slots_per_hour(interval)


@pytest.mark.parametrize(
    ("interval", "minute", "slot"),
    [
        (5, 0, 0),
        (5, 4, 0),
        (5, 5, 1),
        (5, 59, 11),
        (10, 25, 2),
        (15, 44, 2),
        (60, 59, 0),
        (1, 59, 59),
    ],
)
def test_slot_for(interval, minute, slot):
    assert slot_for(minute, interval) == slot


def test_run_minutes_are_multiples_of_the_interval():
    assert run_minutes(5) == list(range(0, 60, 5))
    assert run_minutes(30) == [0, 30]
    assert run_minutes(60) == [0]


# ---------- 활동 점수와 목표 횟수 ----------


@pytest.mark.parametrize(
    ("today", "week", "checks", "score"),
    [
        (0, 0, 1, 0),
        (0, 2, 2, 20),
        (0, 6, 2, 60),
        (1, 1, 2, 110),
        (2, 0, 2, 200),
        (0, 7, 3, 70),
        (3, 0, 3, 300),
    ],
)
def test_desired_checks_and_score(today, week, checks, score):
    activity = Activity(recent_count_7d=week, target_date_count=today)
    feed = FeedRef("x")
    assert desired_checks(feed, activity, slots=12) == checks
    assert activity_score(activity) == score


def test_every_slot_feed_wants_one_check_per_slot_regardless_of_activity():
    feed = FeedRef("x", priority=PRIORITY_EVERY_SLOT)
    assert desired_checks(feed, Activity(), slots=12) == 12
    assert desired_checks(feed, Activity(), slots=6) == 6


# ---------- 스케줄 만들기 ----------


def test_every_feed_is_checked_at_least_once_per_hour():
    feeds = normal_feeds(134)
    schedule = build_schedule(feeds, {}, interval_minutes=5)
    counts = occurrences(schedule)
    assert set(counts) == {f.key for f in feeds}
    assert min(counts.values()) >= 1
    assert len(schedule.batches) == 12


@pytest.mark.parametrize(("feeds", "batch"), [(134, 15), (180, 15), (181, 16), (200, 17)])
def test_batch_size_grows_with_feed_count(feeds, batch):
    schedule = build_schedule(normal_feeds(feeds), {}, interval_minutes=5)
    assert schedule.batch_size == batch
    assert all(len(b) <= batch for b in schedule.batches)
    assert schedule.capacity == batch * 12


@pytest.mark.parametrize(
    ("interval", "slots", "batch"),
    [(1, 60, 15), (5, 12, 15), (10, 6, 23), (15, 4, 34), (30, 2, 67), (60, 1, 134)],
)
def test_batch_size_for_different_intervals(interval, slots, batch):
    schedule = build_schedule(normal_feeds(134), {}, interval_minutes=interval)
    assert schedule.slots == slots
    assert schedule.batch_size == batch
    assert set(occurrences(schedule)) == {f.key for f in normal_feeds(134)}


def test_extra_checks_never_exceed_spare_capacity():
    feeds = normal_feeds(134)
    activity = {f.key: Activity(recent_count_7d=20, target_date_count=4) for f in feeds}
    schedule = build_schedule(feeds, activity, interval_minutes=5)
    assert schedule.extra_capacity == 46
    assert schedule.extras_scheduled == 46
    assert sum(occurrences(schedule).values()) == 134 + 46


def test_extra_checks_go_to_higher_scores_first():
    feeds = normal_feeds(134)
    activity = {f.key: Activity(recent_count_7d=2) for f in feeds}  # 목표 2회, 점수 20
    activity["f000"] = Activity(target_date_count=5)  # 점수 500
    activity["f001"] = Activity(target_date_count=1)  # 점수 100
    schedule = build_schedule(feeds, activity, interval_minutes=5)
    counts = occurrences(schedule)
    assert counts["f000"] == 3
    assert counts["f001"] == 2


def test_repeated_checks_of_a_feed_use_different_slots():
    feeds = normal_feeds(3)
    activity = {"f000": Activity(target_date_count=3)}
    schedule = build_schedule(feeds, activity, interval_minutes=5)
    slots_with_feed = [i for i, b in enumerate(schedule.batches) if "f000" in b]
    assert len(slots_with_feed) == 3
    assert all(len(set(b)) == len(b) for b in schedule.batches)


def test_no_duplicate_feed_inside_a_slot_even_when_slots_are_scarce():
    feeds = normal_feeds(5)
    activity = {f.key: Activity(target_date_count=5) for f in feeds}
    schedule = build_schedule(feeds, activity, interval_minutes=30)  # 슬롯 2개, 목표 3회
    assert all(len(set(b)) == len(b) for b in schedule.batches)
    assert all(count <= 2 for count in occurrences(schedule).values())


def test_every_slot_feed_is_in_all_slots_without_any_activity_stats():
    feeds = [*normal_feeds(133), FeedRef("hot", priority=PRIORITY_EVERY_SLOT)]
    schedule = build_schedule(feeds, {}, interval_minutes=5)
    assert all("hot" in b for b in schedule.batches)


def test_every_slot_feed_is_not_displaced_by_more_active_feeds():
    feeds = [*normal_feeds(133), FeedRef("hot", priority=PRIORITY_EVERY_SLOT)]
    activity = {f.key: Activity(recent_count_7d=30, target_date_count=30) for f in feeds}
    activity["hot"] = Activity(recent_count_7d=50, target_date_count=10)
    schedule = build_schedule(feeds, activity, interval_minutes=5)
    assert all("hot" in b for b in schedule.batches)


def test_many_every_slot_feeds_enlarge_the_batch_and_keep_normal_feeds_covered():
    every = [FeedRef(f"e{i:02d}", priority=PRIORITY_EVERY_SLOT) for i in range(20)]
    normal = normal_feeds(114)
    schedule = build_schedule([*every, *normal], {}, interval_minutes=5)
    assert schedule.batch_size == 30
    counts = occurrences(schedule)
    assert all(counts[f.key] == 12 for f in every)
    assert all(counts[f.key] >= 1 for f in normal)
    assert all(len(b) <= 30 for b in schedule.batches)


def test_schedule_is_deterministic():
    feeds = normal_feeds(50)
    activity = {
        f.key: Activity(recent_count_7d=i % 9, target_date_count=i % 4) for i, f in enumerate(feeds)
    }
    assert build_schedule(feeds, activity, 5) == build_schedule(feeds, activity, 5)


def test_empty_feed_list_gives_empty_slots():
    schedule = build_schedule([], {}, interval_minutes=5)
    assert schedule.batches == ((),) * 12


def test_invalid_interval_is_rejected():
    with pytest.raises(ValueError, match="60"):
        build_schedule(normal_feeds(3), {}, interval_minutes=7)


# ---------- 재사용 판단 ----------


def fingerprint(**overrides):
    args = {
        "feeds": normal_feeds(3),
        "interval_minutes": 5,
        "target_date": "2026-10-16",
        "hour_key": "2026-10-16T14",
        "base_batch_size": 15,
    }
    args.update(overrides)
    return schedule_fingerprint(**args)


def test_fingerprint_is_stable_for_same_input_and_ignores_feed_order():
    assert fingerprint() == fingerprint()
    assert fingerprint(feeds=list(reversed(normal_feeds(3)))) == fingerprint()


@pytest.mark.parametrize(
    "change",
    [
        {"hour_key": "2026-10-16T15"},
        {"target_date": "2026-10-17"},
        {"interval_minutes": 10},
        {"base_batch_size": 20},
        {"feeds": [*normal_feeds(3), FeedRef("extra")]},
        {"feeds": normal_feeds(2)},
        {"feeds": [FeedRef("f000"), FeedRef("f001"), FeedRef("other")]},  # 개수는 같고 구성이 다름
        {
            "feeds": [
                FeedRef("f000"),
                FeedRef("f001"),
                FeedRef("f002", priority=PRIORITY_EVERY_SLOT),
            ]
        },
    ],
)
def test_fingerprint_changes_when_inputs_change(change):
    assert fingerprint(**change) != fingerprint()


def test_priority_constants_are_distinct():
    assert PRIORITY_NORMAL != PRIORITY_EVERY_SLOT
