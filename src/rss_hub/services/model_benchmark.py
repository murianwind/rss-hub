"""모델 벤치마크: 고정된 시험 글을 모델마다 실제 요약 요청으로 보내서 점수를 매긴다.

- 실제 운영과 같은 게이트웨이를 쓰므로 호출은 오늘 호출 수에 포함되고 하루 상한과 예약분이 지켜진다.
- 분당 호출 한도를 넘지 않도록 호출 사이에 간격을 둔다.
- 한도에 도달하면 그 자리에서 멈추고, 그때까지 끝낸 모델의 점수만 남긴다.
"""

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
from rss_hub.storage.models import RUN_DONE, RUN_FAILED, ModelRepository

PACE_SECONDS = 4.5  # 호출 사이 간격(분당 13회 이하)
MAX_MODELS = 5


ACCOUNT_PROBLEMS = {
    LlmErrorKind.UNAUTHORIZED: "OpenRouter가 키를 거부했습니다. 설정에서 키를 확인하세요",
    LlmErrorKind.PAYMENT_REQUIRED: "OpenRouter 잔액이 부족해서 멈췄습니다",
}


class AccountProblem(Exception):
    """키 거부나 잔액 부족처럼 모든 모델에 똑같이 일어나는 문제. 더 호출해도 소용이 없다."""

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
    ) -> None:
        self._gateway = gateway
        self._models = models
        self._sleep = sleep
        self._monotonic = monotonic
        self._pace = pace_seconds

    def run(self, run_id: int, model_ids: Sequence[str]) -> BenchOutcome:
        scores: list[ModelScore] = []
        done = 0
        for model in model_ids:
            results: list[CallResult] = []
            for index, sample in enumerate(SAMPLES):
                try:
                    results.append(self._one(model, sample))
                except BudgetBlocked:
                    return BenchOutcome(tuple(scores), "오늘 LLM 호출 한도에 도달해서 멈췄습니다")
                except LlmNotConfigured:
                    return BenchOutcome(tuple(scores), "OpenRouter 키가 설정되지 않았습니다")
                except AccountProblem as problem:
                    return BenchOutcome(tuple(scores), problem.message)
                done += 1
                self._models.advance(run_id, done)
                if not (model == model_ids[-1] and index == len(SAMPLES) - 1):
                    self._sleep(self._pace)
            score = score_model(model, results)
            self._models.save_score(run_id, score)
            scores.append(score)
        return BenchOutcome(tuple(scores))

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
        run_id = self._models.start_run(len(chosen) * len(SAMPLES))
        self._spawn(lambda: self._execute(run_id, chosen))
        return StartResult("started", run_id)

    def _execute(self, run_id: int, model_ids: Sequence[str]) -> None:
        try:
            outcome = self._service.run(run_id, model_ids)
        except Exception as error:
            self._models.finish_run(
                run_id, RUN_FAILED, f"예상하지 못한 오류({type(error).__name__})"
            )
            return
        if outcome.stopped:
            self._models.finish_run(run_id, RUN_FAILED, outcome.stopped)
        else:
            self._models.finish_run(run_id, RUN_DONE, f"{len(outcome.scores)}개 모델 완료")
