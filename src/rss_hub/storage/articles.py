"""글 저장소와 "이미 본 글" 기록. 중복 방지의 기준은 seen_guids 하나다."""

import json
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

from rss_hub.services.clock import Clock
from rss_hub.storage.database import Database
from rss_hub.storage.timestamps import to_iso

STATUS_COLLECTED = "collected"
STATUS_READY = "ready"  # 요약(또는 원문 발췌)이 끝나서 발송할 수 있다
STATUS_DELIVERED = "delivered"  # 모든 목적지로 보냈다
STATUS_ARCHIVED = "archived"  # 첫 점검 때 뷰어에만 보이도록 보관한 글(요약도 알림도 하지 않는다)
VIEWABLE_STATUSES = (STATUS_COLLECTED, STATUS_READY, STATUS_DELIVERED, STATUS_ARCHIVED)
SEEN_DELIVERED = "delivered"
MODEL_FALLBACK = "fallback-final"  # 요약에 끝까지 실패해서 원문 발췌로 확정한 글
SEEN_BASELINE = "baseline"
SEEN_ARTICLE = "article"
MAX_FULL_TEXT_CHARS = 400_000  # 저장하는 전문의 최대 길이


@dataclass(frozen=True)
class NewArticle:
    feed_id: int
    guid: str
    title: str
    link: str
    content_html: str
    published_raw: str
    published_dt: datetime
    published_date: str


@dataclass(frozen=True)
class Article:
    id: int
    feed_id: int
    guid: str
    title: str
    link: str
    content_html: str
    published_raw: str
    published_dt: datetime
    published_date: str
    discovered_at: datetime
    status: str
    retry_count: int
    title_ko: str | None
    summary_ko: str | None
    llm_topics: tuple[int, ...] | None  # LLM이 고른 주제 번호. None은 판별하지 않았다는 뜻
    llm_model: str | None
    read_at: datetime | None = None  # None이면 읽지 않은 글
    bookmarked_at: datetime | None = None
    full_html: str | None = None  # 원문 페이지에서 뽑은 전문(정제됨)
    full_status: str | None = None  # None(가져온 적 없음), ok, failed
    full_error: str | None = None  # 실패 분류(예: ReadTimeout)


def _article(row: sqlite3.Row) -> Article:
    return Article(
        id=row["id"],
        feed_id=row["feed_id"],
        guid=row["guid"],
        title=row["title"],
        link=row["link"],
        content_html=row["content_html"],
        published_raw=row["published_raw"],
        published_dt=datetime.fromisoformat(row["published_dt"]),
        published_date=row["published_date"],
        discovered_at=datetime.fromisoformat(row["discovered_at"]),
        status=row["status"],
        retry_count=row["retry_count"],
        title_ko=row["title_ko"],
        summary_ko=row["summary_ko"],
        llm_topics=None if row["llm_topics"] is None else tuple(json.loads(row["llm_topics"])),
        llm_model=row["llm_model"],
        read_at=None if row["read_at"] is None else datetime.fromisoformat(row["read_at"]),
        bookmarked_at=(
            None if row["bookmarked_at"] is None else datetime.fromisoformat(row["bookmarked_at"])
        ),
        full_html=row["full_html"],
        full_status=row["full_status"],
        full_error=row["full_error"],
    )


