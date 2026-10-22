"""모델 스캔, 벤치마크, 체인 교체 서비스."""

import pytest

from rss_hub.domain.benchmark import SAMPLES
from rss_hub.services.model_benchmark import (
    CANCEL_POLL_SECONDS,
    CANCELLED,
    MAX_MODELS,
    BenchmarkRunner,
    BenchmarkService,
)
from rss_hub.services.model_chain import MAX_CHAIN
from rss_hub.services.model_scan import ALERT_CHAIN_GONE
from rss_hub.services.ports import LlmErrorKind
from rss_hub.storage.models import (
    RUN_DONE,
    RUN_FAILED,
    RUN_INTERRUPTED,
    RUN_RUNNING,
)
from tests.fakes.llm_client import failure, good, reply
from tests.fakes.models_env import Env, free


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


# ---------- 스캔 ----------


def test_a_scan_stores_the_free_models_and_reports_the_first_time(env):
    env.client.free_models = [free("model-a"), free("model-x")]
    report = env.scanner.scan()
    assert (
        report.ok and report.first_scan and [m.id for m in report.models] == ["model-a", "model-x"]
    )
    assert [e.id for e in env.models.catalog()] == ["model-a", "model-x"]


def test_the_scan_costs_no_llm_call(env):
    env.client.free_models = [free("model-a")]
    env.scanner.scan()
    assert env.client.model_lists == 1  # 모델 목록을 한 번 조회했을 뿐이다
    assert env.client.calls == [] and env.usage.count_day(env.clock.now().date()) == 0


def test_a_later_scan_reports_what_changed(env):
    env.client.free_models = [free("model-a"), free("model-b")]
    env.scanner.scan()
    env.client.free_models = [free("model-b"), free("model-c")]
    report = env.scanner.scan()
    assert (report.diff.new, report.diff.gone, report.first_scan) == (
        ("model-c",),
        ("model-a",),
        False,
    )


def test_a_failed_lookup_changes_nothing_and_says_so(env):
    env.client.free_models = [free("model-a")]
    env.scanner.scan()
    env.client.free_models = None
    report = env.scanner.scan()
    assert not report.ok and "가져오지 못했습니다" in report.error
    assert [e.id for e in env.models.catalog()] == ["model-a"]


def test_an_empty_list_is_treated_as_a_service_problem_not_as_everything_gone(env):
    env.client.free_models = [free("model-a"), free("model-b")]
    env.scanner.scan()
    env.client.free_models = []
    report = env.scanner.scan()
    assert (
        not report.ok
        and "비어 있습니다" in report.error
        and [e.id for e in env.models.catalog()] == ["model-a", "model-b"]
    )
    assert env.notifier.texts() == []


def test_a_chain_model_that_left_the_free_list_is_announced_once_a_day(env):
    env.client.free_models = [free("model-a"), free("model-b")]
    env.scanner.scan()
    env.client.free_models = [free("model-b")]  # 체인은 model-a, model-b
    report = env.scanner.scan()
    assert report.chain_missing == ("model-a",)
    assert any("model-a" in text and "사라졌습니다" in text for text in env.notifier.texts())
    env.scanner.scan()
    assert len([t for t in env.notifier.texts() if "사라졌습니다" in t]) == 1
    assert ALERT_CHAIN_GONE == "model_chain_gone"


def test_no_announcement_while_the_whole_chain_is_still_free(env):
    env.client.free_models = [free("model-a"), free("model-b"), free("model-c")]
    assert env.scanner.scan().chain_missing == ()
    assert env.notifier.texts() == []


# ---------- 벤치마크 ----------


def test_a_perfect_model_scores_one_hundred_and_is_saved(env):
    env.perfect_answers("model-a")
    run_id = env.models.start_run(6)
    outcome = env.benchmark().run(run_id, ["model-a"])
    assert outcome.stopped == "" and [s.score for s in outcome.scores] == [100.0]
    assert env.models.latest_scores()["model-a"][0].score == 100.0


def test_every_call_goes_through_the_gateway_so_it_counts_as_usage(env):
    env.perfect_answers("model-a")
    env.benchmark().run(env.models.start_run(6), ["model-a"])
    assert len(env.client.calls) == 6 and env.usage.count_day(env.clock.now().date()) == 6
    assert set(env.client.models_called()) == {"model-a"}


