"""무료 모델 목록(스캔 결과)과 벤치마크 실행, 점수 저장소."""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from rss_hub.domain.benchmark import ModelScore
from rss_hub.domain.models import FreeModel
from rss_hub.services.clock import Clock
from rss_hub.storage.database import Database
from rss_hub.storage.timestamps import from_iso, to_iso

RUN_RUNNING = "running"
RUN_DONE = "done"
RUN_FAILED = "failed"
RUN_INTERRUPTED = "interrupted"


@dataclass(frozen=True)
class CatalogEntry:
    id: str
    name: str
    context_length: int
    supports_json: bool
    first_seen_at: datetime
    last_seen_at: datetime
    gone: bool


@dataclass(frozen=True)
class ScanDiff:
    new: tuple[str, ...]  # 처음 보인 모델
    gone: tuple[str, ...]  # 목록에서 사라진 모델
    returned: tuple[str, ...]  # 사라졌다가 다시 보인 모델


@dataclass(frozen=True)
class RunInfo:
    id: int
    status: str
    finished_at: datetime | None
    total: int
    done: int
    note: str


class ModelRepository:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    # ---------- 목록 ----------

    def save_scan(self, models: Sequence[FreeModel]) -> ScanDiff:
        """스캔 결과를 반영하고 새로 보인 모델, 사라진 모델, 돌아온 모델을 알려 준다."""
        now = to_iso(self._clock.now())
        seen = {m.id for m in models}
        new: list[str] = []
        returned: list[str] = []
        gone: list[str] = []
        with self._db.connect() as conn:
            existing = {
                r["id"]: bool(r["gone"]) for r in conn.execute("SELECT id, gone FROM model_catalog")
            }
            for model in models:
                if model.id not in existing:
                    new.append(model.id)
                    conn.execute(
                        "INSERT INTO model_catalog(id, name, context_length, supports_json, "
                        "first_seen_at, last_seen_at) VALUES(?, ?, ?, ?, ?, ?)",
                        (
                            model.id,
                            model.name,
                            model.context_length,
                            int(model.supports_json),
                            now,
                            now,
                        ),
                    )
                else:
                    if existing[model.id]:
                        returned.append(model.id)
                    conn.execute(
                        "UPDATE model_catalog SET name = ?, context_length = ?, supports_json = ?, "
                        "last_seen_at = ?, gone = 0 WHERE id = ?",
                        (model.name, model.context_length, int(model.supports_json), now, model.id),
                    )
            for model_id, was_gone in existing.items():
                if model_id not in seen and not was_gone:
                    gone.append(model_id)
                    conn.execute("UPDATE model_catalog SET gone = 1 WHERE id = ?", (model_id,))
        return ScanDiff(tuple(sorted(new)), tuple(sorted(gone)), tuple(sorted(returned)))

    def catalog(self, *, include_gone: bool = False) -> list[CatalogEntry]:
        query = "SELECT * FROM model_catalog" + ("" if include_gone else " WHERE gone = 0")
        with self._db.connect() as conn:
            rows = conn.execute(query + " ORDER BY id").fetchall()
        return [
            CatalogEntry(
                r["id"],
                r["name"],
                r["context_length"],
                bool(r["supports_json"]),
                datetime.fromisoformat(r["first_seen_at"]),
                datetime.fromisoformat(r["last_seen_at"]),
                bool(r["gone"]),
            )
            for r in rows
        ]

    # ---------- 벤치마크 실행 ----------

    def start_run(self, total: int) -> int:
        with self._db.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO benchmark_runs(status, started_at, total) VALUES(?, ?, ?)",
                (RUN_RUNNING, to_iso(self._clock.now()), total),
            )
            return int(cursor.lastrowid or 0)

    def advance(self, run_id: int, done: int) -> None:
        with self._db.connect() as conn:
            conn.execute("UPDATE benchmark_runs SET done = ? WHERE id = ?", (done, run_id))

    def finish_run(self, run_id: int, status: str, note: str = "") -> None:
        with self._db.connect() as conn:
            conn.execute(
                "UPDATE benchmark_runs SET status = ?, finished_at = ?, note = ? WHERE id = ?",
                (status, to_iso(self._clock.now()), note, run_id),
            )

    def running_run(self) -> RunInfo | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM benchmark_runs WHERE status = ? ORDER BY id DESC LIMIT 1",
                (RUN_RUNNING,),
            ).fetchone()
        return None if row is None else _run(row)

    def latest_run(self) -> RunInfo | None:
        with self._db.connect() as conn:
            row = conn.execute("SELECT * FROM benchmark_runs ORDER BY id DESC LIMIT 1").fetchone()
        return None if row is None else _run(row)

    def interrupt_stale_runs(self, older_than: timedelta = timedelta(0)) -> int:
        """서비스가 꺼지면서 끝나지 못한 실행을 중단으로 표시한다(older_than보다 오래된 것만)."""
        cutoff = to_iso(self._clock.now() - older_than)
        with self._db.connect() as conn:
            return conn.execute(
                "UPDATE benchmark_runs SET status = ?, finished_at = ?, note = ? "
                "WHERE status = ? AND started_at <= ?",
                (
                    RUN_INTERRUPTED,
                    to_iso(self._clock.now()),
                    "서비스가 멈춰서 끝나지 못했습니다",
                    RUN_RUNNING,
                    cutoff,
                ),
            ).rowcount

    # ---------- 점수 ----------

    def save_score(self, run_id: int, score: ModelScore) -> None:
        with self._db.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO benchmark_scores(run_id, model, calls, ok, korean, topic, "
                "p50_ms, score, errors) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    score.model,
                    score.calls,
                    score.ok,
                    score.korean,
                    score.topic,
                    score.p50_ms,
                    score.score,
                    json.dumps(list(score.errors), ensure_ascii=False),
                ),
            )

    def latest_scores(self) -> dict[str, tuple[ModelScore, datetime]]:
        """모델마다 가장 최근 실행의 점수와 그 실행이 끝난 시각."""
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT s.*, r.finished_at, r.started_at FROM benchmark_scores s "
                "JOIN benchmark_runs r ON r.id = s.run_id "
                "WHERE s.run_id = (SELECT MAX(run_id) FROM benchmark_scores WHERE model = s.model)"
            ).fetchall()
        return {
            r["model"]: (
                ModelScore(
                    r["model"],
                    r["calls"],
                    r["ok"],
                    r["korean"],
                    r["topic"],
                    r["p50_ms"],
                    r["score"],
                    tuple(json.loads(r["errors"])),
                ),
                datetime.fromisoformat(r["finished_at"] or r["started_at"]),
            )
            for r in rows
        }


def _run(row: object) -> RunInfo:
    return RunInfo(
        id=row["id"],  # type: ignore[index]
        status=row["status"],  # type: ignore[index]
        finished_at=from_iso(row["finished_at"]),  # type: ignore[index]
        total=row["total"],  # type: ignore[index]
        done=row["done"],  # type: ignore[index]
        note=row["note"],  # type: ignore[index]
    )
