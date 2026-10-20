"""피드 개별 등록: 주소를 확인하고(피드면 제목, 웹페이지면 그 페이지가 알려 준 피드들), 등록한다.

- 주소는 가져오기와 같은 규칙(http, https, 사설망 거부)으로 먼저 거르고,
  실제 요청도 같은 연결 검사를 거친다.
- 등록하기 직전에 다시 가져와서 피드인지 확인한다. 화면에서 넘어온 값은 믿지 않는다.
- 등록한 피드는 baseline_pending이라 첫 점검에서 지금 있는 글을 "이미 본 글"로만 기록한다.
"""

from dataclasses import dataclass
from urllib.parse import urlsplit

from rss_hub.domain.discovery import describe_fetch_failure, find_feed_links
from rss_hub.domain.feed_url import FeedUrlError, feed_url_key, validate_feed_url
from rss_hub.domain.importing import MAX_NAME_LENGTH, MAX_URL_TEXT_LENGTH
from rss_hub.domain.page_feed import MIN_ITEMS, PageListing, extract_page_items
from rss_hub.services.page_source import site_of
from rss_hub.services.ports import DiscoveryFetcher, FetchError, FetchResult
from rss_hub.storage.feeds import (
    KIND_FEED,
    KIND_PAGE,
    DuplicateFeedError,
    FeedRepository,
    FeedRuleError,
)

MAX_CANDIDATES = 5  # 웹페이지가 알려 준 피드 중 실제로 확인해서 보여 주는 최대 개수
ALREADY_SUBSCRIBED = "이미 구독 중인 피드입니다"
NOTHING_FOUND = "이 주소에서 피드를 찾지 못했습니다"
PAGE_HAS_FEEDS = (
    "이 주소는 피드가 아니라 웹페이지이고, 이 페이지가 피드를 알려 주고 있습니다. "
    "'변경' 버튼으로 찾아서 고르세요"
)
NO_PAGE_ITEMS = (
    "글 목록을 찾지 못했습니다. 글 목록 페이지 주소가 맞는지, "
    "사이트 구조가 바뀌지 않았는지 확인하세요"
)
ALL_SUBSCRIBED = "이 주소가 알려 준 피드는 모두 이미 구독 중입니다"


@dataclass(frozen=True)
class Candidate:
    url: str
    title: str  # 피드가 알려 준 제목. 없으면 사이트 이름(호스트)
    site_url: str
    kind: str = KIND_FEED  # page면 RSS가 없어서 글 목록 페이지로 구독하는 후보
    count: int = 0  # page일 때 목록에서 찾은 글 수
    sample: tuple[str, ...] = ()  # page일 때 찾은 글 제목 몇 개(맞게 찾았는지 눈으로 확인용)


@dataclass(frozen=True)
class DiscoveryResult:
    candidates: tuple[Candidate, ...] = ()
    error: str = ""


@dataclass(frozen=True)
class Resolution:
    """주소 판정 결과. error가 비어 있으면 kind(feed 또는 page)로 구독할 수 있다."""

    kind: str = KIND_FEED
    site_url: str = ""
    title: str = ""
    error: str = ""


@dataclass(frozen=True)
class RegistrationResult:
    feed_id: int | None = None
    name: str = ""
    error: str = ""


def _usable(url: str) -> bool:
    try:
        validate_feed_url(url)
    except FeedUrlError:
        return False
    return True


def _page_candidate(url: str, final_url: str, listing: PageListing) -> Candidate:
    return Candidate(
        url,
        listing.title or _host(url),
        site_of(final_url),
        kind=KIND_PAGE,
        count=len(listing.items),
        sample=tuple(item.title for item in listing.items[:3]),
    )


def _host(url: str) -> str:
    return urlsplit(url).hostname or url


def _title(result: FetchResult, fallback: str, url: str) -> str:
    return (result.title or fallback or _host(url))[:MAX_NAME_LENGTH]


