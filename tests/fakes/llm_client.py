"""LLM 호출을 정해 둔 대로 돌려주는 가짜 클라이언트와 알림 수신기."""

import json
from collections.abc import Callable
from dataclasses import dataclass, field

from rss_hub.services.ports import (
    CallOptions,
    KeyCheck,
    LlmCallError,
    LlmErrorKind,
    LlmResult,
    ServerUsage,
)

GOOD_CONTENT = json.dumps(
    {"title_ko": "애플, 새 폰 공개", "summary_ko": "애플이 새 폰을 공개했다.", "topics": []},
    ensure_ascii=False,
)

Outcome = LlmResult | LlmCallError | Exception | Callable[[], LlmResult]


def good(content: str = GOOD_CONTENT, finish: str = "stop") -> LlmResult:
    return LlmResult(content, finish, prompt_tokens=250, completion_tokens=100, reasoning_tokens=0)


def reply(title_ko: str, summary_ko: str, topics: list[object] | None = None) -> LlmResult:
    """topics가 None이면 응답에 "topics" 항목을 넣지 않는다."""
    data: dict[str, object] = {"title_ko": title_ko, "summary_ko": summary_ko}
    if topics is not None:
        data["topics"] = topics
    return good(json.dumps(data, ensure_ascii=False))


def failure(kind: LlmErrorKind, status: int = 0, retry_after: float | None = None) -> LlmCallError:
    return LlmCallError(kind, status=status, retry_after=retry_after, message="시험용 실패")


@dataclass
class FakeCall:
    model: str
    prompt: str
    options: CallOptions


@dataclass
class FakeLlmClient:
    """모델마다 "다음에 돌려줄 결과"를 줄 세워 둔다. 줄이 비면 기본 결과를 돌려준다."""

    queues: dict[str, list[Outcome]] = field(default_factory=dict)
    default: Outcome | None = None
    calls: list[FakeCall] = field(default_factory=list)
    parameters: dict[str, frozenset[str] | None] = field(default_factory=dict)
    usage: ServerUsage | None = None
    usage_queries: int = 0
    key_check: KeyCheck = field(default_factory=lambda: KeyCheck(valid=True, used=33, limit=1000))
    key_checks: int = 0

    def will(self, model: str, *outcomes: Outcome) -> None:
        self.queues.setdefault(model, []).extend(outcomes)

    def complete(self, model: str, prompt: str, options: CallOptions) -> LlmResult:
        self.calls.append(FakeCall(model, prompt, options))
        queue = self.queues.get(model)
        outcome: Outcome | None = queue.pop(0) if queue else self.default
        if outcome is None:
            raise AssertionError(f"{model}에 대해 정해 둔 결과가 없습니다")
        if isinstance(outcome, Exception):
            raise outcome
        return outcome() if callable(outcome) else outcome

    def model_parameters(self, model: str) -> frozenset[str] | None:
        return self.parameters.get(model)

    def server_usage(self) -> ServerUsage | None:
        self.usage_queries += 1
        return self.usage

    def check_key(self) -> KeyCheck:
        self.key_checks += 1
        return self.key_check

    def models_called(self) -> list[str]:
        return [call.model for call in self.calls]


@dataclass
class FakeNotifier:
    sent: list[tuple[str, str]] = field(default_factory=list)
    fail: bool = False

    def send(self, webhook_url: str, text: str) -> None:
        if self.fail:
            raise ConnectionError("Discord에 연결할 수 없음")
        self.sent.append((webhook_url, text))

    def texts(self) -> list[str]:
        return [text for _, text in self.sent]
