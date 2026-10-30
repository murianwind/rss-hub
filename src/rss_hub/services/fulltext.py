"""글의 전문: 글을 처음 열 때 원문 페이지를 가져와 본문을 뽑아 저장한다.

- 가져오기는 기존 수집기의 연결 검사(사설망 차단, 크기 제한, 시간 제한)를 그대로 거친다.
- 성공하면 저장해 두고 다시 가져오지 않는다. 실패해도 기록해서 같은 글을 열 때마다 반복하지 않는다.
  사용자가 "다시 가져오기"를 누르면(force) 다시 시도한다.
- 실패하거나 본문을 찾지 못하면 호출한 쪽이 RSS 본문을 대신 보여 준다.
"""

from dataclasses import dataclass
from urllib.parse import urlsplit

from rss_hub.domain.discovery import describe_fetch_failure
from rss_hub.domain.error_log import KIND_FULLTEXT
from rss_hub.domain.feed_url import FeedUrlError, validate_feed_url
from rss_hub.domain.fulltext import (
    COVERAGE_COMPLETE,
    COVERAGE_MIN,
    extract_article,
    find_page_redirect,
    page_title,
    reference_is_complete,
)
from rss_hub.domain.page_urls import reading_url
from rss_hub.domain.text import strip_html
from rss_hub.services.activity_log import NO_ACTIVITY, ActivityRecorder
from rss_hub.services.error_log import NO_ERRORS, ErrorRecorder
from rss_hub.services.ports import FetchError, PageFetcher, PageResult
from rss_hub.storage.articles import MAX_FULL_TEXT_CHARS, Article, ArticleRepository

MISMATCH = "Mismatch"  # 뽑은 글이 RSS 전문과 맞지 않는다(엉뚱한 덩어리를 뽑았거나 다른 글이다)
NO_CONTENT = "NoContent"  # 페이지는 받았지만 본문을 찾지 못했다
SHORTER_THAN_RSS = "ShorterThanRss"  # 페이지 본문이 RSS 본문보다 짧다(유료 벽으로 잘린 페이지 등)
MIN_RSS_TO_COMPARE = 300  # RSS 본문이 이만큼 되어야 "이미 전문"으로 보고 비교한다
SHORTER_RATIO = 0.8  # 페이지 본문이 RSS 본문의 이 비율보다 짧으면 RSS 본문을 쓴다
MAX_SHELL_HOPS = 2  # 스크립트로만 다른 주소로 보내는 껍데기 페이지를 따라가는 최대 횟수


@dataclass(frozen=True)
class FullText:
    html: str | None  # 정제된 전문. 없으면 None(RSS 본문을 보여 준다)
    state: str  # ok, failed, skipped
    reason: str = ""  # 화면에 보여 줄 수 있는 실패 이유


class FullTextService:
    def __init__(
        self,
        *,
        articles: ArticleRepository,
        pages: PageFetcher,
        errors: ErrorRecorder = NO_ERRORS,
        activity: ActivityRecorder = NO_ACTIVITY,
    ) -> None:
        self._articles = articles
        self._pages = pages
        self._errors = errors
        self._activity = activity

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
            page, hops = self._load_page(reading_url(link))
        except FetchError as error:
            return self._failed(article, error.reason)
        extraction = extract_article(page.text, page.final_url, article.title, article.content_html)
        if extraction is None:
            host = urlsplit(page.final_url).hostname or ""
            # 왜 못 찾았는지 사람이 가늠할 수 있게 받은 페이지의 크기, 주소, 따라간 횟수를 남긴다
            title = page_title(page.text).replace("|", "/")
            return self._failed(article, f"{NO_CONTENT}|{len(page.text)}|{host}|{hops}|{title}")
        html = extraction.html
        if (
            extraction.coverage is not None
            and extraction.coverage < COVERAGE_MIN
            and reference_is_complete(article.content_html)
        ):
            return self._failed(article, MISMATCH)  # 더 넓게 뽑아도 RSS 전문과 맞지 않는다
        rss_length = len(strip_html(article.content_html))
        found_all = extraction.coverage is not None and extraction.coverage >= COVERAGE_COMPLETE
        # RSS 끝의 자동 문구는 페이지에 없어 짧아 보일 수 있다: RSS 내용이 다 있으면 건너뛴다
        if (
            not found_all
            and rss_length >= MIN_RSS_TO_COMPARE
            and len(strip_html(html)) < SHORTER_RATIO * rss_length
        ):
            return self._failed(article, SHORTER_THAN_RSS)  # RSS가 이미 더 완전한 전문이다
        self._articles.save_full_text(article.id, html[:MAX_FULL_TEXT_CHARS])
        self._activity.done(KIND_FULLTEXT, article.title, "원문 전문을 가져옴", article.link)
        return FullText(html[:MAX_FULL_TEXT_CHARS], "ok")

    def _load_page(self, link: str) -> tuple[PageResult, int]:
        """(페이지, 따라간 횟수). 스크립트로만 다른 주소로 보내는 짧은 껍데기면 그 주소를 따라간다.

        따라가는 주소도 같은 주소 검사(사설망 차단)를 거치고, 횟수는 MAX_SHELL_HOPS까지다."""
        page = self._pages.fetch_page(link)
        hops = 0
        for _ in range(MAX_SHELL_HOPS):
            target = find_page_redirect(page.text, page.final_url)
            if target is None:
                break
            try:
                page = self._pages.fetch_page(validate_feed_url(target))
            except FeedUrlError:
                break
            hops += 1
        return page, hops

    def _failed(self, article: Article, reason: str) -> FullText:
        self._articles.save_full_text_failure(article.id, reason)
        message = _describe(reason)
        self._errors.record(KIND_FULLTEXT, article.title, message, f"{reason} · {article.link}")
        self._activity.failed(KIND_FULLTEXT, article.title, message, f"{reason} · {article.link}")
        return FullText(None, "failed", message)


def _no_content_detail(reason: str) -> str:
    """ "NoContent|글자 수|주소|따라간 횟수|제목"에서 괄호 설명을 만든다(옛 기록은 있는 만큼)."""
    parts = reason.split("|", 4)
    if len(parts) < 4 or not parts[1].isdigit() or not parts[3].isdigit():
        return ""
    title = f', 제목 "{parts[4]}"' if len(parts) == 5 and parts[4] else ""
    return f"(받은 페이지 {int(parts[1]):,}자, {parts[2]}, 다른 주소로 {parts[3]}번 이동{title})"


def _describe(reason: str) -> str:
    if reason.split("|")[0] == NO_CONTENT:
        return "원문 페이지에서 본문을 찾지 못했습니다" + _no_content_detail(reason)
    if reason == MISMATCH:
        return "원문 페이지에서 뽑은 글이 RSS 내용과 맞지 않습니다"
    if reason == SHORTER_THAN_RSS:
        return "원문 페이지의 본문이 RSS 본문보다 짧습니다(유료 구독이 필요한 글일 수 있습니다)"
    return describe_fetch_failure(reason)
