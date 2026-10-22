"""잡 실행 기록: 작업마다 한 줄. /healthz, /status가 읽고, 재시작 뒤 슬롯 판단의 기준이 된다."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from rss_hub.services.clock import Clock
from rss_hub.storage.database import Database
from rss_hub.storage.timestamps import from_iso, to_iso

STATUS_RUNNING = "running"
STATUS_OK = "ok"
STATUS_ERROR = "error"


@dataclass(frozen=True)
class JobRun:
    job: str
    last_started_at: datetime | None
    last_finished_at: datetime | None
    last_ok_at: datetime | None
    last_status: str | None
    last_error: str | None
    last_slot: datetime | None
    skipped_count: int
    last_skipped_at: datetime | None
    last_result: str = ""  # 마지막으로 끝난 실행의 처리 결과 한 줄


def _run(row: sqlite3.Row) -> JobRun:
    return JobRun(
        job=row["job"],
        last_started_at=from_iso(row["last_started_at"]),
        last_finished_at=from_iso(row["last_finished_at"]),
        last_ok_at=from_iso(row["last_ok_at"]),
        last_status=row["last_status"],
        last_error=row["last_error"],
        last_slot=from_iso(row["last_slot"]),
        skipped_count=row["skipped_count"],
        last_skipped_at=from_iso(row["last_skipped_at"]),
        last_result=row["last_result"],
    )


class JobRunRepository:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    def _now(self) -> str:
        return to_iso(self._clock.now())

    def get(self, job: str) -> JobRun | None:
        with self._db.connect() as conn:
            row = conn.execute("SELECT * FROM job_runs WHERE job = ?", (job,)).fetchone()
        return None if row is None else _run(row)

    def all(self) -> dict[str, JobRun]:
        with self._db.connect() as conn:
            rows = conn.execute("SELECT * FROM job_runs").fetchall()
        return {row["job"]: _run(row) for row in rows}

    def mark_started(self, job: str, slot: datetime | None = None) -> None:
        """작업을 시작했다. 슬롯 작업이면 그 슬롯의 시작 시각을 함께 기록한다."""
        with self._db.connect() as conn:
            conn.execute("INSERT OR IGNORE INTO job_runs(job) VALUES(?)", (job,))
            conn.execute(
                "UPDATE job_runs SET last_started_at = ?, last_status = ?, "
                "last_slot = COALESCE(?, last_slot) WHERE job = ?",
                (self._now(), STATUS_RUNNING, None if slot is None else slot.isoformat(), job),
            )

    def mark_finished(self, job: str, error: str | None = None, result: str = "") -> None:
        """작업이 끝났다. error가 없으면 성공이다. result는 처리 결과 한 줄(실패하면 비운다)."""
        now = self._now()
        with self._db.connect() as conn:
            conn.execute("INSERT OR IGNORE INTO job_runs(job) VALUES(?)", (job,))
            conn.execute(
                "UPDATE job_runs SET last_finished_at = ?, last_status = ?, last_error = ?, "
                "last_result = ?, "
                "last_ok_at = CASE WHEN ? IS NULL THEN ? ELSE last_ok_at END WHERE job = ?",
                (
                    now,
                    STATUS_OK if error is None else STATUS_ERROR,
                    error,
                    "" if error else result,
                    error,
                    now,
                    job,
                ),
            )

    def recover_interrupted(self) -> int:
        """끝나지 못한 작업의 "실행 중"을 오류(Interrupted)로 바꾼다. 바꾼 수."""
        with self._db.connect() as conn:
            return conn.execute(
                "UPDATE job_runs SET last_status = ?, last_error = 'Interrupted', "
                "last_result = '', last_finished_at = ? WHERE last_status = ?",
                (STATUS_ERROR, self._now(), STATUS_RUNNING),
            ).rowcount

    def mark_skipped(self, job: str) -> None:
        """이전 실행이 끝나지 않아서 이번 실행을 건너뛰었다."""
        with self._db.connect() as conn:
            conn.execute("INSERT OR IGNORE INTO job_runs(job) VALUES(?)", (job,))
            conn.execute(
                "UPDATE job_runs SET skipped_count = skipped_count + 1, last_skipped_at = ? "
                "WHERE job = ?",
                (self._now(), job),
            )
