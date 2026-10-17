"""기존 스크립트(골든 데이터)와 새 도메인 구현을 비교한다.

parity          같은 입력에 같은 결과
known_defects   기존이 틀렸던 케이스. 새 구현은 new_expected를 따라야 한다
invariants      정확한 값이 아니라 만족해야 할 성질
"""

import json
import time
from collections import Counter
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from rss_hub.domain.dates import parse_entry_datetime
from rss_hub.domain.guid import normalize_guid, select_guid
from rss_hub.domain.keywords import DEFAULT_OTT_KEYWORDS
from rss_hub.domain.korean import is_korean
from rss_hub.domain.message import MAX_MESSAGE_LENGTH, build_message
from rss_hub.domain.schedule import (
    PRIORITY_EVERY_SLOT,
    Activity,
    FeedRef,
    activity_score,
    build_schedule,
    desired_checks,
    slot_for,
)
from rss_hub.domain.topics import Topic, match_topic
from rss_hub.domain.validation import find_bad_content

pytestmark = pytest.mark.golden

GOLDEN = json.loads(Path(__file__).with_name("legacy_golden.json").read_text(encoding="utf-8"))
SEOUL = ZoneInfo(GOLDEN["meta"]["tz"])
LEGACY_MODEL_RULES = {"fallback", "korean-passthrough", "korean-summary"}


def test_golden_file_was_generated_for_the_expected_environment():
    assert GOLDEN["meta"]["tz"] == "Asia/Seoul"
    assert "rss_collector.py" in GOLDEN["meta"]["legacy_files"]


# ---------- GUID ----------


@pytest.mark.parametrize(
    "case", GOLDEN["normalize_guid"]["parity"], ids=lambda c: repr(c["input"])[:50]
)
def test_normalize_guid_parity(case):
    assert normalize_guid(case["input"]) == case["expected"]


def test_normalize_guid_idempotency_matches_legacy():
    assert GOLDEN["normalize_guid"]["idempotent_for_all_inputs"] is True
    for case in GOLDEN["normalize_guid"]["parity"]:
        once = normalize_guid(case["input"])
        assert normalize_guid(once) == once


@pytest.mark.parametrize(
    "case", GOLDEN["guid_for"]["parity"], ids=lambda c: str(sorted(c["entry"]))[:40]
)
def test_select_guid_parity(case):
    assert select_guid(case["entry"]) == case["expected"]


# ---------- 발행 시각 ----------


def _entry_from_json(entry):
    return {k: (time.struct_time(v) if k.endswith("_parsed") else v) for k, v in entry.items()}


@pytest.mark.parametrize(
    "case",
    GOLDEN["parsed_entry_datetime"]["parity"],
    ids=lambda c: str(sorted(c["entry"].items()))[:50],
)
def test_parse_entry_datetime_parity(case):
    result = parse_entry_datetime(_entry_from_json(case["entry"]), SEOUL)
    if case["expected_iso"] is None:
        assert result is None
    else:
        assert result is not None
        assert result.isoformat() == case["expected_iso"]
        assert result.date().isoformat() == case["expected_date"]


# ---------- 한국어 판별과 불량 응답 ----------


@pytest.mark.parametrize("case", GOLDEN["is_korean"]["parity"], ids=lambda c: repr(c["text"])[:30])
def test_is_korean_parity(case):
    assert is_korean(case["text"]) is case["expected"]


def _content_based(case):
    item = case["item"]
    return (
        bool(item.get("translated")) and item.get("translated_model", "") not in LEGACY_MODEL_RULES
    )


@pytest.mark.parametrize(
    "case",
    [c for c in GOLDEN["needs_retranslation"]["parity"] if _content_based(c)],
    ids=lambda c: repr(c["item"])[:50],
)
def test_bad_content_rules_match_legacy_content_checks(case):
    # 레거시 판정 중 "내용" 기반 규칙(형식 표지, 사고 과정 문구, 한자)만 새 검증 규칙과 비교한다.
    # 모델 이름 기반 규칙(fallback 등)은 기존 데이터를 가져오지 않으므로 더 이상 쓰지 않는다.
    assert (find_bad_content(case["item"]["translated"]) is not None) is case["expected"]


# ---------- 스케줄 ----------


