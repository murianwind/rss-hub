"""뷰어용 조회: 글 목록(전체, 사이트, 카테고리, 주제, 북마크)과 검색, 필터, 읽음, 사이드바 개수."""

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from rss_hub.services.clock import Clock
from rss_hub.storage.articles import VIEWABLE_STATUSES
from rss_hub.storage.database import Database
from rss_hub.storage.timestamps import to_iso

PER_PAGE = 30
ONLY_UNREAD = "unread"
ONLY_BOOKMARKS = "bookmarks"
MAX_QUERY_LENGTH = 100


@dataclass(frozen=True)
class ListedArticle:
    id: int
    feed_id: int
    feed_name: str
    title: str  # 번역 제목이 있으면 번역 제목, 없으면 원래 제목
    summary: str | None
    published_dt: datetime
    status: str
    topics: tuple[str, ...]
    read: bool
    bookmarked: bool
    keep_unread: bool = False  # 사용자가 읽지 않음으로 고정(자동 읽음 처리에서 빠진다)


@dataclass(frozen=True)
class ArticlePage:
    items: tuple[ListedArticle, ...]
    page: int
    has_next: bool
    total: int  # 같은 조건에 맞는 글의 전체 수


@dataclass(frozen=True)
class TopicMatch:
    topic_id: int
    name: str
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class SideFeed:
    id: int
    name: str
    category_id: int | None
    total: int
    unread: int
    state: str = "never"  # ok(정상), error(마지막 점검 실패), never(아직 수집 전)
    error: str = ""


def feed_state(fail_count: int, last_checked_at: object) -> str:
    """피드의 상태 점: 마지막 점검이 실패했으면 error, 점검한 적이 없으면 never, 아니면 ok."""
    if fail_count > 0:
        return "error"
    return "never" if last_checked_at is None else "ok"


@dataclass(frozen=True)
class SideCategory:
    id: int
    name: str
    feeds: tuple[SideFeed, ...]
    total: int
    unread: int


@dataclass(frozen=True)
class SideTopic:
    id: int
    name: str
    total: int
    unread: int


@dataclass(frozen=True)
class Sidebar:
    feeds: tuple[SideFeed, ...]
    categories: tuple[SideCategory, ...]
    topics: tuple[SideTopic, ...]
    all_unread: int
    bookmarks: int


