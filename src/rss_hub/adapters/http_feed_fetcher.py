"""HTTP로 피드를 가져와서 feedparser로 해석하는 어댑터."""

from collections.abc import Callable

import feedparser
import requests

from rss_hub.adapters.guarded_http import ForbiddenAddress, build_guarded_session
from rss_hub.domain.network import is_forbidden_ip
from rss_hub.services.ports import FetchError, FetchResult, PageResult
from rss_hub.version import get_version

DEFAULT_TIMEOUT = (4.0, 12.0)  # (연결, 읽기) 초
DEFAULT_MAX_BYTES = 5_000_000
MAX_PAGE_BYTES = 1_000_000  # 웹페이지는 피드보다 작게 제한한다
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
        return FetchResult(
            200,
            tuple(parsed.entries),
            new_etag,
            new_last_modified,
            title=str(parsed.feed.get("title") or "").strip(),
            site_url=str(parsed.feed.get("link") or "").strip(),
        )

    def fetch_page(self, url: str) -> PageResult:
        """웹페이지를 가져온다(피드 자동 탐색용). 같은 연결 검사를 거치고 1MB까지만 읽는다."""
        headers = {"User-Agent": self._user_agent, "Accept": "text/html,application/xhtml+xml"}
        try:
            with self._session.get(
                url, headers=headers, timeout=self.timeout, allow_redirects=True, stream=True
            ) as response:
                if not 200 <= response.status_code < 300:
                    raise FetchError(f"HTTP {response.status_code}")
                body = self._read_limited(response, MAX_PAGE_BYTES)
                final_url = str(response.url)
                declared = response.encoding or "utf-8"
        except ForbiddenAddress as error:
            raise FetchError("ForbiddenAddress") from error
        except requests.exceptions.RequestException as error:
            raise FetchError(type(error).__name__) from error
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            text = body.decode(declared, errors="replace")
        return PageResult(text=text, final_url=final_url)

    def _read_limited(self, response: requests.Response, limit: int | None = None) -> bytes:
        maximum = self._max_bytes if limit is None else limit
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
            total += len(chunk)
            if total > maximum:
                raise FetchError("TooLarge")
            chunks.append(chunk)
        return b"".join(chunks)
