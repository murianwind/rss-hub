"""시스템 알림 기록: 같은 종류의 알림을 얼마나 자주 보냈는지 판단하는 데 쓴다."""

from datetime import UTC, datetime

from rss_hub.services.clock import Clock
from rss_hub.storage.database import Database


class AlertRepository:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    def last_sent(self, kind: str) -> datetime | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT MAX(sent_at) AS last FROM alert_log WHERE kind = ?", (kind,)
            ).fetchone()
        return None if row["last"] is None else datetime.fromisoformat(row["last"])

    def record(self, kind: str, text: str) -> None:
        with self._db.connect() as conn:
            conn.execute(
                "INSERT INTO alert_log(kind, sent_at, text) VALUES(?, ?, ?)",
                (kind, self._clock.now().astimezone(UTC).isoformat(), text),
            )