def test_the_request_is_the_real_summary_prompt_with_the_candidate_topic(env):
    env.perfect_answers("model-a")
    env.benchmark().run(env.models.start_run(6), ["model-a"])
    prompt = env.client.calls[0].prompt
    assert "Candidate topics:\n1. OTT" in prompt and "Title: Netflix announces" in prompt


def test_calls_are_spaced_out_but_not_after_the_last_one(env):
    env.perfect_answers("model-a")
    env.perfect_answers("model-b")
    env.benchmark().run(env.models.start_run(12), ["model-a", "model-b"])
    assert len(env.sleeps_log) == 11 and set(env.sleeps_log) == {4.5}


def test_progress_is_recorded_after_every_call(env):
    env.perfect_answers("model-a")
    run_id = env.models.start_run(6)
    seen = []
    original = env.models.advance
    env.models.advance = lambda rid, done: (seen.append(done), original(rid, done))[1]
    env.benchmark().run(run_id, ["model-a"])
    assert seen == [1, 2, 3, 4, 5, 6]


def test_an_english_title_for_every_sample_scores_no_language_points(env):
    env.perfect_answers("model-a", korean=False)
    score = env.benchmark().run(env.models.start_run(6), ["model-a"]).scores[0]
    assert (score.ok, score.korean, score.topic) == (6, 0, 6) and score.score == 50 + 0 + 20 + 10


def test_a_wrong_topic_answer_lowers_the_topic_points(env):
    env.client.will("model-a", *[reply("한국어 제목", "요약입니다.", topics=[]) for _ in SAMPLES])
    score = env.benchmark().run(env.models.start_run(6), ["model-a"]).scores[0]
    assert score.topic == 3  # 해당하지 않는 시험 글 3개만 맞다


def test_failing_calls_are_counted_with_their_kind_and_do_not_stop_the_run(env):
    env.client.will("model-a", *[failure(LlmErrorKind.UNAVAILABLE, status=503)] * 6)
    outcome = env.benchmark().run(env.models.start_run(6), ["model-a"])
    score = outcome.scores[0]
    assert (score.ok, score.score) == (0, 0.0) and set(score.errors) == {"unavailable"}


def test_unusable_answers_are_failures_with_a_reason(env):
    env.client.will("model-a", *[good("이건 JSON이 아닙니다")] * 6)
    score = env.benchmark().run(env.models.start_run(6), ["model-a"]).scores[0]
    assert score.ok == 0 and len(score.errors) == 6


def test_the_run_stops_at_the_daily_limit_and_keeps_the_finished_models(env):
    env.settings.update({"llm_daily_cap": "8"})
    for model in ("model-a", "model-b"):
        env.perfect_answers(model)
    outcome = env.benchmark().run(env.models.start_run(12), ["model-a", "model-b"])
    assert "한도" in outcome.stopped and [s.model for s in outcome.scores] == ["model-a"]
    assert "model-b" not in env.models.latest_scores()


def test_without_a_key_nothing_is_called(tmp_path):
    env = Env(tmp_path, configured=False)
    outcome = env.benchmark().run(env.models.start_run(6), ["model-a"])
    assert "키가 설정되지 않았습니다" in outcome.stopped and env.client.calls == []


def test_latency_is_measured_per_call(env):
    env.latency = 2.5
    env.perfect_answers("model-a")
    assert env.benchmark().run(env.models.start_run(6), ["model-a"]).scores[0].p50_ms == 2500


# ---------- 배경 실행기 ----------


@pytest.fixture
def runner(env):
    env.client.free_models = [
        free(m) for m in ("model-a", "model-b", "model-c", "model-d", "model-e", "model-f")
    ]
    env.scanner.scan()
    env.spawned = []
    return BenchmarkRunner(service=env.benchmark(), models=env.models, spawn=env.spawned.append)


def test_a_run_starts_in_the_background_and_finishes_when_the_work_is_done(env, runner):
    env.perfect_answers("model-a")
    result = runner.start(["model-a"])
    assert (result.status, env.models.running_run().id) == ("started", result.run_id)
    env.spawned.pop()()
    latest = env.models.latest_run()
    assert latest.status == RUN_DONE and latest.done == 6 and "1개 모델 완료" in latest.note


