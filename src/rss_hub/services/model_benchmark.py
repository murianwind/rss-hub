"""모델 벤치마크: 고정된 시험 글을 모델마다 실제 요약 요청으로 보내서 점수를 매긴다.

- 실제 운영과 같은 게이트웨이를 쓰므로 호출은 오늘 호출 수에 포함되고 하루 상한과 예약분이 지켜진다.
- 분당 호출 한도를 넘지 않도록 호출 사이에 간격을 둔다.
- 한도에 도달하면 그 자리에서 멈추고, 그때까지 끝낸 모델의 점수만 남긴다.
"""

import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from rss_hub.domain.benchmark import (
    BENCH_TOPIC,
    SAMPLES,
    BenchSample,
    CallResult,
    ModelScore,
    score_model,
)
from rss_hub.domain.korean import is_korean
from rss_hub.domain.prompts import build_summary_prompt, summary_excerpt
from rss_hub.domain.validation import validate_summary
from rss_hub.jobs.runner import start_thread
from rss_hub.services.llm_gateway import BudgetBlocked, LlmGateway, LlmNotConfigured, LlmOutage
from rss_hub.services.ports import LlmErrorKind
from rss_hub.storage.models import RUN_DONE, RUN_FAILED, RUN_INTERRUPTED, ModelRepository

PACE_SECONDS = 4.5  # 호출 사이 간격(분당 13회 이하)
RATE_LIMIT_STREAK = 2  # 한도 초과가 이만큼 연달아 나오면 그 모델은 미룬다
RETRY_WAIT_SECONDS = 60.0  # 미룬 모델을 다시 시험하기 전에 한도가 풀리기를 기다리는 시간
MAX_MODELS = 5
CANCELLED = "사용자가 중단했습니다"
CANCEL_POLL_SECONDS = 1.0  # 기다리는 동안 중단 요청을 확인하는 간격


ACCOUNT_PROBLEMS = {
    LlmErrorKind.UNAUTHORIZED: "OpenRouter가 키를 거부했습니다. 설정에서 키를 확인하세요",
    LlmErrorKind.PAYMENT_REQUIRED: "OpenRouter 잔액이 부족해서 멈췄습니다",
}


class AccountProblem(Exception):
    """키 거부나 잔액 부족처럼 모든 모델에 똑같이 일어나는 문제. 더 호출해도 소용이 없다."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class _Deferred(Exception):
    """한도 초과가 연달아 나와서 이 모델의 시험을 뒤로 미룬다."""


class _Stop(Exception):
    """더 시험할 수 없는 이유(한도, 키, 잔액). message는 화면에 그대로 보여 준다."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class BenchOutcome:
    scores: tuple[ModelScore, ...]
    stopped: str = ""  # 비어 있지 않으면 끝까지 가지 못한 이유


