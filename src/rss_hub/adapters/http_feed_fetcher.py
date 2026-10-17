"""HTTP로 피드를 가져와서 feedparser로 해석하는 어댑터."""

from collections.abc import Callable

import feedparser
import requests

from rss_hub.adapters.guarded_http import ForbiddenAddress, build_guarded_session
from rss_hub.domain.network import is_forbidden_ip
from rss_hub.services.ports import FetchError, FetchResult
from rss_hub.version import get_version

DEFAULT_TIMEOUT = (4.0, 12.0)  # (연결, 읽기) 초
DEFAULT_MAX_BYTES = 5_000_000
CHUNK_SIZE = 65_536


class RequestsFeedFetcher:
    """조건부 요청, 크기 제한, 피드가 아닌 응답 거부, 사설망 연결 차단을 처리한다."""

    def __init__(
        self,
        timeout: tuple[float, float] = DEFAULT_TIMEOUT,
        max_bytes: int = DEFAULT_MAX_BYTES,
        user_agent: str | None = None,
        *,
        forbid_address: Callable[[str], bool] = is_forbidden_ip,
    ) -> None:
        self.timeout = timeout
        self._session = build_guarded_session(forbid_address)
        self._max_bytes = max_bytes
        self._user_agent = user_agent or f"RSS Hub/{get_version()}"

    def fetch(self, url: str, *, etag: str | None, last_modified: str | None) -> FetchResult:
        headers = {"User-Agent": self._user_agent}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified

        try:
            with self._session.get(
                url, headers=headers, timeout=self.timeout, allow_redirects=True, stream=True
            ) as response:
                if response.status_code == 304:
                    return FetchResult(304, (), etag, last_modified)
                if not 200 <= response.status_code < 300:
                    raise FetchError(f"HTTP {response.status_code}")
                body = self._read_limited(response)
                new_etag = response.headers.get("ETag")
                new_last_modified = response.headers.get("Last-Modified")
        except ForbiddenAddress as error:  # 사설망으로 연결되어서 끊었다(주소는 밝히지 않는다)
            raise FetchError("ForbiddenAddress") from error
        except requests.exceptions.RequestException as error:
            raise FetchError(type(error).__name__) from error

        parsed = feedparser.parse(body)
        if not parsed.version:  # HTML 페이지 같은 피드가 아닌 응답
            raise FetchError("NotAFeed")
        return FetchResult(200, tuple(parsed.entries), new_etag, new_last_modified)

    def _read_limited(self, response: requests.Response) -> bytes:
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
            total += len(chunk)
            if total > self._max_bytes:
                raise FetchError("TooLarge")
            chunks.append(chunk)
        return b"".join(chunks)