def _like(text: str) -> str:
    """LIKE에서 %와 _와 \\를 글자 그대로 찾도록 막는다."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _where(
    *,
    feed_id: int | None,
    category_id: int | None,
    topic_id: int | None,
    query: str,
    only: str,
) -> tuple[str, list[str | int]]:
    marks = ",".join("?" for _ in VIEWABLE_STATUSES)
    where = [f"a.status IN ({marks})"]
    params: list[str | int] = list(VIEWABLE_STATUSES)
    if feed_id is not None:
        where.append("a.feed_id = ?")
        params.append(feed_id)
    if category_id is not None:
        where.append("f.category_id = ?")
        params.append(category_id)
    if topic_id is not None:
        where.append(
            "EXISTS (SELECT 1 FROM article_topics t "
            "WHERE t.article_id = a.id AND t.topic_id = ? AND t.rejected = 0)"
        )
        params.append(topic_id)
    text = query.strip()[:MAX_QUERY_LENGTH]
    if text:
        like = "LIKE ? ESCAPE '\\'"
        where.append(f"(a.title {like} OR a.title_ko {like} OR a.summary_ko {like})")
        params += [_like(text)] * 3
    if only == ONLY_UNREAD:
        where.append("a.read_at IS NULL")
    elif only == ONLY_BOOKMARKS:
        where.append("a.bookmarked_at IS NOT NULL")
    return " AND ".join(where), params


class ReaderRepository:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    def list_articles(
        self,
        *,
        feed_id: int | None = None,
        category_id: int | None = None,
        topic_id: int | None = None,
        query: str = "",
        only: str = "",
        page: int = 1,
        per_page: int = PER_PAGE,
    ) -> ArticlePage:
        """최신순(발행 시각, 같으면 나중에 저장한 글 먼저). 다음 쪽 여부는 한 건 더 읽어서 안다."""
        page = max(page, 1)
        where, params = _where(
            feed_id=feed_id, category_id=category_id, topic_id=topic_id, query=query, only=only
        )
        source = "FROM articles a JOIN feeds f ON f.id = a.feed_id"
        select = (
            "SELECT a.id, a.feed_id, f.name AS feed_name, "
            "COALESCE(a.title_ko, a.title) AS title, a.summary_ko, a.published_dt, a.status, "
            "a.read_at, a.bookmarked_at, a.keep_unread "
            f"{source} WHERE {where} ORDER BY a.published_dt DESC, a.id DESC LIMIT ? OFFSET ?"
        )
        with self._db.connect() as conn:
            rows = conn.execute(select, [*params, per_page + 1, (page - 1) * per_page]).fetchall()
            total = conn.execute(f"SELECT COUNT(*) AS n {source} WHERE {where}", params).fetchone()[
                "n"
            ]
            shown = rows[:per_page]
            names = self._topic_names(conn, [row["id"] for row in shown])
        items = tuple(_listed(row, names.get(row["id"], ())) for row in shown)
        return ArticlePage(items=items, page=page, has_next=len(rows) > per_page, total=int(total))

    @staticmethod
    def _topic_names(
        conn: sqlite3.Connection, article_ids: Sequence[int]
    ) -> dict[int, tuple[str, ...]]:
        if not article_ids:
            return {}
        marks = ",".join("?" for _ in article_ids)
        rows = conn.execute(
            "SELECT at.article_id, tp.name FROM article_topics at "
            "JOIN topics tp ON tp.id = at.topic_id WHERE at.rejected = 0 "
            f"AND at.article_id IN ({marks}) "
            "ORDER BY tp.id",
            list(article_ids),
        ).fetchall()
        grouped: dict[int, list[str]] = {}
        for row in rows:
            grouped.setdefault(row["article_id"], []).append(row["name"])
        return {key: tuple(value) for key, value in grouped.items()}

    def mark_all_read(
        self,
        *,
        feed_id: int | None = None,
        category_id: int | None = None,
        topic_id: int | None = None,
        only: str = "",
    ) -> int:
        """범위 안의 읽지 않은 글을 모두 읽음으로 표시한다. 표시한 글 수를 돌려준다."""
        where, params = _where(
            feed_id=feed_id, category_id=category_id, topic_id=topic_id, query="", only=only
        )
        now = to_iso(self._clock.now())
        with self._db.connect() as conn:
            return conn.execute(
                "UPDATE articles SET read_at = ?, keep_unread = 0 WHERE read_at IS NULL AND id IN "
                f"(SELECT a.id FROM articles a JOIN feeds f ON f.id = a.feed_id WHERE {where})",
                [now, *params],
            ).rowcount

    def topics_of(self, article_id: int) -> list[TopicMatch]:
        """글이 해당한 주제와 일치한 키워드."""
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT tp.id, tp.name, at.matched_keywords FROM article_topics at "
                "JOIN topics tp ON tp.id = at.topic_id WHERE at.article_id = ? AND at.rejected = 0 "
                "ORDER BY tp.id",
                (article_id,),
            ).fetchall()
        return [
            TopicMatch(row["id"], row["name"], tuple(json.loads(row["matched_keywords"])))
            for row in rows
        ]

    # ---------- 사이드바 ----------

    def sidebar(self) -> Sidebar:
        """사이드바에 그릴 피드, 카테고리, 주제와 개수(전체 글 수와 읽지 않은 글 수)."""
        marks = ",".join("?" for _ in VIEWABLE_STATUSES)
        statuses = list(VIEWABLE_STATUSES)
        with self._db.connect() as conn:
            feed_rows = conn.execute(
                "SELECT f.id, f.name, f.category_id, f.fail_count, f.last_error, "
                "f.last_checked_at, COALESCE(c.total, 0) AS total, "
                "COALESCE(c.unread, 0) AS unread FROM feeds f LEFT JOIN ("
                "SELECT feed_id, COUNT(*) AS total, SUM(read_at IS NULL) AS unread FROM articles "
                f"WHERE status IN ({marks}) GROUP BY feed_id) c ON c.feed_id = f.id "
                "ORDER BY f.sort_order, LOWER(f.name), f.id",
                statuses,
            ).fetchall()
            category_rows = conn.execute(
                "SELECT id, name FROM categories ORDER BY sort_order, LOWER(name), id"
            ).fetchall()
            topic_rows = conn.execute(
                "SELECT tp.id, tp.name, COALESCE(t.total, 0) AS total, "
                "COALESCE(t.unread, 0) AS unread "
                "FROM topics tp LEFT JOIN ("
                "SELECT at.topic_id, COUNT(*) AS total, SUM(a.read_at IS NULL) AS unread "
                "FROM article_topics at JOIN articles a ON a.id = at.article_id "
                f"WHERE at.rejected = 0 AND a.status IN ({marks}) GROUP BY at.topic_id) t "
                "ON t.topic_id = tp.id ORDER BY tp.sort_order, LOWER(tp.name), tp.id",
                statuses,
            ).fetchall()
            all_unread = conn.execute(
                f"SELECT COUNT(*) AS n FROM articles WHERE status IN ({marks}) AND read_at IS NULL",
                statuses,
            ).fetchone()["n"]
            bookmarks = conn.execute(
                f"SELECT COUNT(*) AS n FROM articles WHERE status IN ({marks}) "
                "AND bookmarked_at IS NOT NULL",
                statuses,
            ).fetchone()["n"]
        feeds = tuple(
            SideFeed(
                r["id"],
                r["name"],
                r["category_id"],
                r["total"],
                r["unread"],
                feed_state(r["fail_count"], r["last_checked_at"]),
                r["last_error"] or "",
            )
            for r in feed_rows
        )
        categories = tuple(
            _category(row, [f for f in feeds if f.category_id == row["id"]])
            for row in category_rows
        )
        topics = tuple(SideTopic(r["id"], r["name"], r["total"], r["unread"]) for r in topic_rows)
        return Sidebar(feeds, categories, topics, int(all_unread), int(bookmarks))


def _category(row: sqlite3.Row, feeds: list[SideFeed]) -> SideCategory:
    return SideCategory(
        row["id"],
        row["name"],
        tuple(feeds),
        sum(f.total for f in feeds),
        sum(f.unread for f in feeds),
    )


def _listed(row: sqlite3.Row, topics: tuple[str, ...]) -> ListedArticle:
    return ListedArticle(
        id=row["id"],
        feed_id=row["feed_id"],
        feed_name=row["feed_name"],
        title=row["title"],
        summary=row["summary_ko"],
        published_dt=datetime.fromisoformat(row["published_dt"]),
        status=row["status"],
        topics=topics,
        read=row["read_at"] is not None,
        bookmarked=row["bookmarked_at"] is not None,
        keep_unread=bool(row["keep_unread"]),
    )
