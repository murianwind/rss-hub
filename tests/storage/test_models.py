from datetime import timedelta

import pytest

from rss_hub.domain.benchmark import ModelScore
from rss_hub.domain.models import FreeModel
from rss_hub.storage.database import Database
from rss_hub.storage.models import (
    RUN_DONE,
    RUN_FAILED,
    RUN_INTERRUPTED,
    RUN_RUNNING,
    ModelRepository,
)
from tests.fakes.clock import FakeClock


@pytest.fixture
def env(tmp_path):
    clock = FakeClock()
    return ModelRepository(Database(tmp_path / "rss_hub.db"), clock), clock


def model(model_id, *, json=False, context=32768, name=None):
    return FreeModel(model_id, name or model_id, context, json)


def score(name, value=80.0, calls=6, ok=6):
    return ModelScore(name, calls, ok, ok, ok, 3000, value, ())


# ---------- 목록 ----------


def test_the_first_scan_reports_everything_as_new(env):
    repo, _ = env
    diff = repo.save_scan([model("a:free"), model("b:free")])
    assert diff.new == ("a:free", "b:free") and diff.gone == () and diff.returned == ()
    assert [e.id for e in repo.catalog()] == ["a:free", "b:free"]


def test_a_later_scan_reports_new_gone_and_returned_models(env):
    repo, clock = env
    repo.save_scan([model("a:free"), model("b:free")])
    clock.advance(days=1)
    diff = repo.save_scan([model("b:free"), model("c:free")])
    assert (diff.new, diff.gone, diff.returned) == (("c:free",), ("a:free",), ())
    assert [e.id for e in repo.catalog()] == ["b:free", "c:free"]
    clock.advance(days=1)
    diff = repo.save_scan([model("a:free"), model("b:free"), model("c:free")])
    assert (diff.new, diff.gone, diff.returned) == ((), (), ("a:free",))


def test_a_model_that_stays_gone_is_reported_only_once(env):
    repo, _ = env
    repo.save_scan([model("a:free")])
    assert repo.save_scan([]).gone == ("a:free",)
    assert repo.save_scan([]).gone == ()


def test_details_are_updated_and_the_first_seen_time_is_kept(env):
    repo, clock = env
    repo.save_scan([model("a:free", json=False, context=8192, name="Old")])
    first = repo.catalog()[0].first_seen_at
    clock.advance(days=3)
    repo.save_scan([model("a:free", json=True, context=65536, name="New")])
    (entry,) = repo.catalog()
    assert (entry.name, entry.context_length, entry.supports_json) == ("New", 65536, True)
    assert entry.first_seen_at == first and entry.last_seen_at == clock.now()


def test_gone_models_can_be_listed_on_request(env):
    repo, _ = env
    repo.save_scan([model("a:free")])
    repo.save_scan([])
    assert repo.catalog() == [] and [e.id for e in repo.catalog(include_gone=True)] == ["a:free"]
    assert repo.catalog(include_gone=True)[0].gone is True


def test_an_empty_first_scan_changes_nothing(env):
    repo, _ = env
    diff = repo.save_scan([])
    assert (diff.new, diff.gone, diff.returned) == ((), (), ()) and repo.catalog() == []


# ---------- 실행 ----------


def test_a_run_starts_progresses_and_finishes(env):
    repo, clock = env
    run_id = repo.start_run(12)
    assert repo.running_run().id == run_id and repo.running_run().status == RUN_RUNNING
    repo.advance(run_id, 5)
    assert (repo.latest_run().done, repo.latest_run().total) == (5, 12)
    clock.advance(minutes=2)
    repo.finish_run(run_id, RUN_DONE, "끝")
    latest = repo.latest_run()
    assert (latest.status, latest.note, latest.finished_at) == (RUN_DONE, "끝", clock.now())
    assert repo.running_run() is None


def test_without_runs_there_is_nothing_to_report(env):
    repo, _ = env
    assert repo.latest_run() is None and repo.running_run() is None


def test_a_failed_run_is_remembered_with_its_reason(env):
    repo, _ = env
    run_id = repo.start_run(6)
    repo.finish_run(run_id, RUN_FAILED, "호출 한도에 도달해서 멈췄습니다")
    assert repo.latest_run().status == RUN_FAILED and "한도" in repo.latest_run().note


