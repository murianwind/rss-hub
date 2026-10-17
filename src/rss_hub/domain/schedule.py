"""수집 스케줄: 한 시간을 같은 길이의 슬롯으로 나누고, 슬롯마다 점검할 피드를 정한다.

- 모든 피드는 한 시간에 최소 한 번 점검된다.
- 활동량이 많은 피드는 남는 용량 안에서 더 자주(최대 3회) 점검된다.
- 폴링 우선순위가 "every_slot"인 피드는 활동 이력과 상관없이 모든 슬롯에서 점검된다.
"""

import hashlib
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

MINUTES_PER_HOUR = 60
DEFAULT_BATCH_SIZE = 15
PRIORITY_NORMAL = "normal"
PRIORITY_EVERY_SLOT = "every_slot"

# 오늘 글 수 × 100 + 최근 7일 글 수 × 10: 오늘의 활동을 가장 크게 본다
TODAY_WEIGHT = 100
WEEK_WEIGHT = 10


@dataclass(frozen=True)
class FeedRef:
    """스케줄 계산에 필요한 피드 정보."""

    key: str
    priority: str = PRIORITY_NORMAL


@dataclass(frozen=True)
class Activity:
    """피드의 최근 활동량(마지막 점검 때 계산한 값)."""

    recent_count_7d: int = 0
    target_date_count: int = 0


@dataclass(frozen=True)
class Schedule:
    """한 시간 분량의 스케줄. batches[i]는 i번 슬롯에서 점검할 피드 키 목록."""

    slots: int
    batch_size: int
    capacity: int
    extra_capacity: int
    extras_scheduled: int
    batches: tuple[tuple[str, ...], ...]


def slots_per_hour(interval_minutes: int) -> int:
    """시간당 슬롯 수. 수집 주기는 60의 약수여야 슬롯이 시각과 어긋나지 않는다."""
    if interval_minutes < 1 or MINUTES_PER_HOUR % interval_minutes != 0:
        raise ValueError(f"수집 주기는 60의 약수여야 합니다: {interval_minutes}")
    return MINUTES_PER_HOUR // interval_minutes


def slot_for(minute: int, interval_minutes: int) -> int:
    """현재 시각의 분(0~59)이 속한 슬롯 번호."""
    slots = slots_per_hour(interval_minutes)
    return min(slots - 1, max(0, minute // interval_minutes))


def run_minutes(interval_minutes: int) -> list[int]:
    """한 시간 안에서 수집 잡이 실행되는 분 목록(주기의 배수)."""
    return list(range(0, MINUTES_PER_HOUR, interval_minutes))


def activity_score(activity: Activity) -> int:
    """추가 점검의 우선순위를 정하는 점수."""
    return activity.target_date_count * TODAY_WEIGHT + activity.recent_count_7d * WEEK_WEIGHT


def desired_checks(feed: FeedRef, activity: Activity, slots: int) -> int:
    """시간당 목표 점검 횟수. every_slot 피드는 슬롯 수만큼, 나머지는 활동량에 따라 1~3회."""
    if feed.priority == PRIORITY_EVERY_SLOT:
        return slots
    if activity.target_date_count >= 3 or activity.recent_count_7d >= 7:
        return 3
    if activity.target_date_count >= 1 or activity.recent_count_7d >= 2:
        return 2
    return 1


def build_schedule(
    feeds: Sequence[FeedRef],
    activity: Mapping[str, Activity],
    interval_minutes: int,
    base_batch_size: int = DEFAULT_BATCH_SIZE,
) -> Schedule:
    """피드 목록과 활동량으로 한 시간 분량의 스케줄을 만든다. 같은 입력이면 항상 같은 결과다."""
    slots = slots_per_hour(interval_minutes)
    every = [f for f in feeds if f.priority == PRIORITY_EVERY_SLOT]
    normal = [f for f in feeds if f.priority != PRIORITY_EVERY_SLOT]

    required = len(every) * slots + len(normal)
    batch_size = max(base_batch_size, math.ceil(required / slots))
    capacity = batch_size * slots
    extra_capacity = max(0, capacity - required)

    batches: list[list[str]] = [[f.key for f in every] for _ in range(slots)]
    for index, feed in enumerate(normal):
        batches[index % slots].append(feed.key)

    extras_scheduled = _add_extra_checks(batches, normal, activity, slots, extra_capacity)

    return Schedule(
        slots=slots,
        batch_size=batch_size,
        capacity=capacity,
        extra_capacity=extra_capacity,
        extras_scheduled=extras_scheduled,
        batches=tuple(tuple(batch) for batch in batches),
    )


def _add_extra_checks(
    batches: list[list[str]],
    normal: Sequence[FeedRef],
    activity: Mapping[str, Activity],
    slots: int,
    extra_capacity: int,
) -> int:
    """남는 용량에 활동 점수가 높은 피드의 추가 점검을 채운다. 배정한 추가 점검 수를 돌려준다."""
    candidates: list[tuple[int, int, str]] = []
    for feed in normal:
        feed_activity = activity.get(feed.key, Activity())
        score = activity_score(feed_activity)
        for copy_no in range(desired_checks(feed, feed_activity, slots) - 1):
            candidates.append((-score, copy_no, feed.key))
    candidates.sort()  # 점수 높은 순 → 첫 번째 추가 점검 먼저 → 키 순(결정적 순서)

    added = 0
    for _, _, key in candidates:
        if added >= extra_capacity:
            break
        slot = _quietest_slot_without(batches, key)
        if slot is None:  # 이 피드가 이미 모든 슬롯에 있으면 더 넣지 않는다(같은 슬롯에 중복 금지)
            continue
        batches[slot].append(key)
        added += 1
    return added


def _quietest_slot_without(batches: Sequence[Sequence[str]], key: str) -> int | None:
    """key가 아직 없는 슬롯 중 피드가 가장 적은 슬롯(동률이면 번호가 작은 쪽)."""
    best: int | None = None
    for index, batch in enumerate(batches):
        if key in batch:
            continue
        if best is None or len(batch) < len(batches[best]):
            best = index
    return best


def schedule_fingerprint(
    feeds: Sequence[FeedRef],
    interval_minutes: int,
    target_date: str,
    hour_key: str,
    base_batch_size: int = DEFAULT_BATCH_SIZE,
) -> str:
    """스케줄을 다시 만들어야 하는지 판단하는 값. 같으면 만들어 둔 스케줄을 재사용한다.

    피드 개수가 아니라 구성(키와 우선순위)을 본다. 순서는 상관없다.
    """
    members = ",".join(sorted(f"{f.key}:{f.priority}" for f in feeds))
    raw = f"{hour_key}|{target_date}|{interval_minutes}|{base_batch_size}|{members}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()
