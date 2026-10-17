"""잡 실행기: 수집, 요약, 발송을 정해진 때에 돌리고, 겹치지 않게 하고, 종료할 때 마무리를 기다린다.

- 수집은 시각에 맞춘 슬롯에, 요약과 발송은 정해진 간격으로 실행한다.
- 같은 작업이 아직 실행 중이면 다음 실행은 건너뛰고 그 사실을 기록한다(겹쳐 실행하지 않는다).
- 간격과 주기는 설정에서 매번 읽는다. 설정을 바꾸면 진행 중인 작업은 끝까지 마치고
  다음 실행부터 새 값이 적용된다.
- 작업이 실패해도 예외의 종류 이름만 기록한다(메시지에 주소나 키가 들어 있을 수 있다).
"""

import logging
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, tzinfo
from functools import partial
from typing import Any

from rss_hub.domain.jobs import due_slot, interval_due
from rss_hub.services.clock import Clock
from rss_hub.storage.job_runs import JobRunRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SlotJob:
    name: str
    run: Callable[[], object]
    interval_minutes: Callable[[], int]


@dataclass(frozen=True)
class IntervalJob:
    name: str
    run: Callable[[], object]
    interval_seconds: Callable[[], int]


Job = SlotJob | IntervalJob


def start_thread(target: Callable[[], None]) -> threading.Thread:
    thread = threading.Thread(target=target, name="rss-hub-job")
    thread.start()
    return thread


class JobRunner:
    def __init__(
        self,
        *,
        jobs: Iterable[Job],
        clock: Clock,
        records: JobRunRepository,
        timezone: Callable[[], tzinfo],
        spawn: Callable[[Callable[[], None]], Any] = start_thread,
        stop_event: threading.Event | None = None,
        tick_seconds: float = 1.0,
    ) -> None:
        self._jobs = tuple(jobs)
        self._clock = clock
        self._records = records
        self._timezone = timezone
        self._spawn = spawn
        self._stop = stop_event or threading.Event()
        self._tick_seconds = tick_seconds
        self._lock = threading.Lock()
        self._running: set[str] = set()
        self._threads: list[threading.Thread] = []
        self._skip_marker: dict[str, object] = {}
        self._loop: threading.Thread | None = None

    def request_stop(self) -> None:
        """서비스 종료 신호: 새 작업을 시작하지 않고, 발송은 지금 글까지 마치고 멈춘다."""
        self._stop.set()

    @property
    def stopping(self) -> bool:
        return self._stop.is_set()

    @property
    def running(self) -> frozenset[str]:
        with self._lock:
            return frozenset(self._running)

    # ---------- 한 번의 점검 ----------

    def tick(self) -> list[str]:
        """실행할 때가 된 작업을 시작한다. 시작한 작업의 이름을 돌려준다."""
        if self._stop.is_set():
            return []
        now = self._clock.now()
        started: list[str] = []
        for job in self._jobs:
            try:
                due = self._due(job, now)
            except Exception as error:  # 예: 60의 약수가 아닌 수집 주기
                logger.error(
                    "작업 일정을 계산하지 못했습니다: %s (%s)", job.name, type(error).__name__
                )
                continue
            if due is None:
                continue
            with self._lock:
                if job.name in self._running:
                    self._note_skip(job.name, due)
                    continue
                self._running.add(job.name)
                self._skip_marker.pop(job.name, None)
            slot = due if isinstance(job, SlotJob) and isinstance(due, datetime) else None
            self._records.mark_started(job.name, slot)
            self._remember(self._spawn(partial(self._execute, job)))
            started.append(job.name)
        return started

    def _due(self, job: Job, now: datetime) -> object | None:
        record = self._records.get(job.name)
        if isinstance(job, SlotJob):
            local = now.astimezone(self._timezone())
            return due_slot(
                local, None if record is None else record.last_slot, job.interval_minutes()
            )
        last = None if record is None else record.last_started_at
        return (last or now) if interval_due(now, last, job.interval_seconds()) else None

    def _note_skip(self, name: str, marker: object) -> None:
        """같은 시점의 건너뜀은 한 번만 기록한다."""
        if self._skip_marker.get(name) != marker:
            self._skip_marker[name] = marker
            self._records.mark_skipped(name)

    def _remember(self, thread: object) -> None:
        if isinstance(thread, threading.Thread):
            self._threads = [t for t in self._threads if t.is_alive()] + [thread]

    def _execute(self, job: Job) -> None:
        error: str | None = None
        try:
            job.run()
        except Exception as caught:
            error = type(caught).__name__
            logger.error("작업이 실패했습니다: %s (%s)", job.name, error)
        finally:
            try:
                self._records.mark_finished(job.name, error)
            finally:
                with self._lock:
                    self._running.discard(job.name)

    # ---------- 시작과 종료 ----------

    def start(self) -> None:
        """배경 스레드에서 1초마다 tick()을 부른다."""
        if self._loop is not None:
            return
        self._loop = threading.Thread(target=self._run_loop, name="rss-hub-scheduler")
        self._loop.start()

    def _run_loop(self) -> None:
        while True:
            try:
                self.tick()
            except Exception as error:
                logger.error("스케줄러 오류: %s", type(error).__name__)
            if self._stop.wait(self._tick_seconds):
                return

    def wait_idle(self, timeout: float) -> bool:
        """실행 중인 작업이 모두 끝나기를 기다린다. 시간 안에 끝나면 True."""
        deadline = time.monotonic() + timeout
        for thread in list(self._threads):
            thread.join(max(0.0, deadline - time.monotonic()))
        return not self.running

    def shutdown(self, timeout: float = 30.0) -> bool:
        """새 작업을 시작하지 않고, 진행 중인 작업이 끝나기를 기다린다. 모두 끝나면 True."""
        self.request_stop()
        if self._loop is not None:
            self._loop.join(5.0)
        return self.wait_idle(timeout)
