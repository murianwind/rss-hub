"""스파이크 스크립트를 검증하기 위한 가짜 OpenRouter, 가짜 Discord 서버."""

import json
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

Handler = Callable[[str, str, dict[str, str], Any], tuple[int, dict[str, str], bytes]]


class FakeServer:
    def __init__(self, handler: Handler, host: str = "127.0.0.1") -> None:
        outer = self
        self._host = host
        self.requests: list[tuple[str, str, dict[str, str], Any]] = []

        class Request(BaseHTTPRequestHandler):
            def _handle(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                body = json.loads(raw) if raw else None
                headers = {k.lower(): v for k, v in self.headers.items()}
                outer.requests.append((self.command, self.path, headers, body))
                status, reply_headers, reply_body = handler(self.command, self.path, headers, body)
                try:
                    self.send_response(status)
                    for name, value in reply_headers.items():
                        self.send_header(name, value)
                    self.send_header("Content-Length", str(len(reply_body)))
                    self.end_headers()
                    self.wfile.write(reply_body)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # 클라이언트가 먼저 끊은 경우(시간 초과 시험)

            do_GET = do_POST = do_DELETE = _handle

            def log_message(self, *_args: object) -> None:
                return

        class Server(ThreadingHTTPServer):
            daemon_threads = True
            block_on_close = False

        self._server = Server((host, 0), Request)
        self._thread = threading.Thread(
            target=lambda: self._server.serve_forever(poll_interval=0.02), daemon=True
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def url(self, path: str = "") -> str:
        return f"http://{self._host}:{self._server.server_address[1]}{path}"


def json_reply(status: int, data: Any, headers: dict[str, str] | None = None):
    return (
        status,
        {"Content-Type": "application/json", **(headers or {})},
        json.dumps(data).encode(),
    )


GOOD_JSON = json.dumps(
    {
        "title_ko": "애플, 배터리가 큰 새 폰 공개",
        "summary_ko": "애플이 배터리를 키운 새 폰을 공개했다.",
        "is_ott": False,
    },
    ensure_ascii=False,
)
LEGACY_TEXT = "TITLE: 애플, 새 폰 공개\nSUMMARY: 애플이 새 폰을 공개했다.\nOTT: no"

MODELS = {
    "data": [
        {
            "id": "nvidia/nemotron-3-ultra-550b-a55b:free",
            "created": 100,
            "context_length": 128000,
            "pricing": {"prompt": "0", "completion": "0"},
            "supported_parameters": ["reasoning", "include_reasoning"],
            "architecture": {"output_modalities": ["text"]},
        },
        {
            "id": "nvidia/nemotron-3-super-120b-a12b:free",
            "created": 90,
            "context_length": 128000,
            "pricing": {"prompt": "0", "completion": "0"},
            "supported_parameters": ["reasoning"],
            "architecture": {"output_modalities": ["text"]},
        },
        {
            "id": "vendor/json-model:free",
            "created": 200,
            "context_length": 32000,
            "expiration_date": "2026-12-01",
            "pricing": {"prompt": "0", "completion": "0"},
            "supported_parameters": ["response_format", "structured_outputs"],
            "architecture": {"output_modalities": ["text"]},
        },
        {
            "id": "vendor/paid-model",
            "created": 300,
            "context_length": 8000,
            "pricing": {"prompt": "0.000001", "completion": "0.000002"},
            "supported_parameters": ["response_format"],
            "architecture": {"output_modalities": ["text"]},
        },
        {
            "id": "vendor/image-model:free",
            "created": 250,
            "context_length": 8000,
            "pricing": {"prompt": "0", "completion": "0"},
            "supported_parameters": ["response_format"],
            "architecture": {"output_modalities": ["image"]},
        },
    ]
}


def make_openrouter(secret_label: str = "sk-or-v1-LABELSECRET", mode: str = "normal") -> Handler:
    """추론 모델은 추론에 토큰을 다 써서 잘리고, JSON 지원 모델은 항상 잘 답하는 가짜 OpenRouter."""
    state: dict[str, Any] = {"super_calls": 0, "calls": {}}

    def handler(method: str, path: str, headers: dict[str, str], body: Any):
        if path == "/key":
            return json_reply(
                200,
                {
                    "data": {
                        "label": secret_label,
                        "usage": 0,
                        "usage_daily": 0,
                        "limit": None,
                        "is_free_tier": False,
                        "free_model_daily_requests": 1000,
                        "workspace_id": "ws-PRIVATE-IDENTIFIER",
                        "creator_user_id": "user-PRIVATE-IDENTIFIER",
                    }
                },
            )
        if path == "/models":
            return json_reply(200, MODELS)
        assert path == "/chat/completions", path
        model = body["model"]
        state["calls"][model] = state["calls"].get(model, 0) + 1
        if mode == "flaky" and state["calls"][model] > 1:  # 첫 호출(사전 확인)만 성공한다
            return json_reply(
                404,
                {"error": {"code": 404, "message": "No endpoints found matching your data policy"}},
            )
        if mode == "slow_ultra" and model.startswith("nvidia/nemotron-3-ultra"):
            time.sleep(1.0)
        if mode == "policy":
            return json_reply(
                404,
                {
                    "error": {
                        "code": 404,
                        "message": "No endpoints found matching your data policy "
                        "(Free model publication). "
                        "Configure: https://openrouter.ai/settings/privacy",
                    }
                },
            )
        if mode == "unauthorized":
            return json_reply(401, {"error": {"code": 401, "message": "No auth credentials found"}})
        if mode == "payment":
            return json_reply(402, {"error": {"code": 402, "message": "Insufficient credits"}})
        legacy = (
            "TITLE:" in body["messages"][0]["content"]
            and "ONLY the TITLE" in body["messages"][0]["content"]
        )
        reasoning_off = (body.get("reasoning") or {}).get("effort") == "none"
        rate = {"x-ratelimit-remaining": "19"}

        if model == "vendor/json-model:free":
            text = LEGACY_TEXT if legacy else GOOD_JSON
            return json_reply(
                200,
                {
                    "provider": "FakeProvider",
                    "choices": [{"finish_reason": "stop", "message": {"content": text}}],
                    "usage": {"prompt_tokens": 120, "completion_tokens": 60},
                },
                rate,
            )

        if model.endswith("120b-a12b:free"):
            state["super_calls"] += 1
            if state["super_calls"] == 2:  # 사전 확인 다음의 첫 본 호출은 한도 초과(429)
                return json_reply(
                    429, {"error": {"code": 429, "message": "rate limited"}}, {"Retry-After": "0"}
                )

        if "response_format" in body:  # 이 모델은 응답 형식 지정을 지원하지 않는다
            return json_reply(
                404,
                {
                    "error": {
                        "code": 404,
                        "message": "No endpoints found that support response_format",
                    }
                },
            )
        if reasoning_off:
            text = LEGACY_TEXT if legacy else GOOD_JSON
            return json_reply(
                200,
                {
                    "provider": "Fake",
                    "choices": [{"finish_reason": "stop", "message": {"content": text}}],
                    "usage": {
                        "prompt_tokens": 120,
                        "completion_tokens": 70,
                        "completion_tokens_details": {"reasoning_tokens": 0},
                    },
                },
                rate,
            )
        # 추론을 끄지 않으면 토큰을 추론에 다 쓰고 답이 잘린다
        limit = body["max_tokens"]
        return json_reply(
            200,
            {
                "provider": "Fake",
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {"content": "", "reasoning": "We need to translate..."},
                    }
                ],
                "usage": {
                    "prompt_tokens": 120,
                    "completion_tokens": limit,
                    "completion_tokens_details": {"reasoning_tokens": limit},
                },
            },
            rate,
        )

    return handler


