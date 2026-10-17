"""가져오기 미리보기의 임시 보관. 확정하기 전까지 구독 목록은 바뀌지 않는다."""

import secrets
from datetime import UTC, datetime, timedelta

from rss_hub.services.clock import Clock
from rss_hub.storage.database import Database


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


class ImportStagingRepository:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    def save(self, payload: str, *, ttl: timedelta) -> str:
        """미리보기를 보관하고 추측할 수 없는 토큰을 돌려준다."""
        token = secrets.token_urlsafe(24)
        now = self._clock.now()
        with self._db.connect() as conn:
            conn.execute(
                "INSERT INTO import_staging(token, payload, created_at, expires_at) "
                "VALUES(?, ?, ?, ?)",
                (token, payload, _iso(now), _iso(now + ttl)),
            )
        return token

    def load(self, token: str) -> str | None:
        """보관 중인 미리보기. 없거나 만료되었으면 None(만료된 것은 지운다)."""
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT payload, expires_at FROM import_staging WHERE token = ?", (token,)
            ).fetchone()
            if row is None:
                return None
            if datetime.fromisoformat(row["expires_at"]) <= self._clock.now():
                conn.execute("DELETE FROM import_staging WHERE token = ?", (token,))
                return None
            return str(row["payload"])

    def delete(self, token: str) -> None:
        with self._db.connect() as conn:
            conn.execute("DELETE FROM import_staging WHERE token = ?", (token,))

    def purge_expired(self) -> int:
        with self._db.connect() as conn:
            cursor = conn.execute(
                "DELETE FROM import_staging WHERE expires_at <= ?", (_iso(self._clock.now()),)
            )
            return cursor.rowcount

    def count(self) -> int:
        with self._db.connect() as conn:
            return int(conn.execute("SELECT COUNT(*) AS n FROM import_staging").fetchone()["n"])
