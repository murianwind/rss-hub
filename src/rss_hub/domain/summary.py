"""요약 대상 글의 처리 순서."""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol


class Summarizable(Protocol):
    @property
    def retry_count(self) -> int: ...

    @property
    def published_dt(self) -> datetime: ...


def summary_order[T: Summarizable](items: Sequence[T]) -> list[T]:
    """처음 처리하는 글을 재시도 글보다 먼저, 같은 그룹에서는 오래된 글부터 처리한다."""
    return sorted(items, key=lambda item: (item.retry_count > 0, item.published_dt))
