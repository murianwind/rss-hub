from collections import Counter
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from pytest_bdd import given, parsers, then, when

from rss_hub.domain.jobs import due_slot
from rss_hub.domain.schedule import (
    PRIORITY_EVERY_SLOT,
    Activity,
    FeedRef,
    activity_score,
    build_schedule,
    desired_checks,
    slot_for,
    slots_per_hour,
)
from tests.bdd.binding import bind

# 서비스 계층(스케줄 재사용, 잡 겹침, 중단 후 재개)이 필요한 SCH-10~13은 이후 단계에서 연결한다
bind(
    globals(),
    "01_scheduling.feature",
    [f"SCH-0{i}" for i in range(1, 10)] + ["SCH-14", "SCH-15"],
)


def normal_feeds(count):
    return [FeedRef(f"f{i:03d}") for i in range(count)]


def occurrences(schedule):
    return Counter(key for batch in schedule.batches for key in batch)


@pytest.fixture
def ctx():
    return SimpleNamespace(
        interval=5,
        base_batch=15,
        feeds=[],
        activity={},
        schedule=None,
        focus=None,
        slot=None,
        every=[],
        normal=[],
        minutes=[],
    )


# ---------- 배경 ----------


@given('서비스 시간대는 "Asia/Seoul"이다')
def _timezone():
    """시간대는 이 계층(순수 함수)에서 쓰이지 않는다."""


@given("수집 주기는 5분이다")
def _default_interval(ctx):
    ctx.interval = 5


@given("한 슬롯의 기본 배치 크기는 15이다")
def _default_batch(ctx):
    ctx.base_batch = 15


# ---------- 피드 준비 ----------


@given(parsers.parse("활성 피드 {count:d}개가 있다"))
def _feeds(ctx, count):
    ctx.feeds = normal_feeds(count)


@given(parsers.parse("활성 피드 {count:d}개가 있고 한 시간 용량은 {capacity:d}회이다"))
def _feeds_with_capacity(ctx, count, capacity):
    ctx.feeds = normal_feeds(count)
    ctx.expected_capacity = capacity


@given(parsers.parse("수집 주기가 {interval:d}분이고 활성 피드 {count:d}개가 있다"))
def _interval_and_feeds(ctx, interval, count):
    ctx.interval = interval
    ctx.feeds = normal_feeds(count)


@given(parsers.parse("수집 주기가 {interval:d}분이다"))
def _interval(ctx, interval):
    ctx.interval = interval


@given("목표 점검 횟수의 합이 용량을 넘을 만큼 활동이 많은 피드가 있다")
def _busy_feeds(ctx):
    # 활동 점수가 서로 다른 세 그룹: 점검 횟수 합이 여유 용량(46)을 훨씬 넘는다
    for index, feed in enumerate(ctx.feeds):
        if index < 10:
            ctx.activity[feed.key] = Activity(recent_count_7d=20, target_date_count=5)
        elif index < 60:
            ctx.activity[feed.key] = Activity(target_date_count=3)
        else:
            ctx.activity[feed.key] = Activity(recent_count_7d=2)


@given("시간당 3회 점검 대상인 피드가 있다")
def _three_checks_feed(ctx):
    ctx.feeds = normal_feeds(3)
    ctx.focus = ctx.feeds[0].key
    ctx.activity = {ctx.focus: Activity(target_date_count=3)}


@given(
    parsers.parse('폴링 우선순위가 "every_slot"인 피드가 {count:d}개 있고 활동 통계는 비어 있다')
)
def _every_slot_without_stats(ctx, count):
    ctx.every = [FeedRef(f"hot{i:02d}", priority=PRIORITY_EVERY_SLOT) for i in range(count)]
    ctx.focus = ctx.every[0].key
    ctx.feeds = [*normal_feeds(133), *ctx.every]
    ctx.activity = {}


@given(parsers.parse('폴링 우선순위가 "every_slot"인 피드가 {count:d}개 있다'))
def _every_slot_feeds(ctx, count):
    ctx.every = [FeedRef(f"hot{i:02d}", priority=PRIORITY_EVERY_SLOT) for i in range(count)]
    ctx.focus = ctx.every[0].key
    ctx.feeds = list(ctx.every)


@given("다른 모든 피드의 활동 점수가 이 피드보다 높다")
def _others_busier(ctx):
    others = normal_feeds(133)
    ctx.feeds = [*others, *ctx.every]
    ctx.activity = {f.key: Activity(recent_count_7d=30, target_date_count=30) for f in others}
    ctx.activity[ctx.focus] = Activity(recent_count_7d=50, target_date_count=10)


@given(parsers.parse("일반 피드가 {count:d}개 있다"))
def _normal_feeds(ctx, count):
    ctx.normal = normal_feeds(count)
    ctx.feeds = [*ctx.every, *ctx.normal]


@given(parsers.parse("어떤 피드의 오늘 글 수는 {today:d}건이고 최근 7일 글 수는 {week:d}건이다"))
def _activity(ctx, today, week):
    ctx.focus_feed = FeedRef("x")
    ctx.focus_activity = Activity(recent_count_7d=week, target_date_count=today)


# ---------- 동작 ----------


