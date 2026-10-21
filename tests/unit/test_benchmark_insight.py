import pytest

from rss_hub.domain.benchmark import (
    CallResult,
    describe_error,
    explain_score,
    format_tokens,
    is_unmeasured,
    score_model,
)


def ok(latency=2000, topic=True):
    return CallResult(True, True, topic, latency)


def bad(code):
    return CallResult(False, False, False, None, code)


@pytest.mark.parametrize(
    ("count", "text"),
    [
        (512, "512"),
        (999, "999"),
        (1000, "1K"),
        (32768, "33K"),
        (262144, "262K"),
        (1_000_000, "1M"),
        (1_048_576, "1M"),
        (2_500_000, "2.5M"),
    ],
)
def test_context_lengths_are_shortened(count, text):
    assert format_tokens(count) == text


def test_every_known_error_has_a_label_and_a_plain_explanation():
    for code in (
        "rate_limited",
        "unavailable",
        "payment",
        "unauthorized",
        "policy",
        "unsupported",
        "other",
        "not_json",
        "missing_field",
        "empty_title",
        "empty_summary",
        "hanja",
        "reasoning_leak",
        "format_marker",
        "truncated",
    ):
        info = describe_error(code)
        assert info.label and info.explanation and info.label != "응답이 올바르지 않음", code


def test_an_unknown_error_code_still_gets_a_fallback_explanation():
    assert describe_error("brand_new").label == "응답이 올바르지 않음"


def test_only_rate_limits_and_outages_are_transient():
    transient = {
        c
        for c in ("rate_limited", "unavailable", "payment", "truncated", "other")
        if describe_error(c).transient
    }
    assert transient == {"rate_limited", "unavailable"}


def test_a_score_is_explained_with_its_parts_and_failures():
    score = score_model(
        "m", [ok(), ok(), ok(topic=False), ok(), bad("truncated"), bad("rate_limited")]
    )
    explained = explain_score(score)
    assert explained.measured
    assert explained.headline == f"종합 {score.score:g}점"
    assert explained.parts == ("성공 4/6(67%)", "한국어 제목 4/4", "주제 판정 3/4", "응답 2초")
    assert {(f.label, f.count) for f in explained.failures} == {
        ("응답이 잘림", 1),
        ("요청 한도 초과", 1),
    }


def test_failures_are_listed_most_frequent_first():
    explained = explain_score(score_model("m", [bad("truncated")] + [bad("not_json")] * 3))
    assert [f.count for f in explained.failures] == [3, 1]


def test_fractional_seconds_keep_one_decimal():
    assert "응답 4.2초" in explain_score(score_model("m", [ok(latency=4200)])).parts


@pytest.mark.parametrize(
    ("results", "unmeasured"),
    [
        ([bad("rate_limited")] * 6, True),
        ([bad("rate_limited"), bad("unavailable")], True),
        ([bad("rate_limited"), bad("truncated")], False),  # 품질 때문에 실패한 호출이 섞였다
        ([ok(), bad("rate_limited")], False),  # 통과한 호출이 있으면 점수를 낸다
        ([bad("truncated")] * 6, False),
        ([], False),
    ],
)
def test_a_model_is_unmeasured_only_when_every_failure_is_unrelated_to_quality(results, unmeasured):
    score = score_model("m", results)
    assert is_unmeasured(score) is unmeasured
    assert explain_score(score).measured is (not unmeasured)
    if unmeasured:
        assert explain_score(score).headline == "측정 못 함"