class BenchmarkService:
    def __init__(
        self,
        *,
        gateway: LlmGateway,
        models: ModelRepository,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        pace_seconds: float = PACE_SECONDS,
        retry_wait_seconds: float = RETRY_WAIT_SECONDS,
    ) -> None:
        self._gateway = gateway
        self._models = models
        self._sleep = sleep
        self._monotonic = monotonic
        self._pace = pace_seconds
        self._retry_wait = retry_wait_seconds
        self._calls_made = 0
        self._peak = 0
        self._should_stop: Callable[[], bool] = lambda: False

    def run(
        self,
        run_id: int,
        model_ids: Sequence[str],
        *,
        should_stop: Callable[[], bool] = lambda: False,
    ) -> BenchOutcome:
        """모델을 차례로 시험한다. 한도 초과가 연달아 나오면 미뤘다가 한 번만 다시 시험한다.

        should_stop이 참이 되면 다음 호출을 하지 않고 멈춘다(끝낸 모델의 점수는 남는다).
        """
        self._calls_made = 0
        self._peak = 0
        self._should_stop = should_stop
        scores: dict[str, ModelScore] = {}
        deferred: list[str] = []
        stopped = ""
        try:
            for model in model_ids:
                try:
                    scores[model] = self._run_model(run_id, model, retry=False)
                except _Deferred:
                    deferred.append(model)
            if deferred:
                self._wait_for_limits()  # 한도가 풀리기를 기다린 뒤 한 번만 다시 시험한다
            for model in deferred:
                self._models.clear_calls(run_id, model)
                scores[model] = self._run_model(run_id, model, retry=True)
        except _Stop as stop:
            stopped = stop.message
        return BenchOutcome(tuple(scores[m] for m in model_ids if m in scores), stopped)

    def _check_stop(self) -> None:
        if self._should_stop():
            raise _Stop(CANCELLED)

    def _wait_for_limits(self) -> None:
        """기다리는 동안에도 중단 요청을 확인한다."""
        waited = 0.0
        while waited < self._retry_wait:
            self._check_stop()
            step = min(CANCEL_POLL_SECONDS, self._retry_wait - waited)
            self._sleep(step)
            waited += step
        self._check_stop()

    def _run_model(self, run_id: int, model: str, *, retry: bool) -> ModelScore:
        """한 모델의 시험 글을 모두 보낸다. 한도 초과가 연달아 나오면 첫 시험에서는 미룬다."""
        results: list[CallResult] = []
        for index, sample in enumerate(SAMPLES):
            if self._limited_in_a_row(results):
                if not retry:
                    raise _Deferred
                self._skip_rest(run_id, model, index)  # 다시 시험해도 같으면 호출하지 않는다
                break
            self._check_stop()
            if self._calls_made:
                self._sleep(self._pace)
            self._calls_made += 1
            result = self._attempt(model, sample)
            results.append(result)
            self._models.save_call(run_id, model, index, sample.title, result)
            self._progress(run_id)
        score = score_model(model, results)
        self._models.save_score(run_id, score)
        return score

    def _skip_rest(self, run_id: int, model: str, first: int) -> None:
        for index in range(first, len(SAMPLES)):
            reason = LlmErrorKind.RATE_LIMITED.value
            self._models.save_skipped(run_id, model, index, SAMPLES[index].title, reason)
            self._progress(run_id)

    @staticmethod
    def _limited_in_a_row(results: Sequence[CallResult]) -> bool:
        tail = results[-RATE_LIMIT_STREAK:]
        return len(tail) == RATE_LIMIT_STREAK and all(
            r.error == LlmErrorKind.RATE_LIMITED.value for r in tail
        )

    def _progress(self, run_id: int) -> None:
        self._peak = max(self._peak, len(self._models.calls(run_id)))  # 다시 시험해도 줄지 않게
        self._models.advance(run_id, self._peak)

    def _attempt(self, model: str, sample: BenchSample) -> CallResult:
        try:
            return self._one(model, sample)
        except BudgetBlocked as blocked:
            raise _Stop("오늘 LLM 호출 한도에 도달해서 멈췄습니다") from blocked
        except LlmNotConfigured as missing:
            raise _Stop("OpenRouter 키가 설정되지 않았습니다") from missing
        except AccountProblem as problem:
            raise _Stop(problem.message) from problem

    def _one(self, model: str, sample: BenchSample) -> CallResult:
        prompt = build_summary_prompt(sample.title, summary_excerpt(sample.content), [BENCH_TOPIC])
        started = self._monotonic()
        try:
            answer = self._gateway.complete_with(model, prompt)
        except LlmOutage as outage:
            first = outage.failures[0][1] if outage.failures else LlmErrorKind.UNAVAILABLE
            if first in ACCOUNT_PROBLEMS:
                raise AccountProblem(ACCOUNT_PROBLEMS[first]) from outage
            return CallResult(False, False, False, None, first.value)
        latency = int((self._monotonic() - started) * 1000)
        checked = validate_summary(
            answer.content, answer.finish_reason, valid_topic_ids={BENCH_TOPIC.id}
        )
        if checked.draft is None:
            return CallResult(False, False, False, latency, checked.reason or "invalid")
        draft = checked.draft
        return CallResult(
            True,
            is_korean(draft.title_ko),
            (BENCH_TOPIC.id in draft.topics) == sample.expects_topic,
            latency,
        )


@dataclass(frozen=True)
class StartResult:
    status: str  # started, busy, invalid
    run_id: int | None = None
    message: str = ""


class BenchmarkRunner:
    """벤치마크를 배경에서 한 번에 하나만 돌린다."""

    def __init__(
        self,
        *,
        service: BenchmarkService,
        models: ModelRepository,
        spawn: Callable[[Callable[[], None]], object] = start_thread,
    ) -> None:
        self._service = service
        self._models = models
        self._spawn = spawn
        self._cancel = threading.Event()

    def start(self, model_ids: Sequence[str]) -> StartResult:
        chosen = list(dict.fromkeys(model_ids))
        if not chosen:
            return StartResult("invalid", message="시험할 모델을 고르세요")
        if len(chosen) > MAX_MODELS:
            return StartResult("invalid", message=f"한 번에 {MAX_MODELS}개까지 시험할 수 있습니다")
        known = {e.id for e in self._models.catalog()}
        if any(model not in known for model in chosen):
            return StartResult("invalid", message="목록에 없는 모델이 있습니다. 먼저 스캔하세요")
        if self._models.running_run() is not None:
            return StartResult("busy", message="이미 벤치마크가 실행 중입니다")
        self._cancel.clear()
        run_id = self._models.start_run(len(chosen) * len(SAMPLES), chosen)
        self._spawn(lambda: self._execute(run_id, chosen))
        return StartResult("started", run_id)

    def _execute(self, run_id: int, model_ids: Sequence[str]) -> None:
        try:
            outcome = self._service.run(run_id, model_ids, should_stop=self._cancel.is_set)
        except Exception as error:
            self._models.finish_run(
                run_id, RUN_FAILED, f"예상하지 못한 오류({type(error).__name__})"
            )
            return
        if outcome.stopped == CANCELLED:
            self._models.finish_run(run_id, RUN_INTERRUPTED, outcome.stopped)
        elif outcome.stopped:
            self._models.finish_run(run_id, RUN_FAILED, outcome.stopped)
        else:
            self._models.finish_run(run_id, RUN_DONE, f"{len(outcome.scores)}개 모델 완료")

    def cancel(self) -> bool:
        """실행 중인 벤치마크에 중단을 요청한다. 실행 중이 아니면 False."""
        if self._models.running_run() is None:
            return False
        self._cancel.set()
        return True
