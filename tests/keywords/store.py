"""저장소 준비와 관찰 키워드.

제품 코드가 쓰지 않는 조회와 설정은 제품 저장소에 두지 않고 여기서 한다.
준비 키워드는 제품의 공개 메서드만 부르고, 관찰 키워드는 데이터베이스 표를 직접 읽는다.
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from typing import NamedTuple

from rss_hub.domain.feed_edit import FeedEdit


def create_category(feeds, name, webhook_id=None):
    """카테고리를 만들고(웹훅을 주면 지정하고) id를 돌려준다."""
    category_id, _ = feeds.get_or_create_category(name)
    if webhook_id is not None:
        feeds.set_category_webhook(category_id, webhook_id)
    return category_id


def set_poll_priority(feeds, feed_id, priority):
    """다른 설정은 그대로 두고 점검 우선순위만 바꾼다."""
    feed = feeds.get(feed_id)
    feeds.update_feed(feed_id, FeedEdit(feed.name, feed.emoji, priority, feed.max_entries))


class StoredStats(NamedTuple):
    recent_count_7d: int
    target_date_count: int
    last_published: datetime | None


def stored_stats(db, feed_id) -> StoredStats | None:
    """수집 뒤에 저장된 피드 활동량(없으면 None)."""
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM feed_stats WHERE feed_id = ?", (feed_id,)).fetchone()
    if row is None:
        return None
    last = row["last_published_dt"]
    return StoredStats(
        row["recent_count_7d"],
        row["target_date_count"],
        datetime.fromisoformat(last) if last else None,
    )


def topic_matches(db, article_id) -> dict[int, tuple[str, ...]]:
    """글이 해당한 주제별로, 그때 일치한 키워드."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT topic_id, matched_keywords FROM article_topics WHERE article_id = ?",
            (article_id,),
        ).fetchall()
    return {row["topic_id"]: tuple(json.loads(row["matched_keywords"])) for row in rows}


def usage_breakdown(db, day: date) -> dict[str, dict[str, int]]:
    """그날의 LLM 호출 수를 모델별, 결과별로."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT model, outcome, COUNT(*) AS n FROM llm_usage WHERE day = ? "
            "GROUP BY model, outcome",
            (day.isoformat(),),
        ).fetchall()
    result: dict[str, dict[str, int]] = {}
    for row in rows:
        result.setdefault(row["model"], {})[row["outcome"]] = row["n"]
    return result


@contextmanager
def raw_connection(path):
    """제품 코드를 거치지 않고 데이터베이스 파일을 직접 여는 연결(끝나면 닫는다)."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()
