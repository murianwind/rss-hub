"""발송 기록: 글 하나를 목적지(웹훅과 용도)마다 따로 기록한다."""

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from rss_hub.domain.routing import Target
from rss_hub.services.clock import Clock
from rss_hub.storage.database import Database

STATUS_PENDING = "pending"
STATUS_SENT = "sent"
STATUS_FAILED_PERMANENT = "failed_permanent"


@dataclass(frozen=True)
class Delivery:
    id: int
    article_id: int
    webhook_id: int
    purpose: str
    status: str
    attempts: int
    last_error: str | None
    message_id: str | None
    sent_at: datetime | None
    created_at: datetime


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


def _delivery(row: sqlite3.Row) -> Delivery:
    return Delivery(
        id=row["id"],
        article_id=row["article_id"],
        webhook_id=row["webhook_id"],
        purpose=row["purpose"],
        status=row["status"],
        attempts=row["attempts"],
        last_error=row["last_error"],
        message_id=row["message_id"],
        sent_at=datetime.fromisoformat(row["sent_at"]) if row["sent_at"] else None,
        created_at=datetime.fromisoformat(row["created_at"]),
    )


class DeliveryRepository:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    def ensure(self, article_id: int, targets: Sequence[Target]) -> list[Delivery]:
        """대상마다 기록이 없으면 pending으로 만든다. 이미 있으면 진행 상태를 그대로 둔다."""
        now = _iso(self._clock.now())
        rows: list[Delivery] = []
        with self._db.connect() as conn:
            for target in targets:
                conn.execute(
                    "INSERT OR IGNORE INTO deliveries(article_id, webhook_id, purpose, created_at) "
                    "VALUES(?, ?, ?, ?)",
                    (article_id, target.webhook_id, target.purpose, now),
                )
                row = conn.execute(
                    "SELECT * FROM deliveries "
                    "WHERE article_id = ? AND webhook_id = ? AND purpose = ?",
                    (article_id, target.webhook_id, target.purpose),
                ).fetchone()
                rows.append(_delivery(row))
        return rows

    def record_attempt_failure(self, delivery_id: int, error: str) -> None:
        """보내지 못했다: 시도 횟수를 올리고 pending으로 남긴다."""
        with self._db.connect() as conn:
            conn.execute(
                "UPDATE deliveries SET attempts = attempts + 1, last_error = ? WHERE id = ?",
                (error, delivery_id),
            )

    def mark_sent(self, delivery_id: int, message_id: str | None) -> None:
        with self._db.connect() as conn:
            conn.execute(
                "UPDATE deliveries SET status = ?, attempts = attempts + 1, last_error = NULL, "
                "message_id = ?, sent_at = ? WHERE id = ?",
                (STATUS_SENT, message_id, _iso(self._clock.now()), delivery_id),
            )

    def mark_permanent(self, delivery_id: int, error: str) -> None:
        """웹훅이 거부했다: 더 이상 이 대상으로 다시 보내지 않는다."""
        with self._db.connect() as conn:
            conn.execute(
                "UPDATE deliveries SET status = ?, attempts = attempts + 1, last_error = ? "
                "WHERE id = ?",
                (STATUS_FAILED_PERMANENT, error, delivery_id),
            )

    def for_article(self, article_id: int) -> list[Delivery]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM deliveries WHERE article_id = ? ORDER BY id", (article_id,)
            ).fetchall()
        return [_delivery(row) for row in rows]

    def count_by_status(self) -> dict[str, int]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS n FROM deliveries GROUP BY status"
            ).fetchall()
        return {row["status"]: row["n"] for row in rows}
