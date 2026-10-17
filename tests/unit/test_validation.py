import json

import pytest

from rss_hub.domain.validation import (
    RejectReason,
    find_bad_content,
    validate_summary,
)


def good(**overrides):
    payload = {
        "title_ko": "애플, 새 폰 공개",
        "summary_ko": "애플이 새 폰을 공개했다.",
        "topics": [],
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


def test_accepts_a_valid_response():
    result = validate_summary(good(), finish_reason="stop")
    assert result.ok
    assert result.draft is not None
    assert result.draft.title_ko == "애플, 새 폰 공개"
    assert result.draft.summary_ko == "애플이 새 폰을 공개했다."
    assert result.draft.topics == ()
    assert result.reason is None


def test_accepts_json_wrapped_in_a_code_fence():
    raw = "```json\n" + good() + "\n```"
    assert validate_summary(raw, finish_reason="stop").ok


def test_trims_whitespace():
    result = validate_summary(good(title_ko="  제목  ", summary_ko=" 요약 "), "stop")
    assert result.draft is not None
    assert (result.draft.title_ko, result.draft.summary_ko) == ("제목", "요약")


def test_missing_topics_mean_no_topic_and_the_answer_is_still_accepted():
    raw = json.dumps({"title_ko": "제목", "summary_ko": "요약"}, ensure_ascii=False)
    result = validate_summary(raw, "stop", valid_topic_ids={1})
    assert result.ok
    assert result.draft is not None
    assert result.draft.topics == ()


def topics_of(value, valid=(1, 2, 3)):
    result = validate_summary(good(topics=value), "stop", valid_topic_ids=valid)
    assert result.draft is not None
    return result.draft.topics


def test_the_chosen_topic_numbers_are_kept_in_order_without_duplicates():
    assert topics_of([3, 1, 3]) == (3, 1)


def test_numbers_that_were_not_requested_are_dropped():
    assert topics_of([1, 99, 0, -1]) == (1,)
    assert topics_of([1, 2], valid=()) == ()


def test_digit_strings_are_accepted_but_other_values_are_ignored():
    assert topics_of(["2", " 3 ", "x", "1.5", "", None, 1.0, 2.5, True, False, [1], {"a": 1}]) == (
        2,
        3,
    )


@pytest.mark.parametrize("value", ["1", 1, {"1": True}, None, True])
def test_a_topics_value_that_is_not_a_list_means_no_topic(value):
    assert topics_of(value) == ()


@pytest.mark.parametrize(
    ("raw", "finish", "reason"),
    [
        ("그냥 문장입니다.", "stop", RejectReason.NOT_JSON),
        ("[1, 2, 3]", "stop", RejectReason.NOT_JSON),
        ("", "stop", RejectReason.NOT_JSON),
        (json.dumps({"title_ko": "제목"}), "stop", RejectReason.MISSING_FIELD),
        (json.dumps({"summary_ko": "요약"}), "stop", RejectReason.MISSING_FIELD),
        (json.dumps({"title_ko": 1, "summary_ko": "요약"}), "stop", RejectReason.MISSING_FIELD),
        (good(title_ko="   "), "stop", RejectReason.EMPTY_TITLE),
        (good(summary_ko=""), "stop", RejectReason.EMPTY_SUMMARY),
        (good(summary_ko="요약에 漢字가 섞임"), "stop", RejectReason.HANJA),
        (good(title_ko="제목에 漢字가 섞임"), "stop", RejectReason.HANJA),
        (good(summary_ko="We need to translate this"), "stop", RejectReason.REASONING_LEAK),
        (good(summary_ko="Korean summary: 요약"), "stop", RejectReason.REASONING_LEAK),
        (good(summary_ko="SUMMARY: 요약"), "stop", RejectReason.FORMAT_MARKER),
        (good(title_ko="TITLE: 제목"), "stop", RejectReason.FORMAT_MARKER),
        (good(), "length", RejectReason.TRUNCATED),
    ],
)
def test_rejections(raw, finish, reason):
    result = validate_summary(raw, finish)
    assert not result.ok
    assert result.draft is None
    assert result.reason is reason


def test_forbidden_phrases_are_configurable():
    custom = ("As an AI",)
    assert validate_summary(good(summary_ko="As an AI model"), "stop", custom).reason is (
        RejectReason.REASONING_LEAK
    )
    assert validate_summary(good(summary_ko="We need to translate"), "stop", custom).ok


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("ok", None),
        ("정상 요약", None),
        ("TITLE: x", RejectReason.FORMAT_MARKER),
        ("We need to translate this", RejectReason.REASONING_LEAK),
        ("漢字 포함", RejectReason.HANJA),
    ],
)
def test_find_bad_content(text, reason):
    assert find_bad_content(text) is reason
