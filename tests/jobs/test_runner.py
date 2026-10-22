import logging
import threading
import time
from datetime import UTC, timedelta, timezone

import pytest

from rss_hub.jobs.runner import IntervalJob, JobRunner, SlotJob
from rss_hub.storage.database import Database
from rss_hub.storage.job_runs import STATUS_ERROR, STATUS_OK, STATUS_RUNNING, JobRunRepository
from tests.fakes.clock import FakeClock

KST = timezone(timedelta(hours=9))


class Env:
    def __init__(self, tmp_path, *, inline=True):
        from datetime import datetime

        self.clock = FakeClock(datetime(2026, 10, 16, 5, 0, tzinfo=UTC))  # 14:00 KST
        self.records = JobRunRepository(Database(tmp_path / "rss_hub.db"), self.clock)
        self.calls: dict[str, int] = {}
        self.interval = {"collect": 5, "summarize": 60}
        self.pending: list = []
        self.spawn = (lambda fn: fn()) if inline else self.pending.append

    def job(self, name, *, action=None):
        def run():
            self.calls[name] = self.calls.get(name, 0) + 1
            if action:
                action()

        return run

    def runner(self, *, collect_action=None, summarize_action=None, **extra):
        jobs = [
            SlotJob(
                "collect",
                self.job("collect", action=collect_action),
                lambda: self.interval["collect"],
            ),
            IntervalJob(
                "summarize",
                self.job("summarize", action=summarize_action),
                lambda: self.interval["summarize"],
            ),
        ]
        return JobRunner(
            jobs=jobs,
            clock=self.clock,
            records=self.records,
            timezone=lambda: KST,
            spawn=self.spawn,
            **extra,
        )


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def test_a_slot_job_runs_once_in_its_slot_and_again_in_the_next(env):
    runner = env.runner()
    assert runner.tick() == ["collect", "summarize"]
    assert runner.tick() == []  # 같은 슬롯과 같은 초에 다시 시작하지 않는다
    env.clock.advance(minutes=5)
    assert "collect" in runner.tick()
    assert env.calls["collect"] == 2


def test_a_slot_job_does_not_start_in_the_middle_of_a_slot(env):
    runner = env.runner()
    runner.tick()
    env.clock.advance(minutes=2)
    assert "collect" not in runner.tick()


def test_slots_missed_while_down_are_not_caught_up_after_a_restart(env):
    first = env.runner()
    first.tick()  # 14:00 슬롯을 실행하고 기록
    env.clock.advance(minutes=20, seconds=5)  # 14:20:05에 서비스가 다시 시작된다
    second = env.runner()  # 새 실행기. 기록은 데이터베이스에서 읽는다
    assert "collect" in second.tick()
    assert env.calls["collect"] == 2  # 14:00과 14:20만. 14:05~14:15는 실행하지 않았다
    assert second.tick() == []


def test_a_restart_in_the_middle_of_a_slot_waits_for_the_next_slot(env):
    env.runner().tick()
    env.clock.advance(minutes=23)
    assert "collect" not in env.runner().tick()


def test_an_interval_job_runs_immediately_then_after_each_interval(env):
    runner = env.runner()
    assert "summarize" in runner.tick()
    env.clock.advance(seconds=59)
    assert "summarize" not in runner.tick()
    env.clock.advance(seconds=1)
    assert "summarize" in runner.tick()
    assert env.calls["summarize"] == 2


def test_a_changed_interval_applies_from_the_next_run_without_a_restart(env):
    runner = env.runner()
    runner.tick()
    env.interval["summarize"] = 30
    env.clock.advance(seconds=30)
    assert "summarize" in runner.tick()


def test_a_finished_job_is_recorded_as_ok_with_its_times(env):
    env.runner().tick()
    run = env.records.get("collect")
    assert run.last_status == STATUS_OK and run.last_ok_at == env.clock.now()
    assert run.last_slot is not None


