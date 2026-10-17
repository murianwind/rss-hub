"""OpenRouter 호출 어댑터. 호출 방식의 근거는 docs/07-spike-s1-result.md.

- 키는 호출할 때마다 `key_provider`로 읽는다(설정 화면에서 바꾸면 바로 반영된다).
- 키는 인증 헤더에만 쓰고, 오류 메시지와 로그에는 넣지 않는다.
"""

import time
from collections.abc import Callable
from typing import Any

import requests

from rss_hub.services.ports import (
    CallOptions,
    KeyCheck,
    LlmCallError,
    LlmErrorKind,
    LlmResult,
    ServerUsage,
)

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_TIMEOUT = (5.0, 30.0)  # (연결, 읽기) 초
MODELS_TTL = 3600.0
MODELS_RETRY_AFTER_FAILURE = 60.0
MAX_MESSAGE_LENGTH = 200


def build_payload(model: str, prompt: str, options: CallOptions) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": options.max_tokens,
    }
    if options.reasoning_off:
        payload["reasoning"] = {"effort": "none"}
    if options.json_object:
        payload["response_format"] = {"type": "json_object"}
        payload["provider"] = {"require_parameters": True}
    return payload


def _error_text(body: Any) -> str:
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        return str(body["error"].get("message") or "")
    return ""


def _retry_after(value: str | None) -> float | None:
    try:
        return None if value is None else float(value)
    except ValueError:
        return None


def classify_error(status: int, message: str, retry_after: str | None = None) -> LlmCallError:
    """상태 코드와 오류 문구로 실패 종류를 가른다."""
    text = message.lower()
    kind = LlmErrorKind.OTHER
    if status == 429:
        kind = LlmErrorKind.RATE_LIMITED
    elif status == 402:
        kind = LlmErrorKind.PAYMENT_REQUIRED
    elif status in (401, 403):
        kind = LlmErrorKind.UNAUTHORIZED
    elif status in (408, 502, 503, 504) or status >= 500:
        kind = LlmErrorKind.UNAVAILABLE
    elif status == 404:
        if "policy" in text or "privacy" in text:
            kind = LlmErrorKind.POLICY
        elif "support" in text:
            kind = LlmErrorKind.UNSUPPORTED_PARAMETER
        else:
            kind = LlmErrorKind.UNAVAILABLE
    elif status == 400 and ("not supported" in text or "unsupported" in text):
        kind = LlmErrorKind.UNSUPPORTED_PARAMETER
    return LlmCallError(
        kind,
        status=status,
        retry_after=_retry_after(retry_after),
        message=message[:MAX_MESSAGE_LENGTH],
    )


