from datetime import UTC, datetime, timedelta


class FakeClock:
    """시각을 직접 정하고 앞으로 보낼 수 있는 시계."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 10, 16, 5, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def set(self, moment: datetime) -> None:
        self._now = moment

    def advance(self, **kwargs: float) -> None:
        self._now += timedelta(**kwargs)
