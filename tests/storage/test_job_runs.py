from datetime import UTC, datetime

import pytest

from rss_hub.storage.database import Database
from rss_hub.storage.job_runs import STATUS_ERROR, STATUS_OK, STATUS_RUNNING, JobRunRepository
from tests.fakes.clock import FakeClock


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def runs(tmp_path, clock):
    return JobRunRepository(Database(tmp_path / "rss_hub.db"), clock)


def test_an_unknown_job_has_no_record(runs):
    assert runs.get("collect") is None and runs.all() == {}


def test_starting_a_job_records_the_time_status_and_slot(runs, clock):
    slot = datetime(2026, 10, 16, 14, 20, tzinfo=UTC)
    runs.mark_started("collect", slot)
    run = runs.get("collect")
    assert (run.last_status, run.last_started_at, run.last_slot) == (
        STATUS_RUNNING,
        clock.now(),
        slot,
    )
    assert (run.last_finished_at, run.last_ok_at, run.skipped_count) == (None, None, 0)


def test_a_job_without_a_slot_keeps_the_previous_slot(runs):
    slot = datetime(2026, 10, 16, 14, 20, tzinfo=UTC)
    runs.mark_started("collect", slot)
    runs.mark_started("collect")
    assert runs.get("collect").last_slot == slot


def test_a_successful_finish_records_ok_and_the_time(runs, clock):
    runs.mark_started("summarize")
    clock.advance(seconds=5)
    runs.mark_finished("summarize")
    run = runs.get("summarize")
    assert (run.last_status, run.last_error) == (STATUS_OK, None)
    assert run.last_finished_at == run.last_ok_at == clock.now()


def test_a_failed_finish_keeps_the_last_success_time(runs, clock):
    runs.mark_started("deliver")
    runs.mark_finished("deliver")
    good_time = clock.now()
    clock.advance(minutes=1)
    runs.mark_started("deliver")
    runs.mark_finished("deliver", "ConnectionError")
    run = runs.get("deliver")
    assert (run.last_status, run.last_error) == (STATUS_ERROR, "ConnectionError")
    assert run.last_ok_at == good_time and run.last_finished_at == clock.now()


def test_a_later_success_clears_the_error(runs):
    runs.mark_finished("deliver", "boom")
    runs.mark_finished("deliver")
    assert runs.get("deliver").last_error is None


def test_skips_are_counted_and_timestamped(runs, clock):
    runs.mark_skipped("collect")
    clock.advance(minutes=5)
    runs.mark_skipped("collect")
    run = runs.get("collect")
    assert (run.skipped_count, run.last_skipped_at) == (2, clock.now())


def test_all_returns_one_record_per_job(runs):
    runs.mark_started("collect")
    runs.mark_started("summarize")
    assert set(runs.all()) == {"collect", "summarize"}


# ---------- 결과 한 줄과 끊긴 실행 ----------


def test_the_result_line_is_kept_and_cleared_when_a_run_fails(runs):
    runs.mark_started("summarize")
    runs.mark_finished("summarize", None, "요약 3건")
    assert runs.get("summarize").last_result == "요약 3건"
    runs.mark_started("summarize")
    assert (
        runs.get("summarize").last_result == "요약 3건"
    )  # 새 실행이 끝나기 전에는 이전 결과를 둔다
    runs.mark_finished("summarize", "Timeout", "무시되는 결과")
    assert runs.get("summarize").last_result == ""


def test_interrupted_runs_are_recovered_once(runs):
    runs.mark_started("deliver")
    runs.mark_started("collect")
    runs.mark_finished("collect", None, "ok")
    assert runs.recover_interrupted() == 1
    record = runs.get("deliver")
    assert (record.last_status, record.last_error) == (STATUS_ERROR, "Interrupted")
    assert runs.get("collect").last_status == STATUS_OK and runs.recover_interrupted() == 0
