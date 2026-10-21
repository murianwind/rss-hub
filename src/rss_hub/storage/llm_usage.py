"""LLM 호출 기록. 호출 한 번(성공이든 실패든)마다 한 줄을 남기고 날짜(UTC)별로 센다."""

from datetime import UTC, date, datetime

from rss_hub.services.clock import Clock
from rss_hub.storage.database import Database
from rss_hub.storage.timestamps import to_iso


class LlmUsageRepository:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    def record(
        self,
        *,
        model: str,
        outcome: str,
        status: int,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        reasoning_tokens: int | None = None,
    ) -> None:
        now = self._clock.now().astimezone(UTC)
        with self._db.connect() as conn:
            conn.execute(
                "INSERT INTO llm_usage(called_at, day, model, outcome, status, prompt_tokens, "
                "completion_tokens, reasoning_tokens) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    now.isoformat(),
                    now.date().isoformat(),
                    model,
                    outcome,
                    status,
                    prompt_tokens,
                    completion_tokens,
                    reasoning_tokens,
                ),
            )

    def count_day(self, day: date) -> int:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM llm_usage WHERE day = ?", (day.isoformat(),)
            ).fetchone()
        return int(row["n"])

    def count_since(self, moment: datetime) -> int:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM llm_usage WHERE called_at >= ?",
                (to_iso(moment),),
            ).fetchone()
        return int(row["n"])
