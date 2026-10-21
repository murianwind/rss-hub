"""시험용 로컬 HTTP 서버.

- FakeServer: 요청마다 handler(method, path, headers, json_body)가 (상태, 헤더, 본문)을 돌려준다.
- LocalServer: 경로별로 응답(상태, 헤더, 본문, 지연)을 미리 정해 둔다(GET만).
둘 다 실제 소켓으로 듣기 때문에 어댑터의 연결, 시간 초과, 리디렉션 처리를 그대로 검증할 수 있다.
"""

import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

Handler = Callable[[str, str, dict[str, str], Any], tuple[int, dict[str, str], bytes]]


class _Server(ThreadingHTTPServer):
    daemon_threads = True  # 응답을 지연 중인 요청이 있어도 종료를 기다리지 않는다
    block_on_close = False


class _Serving:
    """handler를 단 서버를 스레드에서 돌리고 멈추는 공통 부분."""

    def __init__(self, handler: Handler, host: str = "127.0.0.1") -> None:
        self._host = host
        self.requests: list[Any] = []
        outer = self

        class Request(BaseHTTPRequestHandler):
            def _handle(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                body = json.loads(raw) if raw else None
                headers = {k.lower(): v for k, v in self.headers.items()}
                outer._record(self.command, self.path, headers, body)
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

        self._server = _Server((host, 0), Request)
        self._thread = threading.Thread(
            target=lambda: self._server.serve_forever(poll_interval=0.02), daemon=True
        )

    def _record(self, method: str, path: str, headers: dict[str, str], body: Any) -> None:
        self.requests.append((method, path, headers, body))

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    def url(self, path: str = "") -> str:
        return f"http://{self._host}:{self._server.server_address[1]}{path}"


class FakeServer(_Serving):
    """requests는 (메서드, 경로, 머리글, JSON 본문) 튜플 목록이다."""


def json_reply(status: int, data: Any, headers: dict[str, str] | None = None):
    return (
        status,
        {"Content-Type": "application/json", **(headers or {})},
        json.dumps(data).encode(),
    )


@dataclass
class Route:
    status: int = 200
    body: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)
    delay: float = 0.0


@dataclass
class RecordedRequest:
    path: str
    headers: dict[str, str]


class LocalServer(_Serving):
    """경로별 고정 응답. requests는 RecordedRequest 목록이다. 없는 경로는 404."""

    def __init__(self) -> None:
        self.routes: dict[str, Route] = {}
        super().__init__(self._respond)

    def _record(self, method: str, path: str, headers: dict[str, str], body: Any) -> None:
        self.requests.append(RecordedRequest(path, headers))

    def _respond(
        self, _method: str, path: str, _headers: dict[str, str], _body: Any
    ) -> tuple[int, dict[str, str], bytes]:
        route = self.routes.get(path)
        if route is None:
            return 404, {}, b""
        if route.delay:
            time.sleep(route.delay)
        return route.status, route.headers, route.body

    def serve(self, path: str, **kwargs: object) -> None:
        self.routes[path] = Route(**kwargs)  # type: ignore[arg-type]
