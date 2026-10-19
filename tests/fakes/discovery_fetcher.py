"""피드 자동 탐색 시험용 가짜 수집기: 주소마다 "피드", "웹페이지", "오류"를 정해 둔다."""

from dataclasses import dataclass, field

from rss_hub.services.ports import FetchError, FetchResult, PageResult


@dataclass
class FakeDiscoveryFetcher:
    feeds: dict[str, tuple[str, str]] = field(default_factory=dict)  # 주소 -> (제목, 사이트 주소)
    pages: dict[str, str] = field(default_factory=dict)  # 주소 -> HTML
    errors: dict[str, str] = field(default_factory=dict)  # 주소 -> 실패 분류
    page_errors: dict[str, str] = field(
        default_factory=dict
    )  # 주소 -> 웹페이지를 가져올 때만의 실패 분류
    final_urls: dict[str, str] = field(default_factory=dict)  # 리다이렉트 뒤의 주소
    fetch_calls: list[str] = field(default_factory=list)
    page_calls: list[str] = field(default_factory=list)

    def feed(self, url: str, title: str = "", site_url: str = "") -> None:
        self.feeds[url] = (title, site_url)

    def page(self, url: str, html: str) -> None:
        self.pages[url] = html

    def fail(self, url: str, reason: str) -> None:
        self.errors[url] = reason

    def fetch(self, url: str, *, etag: str | None, last_modified: str | None) -> FetchResult:
        self.fetch_calls.append(url)
        if url in self.errors:
            raise FetchError(self.errors[url])
        if url in self.feeds:
            title, site = self.feeds[url]
            return FetchResult(200, (), None, None, title=title, site_url=site)
        if url in self.pages:
            raise FetchError("NotAFeed")
        raise FetchError("HTTP 404")

    def fetch_page(self, url: str) -> PageResult:
        self.page_calls.append(url)
        if url in self.page_errors:
            raise FetchError(self.page_errors[url])
        if url in self.errors:
            raise FetchError(self.errors[url])
        if url in self.pages:
            return PageResult(self.pages[url], self.final_urls.get(url, url))
        raise FetchError("HTTP 404")
