"""피드 저장소: 피드, 점검 결과, 활동 통계."""

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from rss_hub.domain.activity import FeedMeasurement
from rss_hub.domain.feed_url import feed_url_key
from rss_hub.domain.schedule import PRIORITY_NORMAL, Activity
from rss_hub.services.clock import Clock
from rss_hub.storage.database import Database

STATUS_BASELINE = "baseline_pending"
STATUS_ACTIVE = "active"
DEFAULT_EMOJI = "📢"


class DuplicateFeedError(Exception):
    """같은 피드(정규화한 주소가 같은 피드)가 이미 있다."""


@dataclass(frozen=True)
class Feed:
    id: int
    url: str
    name: str
    html_url: str
    category_id: int | None
    webhook_id: int | None  # 카테고리에 속하지 않은 피드만 지정할 수 있다
    emoji: str
    poll_priority: str
    max_entries: int | None
    status: str
    fail_count: int
    last_error: str | None
    etag: str | None
    last_modified: str | None
    last_checked_at: datetime | None


RULE_CATEGORY_FEED_WEBHOOK = "카테고리에 속한 피드는 웹훅을 지정할 수 없음"
RULE_FEED_WEBHOOK_BLOCKS_CATEGORY = (
    "웹훅이 지정된 피드는 카테고리에 넣을 수 없음(먼저 웹훅 지정을 해제하세요)"
)
RULE_WEBHOOK_MISSING = "웹훅을 찾을 수 없음"
RULE_CATEGORY_MISSING = "카테고리를 찾을 수 없음"


