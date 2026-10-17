"""사설망으로 연결되지 않는 HTTP 세션.

이름을 풀어 본 결과만 검사하면, 검사와 실제 연결 사이에 답이 바뀌는 경우(DNS 재바인딩)나
리다이렉트로 사설망에 닿는 경우를 놓친다. 그래서 **실제로 연결된 소켓의 상대 IP**를
연결 직후에 검사한다. 리다이렉트도 새 연결을 만들기 때문에 같은 검사를 거친다.
환경 변수의 프록시 설정은 쓰지 않는다.
"""

from collections.abc import Callable
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool


class ForbiddenAddress(Exception):
    """연결된 상대가 사설망, 내부 주소여서 연결을 끊었다. 메시지에 주소를 넣지 않는다."""

    def __init__(self) -> None:
        super().__init__("연결 상대가 허용되지 않는 주소")


def build_guarded_session(forbid_address: Callable[[str], bool]) -> requests.Session:
    """연결된 상대 IP가 forbid_address에 걸리면 ForbiddenAddress를 올리는 세션을 만든다."""

    def check(connection_socket: Any) -> None:
        peer = connection_socket.getpeername()[0]
        if forbid_address(peer):
            connection_socket.close()
            raise ForbiddenAddress

    class GuardedConnection(HTTPConnection):
        def _new_conn(self) -> Any:
            connection_socket = super()._new_conn()
            check(connection_socket)
            return connection_socket

    class GuardedSecureConnection(HTTPSConnection):
        def _new_conn(self) -> Any:
            connection_socket = super()._new_conn()
            check(connection_socket)  # TLS 협상을 시작하기 전에 검사한다
            return connection_socket

    class GuardedPool(HTTPConnectionPool):
        ConnectionCls = GuardedConnection

    class GuardedSecurePool(HTTPSConnectionPool):
        ConnectionCls = GuardedSecureConnection

    class GuardedAdapter(HTTPAdapter):  # type: ignore[misc]  # requests는 타입 정보가 없다
        def init_poolmanager(self, *args: Any, **kwargs: Any) -> None:
            super().init_poolmanager(*args, **kwargs)
            self.poolmanager.pool_classes_by_scheme = {
                "http": GuardedPool,
                "https": GuardedSecurePool,
            }

    session = requests.Session()
    session.trust_env = False  # 환경 변수의 프록시 설정, .netrc를 쓰지 않는다
    adapter = GuardedAdapter()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session