def test_a_failing_job_is_recorded_without_the_message_and_does_not_stop_the_others(env, caplog):
    caplog.set_level(logging.ERROR)

    def explode():
        raise RuntimeError("https://discord.com/api/webhooks/1/SECRETTOKEN")

    runner = env.runner(collect_action=explode)
    assert runner.tick() == ["collect", "summarize"]
    run = env.records.get("collect")
    assert (run.last_status, run.last_error) == (STATUS_ERROR, "RuntimeError")
    assert env.records.get("summarize").last_status == STATUS_OK
    assert "SECRETTOKEN" not in caplog.text and "RuntimeError" in caplog.text
    assert runner.running == frozenset()


def test_an_invalid_interval_is_logged_and_the_other_jobs_still_run(env, caplog):
    caplog.set_level(logging.ERROR)

    def bad():
        raise ValueError("수집 주기는 60의 약수여야 합니다: 7")

    runner = JobRunner(
        jobs=[
            SlotJob("collect", env.job("collect"), bad),
            IntervalJob("summarize", env.job("summarize"), lambda: 60),
        ],
        clock=env.clock,
        records=env.records,
        timezone=lambda: KST,
        spawn=env.spawn,
    )
    assert runner.tick() == ["summarize"]
    assert "작업 일정을 계산하지 못했습니다: collect (ValueError)" in caplog.text


# ---------- 겹쳐 실행하지 않는다 ----------


def test_a_slot_that_arrives_while_the_job_is_still_running_is_skipped_and_recorded(tmp_path):
    env = Env(tmp_path, inline=False)  # 시작한 작업은 우리가 끝낼 때까지 실행 중으로 남는다
    runner = env.runner()
    assert runner.tick() == ["collect", "summarize"]
    assert runner.running == {"collect", "summarize"}
    assert env.records.get("collect").last_status == STATUS_RUNNING

    env.clock.advance(minutes=5)
    assert runner.tick() == []  # 아직 실행 중이라 시작하지 않는다
    assert runner.tick() == []
    assert env.records.get("collect").skipped_count == 1  # 같은 슬롯의 건너뜀은 한 번만 기록한다

    env.clock.advance(minutes=5)
    runner.tick()
    assert env.records.get("collect").skipped_count == 2
    assert env.calls == {}  # 보류된 작업은 한 번도 실행되지 않았다


def test_after_the_running_job_finishes_the_next_slot_starts_normally(tmp_path):
    env = Env(tmp_path, inline=False)
    runner = env.runner()
    runner.tick()
    env.pending.pop(0)()  # collect 작업이 끝난다
    env.pending.pop(0)()  # summarize 작업이 끝난다
    env.clock.advance(minutes=5)
    assert "collect" in runner.tick()


def test_an_interval_job_that_is_still_running_when_due_again_is_skipped_once(tmp_path):
    env = Env(tmp_path, inline=False)
    runner = env.runner()
    runner.tick()
    env.clock.advance(seconds=61)
    runner.tick()
    runner.tick()
    assert env.records.get("summarize").skipped_count == 1


# ---------- 종료 ----------


def test_after_a_stop_request_nothing_new_starts(env):
    stop = threading.Event()
    runner = env.runner(stop_event=stop)
    stop.set()
    assert runner.tick() == []


def test_shutdown_waits_for_a_running_job_to_finish(tmp_path):
    env = Env(tmp_path)
    release, started = threading.Event(), threading.Event()

    def slow():
        started.set()
        release.wait(5)

    from rss_hub.jobs.runner import start_thread

    runner = JobRunner(
        jobs=[IntervalJob("deliver", env.job("deliver", action=slow), lambda: 60)],
        clock=env.clock,
        records=env.records,
        timezone=lambda: KST,
        spawn=start_thread,
    )
    runner.tick()
    assert started.wait(2) and runner.running == {"deliver"}
    assert runner.shutdown(timeout=0.05) is False  # 아직 끝나지 않았다
    release.set()
    assert runner.wait_idle(2) is True
    assert env.records.get("deliver").last_status == STATUS_OK