class OpenRouterClient:
    def __init__(
        self,
        key_provider: Callable[[], str | None],
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: tuple[float, float] = DEFAULT_TIMEOUT,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._key_provider = key_provider
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._clock = clock
        self._models: dict[str, frozenset[str]] | None = None
        self._models_next_fetch = 0.0

    # ---------- 채팅 ----------

    def complete(self, model: str, prompt: str, options: CallOptions) -> LlmResult:
        key = self._require_key()
        try:
            response = requests.post(
                f"{self._base_url}/chat/completions",
                json=build_payload(model, prompt, options),
                headers=self._headers(key),
                timeout=self._timeout,
            )
        except requests.exceptions.RequestException as error:
            raise LlmCallError(LlmErrorKind.UNAVAILABLE, message=type(error).__name__) from error

        body = self._json(response)
        if response.status_code != 200:
            raise self._error(response.status_code, body, response.headers.get("Retry-After"), key)
        if isinstance(body, dict) and "error" in body:  # 200이지만 제공자 오류를 담은 응답
            code = body["error"].get("code") if isinstance(body["error"], dict) else None
            raise self._error(code if isinstance(code, int) else 502, body, None, key)

        choices = body.get("choices") if isinstance(body, dict) else None
        if not choices:
            raise LlmCallError(
                LlmErrorKind.UNAVAILABLE, status=200, message="응답에 choices가 없음"
            )
        choice = choices[0]
        usage = body.get("usage") or {}
        details = usage.get("completion_tokens_details") or {}
        return LlmResult(
            content=(choice.get("message") or {}).get("content") or "",
            finish_reason=choice.get("finish_reason"),
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            reasoning_tokens=details.get("reasoning_tokens"),
        )

    # ---------- 모델이 지원하는 옵션 ----------

    def model_parameters(self, model: str) -> frozenset[str] | None:
        """모델 목록을 한 시간 동안 재사용한다. 가져오지 못하면 1분 뒤에 다시 시도한다."""
        if self._clock() >= self._models_next_fetch:
            self._refresh_models()
        if self._models is None:
            return None
        return self._models.get(model)

    def _refresh_models(self) -> None:
        key = self._key_provider()
        loaded: dict[str, frozenset[str]] | None = None
        if key:
            try:
                response = requests.get(
                    f"{self._base_url}/models", headers=self._headers(key), timeout=self._timeout
                )
                body = self._json(response)
                if response.status_code == 200 and isinstance(body, dict):
                    loaded = {
                        str(item["id"]): frozenset(item.get("supported_parameters") or [])
                        for item in body.get("data", [])
                        if isinstance(item, dict) and "id" in item
                    }
            except requests.exceptions.RequestException:
                loaded = None
        if loaded is None:
            self._models_next_fetch = self._clock() + MODELS_RETRY_AFTER_FAILURE
            return
        self._models = loaded
        self._models_next_fetch = self._clock() + MODELS_TTL

    # ---------- 서버가 알려 주는 오늘 호출 수 ----------

    def server_usage(self) -> ServerUsage | None:
        key = self._key_provider()
        if not key:
            return None
        try:
            response = requests.get(
                f"{self._base_url}/key", headers=self._headers(key), timeout=self._timeout
            )
        except requests.exceptions.RequestException:
            return None
        body = self._json(response)
        data = body.get("data") if isinstance(body, dict) else None
        counter = data.get("free_model_daily_requests") if isinstance(data, dict) else None
        if response.status_code != 200 or not isinstance(counter, dict):
            return None
        used, limit = counter.get("used"), counter.get("limit")
        if not isinstance(used, int) or not isinstance(limit, int):
            return None
        return ServerUsage(used=used, limit=limit)

    def check_key(self) -> KeyCheck:
        """GET /key만 호출한다(채팅 호출이 아니고 호출 한도를 쓰지 않는다)."""
        key = self._key_provider()
        if not key:
            return KeyCheck(valid=False, reason="OpenRouter 키가 설정되지 않았습니다")
        try:
            response = requests.get(
                f"{self._base_url}/key", headers=self._headers(key), timeout=self._timeout
            )
        except requests.exceptions.RequestException as error:
            return KeyCheck(
                valid=None, reason=f"OpenRouter에 연결하지 못했습니다({type(error).__name__})"
            )
        if response.status_code in (401, 403):
            return KeyCheck(
                valid=False, reason=f"OpenRouter가 키를 거부했습니다(HTTP {response.status_code})"
            )
        if response.status_code != 200:
            return KeyCheck(
                valid=None, reason=f"키를 확인하지 못했습니다(HTTP {response.status_code})"
            )
        body = self._json(response)
        data = body.get("data") if isinstance(body, dict) else None
        counter = data.get("free_model_daily_requests") if isinstance(data, dict) else None
        used = counter.get("used") if isinstance(counter, dict) else None
        limit = counter.get("limit") if isinstance(counter, dict) else None
        return KeyCheck(
            valid=True,
            used=used if isinstance(used, int) else None,
            limit=limit if isinstance(limit, int) else None,
        )

    # ---------- 내부 ----------

    def _require_key(self) -> str:
        key = self._key_provider()
        if not key:
            raise LlmCallError(
                LlmErrorKind.UNAUTHORIZED, message="OpenRouter 키가 설정되지 않았습니다"
            )
        return key

    @staticmethod
    def _headers(key: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {key}", "X-Title": "RSS Hub"}

    @staticmethod
    def _json(response: requests.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return None

    @staticmethod
    def _error(status: int, body: Any, retry_after: str | None, key: str) -> LlmCallError:
        message = _error_text(body).replace(key, "[비밀 값]")
        return classify_error(status, message, retry_after)
