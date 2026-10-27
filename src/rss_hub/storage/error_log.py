"""서버 오류 기록. 같은 날의 같은 유형, 대상, 메시지는 한 줄로 묶어 횟수와 시각만 갱신한다."""

import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime

from rss_hub.domain.error_log import (
    MAX_DETAIL,
    MAX_FIELD,
    MAX_LISTED,
    SORT_COUNT,
    SORT_KIND,
)
from rss_hub.services.clock import Clock
from rss_hub.storage.database import Database
from rss_hub.storage.timestamps import to_iso


@dataclass(frozen=True)
class ErrorEntry:
    id: int
    kind: str
    source: str
    message: str
    detail: str
    count: int
    first_at: datetime
    last_at: datetime


_ORDER = {
    SORT_KIND: "kind, last_at DESC, id DESC",
    SORT_COUNT: "count DESC, last_at DESC, id DESC",
}
_DEFAULT_ORDER = "last_at DESC, id DESC"


def _entry(row: sqlite3.Row) -> ErrorEntry:
    return ErrorEntry(
        id=row["id"],
        kind=row["kind"],
        source=row["source"],
        message=row["message"],
        detail=row["detail"],
        count=row["count"],
        first_at=datetime.fromisoformat(row["first_at"]),
        last_at=datetime.fromisoformat(row["last_at"]),
    )


class ErrorLogRepository:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    def record(self, kind: str, source: str, message: str, detail: str = "") -> None:
        now = self._clock.now().astimezone(UTC)
        stamp, day = to_iso(now), now.date().isoformat()
        source, message, detail = source[:MAX_FIELD], message[:MAX_FIELD], detail[:MAX_DETAIL]
        with self._db.connect() as conn:
            updated = conn.execute(
                "UPDATE error_log SET count = count + 1, last_at = ?, detail = ? "
                "WHERE day = ? AND kind = ? AND source = ? AND message = ?",
                (stamp, detail, day, kind, source, message),
            ).rowcount
            if not updated:
                conn.execute(
                    "INSERT INTO error_log(day, kind, source, message, detail, first_at, last_at) "
                    "VALUES(?, ?, ?, ?, ?, ?, ?)",
                    (day, kind, source, message, detail, stamp, stamp),
                )

    def list(self, *, kind: str = "", sort: str = "") -> list[ErrorEntry]:
        where, params = ("WHERE kind = ?", [kind]) if kind else ("", [])
        order = _ORDER.get(sort, _DEFAULT_ORDER)
        with self._db.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM error_log {where} ORDER BY {order} LIMIT ?", [*params, MAX_LISTED]
            ).fetchall()
        return [_entry(row) for row in rows]

    def counts_by_kind(self) -> dict[str, int]:
        """유형별 일어난 횟수의 합(같은 줄로 묶인 것도 센다)."""
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT kind, SUM(count) AS n FROM error_log GROUP BY kind"
            ).fetchall()
        return {row["kind"]: int(row["n"]) for row in rows}

    def delete_before(self, day: date) -> int:
        """주어진 날짜(UTC) 이전의 기록을 지운다. 지운 줄 수."""
        with self._db.connect() as conn:
            return conn.execute("DELETE FROM error_log WHERE day < ?", (day.isoformat(),)).rowcount
