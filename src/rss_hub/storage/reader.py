"""뷰어용 조회: 글 목록(전체, 사이트, 카테고리, 주제)과 글 하나의 주제 소속."""

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from rss_hub.storage.articles import VIEWABLE_STATUSES
from rss_hub.storage.database import Database

PER_PAGE = 30


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


@dataclass(frozen=True)
class ArticlePage:
    items: tuple[ListedArticle, ...]
    page: int
    has_next: bool


@dataclass(frozen=True)
class TopicMatch:
    topic_id: int
    name: str
    keywords: tuple[str, ...]


class ReaderRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def list_articles(
        self,
        *,
        feed_id: int | None = None,
        category_id: int | None = None,
        topic_id: int | None = None,
        page: int = 1,
        per_page: int = PER_PAGE,
    ) -> ArticlePage:
        """최신순(발행 시각, 같으면 나중에 저장한 글 먼저). 다음 쪽 여부는 한 건 더 읽어서 안다."""
        page = max(page, 1)
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
        query = (
            "SELECT a.id, a.feed_id, f.name AS feed_name, "
            "COALESCE(a.title_ko, a.title) AS title, a.summary_ko, a.published_dt, a.status "
            "FROM articles a JOIN feeds f ON f.id = a.feed_id "
            f"WHERE {' AND '.join(where)} "
            "ORDER BY a.published_dt DESC, a.id DESC LIMIT ? OFFSET ?"
        )
        params += [per_page + 1, (page - 1) * per_page]
        with self._db.connect() as conn:
            rows = conn.execute(query, params).fetchall()
            shown = rows[:per_page]
            names = self._topic_names(conn, [row["id"] for row in shown])
        items = tuple(_listed(row, names.get(row["id"], ())) for row in shown)
        return ArticlePage(items=items, page=page, has_next=len(rows) > per_page)

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
    )
