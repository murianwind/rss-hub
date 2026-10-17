"""주제 저장소: 주제 목록, 글이 해당한 주제 기록, 처음 설치할 때의 기본 주제."""

import json
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import UTC

from rss_hub.domain.keywords import DEFAULT_OTT_KEYWORDS
from rss_hub.domain.topics import MAX_TOPICS, Topic, TopicFields, TopicInputError
from rss_hub.services.clock import Clock
from rss_hub.storage.database import Database

SEEDED_KEY = "topics_seeded"
DEFAULT_TOPIC_NAME = "OTT"
DEFAULT_TOPIC_DESCRIPTION = "OTT, 스트리밍 콘텐츠(영화, 드라마, TV 쇼, 스트리밍 서비스 소식)"


def _topic(row: sqlite3.Row) -> Topic:
    return Topic(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        keywords=tuple(json.loads(row["keywords"])),
        webhook_id=row["webhook_id"],
        enabled=bool(row["enabled"]),
    )


def _dump(values: Sequence[str]) -> str:
    return json.dumps(list(values), ensure_ascii=False)


class TopicRepository:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    def _check_webhook(self, conn: sqlite3.Connection, webhook_id: int | None) -> None:
        if webhook_id is None:
            return
        if conn.execute("SELECT 1 FROM webhooks WHERE id = ?", (webhook_id,)).fetchone() is None:
            raise TopicInputError("웹훅을 찾을 수 없음")

    def add(
        self, fields: TopicFields, *, webhook_id: int | None = None, enabled: bool = True
    ) -> int:
        with self._db.connect() as conn:
            if conn.execute("SELECT COUNT(*) AS n FROM topics").fetchone()["n"] >= MAX_TOPICS:
                raise TopicInputError(f"주제는 {MAX_TOPICS}개까지")
            self._check_webhook(conn, webhook_id)
            try:
                cursor = conn.execute(
                    "INSERT INTO topics(name, name_key, description, keywords, webhook_id, "
                    "enabled, created_at) VALUES(?, ?, ?, ?, ?, ?, ?)",
                    (
                        fields.name,
                        fields.name.lower(),
                        fields.description,
                        _dump(fields.keywords),
                        webhook_id,
                        int(enabled),
                        self._clock.now().astimezone(UTC).isoformat(),
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise TopicInputError("같은 이름의 주제가 이미 있음") from error
            return int(cursor.lastrowid or 0)

    def update(
        self, topic_id: int, fields: TopicFields, *, webhook_id: int | None, enabled: bool
    ) -> bool:
        """주제를 고친다. 그런 주제가 없으면 False."""
        with self._db.connect() as conn:
            self._check_webhook(conn, webhook_id)
            try:
                cursor = conn.execute(
                    "UPDATE topics SET name = ?, name_key = ?, description = ?, keywords = ?, "
                    "webhook_id = ?, enabled = ? WHERE id = ?",
                    (
                        fields.name,
                        fields.name.lower(),
                        fields.description,
                        _dump(fields.keywords),
                        webhook_id,
                        int(enabled),
                        topic_id,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise TopicInputError("같은 이름의 주제가 이미 있음") from error
            return cursor.rowcount > 0

    def delete(self, topic_id: int) -> bool:
        with self._db.connect() as conn:
            return conn.execute("DELETE FROM topics WHERE id = ?", (topic_id,)).rowcount > 0

    def get(self, topic_id: int) -> Topic | None:
        with self._db.connect() as conn:
            row = conn.execute("SELECT * FROM topics WHERE id = ?", (topic_id,)).fetchone()
        return None if row is None else _topic(row)

    def list_all(self) -> list[Topic]:
        with self._db.connect() as conn:
            return [_topic(r) for r in conn.execute("SELECT * FROM topics ORDER BY id")]

    def list_enabled(self) -> list[Topic]:
        return [topic for topic in self.list_all() if topic.enabled]

    # ---------- 글이 해당한 주제 ----------

    def record_matches(self, article_id: int, matches: Mapping[int, Sequence[str]]) -> None:
        """글이 해당한 주제와 일치한 키워드를 기록한다(M5의 피드백과 키워드 개선 제안에 쓴다)."""
        with self._db.connect() as conn:
            for topic_id, keywords in matches.items():
                conn.execute(
                    "INSERT OR REPLACE INTO article_topics(article_id, topic_id, matched_keywords) "
                    "VALUES(?, ?, ?)",
                    (article_id, topic_id, _dump(keywords)),
                )

    def matches_for(self, article_id: int) -> dict[int, tuple[str, ...]]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT topic_id, matched_keywords FROM article_topics WHERE article_id = ?",
                (article_id,),
            ).fetchall()
        return {row["topic_id"]: tuple(json.loads(row["matched_keywords"])) for row in rows}

    # ---------- 처음 설치할 때 ----------

    def ensure_defaults(self) -> bool:
        """주제가 없고 만든 적도 없으면 기본 주제(OTT)를 만든다. 지워도 다시 만들지 않는다."""
        now = self._clock.now().astimezone(UTC).isoformat()
        with self._db.connect() as conn:
            if conn.execute("SELECT 1 FROM settings WHERE key = ?", (SEEDED_KEY,)).fetchone():
                return False
            created = bool(conn.execute("SELECT COUNT(*) AS n FROM topics").fetchone()["n"] == 0)
            if created:
                conn.execute(
                    "INSERT INTO topics(name, name_key, description, keywords, webhook_id, "
                    "enabled, created_at) VALUES(?, ?, ?, ?, ?, 1, ?)",
                    (
                        DEFAULT_TOPIC_NAME,
                        DEFAULT_TOPIC_NAME.lower(),
                        DEFAULT_TOPIC_DESCRIPTION,
                        _dump((*DEFAULT_OTT_KEYWORDS.ko, *DEFAULT_OTT_KEYWORDS.en)),
                        self._legacy_ott_webhook(conn),
                        now,
                    ),
                )
            conn.execute(
                "INSERT INTO settings(key, value, updated_at) VALUES(?, '1', ?)", (SEEDED_KEY, now)
            )
            return created

    @staticmethod
    def _legacy_ott_webhook(conn: sqlite3.Connection) -> int | None:
        """이전 설정에서 OTT 웹훅으로 지정했던 웹훅(있고 아직 존재할 때)."""
        row = conn.execute("SELECT value FROM settings WHERE key = 'webhook_ott_id'").fetchone()
        if row is None or not str(row["value"]).isdigit():
            return None
        found = conn.execute(
            "SELECT id FROM webhooks WHERE id = ?", (int(row["value"]),)
        ).fetchone()
        return None if found is None else int(found["id"])
