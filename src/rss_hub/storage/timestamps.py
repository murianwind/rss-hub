"""저장소가 시각을 문자열 열에 저장하고 읽는 방식(UTC ISO 8601) 한 곳."""

from datetime import UTC, datetime


def to_iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


def from_iso(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None