def test_runs_left_over_from_a_stopped_service_are_marked_interrupted(env):
    repo, clock = env
    old = repo.start_run(6)
    clock.advance(hours=2)
    recent = repo.start_run(6)
    assert repo.interrupt_stale_runs(timedelta(hours=1)) == 1
    assert repo.latest_run().id == recent and repo.running_run().id == recent
    assert repo.interrupt_stale_runs() == 1 and repo.running_run() is None
    repo.finish_run(old, RUN_DONE)


def test_interrupting_with_no_open_runs_changes_nothing(env):
    repo, _ = env
    assert repo.interrupt_stale_runs() == 0
    assert RUN_INTERRUPTED == "interrupted"


# ---------- 점수 ----------


def test_the_latest_score_of_each_model_is_returned_with_its_time(env):
    repo, clock = env
    first = repo.start_run(12)
    repo.save_score(first, score("a:free", 70))
    repo.save_score(first, score("b:free", 90))
    repo.finish_run(first, RUN_DONE)
    clock.advance(days=1)
    second = repo.start_run(6)
    repo.save_score(second, score("a:free", 95))
    repo.finish_run(second, RUN_DONE)
    latest = repo.latest_scores()
    assert latest["a:free"][0].score == 95.0 and latest["b:free"][0].score == 90.0
    assert latest["a:free"][1] > latest["b:free"][1]


def test_errors_and_the_missing_median_survive_storage(env):
    repo, _ = env
    run_id = repo.start_run(6)
    repo.save_score(run_id, ModelScore("a:free", 6, 0, 0, 0, None, 0.0, ("timeout", "invalid")))
    saved = repo.latest_scores()["a:free"][0]
    assert saved.p50_ms is None and saved.errors == ("timeout", "invalid")


def test_saving_the_same_model_twice_in_a_run_keeps_the_last(env):
    repo, _ = env
    run_id = repo.start_run(6)
    repo.save_score(run_id, score("a:free", 10))
    repo.save_score(run_id, score("a:free", 20))
    assert repo.latest_scores()["a:free"][0].score == 20.0


def test_no_scores_yet(env):
    assert env[0].latest_scores() == {}


# ---------- 호출 기록 ----------


def test_calls_are_recorded_one_by_one_in_order_with_their_state(env):
    from rss_hub.domain.benchmark import CallResult

    models, _ = env
    run_id = models.start_run(6, ["a", "b"])
    models.save_call(run_id, "a", 0, "첫 글", CallResult(True, True, False, 1500))
    models.save_call(run_id, "a", 1, "둘째 글", CallResult(False, False, False, None, "truncated"))
    models.save_skipped(run_id, "a", 2, "셋째 글", "rate_limited")
    calls = models.calls(run_id)
    assert [(c.index, c.state, c.latency_ms, c.error) for c in calls] == [
        (0, "ok", 1500, ""),
        (1, "failed", None, "truncated"),
        (2, "skipped", None, "rate_limited"),
    ]
    assert (calls[0].korean_ok, calls[0].topic_ok) == (True, False)
    assert models.latest_run().models == ("a", "b")


def test_saving_a_call_again_replaces_it_and_clearing_removes_only_that_model(env):
    from rss_hub.domain.benchmark import CallResult

    models, _ = env
    run_id = models.start_run(6, ["a", "b"])
    models.save_call(run_id, "a", 0, "t", CallResult(False, False, False, None, "rate_limited"))
    models.save_call(run_id, "b", 0, "t", CallResult(True, True, True, 900))
    models.save_call(run_id, "a", 0, "t", CallResult(True, True, True, 800))
    assert [(c.model, c.state) for c in models.calls(run_id)] == [("a", "ok"), ("b", "ok")]
    models.clear_calls(run_id, "a")
    assert [c.model for c in models.calls(run_id)] == ["b"]


def test_a_run_started_without_a_model_list_has_no_models(env):
    models, _ = env
    models.start_run(6)
    assert models.latest_run().models == ()
