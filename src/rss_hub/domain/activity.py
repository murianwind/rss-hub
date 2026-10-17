"""피드의 최근 활동 측정: 스케줄의 추가 점검 횟수를 정하는 데 쓴다."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from rss_hub.domain.schedule import Activity

RECENT_WINDOW = timedelta(days=7)


@dataclass(frozen=True)
class FeedMeasurement:
    activity: Activity
    last_published: datetime | None


def measure_activity(
    published: Iterable[datetime | None], now: datetime, today: date
) -> FeedMeasurement:
    """발행 시각 목록에서 최근 7일 글 수, 오늘 글 수, 가장 최근 발행 시각을 센다.

    발행 시각을 알 수 없는 항목은 세지 않는다. 7일 창은 정확히 7일 전 시각을 포함한다.
    """
    cutoff = now - RECENT_WINDOW
    recent = 0
    todays = 0
    latest: datetime | None = None
    for moment in published:
        if moment is None:
            continue
        if moment >= cutoff:
            recent += 1
        if moment.date() == today:
            todays += 1
        if latest is None or moment > latest:
            latest = moment
    return FeedMeasurement(
        activity=Activity(recent_count_7d=recent, target_date_count=todays),
        last_published=latest,
    )