class ArticleRepository:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    def is_seen(self, guid: str) -> bool:
        with self._db.connect() as conn:
            row = conn.execute("SELECT 1 FROM seen_guids WHERE guid = ?", (guid,)).fetchone()
        return row is not None

    def mark_seen(self, guids: Iterable[str], reason: str) -> int:
        """글을 만들지 않고 "이미 본 글"로만 기록한다. 새로 기록한 개수를 돌려준다."""
        now = to_iso(self._clock.now())
        recorded = 0
        with self._db.connect() as conn:
            for guid in guids:
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO seen_guids(guid, reason, first_seen_at) VALUES(?, ?, ?)",
                    (guid, reason, now),
                )
                recorded += cursor.rowcount
        return recorded

    def add(self, article: NewArticle) -> int | None:
        """새 글을 저장한다. 이미 본 글이면 저장하지 않고 None을 돌려준다."""
        now = to_iso(self._clock.now())
        with self._db.connect() as conn:
            seen = conn.execute(
                "INSERT OR IGNORE INTO seen_guids(guid, reason, first_seen_at) VALUES(?, ?, ?)",
                (article.guid, SEEN_ARTICLE, now),
            )
            if seen.rowcount == 0:
                return None
            cursor = conn.execute(
                "INSERT INTO articles(feed_id, guid, title, link, content_html, published_raw, "
                "published_dt, published_date, discovered_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    article.feed_id,
                    article.guid,
                    article.title,
                    article.link,
                    article.content_html,
                    article.published_raw,
                    to_iso(article.published_dt),
                    article.published_date,
                    now,
                ),
            )
            return int(cursor.lastrowid or 0)

    def add_archived(self, article: NewArticle) -> int | None:
        """첫 점검 때 뷰어에서 볼 최근 글을 보관한다. 이미 있는 글이면 None.

        요약과 알림의 대상이 아니다(status가 archived). 본 글 기록은 baseline으로 남긴다.
        """
        now = to_iso(self._clock.now())
        with self._db.connect() as conn:
            if conn.execute("SELECT 1 FROM articles WHERE guid = ?", (article.guid,)).fetchone():
                return None
            conn.execute(
                "INSERT OR IGNORE INTO seen_guids(guid, reason, first_seen_at) VALUES(?, ?, ?)",
                (article.guid, SEEN_BASELINE, now),
            )
            cursor = conn.execute(
                "INSERT INTO articles(feed_id, guid, title, link, content_html, published_raw, "
                "published_dt, published_date, discovered_at, status, read_at) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    article.feed_id,
                    article.guid,
                    article.title,
                    article.link,
                    article.content_html,
                    article.published_raw,
                    to_iso(article.published_dt),
                    article.published_date,
                    now,
                    STATUS_ARCHIVED,
                    now,  # 보관 글은 읽은 것으로 시작한다(읽지 않은 글 수를 부풀리지 않게)
                ),
            )
            return int(cursor.lastrowid or 0)

    def delete_older_than(self, cutoff: datetime) -> int:
        """저장한 지 cutoff보다 오래된 글을 지운다(발송 기록과 주제 소속도 함께). 지운 개수.

        북마크한 글은 지우지 않는다. 본 글 기록(seen_guids)은 남겨서 다시 수집되지 않게 한다.
        """
        with self._db.connect() as conn:
            return conn.execute(
                "DELETE FROM articles WHERE discovered_at < ? AND bookmarked_at IS NULL",
                (to_iso(cutoff),),
            ).rowcount

    # ---------- 읽음과 북마크 ----------

    def mark_read(self, article_id: int) -> bool:
        """사용자가 읽음으로 표시한다(글을 열거나 읽음 버튼). 처음 읽은 시각을 지키고,
        "읽지 않음으로 고정"한 표시도 푼다. 바뀐 것이 없으면 False."""
        now = to_iso(self._clock.now())
        with self._db.connect() as conn:
            return (
                conn.execute(
                    "UPDATE articles SET read_at = COALESCE(read_at, ?), keep_unread = 0 "
                    "WHERE id = ? AND (read_at IS NULL OR keep_unread = 1)",
                    (now, article_id),
                ).rowcount
                > 0
            )

    def mark_unread(self, article_id: int) -> bool:
        """사용자가 읽지 않음으로 바꾼다. 자동 읽음 처리에서 빠지도록 고정한다.
        이미 읽지 않음이고 고정되어 있으면 False."""
        with self._db.connect() as conn:
            return (
                conn.execute(
                    "UPDATE articles SET read_at = NULL, keep_unread = 1 "
                    "WHERE id = ? AND (read_at IS NOT NULL OR keep_unread = 0)",
                    (article_id,),
                ).rowcount
                > 0
            )

    def save_full_text(self, article_id: int, html: str) -> bool:
        """원문에서 뽑은 전문(정제된 HTML)을 저장한다. 그런 글이 없으면 False."""
        with self._db.connect() as conn:
            return (
                conn.execute(
                    "UPDATE articles SET full_html = ?, full_status = 'ok', full_error = NULL "
                    "WHERE id = ?",
                    (html, article_id),
                ).rowcount
                > 0
            )

    def save_full_text_failure(self, article_id: int, reason: str) -> bool:
        """전문을 가져오지 못했다고 기록한다(같은 글을 열 때마다 다시 가져오지 않기 위해)."""
        with self._db.connect() as conn:
            return (
                conn.execute(
                    "UPDATE articles SET full_html = NULL, full_status = 'failed', full_error = ? "
                    "WHERE id = ?",
                    (reason[:100], article_id),
                ).rowcount
                > 0
            )

    def auto_mark_read(self, article_ids: Sequence[int]) -> int:
        """스크롤로 지나간 글을 읽음 처리한다. 읽지 않음으로 고정한 글은 건드리지 않는다."""
        if not article_ids:
            return 0
        marks = ",".join("?" for _ in article_ids)
        with self._db.connect() as conn:
            return conn.execute(
                f"UPDATE articles SET read_at = ? WHERE id IN ({marks}) "
                "AND read_at IS NULL AND keep_unread = 0",
                [to_iso(self._clock.now()), *article_ids],
            ).rowcount

    def set_bookmark(self, article_id: int, on: bool) -> bool:
        """북마크를 켜거나 끈다. 바뀐 것이 없거나 없는 글이면 False."""
        return self._set("bookmarked_at", article_id, on=on)

    def _set(self, column: str, article_id: int, *, on: bool) -> bool:
        value = to_iso(self._clock.now()) if on else None
        condition = "IS NULL" if on else "IS NOT NULL"
        with self._db.connect() as conn:
            cursor = conn.execute(
                f"UPDATE articles SET {column} = ? WHERE id = ? AND {column} {condition}",
                (value, article_id),
            )
            return cursor.rowcount > 0

    def get(self, article_id: int) -> Article | None:
        with self._db.connect() as conn:
            row = conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
        return None if row is None else _article(row)

    def list_by_status(self, status: str) -> list[Article]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM articles WHERE status = ? ORDER BY published_dt, id", (status,)
            ).fetchall()
        return [_article(row) for row in rows]

    def count_by_status(self) -> dict[str, int]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS n FROM articles GROUP BY status"
            ).fetchall()
        return {row["status"]: row["n"] for row in rows}

    def mark_ready(
        self,
        article_id: int,
        *,
        title_ko: str,
        summary_ko: str,
        topics: Sequence[int],
        model: str,
    ) -> None:
        """요약을 채택한다. 재시도 횟수는 0으로 되돌린다."""
        with self._db.connect() as conn:
            conn.execute(
                "UPDATE articles SET title_ko = ?, summary_ko = ?, llm_topics = ?, llm_model = ?, "
                "status = ?, retry_count = 0 WHERE id = ?",
                (title_ko, summary_ko, json.dumps(list(topics)), model, STATUS_READY, article_id),
            )

    def bump_retry(self, article_id: int) -> int:
        """불량 응답을 받았을 때 재시도 횟수를 1 올리고 새 값을 돌려준다."""
        with self._db.connect() as conn:
            conn.execute(
                "UPDATE articles SET retry_count = retry_count + 1 WHERE id = ?", (article_id,)
            )
            row = conn.execute(
                "SELECT retry_count FROM articles WHERE id = ?", (article_id,)
            ).fetchone()
        return int(row["retry_count"])

    def finalize_fallback(self, article_id: int, *, title_ko: str, summary_ko: str) -> None:
        """요약에 끝까지 실패한 글을 원문 발췌로 확정한다(다시 요약하지 않는다)."""
        with self._db.connect() as conn:
            conn.execute(
                "UPDATE articles SET title_ko = ?, summary_ko = ?, llm_topics = NULL, "
                "llm_model = ?, status = ? WHERE id = ?",
                (title_ko, summary_ko, MODEL_FALLBACK, STATUS_READY, article_id),
            )

    def mark_delivered(self, article_id: int) -> None:
        """모든 목적지로 보냈다. 같은 글을 다시 수집하지 않게 "이미 본 글" 기록에도 표시한다."""
        with self._db.connect() as conn:
            conn.execute(
                "UPDATE articles SET status = ? WHERE id = ?", (STATUS_DELIVERED, article_id)
            )
            conn.execute(
                "UPDATE seen_guids SET reason = ? WHERE guid = "
                "(SELECT guid FROM articles WHERE id = ?)",
                (SEEN_DELIVERED, article_id),
            )