class FeedRegistrationService:
    def __init__(self, *, fetcher: DiscoveryFetcher, feeds: FeedRepository) -> None:
        self._fetcher = fetcher
        self._feeds = feeds

    def discover(self, raw_url: str) -> DiscoveryResult:
        """피드 주소면 그 피드를, 웹페이지면 그 페이지가 알려 준 피드들을 후보로 돌려준다."""
        try:
            url = validate_feed_url(raw_url)
        except FeedUrlError as error:
            return DiscoveryResult(error=error.message)
        existing = self._feeds.existing_url_keys()
        if feed_url_key(url) in existing:
            return DiscoveryResult(error=ALREADY_SUBSCRIBED)

        try:
            result = self._fetcher.fetch(url, etag=None, last_modified=None)
        except FetchError as error:
            if error.reason != "NotAFeed":
                return DiscoveryResult(error=describe_fetch_failure(error.reason))
            return self._discover_in_page(url, existing)
        return DiscoveryResult(
            candidates=(Candidate(url, _title(result, "", url), result.site_url),)
        )

    def _discover_in_page(self, url: str, existing: set[str]) -> DiscoveryResult:
        try:
            page = self._fetcher.fetch_page(url)
        except FetchError as error:
            return DiscoveryResult(error=describe_fetch_failure(error.reason))
        links = find_feed_links(page.text, page.final_url)
        candidates: list[Candidate] = []
        skipped_as_subscribed = 0
        for link in links:
            if len(candidates) >= MAX_CANDIDATES:
                break
            try:
                link_url = validate_feed_url(link.url)
            except FeedUrlError:
                continue  # 사설망 주소 등은 요청하지 않고 버린다
            if feed_url_key(link_url) in existing:
                skipped_as_subscribed += 1
                continue
            try:
                result = self._fetcher.fetch(link_url, etag=None, last_modified=None)
            except FetchError:
                continue  # 알려 준 주소가 피드가 아니면 후보에서 뺀다
            candidates.append(
                Candidate(link_url, _title(result, link.title, link_url), result.site_url)
            )
        if candidates:
            return DiscoveryResult(candidates=tuple(candidates))
        if skipped_as_subscribed:
            return DiscoveryResult(error=ALL_SUBSCRIBED)
        listing = extract_page_items(page.text, page.final_url)
        if len(listing.items) >= MIN_ITEMS:  # 피드는 없지만 글 목록 페이지로는 구독할 수 있다
            return DiscoveryResult(candidates=(_page_candidate(url, page.final_url, listing),))
        return DiscoveryResult(error=NOTHING_FOUND)

    def resolve(self, raw_url: str) -> Resolution:
        """주소를 판정한다(저장하지 않는다). 피드 주소면 feed, 글 목록 페이지면 page.

        피드 주소를 바꿀 때 쓴다. 피드를 먼저 보고, 피드가 아니면 글 목록 페이지로 본다.
        단, 그 페이지가 피드를 알려 주고 있으면 거부한다(그 피드를 고르도록 안내한다).
        """
        try:
            url = validate_feed_url(raw_url)
        except FeedUrlError as error:
            return Resolution(error=error.message)
        try:
            result = self._fetcher.fetch(url, etag=None, last_modified=None)
        except FetchError as error:
            if error.reason != "NotAFeed":
                return Resolution(error=describe_fetch_failure(error.reason))
            return self._resolve_page(url)
        return Resolution(
            kind=KIND_FEED,
            site_url=result.site_url[:MAX_URL_TEXT_LENGTH],
            title=_title(result, "", url),
        )

    def _resolve_page(self, url: str) -> Resolution:
        try:
            page = self._fetcher.fetch_page(url)
        except FetchError as error:
            return Resolution(error=describe_fetch_failure(error.reason))
        if any(_usable(link.url) for link in find_feed_links(page.text, page.final_url)):
            return Resolution(error=PAGE_HAS_FEEDS)
        listing = extract_page_items(page.text, page.final_url)
        if len(listing.items) < MIN_ITEMS:
            return Resolution(error=NO_PAGE_ITEMS)
        return Resolution(
            kind=KIND_PAGE, site_url=site_of(url)[:MAX_URL_TEXT_LENGTH], title=listing.title
        )

    def _read_listing(self, url: str) -> tuple[PageListing | None, str]:
        """글 목록 페이지를 가져와 글을 뽑는다. (목록, 오류 문구). 글이 적으면 오류."""
        try:
            page = self._fetcher.fetch_page(url)
        except FetchError as error:
            return None, describe_fetch_failure(error.reason)
        listing = extract_page_items(page.text, page.final_url)
        if len(listing.items) < MIN_ITEMS:
            return None, NO_PAGE_ITEMS
        return listing, ""

    def _register_page(
        self, url: str, name: str, category_id: int | None, webhook_id: int | None
    ) -> RegistrationResult:
        listing, error_text = self._read_listing(url)
        if listing is None:
            return RegistrationResult(error=error_text)
        final_name = name or listing.title or _host(url)
        try:
            feed_id = self._feeds.add(
                url,
                final_name[:MAX_NAME_LENGTH],
                html_url=site_of(url)[:MAX_URL_TEXT_LENGTH],
                category_id=category_id,
                webhook_id=webhook_id,
                kind=KIND_PAGE,
            )
        except FeedRuleError as error:
            return RegistrationResult(error=error.message)
        except DuplicateFeedError:
            return RegistrationResult(error=ALREADY_SUBSCRIBED)
        return RegistrationResult(feed_id=feed_id, name=final_name)

    def register(
        self,
        raw_url: str,
        *,
        name: str = "",
        category_id: int | None = None,
        webhook_id: int | None = None,
        kind: str = KIND_FEED,
    ) -> RegistrationResult:
        """피드(웹페이지 구독이면 글 목록)를 등록한다. 등록 직전에 다시 가져와서 확인한다."""
        try:
            url = validate_feed_url(raw_url)
        except FeedUrlError as error:
            return RegistrationResult(error=error.message)
        if feed_url_key(url) in self._feeds.existing_url_keys():
            return RegistrationResult(error=ALREADY_SUBSCRIBED)
        name = name.strip()
        if len(name) > MAX_NAME_LENGTH:
            return RegistrationResult(error=f"이름은 {MAX_NAME_LENGTH}자까지")
        if kind == KIND_PAGE:
            return self._register_page(url, name, category_id, webhook_id)
        try:
            result = self._fetcher.fetch(url, etag=None, last_modified=None)
        except FetchError as error:
            return RegistrationResult(error=describe_fetch_failure(error.reason))
        final_name = name or _title(result, "", url)
        try:
            feed_id = self._feeds.add(
                url,
                final_name,
                html_url=result.site_url[:MAX_URL_TEXT_LENGTH],
                category_id=category_id,
                webhook_id=webhook_id,
            )
        except FeedRuleError as error:
            return RegistrationResult(error=error.message)
        except DuplicateFeedError:
            return RegistrationResult(error=ALREADY_SUBSCRIBED)
        return RegistrationResult(feed_id=feed_id, name=final_name)
