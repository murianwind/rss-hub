"""작업 이력. 수집, 전문 가져오기, 요약, 발송, LLM 호출의 결과를 일어난 순간마다 한 줄씩 남긴다."""

import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime

from rss_hub.domain.activity_log import (
    MAX_DETAIL,
    MAX_FIELD,
    MAX_LISTED,
    SORT_FAIL,
    SORT_KIND,
)
from rss_hub.services.clock import Clock
from rss_hub.storage.database import Database
from rss_hub.storage.timestamps import to_iso


@dataclass(frozen=True)
class ActivityEntry:
    id: int
    kind: str
    outcome: str
    source: str
    message: str
    detail: str
    at: datetime


_ORDER = {
    SORT_KIND: "kind, at DESC, id DESC",
    SORT_FAIL: "(outcome = 'fail') DESC, at DESC, id DESC",
}
_DEFAULT_ORDER = "at DESC, id DESC"


def _entry(row: sqlite3.Row) -> ActivityEntry:
    return ActivityEntry(
        id=row["id"],
        kind=row["kind"],
        outcome=row["outcome"],
        source=row["source"],
        message=row["message"],
        detail=row["detail"],
        at=datetime.fromisoformat(row["at"]),
    )


class ActivityLogRepository:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    def record(self, kind: str, outcome: str, source: str, message: str, detail: str = "") -> None:
        now = self._clock.now().astimezone(UTC)
        with self._db.connect() as conn:
            conn.execute(
                "INSERT INTO activity_log(day, kind, outcome, source, message, detail, at) "
                "VALUES(?, ?, ?, ?, ?, ?, ?)",
                (
                    now.date().isoformat(),
                    kind,
                    outcome,
                    source[:MAX_FIELD],
                    message[:MAX_FIELD],
                    detail[:MAX_DETAIL],
                    to_iso(now),
                ),
            )

    def list(self, *, kind: str = "", outcome: str = "", sort: str = "") -> list[ActivityEntry]:
        clauses, params = [], []
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        if outcome:
            clauses.append("outcome = ?")
            params.append(outcome)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        order = _ORDER.get(sort, _DEFAULT_ORDER)
        with self._db.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM activity_log {where} ORDER BY {order} LIMIT ?",
                [*params, MAX_LISTED],
            ).fetchall()
        return [_entry(row) for row in rows]

    def counts(self) -> dict[tuple[str, str], int]:
        """(유형, 결과)별 줄 수."""
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT kind, outcome, COUNT(*) AS n FROM activity_log GROUP BY kind, outcome"
            ).fetchall()
        return {(row["kind"], row["outcome"]): int(row["n"]) for row in rows}

    def delete_before(self, day: date) -> int:
        """주어진 날짜(UTC) 이전의 기록을 지운다. 지운 줄 수."""
        with self._db.connect() as conn:
            return conn.execute(
                "DELETE FROM activity_log WHERE day < ?", (day.isoformat(),)
            ).rowcount