@pytest.mark.parametrize("case", GOLDEN["desired_checks_per_hour"]["parity"])
def test_desired_checks_parity(case):
    activity = Activity(
        recent_count_7d=case["recent_count_7d"], target_date_count=case["target_date_count"]
    )
    assert desired_checks(FeedRef("x"), activity, slots=12) == case["expected_checks"]
    assert activity_score(activity) == case["expected_score"]


@pytest.mark.parametrize("case", GOLDEN["current_slot"]["parity"])
def test_current_slot_parity(case):
    assert slot_for(case["minute"], 5) == case["expected"]


def _feeds(count, prefix="f"):
    return [FeedRef(f"{prefix}{i:03d}") for i in range(count)]


def test_schedule_invariants_match_legacy():
    inv = GOLDEN["schedule"]["invariants"]
    schedule = build_schedule(_feeds(inv["feeds"]), {}, interval_minutes=5)
    assert schedule.slots == inv["runs_per_hour"]
    assert schedule.batch_size == inv["batch_size"]
    assert schedule.capacity == inv["capacity"]
    covered = {key for batch in schedule.batches for key in batch}
    assert (len(covered) == inv["feeds"]) is inv["every_feed_covered_at_least_once"]
    assert max(len(b) for b in schedule.batches) == inv["max_slot_size"]


def test_batch_size_for_200_feeds_matches_legacy():
    schedule = build_schedule(_feeds(200), {}, interval_minutes=5)
    assert schedule.batch_size == GOLDEN["schedule"]["batch_size_for_200_feeds"]


def _slots_with(schedule, key):
    return sum(1 for batch in schedule.batches if key in batch)


@pytest.mark.parametrize("case", GOLDEN["schedule"]["known_defects"], ids=lambda c: c["case"])
def test_every_slot_feed_defect_is_fixed(case):
    hot = FeedRef("hot", priority=PRIORITY_EVERY_SLOT)
    feeds = [*_feeds(133), hot]
    if "통계가 없는" in case["case"]:
        activity: dict[str, Activity] = {}
    else:
        activity = {f.key: Activity(recent_count_7d=30, target_date_count=30) for f in feeds}
        activity["hot"] = Activity(recent_count_7d=50, target_date_count=10)
    schedule = build_schedule(feeds, activity, interval_minutes=5)
    assert case["legacy_slots_for_every_slot_feed"] != case["new_expected_slots"]
    assert _slots_with(schedule, "hot") == case["new_expected_slots"]
    assert Counter(key for b in schedule.batches for key in b)["hot"] == 12


# ---------- OTT 키워드 확인(이제는 기본 OTT 주제의 판별) ----------

OTT_TOPIC = Topic(1, "OTT", "", (*DEFAULT_OTT_KEYWORDS.ko, *DEFAULT_OTT_KEYWORDS.en), None, True)


def is_ott_article(llm_flag, title, content):
    """기존 코드의 판정(LLM이 맞다고 했고 키워드도 있어야 OTT)과 같은 결과여야 한다."""
    ids = None if llm_flag is None else ({1} if llm_flag else set())
    return match_topic(OTT_TOPIC, ids, title, content) is not None


@pytest.mark.parametrize(
    "case",
    GOLDEN["ott_gate"]["parity"],
    ids=lambda c: f"{c['title']}|{c['is_ott']}",
)
def test_ott_gate_parity(case):
    assert is_ott_article(case["is_ott"], case["title"], case["content"]) is case["expected"]


@pytest.mark.parametrize(
    "case",
    GOLDEN["ott_gate"]["known_defects"],
    ids=lambda c: f"{c['title']}|{c.get('content', '')[:20]}",
)
def test_ott_gate_known_defects_are_fixed(case):
    result = is_ott_article(True, case["title"], case.get("content", ""))
    assert case["legacy"] != case["new_expected"]
    assert result is case["new_expected"]


# ---------- Discord 메시지 ----------


def test_long_message_keeps_the_link():
    defect = GOLDEN["discord_message"]["known_defects"][0]
    assert defect["legacy_link_preserved"] is False
    link = "https://rss.example.com/a/123"
    message = build_message(
        site="Blog",
        emoji="📢",
        title="제목",
        summary="가" * 2500,
        published="2026-10-16T14:32:00+09:00",
        link_url=link,
        tz=SEOUL,
    )
    assert (link in message) is defect["new_expected_link_preserved"]
    assert len(message) <= defect["new_expected_max_length"] == MAX_MESSAGE_LENGTH
