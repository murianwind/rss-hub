"""LLM 게이트웨이: 모델 체인을 순회하며 호출하고, 호출 예산을 지키고, 호출을 기록한다.

호출 방식(추론 끄기, JSON 강제, 토큰 한도)의 근거:
추론 모델은 답보다 '생각'에 토큰을 먼저 써서 글자 수 한도 안에서 답이 잘리거나 비므로,
추론을 끄고(`reasoning.effort=none`) JSON 출력을 강제한다.

- 한도 초과(429)는 Retry-After(최대 30초)만큼 기다렸다가 같은 모델에 한 번 더 시도하고,
  그래도 실패하면 다음 모델로 간다.
- 잔액, 키, 개인정보 설정 문제는 모든 모델에 똑같이 일어나므로 체인을 멈추고 시스템 알림을 보낸다.
- 호출 한 번마다(실패도) 기록하고, 하루 상한, 분당 상한, 서버가 알려 준 남은 호출 수를
  넘지 않게 막는다.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from rss_hub.domain.budget import BudgetBlock, check_budget, warn_reached
from rss_hub.domain.error_log import KIND_LLM
from rss_hub.services.alerts import AlertService
from rss_hub.services.clock import Clock
from rss_hub.services.error_log import NO_ERRORS, ErrorRecorder
from rss_hub.services.ports import (
    CallOptions,
    LlmCallError,
    LlmClient,
    LlmErrorKind,
    LlmResult,
    ServerUsage,
)
from rss_hub.services.settings import AppSettings, SettingsService
from rss_hub.storage.llm_usage import LlmUsageRepository

MAX_TOKENS = 500
MAX_RATE_LIMIT_WAIT = 30.0
DEFAULT_RATE_LIMIT_WAIT = 5.0
SERVER_USAGE_TTL = timedelta(minutes=5)
SERVER_USAGE_FAILURE_TTL = timedelta(minutes=1)
JSON_PARAMETERS = frozenset({"response_format", "structured_outputs"})

# 호출 자체는 실패하지만 모든 모델에 똑같이 일어나는 문제: 체인을 돌 필요 없이 멈추고 알린다
ACCOUNT_ERRORS = {
    LlmErrorKind.PAYMENT_REQUIRED: (
        "llm_payment",
        "잔액 확인 필요: OpenRouter가 결제 오류(402)로 응답했습니다. 계정 잔액을 확인하세요.",
    ),
    LlmErrorKind.UNAUTHORIZED: (
        "llm_unauthorized",
        "키 확인 필요: OpenRouter가 인증 오류로 응답했습니다. 설정 화면에서 키를 확인하세요.",
    ),
    LlmErrorKind.POLICY: (
        "llm_policy",
        "개인정보 설정 확인 필요: OpenRouter의 개인정보 설정 때문에 무료 모델을 쓸 수 없습니다. "
        "https://openrouter.ai/settings/privacy 를 확인하세요.",
    ),
}


class BudgetBlocked(Exception):
    """호출 예산 때문에 새 호출을 보내지 않았다. 호출 자체의 실패(장애)와는 다르다."""

    def __init__(self, reason: BudgetBlock) -> None:
        super().__init__(reason.value)
        self.reason = reason


class LlmOutage(Exception):
    """체인의 모든 모델이 응답하지 못했다(잘못된 응답이 아니라 호출 자체의 실패)."""

    def __init__(self, failures: tuple[tuple[str, LlmErrorKind], ...]) -> None:
        super().__init__(", ".join(f"{model}:{kind.value}" for model, kind in failures))
        self.failures = failures


class LlmNotConfigured(Exception):
    """OpenRouter 키가 설정되지 않아서 호출하지 않았다."""


@dataclass(frozen=True)
class LlmAnswer:
    content: str
    finish_reason: str | None
    model: str


class LlmGateway:
    def __init__(
        self,
        *,
        client: LlmClient,
        usage: LlmUsageRepository,
        settings: SettingsService,
        alerts: AlertService,
        clock: Clock,
        sleep: Callable[[float], None] = time.sleep,
        errors: ErrorRecorder = NO_ERRORS,
    ) -> None:
        self._errors = errors
        self._client = client
        self._usage = usage
        self._settings = settings
        self._alerts = alerts
        self._clock = clock
        self._sleep = sleep
        self._json_rejected: set[str] = set()
        self._server_cache: tuple[datetime, ServerUsage | None] | None = None

    def complete(self, prompt: str) -> LlmAnswer:
        if not self._settings.has_openrouter_key():
            raise LlmNotConfigured
        config = self._settings.snapshot()
        failures: list[tuple[str, LlmErrorKind]] = []
        for model in config.model_chain:
            answer, stop = self._try_model(model, prompt, failures)
            if answer is not None:
                return answer
            if stop:
                break
        raise LlmOutage(tuple(failures))

    def complete_with(self, model: str, prompt: str) -> LlmAnswer:
        """체인 대신 지정한 모델 하나로만 호출한다(벤치마크용). 예산, 기록, 재시도 규칙은 같다."""
        if not self._settings.has_openrouter_key():
            raise LlmNotConfigured
        failures: list[tuple[str, LlmErrorKind]] = []
        answer, _ = self._try_model(model, prompt, failures)
        if answer is not None:
            return answer
        raise LlmOutage(tuple(failures))

    # ---------- 모델 하나 ----------

    def _try_model(
        self, model: str, prompt: str, failures: list[tuple[str, LlmErrorKind]]
    ) -> tuple[LlmAnswer | None, bool]:
        """(응답, 체인을 여기서 멈춰야 하는지)를 돌려준다."""
        options = self._options(model)
        rate_retried = False
        json_dropped = False
        wait = 0.0
        while True:
            self._ensure_budget()
            if wait:
                self._sleep(wait)
                wait = 0.0
            try:
                result = self._client.complete(model, prompt, options)
            except LlmCallError as error:
                self._record_failure(model, error)
                if error.kind is LlmErrorKind.RATE_LIMITED and not rate_retried:
                    rate_retried = True
                    wait = min(error.retry_after or DEFAULT_RATE_LIMIT_WAIT, MAX_RATE_LIMIT_WAIT)
                    continue
                if (
                    error.kind is LlmErrorKind.UNSUPPORTED_PARAMETER
                    and options.json_object
                    and not json_dropped
                ):
                    json_dropped = True
                    self._json_rejected.add(model)
                    options = replace(options, json_object=False)
                    continue
                failures.append((model, error.kind))
                account = ACCOUNT_ERRORS.get(error.kind)
                if account is not None:
                    self._alerts.notify(*account)
                return None, account is not None
            self._record_success(model, result)
            return LlmAnswer(result.content, result.finish_reason, model), False

    def _options(self, model: str) -> CallOptions:
        parameters = self._client.model_parameters(model)
        reasoning_off = (
            parameters is None or "reasoning" in parameters
        )  # 모르면 끈다(지원하지 않으면 무시된다)
        json_object = (
            parameters is not None
            and bool(JSON_PARAMETERS & parameters)
            and model not in self._json_rejected
        )
        return CallOptions(
            max_tokens=MAX_TOKENS, reasoning_off=reasoning_off, json_object=json_object
        )

    # ---------- 기록과 경고 ----------

    def _record_success(self, model: str, result: LlmResult) -> None:
        self._usage.record(
            model=model,
            outcome="success",
            status=200,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            reasoning_tokens=result.reasoning_tokens,
        )
        self._warn_if_needed()

    def _record_failure(self, model: str, error: LlmCallError) -> None:
        self._usage.record(model=model, outcome=error.kind.value, status=error.status)
        status = f" (HTTP {error.status})" if error.status else ""
        self._errors.record(KIND_LLM, model, f"{error.kind.value}{status}", str(error))
        self._warn_if_needed()

    def _warn_if_needed(self) -> None:
        config = self._settings.snapshot()
        used = self._usage.count_day(self._clock.now().astimezone(UTC).date())
        if warn_reached(used=used, cap=config.llm_daily_cap, warn_percent=config.llm_warn_percent):
            self._alerts.notify(
                "llm_warn",
                f"호출 {config.llm_warn_percent}% 도달: 오늘 {used}/{config.llm_daily_cap}회를 "
                "사용했습니다(UTC 기준).",
                once_per_day=True,
            )

    # ---------- 예산 ----------

    def _ensure_budget(self) -> None:
        config = self._settings.snapshot()
        now = self._clock.now().astimezone(UTC)
        used = self._usage.count_day(now.date())
        # 하루 상한에 이미 도달했으면 서버에 물어볼 필요가 없다
        remaining = None if used >= config.llm_daily_cap else self._server_remaining(now)
        block = check_budget(
            used_today=used,
            daily_cap=config.llm_daily_cap,
            calls_last_minute=self._usage.count_since(now - timedelta(seconds=60)),
            rpm_cap=config.llm_rpm_cap,
            server_remaining=remaining,
            reserve=config.llm_reserve_calls,
        )
        if block is None:
            return
        self._alert_block(block, config, used, remaining)
        raise BudgetBlocked(block)

    def _server_remaining(self, now: datetime) -> int | None:
        """서버가 알려 준 오늘 남은 호출 수.

        5분 동안 재사용하고, 조회에 실패하면 1분 뒤에 다시 묻는다.
        """
        cached = self._server_cache
        if cached is not None:
            fetched_at, usage = cached
            ttl = SERVER_USAGE_TTL if usage is not None else SERVER_USAGE_FAILURE_TTL
            if now - fetched_at < ttl:
                return None if usage is None else usage.remaining
        usage = self._client.server_usage()
        self._server_cache = (now, usage)
        return None if usage is None else usage.remaining

    def _alert_block(
        self, block: BudgetBlock, config: AppSettings, used: int, remaining: int | None
    ) -> None:
        if block is BudgetBlock.DAILY_CAP:
            self._alerts.notify(
                "llm_cap",
                f"호출 상한 도달: 오늘 {used}/{config.llm_daily_cap}회를 모두 사용해서 "
                "요약을 멈춥니다. "
                "UTC 날짜가 바뀌거나 설정에서 상한을 올리면 다시 시작합니다.",
            )
        elif block is BudgetBlock.SERVER_LOW:
            self._alerts.notify(
                "llm_server_low",
                f"서버 한도 임박: OpenRouter가 알려 준 오늘 남은 무료 호출은 {remaining}회입니다. "
                f"예비분({config.llm_reserve_calls}회) 이하라서 요약을 멈춥니다.",
            )
