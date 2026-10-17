"""어댑터 테스트용 로컬 HTTP 서버. 경로별로 응답(상태, 헤더, 본문, 지연)을 정해 둔다."""

import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


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


class LocalServer:
    def __init__(self) -> None:
        self.routes: dict[str, Route] = {}
        self.requests: list[RecordedRequest] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                outer.requests.append(
                    RecordedRequest(self.path, {k.lower(): v for k, v in self.headers.items()})
                )
                route = outer.routes.get(self.path)
                if route is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                if route.delay:
                    time.sleep(route.delay)
                try:
                    self.send_response(route.status)
                    for name, value in route.headers.items():
                        self.send_header(name, value)
                    self.send_header("Content-Length", str(len(route.body)))
                    self.end_headers()
                    self.wfile.write(route.body)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # 클라이언트가 먼저 끊은 경우(시간 초과 테스트)

            def log_message(self, *_args: object) -> None:
                return

        class Server(ThreadingHTTPServer):
            daemon_threads = True  # 응답을 지연 중인 요청이 있어도 종료를 기다리지 않는다
            block_on_close = False

        self._server = Server(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(
            target=lambda: self._server.serve_forever(poll_interval=0.02), daemon=True
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}{path}"

    def serve(self, path: str, **kwargs: object) -> None:
        self.routes[path] = Route(**kwargs)  # type: ignore[arg-type]
