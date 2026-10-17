"""서비스 계층이 외부 세계와 만나는 모양(포트)."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol


@dataclass(frozen=True)
class FetchResult:
    """피드 한 번 가져온 결과. status가 304면 entries는 비어 있고 검증값은 이전 값이다."""

    status: int
    entries: tuple[Mapping[str, Any], ...]
    etag: str | None
    last_modified: str | None


class FetchError(Exception):
    """피드를 가져오지 못했다. reason은 사용자에게 보여 줄 수 있는 짧은 분류(예: ReadTimeout)다."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class FeedFetcher(Protocol):
    def fetch(self, url: str, *, etag: str | None, last_modified: str | None) -> FetchResult:
        """피드를 가져온다. 실패하면 FetchError를 올린다."""
        ...


# ---------- LLM ----------


class LlmErrorKind(StrEnum):
    RATE_LIMITED = "rate_limited"  # 429: 한도 초과
    UNAVAILABLE = "unavailable"  # 5xx, 시간 초과, 연결 실패 등 일시적인 장애
    PAYMENT_REQUIRED = "payment"  # 402: 잔액 부족
    UNAUTHORIZED = "unauthorized"  # 401, 403: 키 문제
    POLICY = "policy"  # 404: 개인정보(데이터 정책) 설정 때문에 무료 모델을 쓸 수 없음
    UNSUPPORTED_PARAMETER = "unsupported"  # 모델이나 제공자가 요청 옵션을 지원하지 않음
    OTHER = "other"


class LlmCallError(Exception):
    """LLM 호출 자체가 실패했다(잘못된 응답과는 다르다). 메시지에는 키나 주소를 넣지 않는다."""

    def __init__(
        self,
        kind: LlmErrorKind,
        *,
        status: int = 0,
        retry_after: float | None = None,
        message: str = "",
    ) -> None:
        super().__init__(f"{kind.value} (HTTP {status}) {message}".strip())
        self.kind = kind
        self.status = status
        self.retry_after = retry_after
        self.message = message


@dataclass(frozen=True)
class CallOptions:
    max_tokens: int
    reasoning_off: bool  # reasoning: {"effort": "none"}
    json_object: bool  # response_format: json_object (지원하는 모델에만)


@dataclass(frozen=True)
class LlmResult:
    content: str
    finish_reason: str | None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    reasoning_tokens: int | None = None


@dataclass(frozen=True)
class ServerUsage:
    """서버가 알려 주는 오늘의 무료 모델 호출 수(같은 키를 쓰는 모든 프로그램의 합계)."""

    used: int
    limit: int

    @property
    def remaining(self) -> int:
        return self.limit - self.used


class LlmClient(Protocol):
    def complete(self, model: str, prompt: str, options: CallOptions) -> LlmResult:
        """호출 한 번. 실패하면 LlmCallError를 올린다."""
        ...

    def model_parameters(self, model: str) -> frozenset[str] | None:
        """모델이 지원한다고 알린 요청 옵션 이름들. 알 수 없으면 None."""
        ...

    def server_usage(self) -> ServerUsage | None:
        """서버가 알려 주는 오늘 호출 수. 호출 한도를 쓰지 않는다. 조회에 실패하면 None."""
        ...


class Notifier(Protocol):
    def send(self, webhook_url: str, text: str) -> None:
        """시스템 알림을 보낸다. 실패하면 예외를 올린다."""
        ...


# ---------- Discord 웹훅 ----------


@dataclass(frozen=True)
class SendResult:
    """웹훅으로 한 번 보낸 결과. 실패해도 예외가 아니라 결과로 돌려준다(status 0은 연결 실패)."""

    status: int
    retry_after: float | None = None  # 429일 때 기다릴 초
    rate_remaining: int | None = None  # 이 웹훅의 남은 호출 수(헤더)
    rate_reset_after: float | None = None  # 한도가 다시 채워질 때까지 초(헤더)
    message_id: str | None = None
    error: str = ""  # 오류 종류 이름. 주소나 토큰을 넣지 않는다


class WebhookSender(Protocol):
    def send(self, webhook_url: str, content: str) -> SendResult:
        """메시지를 보낸다. 실패는 예외가 아니라 SendResult의 status로 알린다."""
        ...