def make_discord(token: str = "TOKENXYZ") -> Handler:
    state = {"next_id": 1000, "posts": 0, "messages": set(), "deleted_webhook": False}
    base = f"/api/webhooks/123/{token}"

    def handler(method: str, path: str, headers: dict[str, str], body: Any):
        rate = {
            "X-RateLimit-Limit": "5",
            "X-RateLimit-Remaining": "4",
            "X-RateLimit-Reset-After": "2",
        }
        if state["deleted_webhook"]:
            return json_reply(404, {"message": "Unknown Webhook", "code": 10015})
        if method == "POST" and path.startswith(base):
            if len(body["content"]) > 2000:
                return json_reply(400, {"code": 50035, "message": "Invalid Form Body"})
            state["posts"] += 1
            if state["posts"] % 6 == 0:  # 몇 번 연속으로 보내면 한도에 걸린다
                return json_reply(
                    429,
                    {
                        "message": "You are being rate limited.",
                        "retry_after": 0.01,
                        "global": False,
                    },
                    {"Retry-After": "0.01", **rate},
                )
            if "wait=true" in path:
                state["next_id"] += 1
                state["messages"].add(str(state["next_id"]))
                return json_reply(
                    200,
                    {
                        "id": str(state["next_id"]),
                        "channel_id": "1",
                        "content": body["content"][:10],
                    },
                    rate,
                )
            return 204, rate, b""
        if method == "DELETE" and "/messages/" in path:
            message = path.rsplit("/", 1)[-1]
            if message in state["messages"]:
                state["messages"].discard(message)
                return 204, {}, b""
            return json_reply(404, {"message": "Unknown Message", "code": 10008})
        return json_reply(404, {"message": "404: Not Found", "code": 0})

    handler.state = state  # type: ignore[attr-defined]
    return handler
