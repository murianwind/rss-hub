"""피드 관리 화면에 보여 줄 피드 정보를 한꺼번에 읽는다(상태, 활동량, 글 수 포함)."""

from dataclasses import dataclass
from datetime import datetime

from rss_hub.storage.articles import VIEWABLE_STATUSES
from rss_hub.storage.database import Database
from rss_hub.storage.reader import feed_state


@dataclass(frozen=True)
class FeedOverview:
    id: int
    name: str
    emoji: str
    url: str
    site_url: str
    category_id: int | None
    category_name: str
    webhook_id: int | None
    max_entries: int | None
    status: str  # baseline_pending(첫 점검 전), active
    state: str  # ok, error, never
    fail_count: int
    last_error: str
    last_checked_at: datetime | None
    recent_count_7d: int
    today_count: int
    last_published: datetime | None
    total: int
    unread: int
    kind: str = "feed"  # feed 또는 page(웹페이지 구독)


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class OverviewRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def feeds(self) -> list[FeedOverview]:
        """사이드바와 같은 순서(저장한 순서, 이름순)로 피드 전체."""
        marks = ",".join("?" for _ in VIEWABLE_STATUSES)
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT f.*, c.name AS category_name, s.recent_count_7d, s.target_date_count, "
                "s.last_published_dt, COALESCE(a.total, 0) AS total, "
                "COALESCE(a.unread, 0) AS unread "
                "FROM feeds f LEFT JOIN categories c ON c.id = f.category_id "
                "LEFT JOIN feed_stats s ON s.feed_id = f.id LEFT JOIN ("
                "SELECT feed_id, COUNT(*) AS total, SUM(read_at IS NULL) AS unread FROM articles "
                f"WHERE status IN ({marks}) GROUP BY feed_id) a ON a.feed_id = f.id "
                "ORDER BY f.sort_order, LOWER(f.name), f.id",
                list(VIEWABLE_STATUSES),
            ).fetchall()
        return [
            FeedOverview(
                id=r["id"],
                name=r["name"],
                emoji=r["emoji"],
                url=r["url"],
                site_url=r["html_url"] or "",
                category_id=r["category_id"],
                category_name=r["category_name"] or "",
                webhook_id=r["webhook_id"],
                max_entries=r["max_entries"],
                status=r["status"],
                state=feed_state(r["fail_count"], r["last_checked_at"]),
                fail_count=r["fail_count"],
                last_error=r["last_error"] or "",
                last_checked_at=_parse(r["last_checked_at"]),
                recent_count_7d=r["recent_count_7d"] or 0,
                today_count=r["target_date_count"] or 0,
                last_published=_parse(r["last_published_dt"]),
                total=r["total"],
                unread=r["unread"],
                kind=r["kind"],
            )
            for r in rows
        ]
