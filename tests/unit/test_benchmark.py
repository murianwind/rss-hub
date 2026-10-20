import pytest

from rss_hub.domain.benchmark import (
    BENCH_TOPIC,
    SAMPLES,
    CallResult,
    ModelScore,
    recommend,
    score_model,
    speed_points,
)


def good(latency=3000, *, korean=True, topic=True):
    return CallResult(ok=True, korean_ok=korean, topic_ok=topic, latency_ms=latency)


def bad(error="invalid"):
    return CallResult(ok=False, korean_ok=False, topic_ok=False, latency_ms=None, error=error)


# ---------- 시험 글 ----------


def test_the_sample_set_is_balanced_and_covers_both_languages():
    assert len(SAMPLES) == 6
    assert sum(s.expects_topic for s in SAMPLES) == 3
    assert any(s.title.isascii() for s in SAMPLES) and any(not s.title.isascii() for s in SAMPLES)
    assert BENCH_TOPIC.enabled and BENCH_TOPIC.id == 1


# ---------- 점수 ----------


def test_a_perfect_fast_model_scores_one_hundred():
    score = score_model("m", [good(2000)] * 6)
    assert (score.calls, score.ok, score.score, score.p50_ms) == (6, 6, 100.0, 2000)


def test_failures_lower_the_success_part_and_nothing_else_counts_for_them():
    score = score_model("m", [good(2000)] * 3 + [bad("invalid")] * 3)
    assert (
        score.ok == 3
        and score.score == 50 * 0.5 + 20 + 20 + 10
        and score.errors == ("invalid",) * 3
    )


def test_wrong_language_and_wrong_topic_calls_lower_their_parts():
    results = [good(2000, korean=False)] * 3 + [good(2000, topic=False)] * 3
    score = score_model("m", results)
    assert (score.korean, score.topic) == (3, 3) and score.score == 50 + 10 + 10 + 10


def test_a_model_that_never_answers_scores_zero():
    score = score_model("m", [bad("timeout")] * 6)
    assert (score.score, score.p50_ms, score.ok) == (0.0, None, 0)


def test_no_calls_at_all_scores_zero_without_dividing_by_zero():
    assert score_model("m", []).score == 0.0


def test_the_median_latency_is_taken_over_successful_calls_only():
    score = score_model("m", [good(1000), good(9000), good(3000), bad()])
    assert score.p50_ms == 3000


@pytest.mark.parametrize(
    ("p50", "points"),
    [(None, 0), (0, 10), (5000, 10), (17500, 5), (30000, 0), (90000, 0)],
)
def test_speed_points_fall_linearly_between_five_and_thirty_seconds(p50, points):
    assert speed_points(p50) == pytest.approx(points)


def test_scores_are_rounded_to_one_decimal():
    assert score_model("m", [good(12345)] * 3 + [bad()]).score == round(
        score_model("m", [good(12345)] * 3 + [bad()]).score, 1
    )


# ---------- 추천 ----------


def make(model, score, ok=6, calls=6, p50=3000):
    return ModelScore(model, calls, ok, ok, ok, p50, score, ())


def test_the_best_models_form_the_recommended_chain_best_first():
    result = recommend([make("a", 80), make("b", 95), make("c", 90), make("d", 60)], ("a",), size=3)
    assert result.chain == ("b", "c", "a") and result.changed is True


def test_a_model_below_the_success_threshold_is_never_recommended():
    result = recommend([make("a", 99, ok=4), make("b", 70)], ("x",))
    assert result.chain == ("b",)


def test_ties_prefer_the_faster_model_then_the_name():
    result = recommend(
        [make("b", 90, p50=2000), make("a", 90, p50=4000), make("c", 90, p50=2000)], ("x",)
    )
    assert result.chain == ("b", "c", "a")


def test_when_the_current_chain_is_already_the_best_nothing_changes():
    result = recommend([make("a", 95), make("b", 90)], ("a", "b"))
    assert result.chain == ("a", "b") and result.changed is False and "이미" in result.reason


def test_without_any_eligible_model_there_is_no_recommendation():
    result = recommend([make("a", 50, ok=2), make("b", 10, ok=0)], ("a",))
    assert result.chain == () and result.changed is False and "성공률 80%" in result.reason


def test_the_chain_size_is_limited():
    scores = [make(name, 90 - n) for n, name in enumerate("abcdef")]
    assert len(recommend(scores, ("z",), size=2).chain) == 2


def test_a_model_without_calls_is_not_eligible():
    assert recommend([ModelScore("a", 0, 0, 0, 0, None, 0.0, ())], ("a",)).chain == ()


def test_a_success_rate_of_exactly_the_threshold_still_qualifies():
    result = recommend([make("a", 90, ok=4, calls=5)], ("x",))
    assert result.chain == ("a",)
