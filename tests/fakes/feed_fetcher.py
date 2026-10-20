from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from rss_hub.services.ports import FetchError, FetchResult, PageResult


@dataclass
class FetchCall:
    url: str
    etag: str | None
    last_modified: str | None


@dataclass
class FakeFeedFetcher:
    """주소별로 응답(항목 목록, 304, 오류)을 정해 두는 가짜 피드 수집기."""

    outcomes: dict[str, FetchResult | FetchError | Exception] = field(default_factory=dict)
    calls: list[FetchCall] = field(default_factory=list)

    def serve(
        self,
        url: str,
        entries: Sequence[Mapping[str, Any]],
        *,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> None:
        self.outcomes[url] = FetchResult(200, tuple(entries), etag, last_modified)

    def not_modified(self, url: str) -> None:
        self.outcomes[url] = FetchResult(304, (), None, None)

    def fail(self, url: str, reason: str = "Timeout") -> None:
        self.outcomes[url] = FetchError(reason)

    def crash(self, url: str, error: Exception) -> None:
        self.outcomes[url] = error

    def fetch(self, url: str, *, etag: str | None, last_modified: str | None) -> FetchResult:
        self.calls.append(FetchCall(url, etag, last_modified))
        outcome = self.outcomes[url]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def fetch_page(self, url: str) -> PageResult:
        """주소 판정이 웹페이지를 볼 때: 이 가짜는 웹페이지를 모른다(피드가 아니라는 답과 같다)."""
        raise FetchError("NotAFeed")

    def urls_fetched(self) -> list[str]:
        return [call.url for call in self.calls]
