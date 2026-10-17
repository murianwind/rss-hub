"""피드 항목의 발행 시각 해석."""

import calendar
from collections.abc import Mapping
from datetime import UTC, datetime, tzinfo
from email.utils import parsedate_to_datetime
from typing import Any

PARSED_KEYS = ("published_parsed", "updated_parsed", "created_parsed")
STRING_KEYS = ("published", "updated", "created")


def _from_parsed(value: Any, tz: tzinfo) -> datetime | None:
    """feedparser가 UTC 기준으로 풀어 준 시간 튜플을 서비스 시간대 시각으로 바꾼다."""
    try:
        return datetime.fromtimestamp(calendar.timegm(value), tz=UTC).astimezone(tz)
    except (TypeError, ValueError, OverflowError):
        return None


def _from_string(raw: str, tz: tzinfo) -> datetime | None:
    """RFC 822(이메일 형식)를 먼저, 안 되면 ISO 8601로 해석한다.

    시간대가 없는 값은 서비스 시간대로 본다.
    """
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        parsed = None
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed.astimezone(tz)


def parse_entry_datetime(entry: Mapping[str, Any], tz: tzinfo) -> datetime | None:
    """항목의 발행 시각을 tz 기준으로 돌려준다. 알 수 없으면 None.

    우선순위: 파서가 해석한 값(published → updated → created),
    그다음 원문 문자열(published → updated → created).
    """
    for key in PARSED_KEYS:
        value = entry.get(key)
        if value:
            result = _from_parsed(value, tz)
            if result is not None:
                return result
    for key in STRING_KEYS:
        raw = entry.get(key)
        if raw:
            result = _from_string(str(raw), tz)
            if result is not None:
                return result
    return None
