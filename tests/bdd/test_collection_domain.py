"""02_collection.feature 중 순수 규칙(발행 시각 해석, GUID)만으로 검증되는 시나리오."""

import json
import time
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from pytest_bdd import given, parsers, then, when

from rss_hub.domain.dates import parse_entry_datetime
from rss_hub.domain.guid import normalize_guid, select_guid
from tests.bdd.binding import bind

bind(
    globals(),
    "02_collection.feature",
    ["COL-03", "COL-04", "COL-05", "COL-06", "COL-08", "COL-09", "COL-10"],
)

SEOUL = ZoneInfo("Asia/Seoul")
GOLDEN = json.loads(
    (Path(__file__).resolve().parents[1] / "golden" / "legacy_golden.json").read_text(
        encoding="utf-8"
    )
)


@pytest.fixture
def ctx():
    return SimpleNamespace(entry={}, result=None, inputs=[])


def utc_tuple(text):
    parsed = time.strptime(text, "%Y-%m-%d %H:%M:%S")
    return time.struct_time(parsed)


# ---------- 발행 시각 ----------


@given(parsers.re(r'글의 발행 시각 문자열이 "(?P<published>.*)"이다'))
def _published_string(ctx, published):
    ctx.entry = {"published": published}


@given(parsers.parse("글에 파서가 해석한 발행 시각이 UTC {stamp}으로 있다"))
def _parsed_published(ctx, stamp):
    ctx.entry["published_parsed"] = utc_tuple(stamp)


@given(parsers.parse("글에 발행 시각은 없고 파서가 해석한 수정 시각이 UTC {stamp}으로 있다"))
def _parsed_updated_only(ctx, stamp):
    ctx.entry = {"updated_parsed": utc_tuple(stamp)}


@given(parsers.parse('같은 글의 발행 시각 문자열은 "{published}"이다'))
def _also_string(ctx, published):
    ctx.entry["published"] = published


@when("발행 시각을 해석한다")
def _parse(ctx):
    ctx.result = parse_entry_datetime(ctx.entry, SEOUL)


@then(parsers.parse('서비스 시간대 기준 시각은 "{expected}"이다'))
def _local_time(ctx, expected):
    assert ctx.result is not None
    assert ctx.result.isoformat() == expected


@then("발행 시각은 알 수 없음이다")
def _unknown(ctx):
    assert ctx.result is None


# ---------- GUID ----------

FIELD_PATTERNS = (
    (r'^(?P<name>id|guid|link) "(?P<value>.*)"$', None),
    (r'^제목 "(?P<title>.*)"와 요약 "(?P<summary>.*)"만$', "title_summary"),
)


@given(parsers.re(r"글에 (?P<fields>.+)가 있다"))
def _entry_fields(ctx, fields):
    import re

    simple = re.match(FIELD_PATTERNS[0][0], fields)
    if simple:
        ctx.entry = {simple["name"]: simple["value"]}
        return
    pair = re.match(FIELD_PATTERNS[1][0], fields)
    assert pair, f"해석할 수 없는 항목 표현: {fields}"
    ctx.entry = {"title": pair["title"], "summary": pair["summary"]}


@when("글의 GUID를 정한다")
def _choose_guid(ctx):
    ctx.result = select_guid(ctx.entry)


@then(parsers.parse('GUID는 "{expected}"이다'))
def _guid_is(ctx, expected):
    assert ctx.result == expected


@when(parsers.parse('GUID "{raw}"를 정규화한다'))
def _normalize(ctx, raw):
    ctx.result = normalize_guid(raw)


@then(parsers.parse('결과는 "{expected}"이다'))
def _normalized_is(ctx, expected):
    assert ctx.result == expected


@given("위 정규화 예시의 모든 입력이 있다")
def _all_inputs(ctx):
    ctx.inputs = [case["input"] for case in GOLDEN["normalize_guid"]["parity"]]


@when("각 입력을 두 번 정규화한다")
def _twice(ctx):
    ctx.result = [(normalize_guid(i), normalize_guid(normalize_guid(i))) for i in ctx.inputs]


@then("한 번 정규화한 결과와 두 번 정규화한 결과가 모두 같다")
def _idempotent(ctx):
    assert ctx.result
    assert all(once == twice for once, twice in ctx.result)