@when("이번 시간의 스케줄을 만든다")
def _build(ctx):
    ctx.schedule = build_schedule(ctx.feeds, ctx.activity, ctx.interval, ctx.base_batch)


@when(parsers.parse("현재 시각이 14시 {minute:d}분이다"))
def _now(ctx, minute):
    ctx.slot = slot_for(minute, ctx.interval)


@when("14시 한 시간 동안의 수집 실행 시각을 계산한다")
def _run_times(ctx):
    """잡이 매 분 0초에 점검한다고 보고, 실제 판정(due_slot)이 "실행"이라고 하는 분을 모은다."""
    hour = datetime(2026, 10, 16, 14, tzinfo=ZoneInfo("Asia/Seoul"))
    ctx.minutes = [
        minute
        for minute in range(60)
        if due_slot(hour.replace(minute=minute), None, ctx.interval) is not None
    ]


# ---------- 검증 ----------


@then("12개 슬롯에 걸쳐 모든 피드가 1번 이상 포함된다")
def _twelve_slots_all_covered(ctx):
    assert len(ctx.schedule.batches) == 12
    assert set(occurrences(ctx.schedule)) == {f.key for f in ctx.feeds}


@then("모든 피드가 1번 이상 점검된다")
def _all_covered(ctx):
    assert set(occurrences(ctx.schedule)) == {f.key for f in ctx.feeds}


@then(parsers.parse("배치 크기는 {size:d}이다"))
def _batch_size(ctx, size):
    assert ctx.schedule.batch_size == size


@then(parsers.parse("모든 슬롯의 피드 수는 {size:d} 이하이다"))
def _slot_sizes(ctx, size):
    assert all(len(batch) <= size for batch in ctx.schedule.batches)


@then(parsers.parse("시간당 슬롯 수는 {slots:d}이다"))
def _slots(ctx, slots):
    assert ctx.schedule.slots == slots == slots_per_hour(ctx.interval)


@then(parsers.parse("이 피드의 시간당 목표 점검 횟수는 {checks:d}회이다"))
def _desired(ctx, checks):
    slots = slots_per_hour(ctx.interval)
    assert desired_checks(ctx.focus_feed, ctx.focus_activity, slots) == checks


@then(parsers.parse("이 피드의 활동 점수는 {score:d}이다"))
def _score(ctx, score):
    assert activity_score(ctx.focus_activity) == score


@then(parsers.parse("추가 점검은 {limit:d}회를 넘지 않는다"))
def _extras_limit(ctx, limit):
    assert ctx.schedule.capacity == ctx.expected_capacity
    assert ctx.schedule.extras_scheduled <= limit


@then(
    "추가 점검을 일부라도 받지 못한 피드의 활동 점수는 "
    "추가 점검을 모두 받은 어떤 피드의 점수보다도 높지 않다"
)
def _extras_by_score(ctx):
    counts = occurrences(ctx.schedule)
    served, starved = [], []
    for feed in ctx.feeds:
        activity = ctx.activity.get(feed.key, Activity())
        wanted = desired_checks(feed, activity, ctx.schedule.slots) - 1
        received = counts[feed.key] - 1
        if wanted <= 0:
            continue
        (served if received >= wanted else starved).append(activity_score(activity))
    assert starved, "시나리오가 용량 부족 상황을 만들지 못했다"
    assert served, "시나리오가 추가 점검을 모두 받은 피드를 만들지 못했다"
    assert max(starved) <= min(served)


@then("이 피드는 서로 다른 3개 슬롯에 들어 있다")
def _three_distinct_slots(ctx):
    slots = [i for i, batch in enumerate(ctx.schedule.batches) if ctx.focus in batch]
    assert len(slots) == 3


@then("한 슬롯에 같은 피드가 두 번 들어가지 않는다")
def _no_duplicates(ctx):
    assert all(len(set(batch)) == len(batch) for batch in ctx.schedule.batches)


@then("이 피드는 12개 슬롯 모두에 들어 있다")
def _focus_in_all_slots(ctx):
    assert all(ctx.focus in batch for batch in ctx.schedule.batches)


@then(parsers.parse('"every_slot" 피드 {count:d}개는 모두 12개 슬롯에 들어 있다'))
def _every_feeds_everywhere(ctx, count):
    assert len(ctx.every) == count
    assert all(key in batch for key in (f.key for f in ctx.every) for batch in ctx.schedule.batches)


@then(parsers.parse("일반 피드 {count:d}개는 모두 1번 이상 점검된다"))
def _normal_covered(ctx, count):
    counts = occurrences(ctx.schedule)
    assert len(ctx.normal) == count
    assert all(counts[f.key] >= 1 for f in ctx.normal)


@then(parsers.parse("슬롯 번호는 {slot:d}이다"))
def _slot_number(ctx, slot):
    assert ctx.slot == slot


@then(parsers.parse("실행은 {count:d}번이고 첫 시각은 14:00, 마지막 시각은 {last}이다"))
def _run_count_and_last(ctx, count, last):
    times = [f"14:{m:02d}" for m in ctx.minutes]
    assert len(times) == count
    assert times[0] == "14:00"
    assert times[-1] == last


@then("모든 실행 시각의 분은 수집 주기의 배수이다")
def _multiples(ctx):
    assert all(m % ctx.interval == 0 for m in ctx.minutes)