class FeedRuleError(Exception):
    """피드의 웹훅과 카테고리 규칙을 어겼다. message는 화면에 그대로 보여 줄 수 있다."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class Category:
    id: int
    name: str
    webhook_id: int | None
    feed_count: int


@dataclass(frozen=True)
class StoredStats:
    recent_count_7d: int
    target_date_count: int
    last_published: datetime | None


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _feed(row: sqlite3.Row) -> Feed:
    return Feed(
        id=row["id"],
        url=row["url"],
        name=row["name"],
        html_url=row["html_url"],
        category_id=row["category_id"],
        webhook_id=row["webhook_id"],
        emoji=row["emoji"],
        poll_priority=row["poll_priority"],
        max_entries=row["max_entries"],
        status=row["status"],
        fail_count=row["fail_count"],
        last_error=row["last_error"],
        etag=row["etag"],
        last_modified=row["last_modified"],
        last_checked_at=_parse(row["last_checked_at"]),
    )


class FeedRepository:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    def add(
        self,
        url: str,
        name: str,
        *,
        html_url: str = "",
        emoji: str = DEFAULT_EMOJI,
        poll_priority: str = PRIORITY_NORMAL,
        max_entries: int | None = None,
        category_id: int | None = None,
        webhook_id: int | None = None,
        status: str = STATUS_BASELINE,
    ) -> int:
        if webhook_id is not None and category_id is not None:
            raise FeedRuleError(RULE_CATEGORY_FEED_WEBHOOK)
        if webhook_id is not None:
            with self._db.connect() as conn:
                if (
                    conn.execute("SELECT 1 FROM webhooks WHERE id = ?", (webhook_id,)).fetchone()
                    is None
                ):
                    raise FeedRuleError(RULE_WEBHOOK_MISSING)
        try:
            with self._db.connect() as conn:
                cursor = conn.execute(
                    "INSERT INTO feeds(url, url_key, name, html_url, category_id, webhook_id, "
                    "emoji, poll_priority, max_entries, status, created_at) "
                    "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        url,
                        feed_url_key(url),
                        name,
                        html_url,
                        category_id,
                        webhook_id,
                        emoji,
                        poll_priority,
                        max_entries,
                        status,
                        _iso(self._clock.now()),
                    ),
                )
                return int(cursor.lastrowid or 0)
        except sqlite3.IntegrityError as error:
            raise DuplicateFeedError(url) from error

    def add_category(self, name: str, *, webhook_id: int | None = None) -> int:
        with self._db.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO categories(name, webhook_id) VALUES(?, ?)", (name, webhook_id)
            )
            return int(cursor.lastrowid or 0)

    def set_feed_webhook(self, feed_id: int, webhook_id: int | None) -> bool:
        """피드의 웹훅을 지정하거나(None이면 해제) 한다. 그런 피드가 없으면 False.

        카테고리에 속한 피드는 지정할 수 없다. 카테고리에서 빠지면 다시 지정할 수 있다.
        """
        with self._db.connect() as conn:
            row = conn.execute("SELECT category_id FROM feeds WHERE id = ?", (feed_id,)).fetchone()
            if row is None:
                return False
            if webhook_id is not None:
                if row["category_id"] is not None:
                    raise FeedRuleError(RULE_CATEGORY_FEED_WEBHOOK)
                if (
                    conn.execute("SELECT 1 FROM webhooks WHERE id = ?", (webhook_id,)).fetchone()
                    is None
                ):
                    raise FeedRuleError(RULE_WEBHOOK_MISSING)
            conn.execute("UPDATE feeds SET webhook_id = ? WHERE id = ?", (webhook_id, feed_id))
            return True

    def set_feed_category(self, feed_id: int, category_id: int | None) -> bool:
        """피드를 카테고리에 넣거나(None이면 뺀다) 한다. 그런 피드가 없으면 False.

        웹훅이 지정된 피드는 카테고리에 넣을 수 없다(먼저 웹훅 지정을 해제해야 한다).
        """
        with self._db.connect() as conn:
            row = conn.execute("SELECT webhook_id FROM feeds WHERE id = ?", (feed_id,)).fetchone()
            if row is None:
                return False
            if category_id is not None:
                if row["webhook_id"] is not None:
                    raise FeedRuleError(RULE_FEED_WEBHOOK_BLOCKS_CATEGORY)
                if (
                    conn.execute("SELECT 1 FROM categories WHERE id = ?", (category_id,)).fetchone()
                    is None
                ):
                    raise FeedRuleError(RULE_CATEGORY_MISSING)
            conn.execute("UPDATE feeds SET category_id = ? WHERE id = ?", (category_id, feed_id))
            return True

    def list_categories(self) -> list["Category"]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT c.id, c.name, c.webhook_id, COUNT(f.id) AS feed_count "
                "FROM categories c LEFT JOIN feeds f ON f.category_id = c.id "
                "GROUP BY c.id ORDER BY c.name"
            ).fetchall()
        return [Category(r["id"], r["name"], r["webhook_id"], r["feed_count"]) for r in rows]

    def set_category_webhook(self, category_id: int, webhook_id: int | None) -> bool:
        """카테고리의 웹훅을 지정하거나(None이면 해제) 한다. 그런 카테고리가 없으면 False."""
        with self._db.connect() as conn:
            cursor = conn.execute(
                "UPDATE categories SET webhook_id = ? WHERE id = ?", (webhook_id, category_id)
            )
            return cursor.rowcount > 0

    def get_or_create_category(self, name: str) -> tuple[int, bool]:
        """이름이 같은 카테고리가 있으면 그것을, 없으면 만든다. (id, 새로 만들었는지)"""
        with self._db.connect() as conn:
            row = conn.execute("SELECT id FROM categories WHERE name = ?", (name,)).fetchone()
            if row is not None:
                return int(row["id"]), False
            cursor = conn.execute("INSERT INTO categories(name) VALUES(?)", (name,))
            return int(cursor.lastrowid or 0), True

    def category_names(self) -> set[str]:
        with self._db.connect() as conn:
            return {row["name"] for row in conn.execute("SELECT name FROM categories")}

    def existing_url_keys(self) -> set[str]:
        """이미 구독 중인 피드의 정규화한 주소(중복 판단에 쓴다)."""
        with self._db.connect() as conn:
            return {row["url_key"] for row in conn.execute("SELECT url_key FROM feeds")}

    def category_webhook_id(self, category_id: int | None) -> int | None:
        """카테고리에 지정된 웹훅. 카테고리가 없거나 지정이 없으면 None."""
        if category_id is None:
            return None
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT webhook_id FROM categories WHERE id = ?", (category_id,)
            ).fetchone()
        return None if row is None else row["webhook_id"]

    def get(self, feed_id: int) -> Feed | None:
        with self._db.connect() as conn:
            row = conn.execute("SELECT * FROM feeds WHERE id = ?", (feed_id,)).fetchone()
        return None if row is None else _feed(row)

    def list_all(self) -> list[Feed]:
        with self._db.connect() as conn:
            rows = conn.execute("SELECT * FROM feeds ORDER BY id").fetchall()
        return [_feed(row) for row in rows]

    def delete(self, feed_id: int) -> None:
        """피드와 그 통계, 글을 지운다. 본 글 기록(seen_guids)은 남겨서 되살아나지 않게 한다."""
        with self._db.connect() as conn:
            conn.execute("DELETE FROM feeds WHERE id = ?", (feed_id,))

    def set_poll_priority(self, feed_id: int, priority: str) -> None:
        with self._db.connect() as conn:
            conn.execute("UPDATE feeds SET poll_priority = ? WHERE id = ?", (priority, feed_id))

    def record_success(
        self, feed_id: int, *, etag: str | None, last_modified: str | None, activate: bool
    ) -> None:
        """점검 성공: 연속 실패를 지우고 검증값(ETag 등)과 점검 시각을 기록한다."""
        with self._db.connect() as conn:
            conn.execute(
                "UPDATE feeds SET fail_count = 0, last_error = NULL, etag = ?, last_modified = ?, "
                "last_checked_at = ?, status = CASE WHEN ? THEN ? ELSE status END WHERE id = ?",
                (
                    etag,
                    last_modified,
                    _iso(self._clock.now()),
                    int(activate),
                    STATUS_ACTIVE,
                    feed_id,
                ),
            )

    def record_failure(self, feed_id: int, reason: str) -> None:
        with self._db.connect() as conn:
            conn.execute(
                "UPDATE feeds SET fail_count = fail_count + 1, last_error = ?, last_checked_at = ? "
                "WHERE id = ?",
                (reason, _iso(self._clock.now()), feed_id),
            )

    def save_stats(self, feed_id: int, measurement: FeedMeasurement) -> None:
        published = measurement.last_published
        with self._db.connect() as conn:
            conn.execute(
                "INSERT INTO feed_stats(feed_id, recent_count_7d, target_date_count, "
                "last_published_dt, updated_at) VALUES(?, ?, ?, ?, ?) "
                "ON CONFLICT(feed_id) DO UPDATE SET recent_count_7d = excluded.recent_count_7d, "
                "target_date_count = excluded.target_date_count, "
                "last_published_dt = excluded.last_published_dt, updated_at = excluded.updated_at",
                (
                    feed_id,
                    measurement.activity.recent_count_7d,
                    measurement.activity.target_date_count,
                    None if published is None else _iso(published),
                    _iso(self._clock.now()),
                ),
            )

    def stats(self, feed_id: int) -> StoredStats | None:
        with self._db.connect() as conn:
            row = conn.execute("SELECT * FROM feed_stats WHERE feed_id = ?", (feed_id,)).fetchone()
        if row is None:
            return None
        return StoredStats(
            recent_count_7d=row["recent_count_7d"],
            target_date_count=row["target_date_count"],
            last_published=_parse(row["last_published_dt"]),
        )

    def activity_by_key(self) -> dict[str, Activity]:
        """스케줄 계산에 쓰는 활동량(키는 피드 id 문자열)."""
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT feed_id, recent_count_7d, target_date_count FROM feed_stats"
            ).fetchall()
        return {
            str(r["feed_id"]): Activity(r["recent_count_7d"], r["target_date_count"]) for r in rows
        }
