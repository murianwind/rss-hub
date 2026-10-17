import time
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from rss_hub.domain.dates import parse_entry_datetime

SEOUL = ZoneInfo("Asia/Seoul")


def struct(*parts):
    return time.struct_time(parts)


@pytest.mark.parametrize(
    ("published", "expected"),
    [
        ("Fri, 16 Oct 2026 01:30:00 +0900", "2026-10-16T01:30:00+09:00"),
        ("Fri, 16 Oct 2026 01:30:00 GMT", "2026-10-16T10:30:00+09:00"),
        ("2026-10-16T01:30:00Z", "2026-10-16T10:30:00+09:00"),
        ("2026-10-16T01:30:00", "2026-10-16T01:30:00+09:00"),
        ("Fri, 16 Oct 2026 01:30:00", "2026-10-16T01:30:00+09:00"),
    ],
)
def test_string_dates_are_converted_to_service_timezone(published, expected):
    result = parse_entry_datetime({"published": published}, SEOUL)
    assert result is not None
    assert result.isoformat() == expected


@pytest.mark.parametrize("published", ["not a date", "", None])
def test_unparseable_dates_return_none(published):
    assert parse_entry_datetime({"published": published}, SEOUL) is None


def test_entry_without_any_date_returns_none():
    assert parse_entry_datetime({}, SEOUL) is None


def test_parsed_tuple_is_treated_as_utc():
    entry = {"published_parsed": struct(2026, 10, 15, 16, 30, 0, 0, 0, 0)}
    result = parse_entry_datetime(entry, SEOUL)
    assert result is not None
    assert result.isoformat() == "2026-10-16T01:30:00+09:00"


def test_published_parsed_wins_over_updated_parsed_and_strings():
    entry = {
        "published_parsed": struct(2026, 10, 15, 16, 30, 0, 0, 0, 0),
        "updated_parsed": struct(2026, 10, 14, 0, 0, 0, 0, 0, 0),
        "published": "Fri, 16 Oct 2026 23:00:00 +0900",
    }
    result = parse_entry_datetime(entry, SEOUL)
    assert result is not None
    assert result.isoformat() == "2026-10-16T01:30:00+09:00"


def test_updated_parsed_is_used_when_published_parsed_is_missing():
    entry = {"updated_parsed": struct(2026, 10, 16, 0, 5, 0, 0, 0, 0)}
    result = parse_entry_datetime(entry, SEOUL)
    assert result is not None
    assert result.isoformat() == "2026-10-16T09:05:00+09:00"


def test_string_fields_are_tried_in_order_published_updated_created():
    entry = {"updated": "2026-10-16T01:30:00Z", "created": "2020-01-01T00:00:00Z"}
    result = parse_entry_datetime(entry, SEOUL)
    assert result is not None
    assert result.isoformat() == "2026-10-16T10:30:00+09:00"


def test_broken_parsed_tuple_falls_back_to_string_date():
    entry = {"published_parsed": "garbage", "published": "2026-10-16T01:30:00Z"}
    result = parse_entry_datetime(entry, SEOUL)
    assert result is not None
    assert result.isoformat() == "2026-10-16T10:30:00+09:00"


def test_result_uses_the_given_timezone_not_the_process_timezone():
    entry = {"published": "2026-10-15T16:30:00Z"}
    utc = parse_entry_datetime(entry, UTC)
    seoul = parse_entry_datetime(entry, SEOUL)
    assert utc is not None and seoul is not None
    assert utc.date().isoformat() == "2026-10-15"
    assert seoul.date().isoformat() == "2026-10-16"
    assert utc == seoul
    assert isinstance(seoul, datetime)