def test_only_one_run_at_a_time(env, runner):
    assert runner.start(["model-a"]).status == "started"
    second = runner.start(["model-b"])
    assert second.status == "busy" and "이미" in second.message and len(env.spawned) == 1


def test_a_new_run_is_possible_after_the_previous_one_finished(env, runner):
    env.perfect_answers("model-a")
    runner.start(["model-a"])
    env.spawned.pop()()
    assert runner.start(["model-b"]).status == "started"


@pytest.mark.parametrize(
    ("models", "message"),
    [
        ([], "고르세요"),
        (["model-a", "model-b", "model-c", "model-d", "model-e", "model-f"], f"{MAX_MODELS}개까지"),
        (["unknown"], "스캔"),
    ],
)
def test_invalid_requests_are_refused_before_anything_starts(env, runner, models, message):
    result = runner.start(models)
    assert result.status == "invalid" and message in result.message
    assert env.models.running_run() is None and env.spawned == []


def test_duplicates_are_collapsed(env, runner):
    env.perfect_answers("model-a")
    runner.start(["model-a", "model-a"])
    assert env.models.latest_run().total == 6


def test_a_stopped_run_is_recorded_as_failed_with_the_reason(env, runner):
    env.settings.update({"llm_daily_cap": "2"})
    runner.start(["model-a"])
    env.spawned.pop()()
    latest = env.models.latest_run()
    assert latest.status == RUN_FAILED and "한도" in latest.note


def test_an_unexpected_error_marks_the_run_failed_without_leaking_details(env, runner):
    class Boom(BenchmarkService):
        def run(self, run_id, model_ids, **kwargs):
            raise RuntimeError("https://secret.example.com/token")

    boom = BenchmarkRunner(
        service=Boom(gateway=env.gateway, models=env.models),
        models=env.models,
        spawn=env.spawned.append,
    )
    boom.start(["model-a"])
    env.spawned.pop()()
    latest = env.models.latest_run()
    assert (
        latest.status == RUN_FAILED
        and "RuntimeError" in latest.note
        and "secret" not in latest.note
    )
    assert env.models.running_run() is None and RUN_RUNNING == "running"


# ---------- 체인 교체 ----------


def test_applying_a_chain_changes_the_setting_and_announces_it(env):
    env.client.free_models = [free("model-a"), free("model-b"), free("model-z")]
    env.scanner.scan()
    result = env.chain.apply(["model-z", "model-a"])
    assert (result.ok, result.changed, result.old, result.new) == (
        True,
        True,
        ("model-a", "model-b"),
        ("model-z", "model-a"),
    )
    assert env.settings.snapshot().model_chain == ("model-z", "model-a")
    assert any("모델 체인이 바뀌었습니다" in t and "model-z" in t for t in env.notifier.texts())


def test_applying_the_same_chain_changes_and_announces_nothing(env):
    env.client.free_models = [free("model-a"), free("model-b")]
    env.scanner.scan()
    before = len(env.notifier.sent)
    result = env.chain.apply(["model-a", "model-b"])
    assert result.ok and not result.changed and len(env.notifier.sent) == before


def test_a_model_that_is_not_in_the_free_list_is_refused(env):
    env.client.free_models = [free("model-a")]
    env.scanner.scan()
    result = env.chain.apply(["model-a", "typo-model"])
    assert not result.ok and "스캔" in result.error
    assert env.settings.snapshot().model_chain == ("model-a", "model-b")


@pytest.mark.parametrize("chain", [[], ["", "  "]])
def test_an_empty_chain_is_refused(env, chain):
    assert env.chain.apply(chain).error == "바꿀 모델이 없습니다"


def test_a_chain_longer_than_the_limit_is_refused(env):
    names = [f"model-{n}" for n in range(MAX_CHAIN + 1)]
    env.client.free_models = [free(n) for n in names]
    env.scanner.scan()
    assert f"{MAX_CHAIN}개까지" in env.chain.apply(names).error


def test_duplicate_models_in_the_chain_are_collapsed(env):
    env.client.free_models = [free("model-a"), free("model-b")]
    env.scanner.scan()
    assert env.chain.apply(["model-b", "model-b", "model-a"]).new == ("model-b", "model-a")


def test_a_gone_model_cannot_be_put_in_the_chain(env):
    env.client.free_models = [free("model-a"), free("model-b")]
    env.scanner.scan()
    env.client.free_models = [free("model-b")]
    env.scanner.scan()
    assert not env.chain.apply(["model-a"]).ok