def test_shutdown_with_nothing_running_returns_at_once(env):
    runner = env.runner()
    runner.tick()
    assert runner.shutdown(timeout=1) is True


def test_the_background_loop_runs_jobs_and_stops_cleanly(tmp_path):
    env = Env(tmp_path)
    from rss_hub.jobs.runner import start_thread

    runner = JobRunner(
        jobs=[IntervalJob("summarize", env.job("summarize"), lambda: 3600)],
        clock=env.clock,
        records=env.records,
        timezone=lambda: KST,
        spawn=start_thread,
        tick_seconds=0.01,
    )
    runner.start()
    runner.start()  # 두 번 불러도 스레드는 하나다
    deadline = time.monotonic() + 3
    while env.calls.get("summarize", 0) < 1 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert runner.shutdown(timeout=2) is True
    assert env.calls["summarize"] == 1  # 간격이 길어서 한 번만 실행했다


def test_an_error_inside_the_loop_is_logged_and_the_loop_keeps_running(
    tmp_path, caplog, monkeypatch
):
    caplog.set_level(logging.ERROR)
    env = Env(tmp_path)
    runner = env.runner(tick_seconds=0.01)
    calls = {"n": 0}
    real_tick = runner.tick

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return real_tick()

    monkeypatch.setattr(runner, "tick", flaky)
    runner.start()
    deadline = time.monotonic() + 3
    while env.calls.get("summarize", 0) < 1 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert runner.shutdown(timeout=2) is True
    assert "스케줄러 오류: RuntimeError" in caplog.text and env.calls["summarize"] >= 1


def test_a_stop_request_is_visible_to_everyone_sharing_the_event(env):
    stop = threading.Event()
    runner = env.runner(stop_event=stop)
    assert not stop.is_set()
    runner.request_stop()
    assert stop.is_set()


def test_slots_follow_the_service_timezone_even_when_its_minutes_differ_from_utc(tmp_path):
    from datetime import datetime

    india = timezone(timedelta(hours=5, minutes=30))
    env = Env(tmp_path)
    env.clock = FakeClock(datetime(2026, 10, 16, 8, 30, tzinfo=UTC))  # 인도 시각 14:00
    records = JobRunRepository(Database(tmp_path / "india.db"), env.clock)
    runner = JobRunner(
        jobs=[SlotJob("collect", env.job("collect"), lambda: 60)],
        clock=env.clock,
        records=records,
        timezone=lambda: india,
        spawn=lambda fn: fn(),
    )
    assert runner.tick() == ["collect"]  # UTC로 보면 08:30이라 정각 슬롯이 아니다
    env.clock.advance(minutes=30)  # 인도 시각 14:30
    assert runner.tick() == []
    env.clock.advance(minutes=30)  # 인도 시각 15:00
    assert runner.tick() == ["collect"]


# ---------- 지금 실행 ----------


def test_run_now_starts_a_job_without_waiting_for_its_turn(env):
    runner = env.runner()
    assert runner.run_now("summarize") == "started"
    assert env.calls == {"summarize": 1}
    assert env.records.get("summarize").last_status == STATUS_OK


def test_run_now_refuses_a_job_that_is_already_running(tmp_path):
    env = Env(tmp_path, inline=False)
    runner = env.runner()
    assert runner.run_now("summarize") == "started"
    assert runner.run_now("summarize") == "busy"
    env.pending.pop()()  # 실행이 끝나면 다시 시작할 수 있다
    assert runner.run_now("summarize") == "started"


def test_run_now_reports_an_unknown_job_and_does_nothing_while_stopping(env):
    runner = env.runner()
    assert runner.run_now("nonsense") == "unknown"
    runner.request_stop()
    assert runner.run_now("summarize") == "busy" and env.calls == {}
