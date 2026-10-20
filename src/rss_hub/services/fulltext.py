"""글의 전문: 글을 처음 열 때 원문 페이지를 가져와 본문을 뽑아 저장한다.

- 가져오기는 기존 수집기의 연결 검사(사설망 차단, 크기 제한, 시간 제한)를 그대로 거친다.
- 성공하면 저장해 두고 다시 가져오지 않는다. 실패해도 기록해서 같은 글을 열 때마다 반복하지 않는다.
  사용자가 "다시 가져오기"를 누르면(force) 다시 시도한다.
- 실패하거나 본문을 찾지 못하면 호출한 쪽이 RSS 본문을 대신 보여 준다.
"""

from dataclasses import dataclass

from rss_hub.domain.discovery import describe_fetch_failure
from rss_hub.domain.feed_url import FeedUrlError, validate_feed_url
from rss_hub.domain.fulltext import extract_main_content
from rss_hub.services.ports import FetchError, PageFetcher
from rss_hub.storage.articles import MAX_FULL_TEXT_CHARS, Article, ArticleRepository

NO_CONTENT = "NoContent"  # 페이지는 받았지만 본문을 찾지 못했다


@dataclass(frozen=True)
class FullText:
    html: str | None  # 정제된 전문. 없으면 None(RSS 본문을 보여 준다)
    state: str  # ok, failed, skipped
    reason: str = ""  # 화면에 보여 줄 수 있는 실패 이유


class FullTextService:
    def __init__(self, *, articles: ArticleRepository, pages: PageFetcher) -> None:
        self._articles = articles
        self._pages = pages

    def ensure(self, article: Article, *, force: bool = False) -> FullText:
        """저장된 전문이 있으면 그것을, 없으면 처음 한 번 가져온다(force면 다시 가져온다)."""
        if not force:
            if article.full_status == "ok" and article.full_html:
                return FullText(article.full_html, "ok")
            if article.full_status == "failed":
                return FullText(None, "failed", _describe(article.full_error or ""))
        return self._fetch(article)

    def _fetch(self, article: Article) -> FullText:
        try:
            link = validate_feed_url(article.link)  # http(s)만, 사설망 주소는 여기서 거른다
        except FeedUrlError:
            return FullText(None, "skipped", "")  # 원문 주소가 없거나 쓸 수 없으면 기록하지 않는다
        try:
            page = self._pages.fetch_page(link)
        except FetchError as error:
            return self._failed(article, error.reason)
        html = extract_main_content(page.text, page.final_url)
        if html is None:
            return self._failed(article, NO_CONTENT)
        self._articles.save_full_text(article.id, html[:MAX_FULL_TEXT_CHARS])
        return FullText(html[:MAX_FULL_TEXT_CHARS], "ok")

    def _failed(self, article: Article, reason: str) -> FullText:
        self._articles.save_full_text_failure(article.id, reason)
        return FullText(None, "failed", _describe(reason))


def _describe(reason: str) -> str:
    if reason == NO_CONTENT:
        return "원문 페이지에서 본문을 찾지 못했습니다"
    return describe_fetch_failure(reason)
