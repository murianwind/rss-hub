"""시계. 시간에 의존하는 코드는 이 포트를 통해서만 현재 시각을 얻는다(테스트에서 바꿔 끼운다)."""

from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """현재 시각(시간대 정보가 있는 값)."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)