def test_a_model_name_with_a_comma_cannot_enter_the_chain_because_it_would_split_in_two(env):
    env.client.free_models = [free("model-a"), free("odd,name:free")]
    env.scanner.scan()
    result = env.chain.apply(["odd,name:free"])
    assert not result.ok and "쉼표" in result.error
    assert env.settings.snapshot().model_chain == ("model-a", "model-b")


def test_an_error_from_the_settings_is_passed_on_and_nothing_is_announced(env, monkeypatch):
    from types import SimpleNamespace

    env.client.free_models = [free("model-a"), free("model-z")]
    env.scanner.scan()
    monkeypatch.setattr(
        env.settings,
        "update",
        lambda values: SimpleNamespace(errors={"model_chain": "설정이 거부함"}),
    )
    before = len(env.notifier.sent)
    result = env.chain.apply(["model-z"])
    assert not result.ok and result.error == "설정이 거부함" and len(env.notifier.sent) == before


@pytest.mark.parametrize(
    ("kind", "status", "message"),
    [
        (LlmErrorKind.UNAUTHORIZED, 401, "키를 거부했습니다"),
        (LlmErrorKind.PAYMENT_REQUIRED, 402, "잔액이 부족해서"),
    ],
)
def test_a_rejected_key_or_empty_balance_stops_the_run_at_the_first_call(
    env, kind, status, message
):
    env.client.will("model-a", *[failure(kind, status=status)] * 6)
    env.client.will("model-b", *[failure(kind, status=status)] * 6)
    outcome = env.benchmark().run(env.models.start_run(12), ["model-a", "model-b"])
    assert message in outcome.stopped and outcome.scores == () and len(env.client.calls) == 1
    assert env.sleeps_log == []


def test_a_stopped_account_problem_is_recorded_on_the_run_with_its_reason(env):
    env.client.free_models = [free("model-a")]
    env.scanner.scan()
    env.client.will("model-a", *[failure(LlmErrorKind.UNAUTHORIZED, status=401)] * 6)
    runner = BenchmarkRunner(service=env.benchmark(), models=env.models, spawn=lambda work: work())
    runner.start(["model-a"])
    latest = env.models.latest_run()
    assert latest.status == RUN_FAILED and "키를 거부했습니다" in latest.note


# ---------- 중단 ----------


def test_a_stop_request_keeps_the_scores_of_finished_models_and_calls_no_more(env):
    env.perfect_answers("model-a")
    env.perfect_answers("model-b")
    outcome = env.benchmark().run(
        env.models.start_run(12),
        ["model-a", "model-b"],
        should_stop=lambda: len(env.client.calls) >= 6,
    )
    assert outcome.stopped == CANCELLED and len(env.client.calls) == 6
    assert [s.model for s in outcome.scores] == ["model-a"]


def test_a_stop_request_in_the_middle_of_a_model_leaves_no_score_for_it(env):
    env.perfect_answers("model-a")
    outcome = env.benchmark().run(
        env.models.start_run(6), ["model-a"], should_stop=lambda: len(env.client.calls) >= 2
    )
    assert outcome.stopped == CANCELLED and outcome.scores == () and len(env.client.calls) == 2


def test_a_stop_request_ends_the_wait_for_the_limits_early(env):
    env.client.will("model-a", *[failure(LlmErrorKind.RATE_LIMITED, status=429)] * 4)
    outcome = env.benchmark().run(
        env.models.start_run(6),
        ["model-a"],
        should_stop=lambda: env.sleeps_log.count(CANCEL_POLL_SECONDS) >= 3,
    )
    assert outcome.stopped == CANCELLED and env.sleeps_log.count(CANCEL_POLL_SECONDS) == 3


def test_cancelling_when_nothing_runs_does_nothing(env, runner):
    assert runner.cancel() is False


def test_cancelling_a_started_run_records_it_as_interrupted_without_calls(env, runner):
    runner.start(["model-a"])
    assert runner.cancel() is True
    env.spawned.pop()()
    latest = env.models.latest_run()
    assert latest.status == RUN_INTERRUPTED and latest.note == CANCELLED and env.client.calls == []
    assert runner.start(["model-a"]).status == "started"  # 중단 요청은 다음 실행에 남지 않는다
