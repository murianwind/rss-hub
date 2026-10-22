"""웹페이지 구독의 수집원: 글 목록 페이지를 가져와 일반 피드와 같은 모양(FetchResult)으로 바꾼다.

- 목록에서 글을 찾지 못하면(사이트 구조가 바뀐 경우 등) NO_ITEMS로 실패한다. 그러면 피드 상태 점이
  빨갛게 바뀌므로, 주소를 다시 확인해 고치면 된다.
- 목록의 날짜가 있으면 그 날짜를(날짜만 아는 값), 없으면 가져온 시각을 임시 발행 시각으로 쓴다
  (목록 순서를 지킨다). 이때 항목에 published_kind를 적어서 수집 서비스가 글 페이지에서 발행일을
  더 찾아볼지 정한다.
- 새 글의 본문과 발행일은 글 페이지에서 따로 뽑는다(read_article_details). 요약은 본문이 있어야
  잘 나온다.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from urllib.parse import urlsplit

from rss_hub.domain.fulltext import extract_main_content
from rss_hub.domain.page_date import extract_published_date
from rss_hub.domain.page_feed import PageItem, extract_page_items
from rss_hub.services.clock import Clock
from rss_hub.services.ports import FetchError, FetchResult, PageFetcher
from rss_hub.storage.articles import PUBLISHED_DATE, PUBLISHED_UNKNOWN

NO_ITEMS = "NoItems"
MAX_ARTICLE_CHARS = 60_000  # 요약에 쓸 본문의 최대 글자 수(HTML)


@dataclass(frozen=True)
class ArticleDetails:
    """글 페이지에서 읽은 본문(정제된 HTML)과 발행일. 못 읽은 것은 빈 글자와 None."""

    content: str = ""
    published: date | None = None


def site_of(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}/" if parts.scheme and parts.netloc else ""


class PageFeedSource:
    def __init__(self, *, pages: PageFetcher, clock: Clock) -> None:
        self._pages = pages
        self._clock = clock

    def fetch(self, url: str) -> FetchResult:
        """목록 페이지를 가져와 글 항목들로 바꾼다. 글이 없으면 FetchError(NO_ITEMS)."""
        page = self._pages.fetch_page(url)
        listing = extract_page_items(page.text, page.final_url)
        if not listing.items:
            raise FetchError(NO_ITEMS)
        now = self._clock.now()
        entries = tuple(self._entry(item, index, now) for index, item in enumerate(listing.items))
        return FetchResult(
            200, entries, None, None, title=listing.title, site_url=site_of(page.final_url)
        )

    def read_article_details(self, url: str, tz: tzinfo) -> ArticleDetails:
        """글 페이지의 본문과 발행일. 가져오지 못하면 비어 있다(글은 제목만으로 저장된다)."""
        try:
            page = self._pages.fetch_page(url)
        except Exception:  # 글 페이지를 못 가져와도 글 저장은 계속한다
            return ArticleDetails()
        html = extract_main_content(page.text, page.final_url)  # 해석하지 못하면 None
        return ArticleDetails(
            (html or "")[:MAX_ARTICLE_CHARS], extract_published_date(page.text, tz)
        )

    @staticmethod
    def _entry(item: PageItem, index: int, now: datetime) -> dict[str, str]:
        if item.date:
            stamp = f"{item.date}T12:00:00"  # 날짜만 있는 값: 하루 중 어느 때든 같은 날이다
            kind = PUBLISHED_DATE
        else:
            stamp = (now - timedelta(milliseconds=index)).isoformat()  # 목록 순서를 지킨다
            kind = PUBLISHED_UNKNOWN
        return {
            "id": item.url,
            "title": item.title,
            "link": item.url,
            "published": stamp,
            "published_kind": kind,
        }
