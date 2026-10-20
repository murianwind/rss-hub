"""뷰어: 글 목록(전체, 사이트, 카테고리, 주제, 북마크)과 글 페이지.

- 사이드바는 모든 화면 공통이라 web/ui.py의 컨텍스트가 넣어 준다.
  이 라우터는 현재 위치(scope)만 알린다.
- 글 본문은 외부 사이트가 준 HTML이라 항상 정제해서 보여 준다(domain/sanitize).
- 번역은 브라우저(Safari)의 페이지 번역에 맡긴다. 글 영역에 lang을 붙여서 번역이 동작하게 한다.
- 글 페이지를 열면 읽음으로 표시한다(Discord 알림의 링크로 열어도 같다).
"""

from dataclasses import dataclass
from urllib.parse import quote

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from rss_hub.domain.language import detect_language
from rss_hub.domain.sanitize import sanitize_html
from rss_hub.domain.text import strip_html
from rss_hub.services.settings import SettingsService
from rss_hub.storage.articles import ArticleRepository
from rss_hub.storage.feeds import FeedRepository
from rss_hub.storage.reader import ONLY_BOOKMARKS, ONLY_UNREAD, ReaderRepository
from rss_hub.storage.topics import TopicRepository
from rss_hub.web.articles import is_web_link
from rss_hub.web.ui import list_url, safe_path

SNIPPET_LENGTH = 140
MAX_PAGE = 10_000
HEADING_ICONS = {
    "all": "list",
    "feed": "rss",
    "category": "folder",
    "topic": "hash",
    "bookmarks": "bookmark",
}
FILTERS = (ONLY_UNREAD, ONLY_BOOKMARKS)


@dataclass(frozen=True)
class Scope:
    kind: str  # all, feed, category, topic, bookmarks
    ident: int | None = None


def _page_number(raw: str) -> int:
    text = raw.strip()
    return min(int(text), MAX_PAGE) if text.isascii() and text.isdigit() and int(text) >= 1 else 1


def build_reader_router(
    *,
    reader: ReaderRepository,
    feeds: FeedRepository,
    topics: TopicRepository,
    articles: ArticleRepository,
    settings: SettingsService,
    templates: Jinja2Templates,
) -> APIRouter:
    router = APIRouter()

    def not_found(request: Request, scope: Scope) -> HTMLResponse:
        request.state.scope = scope
        context = {
            "scope": scope,
            "heading": "찾을 수 없음",
            "heading_icon": HEADING_ICONS["all"],
            "page": None,
            "snippets": {},
            "q": "",
            "only": "",
            "back": "/reader",
            "base_path": "/reader",
        }
        return templates.TemplateResponse(request, "reader.html", context, status_code=404)

    def listing(
        request: Request,
        scope: Scope,
        heading: str,
        base_path: str,
        *,
        page_text: str,
        q: str,
        only: str,
    ) -> Response:
        request.state.scope = scope
        query = q.strip()[:100]
        chosen = ONLY_BOOKMARKS if scope.kind == "bookmarks" else (only if only in FILTERS else "")
        number = _page_number(page_text)
        page = reader.list_articles(
            feed_id=scope.ident if scope.kind == "feed" else None,
            category_id=scope.ident if scope.kind == "category" else None,
            topic_id=scope.ident if scope.kind == "topic" else None,
            query=query,
            only=chosen,
            page=number,
        )
        shown_only = "" if scope.kind == "bookmarks" else chosen
        zone = settings.snapshot().timezone
        context = {
            "scope": scope,
            "heading": heading,
            "heading_icon": HEADING_ICONS[scope.kind],
            "page": page,
            "base_path": base_path,
            "q": query,
            "only": shown_only,
            "back": list_url(base_path, page=page.page, query=query, only=shown_only),
            "prev_url": list_url(base_path, page=page.page - 1, query=query, only=shown_only),
            "next_url": list_url(base_path, page=page.page + 1, query=query, only=shown_only),
            "times": {
                i.id: i.published_dt.astimezone(zone).strftime("%Y-%m-%d %H:%M") for i in page.items
            },
            "snippets": {i.id: _snippet(i.summary) for i in page.items},
        }
        return templates.TemplateResponse(request, "reader.html", context)

    @router.get("/reader", response_class=HTMLResponse)
    def all_articles(request: Request, page: str = "1", q: str = "", only: str = "") -> Response:
        return listing(request, Scope("all"), "전체 글", "/reader", page_text=page, q=q, only=only)

    @router.get("/reader/bookmarks", response_class=HTMLResponse)
    def bookmarked_articles(request: Request, page: str = "1", q: str = "") -> Response:
        return listing(
            request, Scope("bookmarks"), "북마크", "/reader/bookmarks", page_text=page, q=q, only=""
        )

    @router.get("/reader/feed/{feed_id}", response_class=HTMLResponse)
    def feed_articles(
        request: Request, feed_id: int, page: str = "1", q: str = "", only: str = ""
    ) -> Response:
        feed = feeds.get(feed_id)
        if feed is None:
            return not_found(request, Scope("feed", feed_id))
        return listing(
            request,
            Scope("feed", feed_id),
            feed.name,
            f"/reader/feed/{feed_id}",
            page_text=page,
            q=q,
            only=only,
        )

    @router.get("/reader/category/{category_id}", response_class=HTMLResponse)
    def category_articles(
        request: Request, category_id: int, page: str = "1", q: str = "", only: str = ""
    ) -> Response:
        category = next((c for c in feeds.list_categories() if c.id == category_id), None)
        if category is None:
            return not_found(request, Scope("category", category_id))
        return listing(
            request,
            Scope("category", category_id),
            category.name,
            f"/reader/category/{category_id}",
            page_text=page,
            q=q,
            only=only,
        )

    @router.get("/reader/topic/{topic_id}", response_class=HTMLResponse)
    def topic_articles(
        request: Request, topic_id: int, page: str = "1", q: str = "", only: str = ""
    ) -> Response:
        topic = next((t for t in topics.list_all() if t.id == topic_id), None)
        if topic is None:
            return not_found(request, Scope("topic", topic_id))
        return listing(
            request,
            Scope("topic", topic_id),
            topic.name,
            f"/reader/topic/{topic_id}",
            page_text=page,
            q=q,
            only=only,
        )

    @router.get("/a/{article_id}", response_class=HTMLResponse)
    def article_page(request: Request, article_id: int, back: str = "") -> Response:
        article = articles.get(article_id)
        feed = None if article is None else feeds.get(article.feed_id)
        if article is None or feed is None:
            return not_found(request, Scope("all"))
        articles.mark_read(article.id)  # 처음 열 때 읽음으로 표시한다(이미 읽었으면 그대로)
        request.state.scope = Scope("feed", feed.id)
        zone = settings.snapshot().timezone
        plain = strip_html(article.content_html)
        checked_back = safe_path(back, "")  # 검증을 통과한 것만 다시 주소에 싣는다
        here = f"/a/{article.id}" + (
            f"?back={quote(checked_back, safe='')}" if checked_back else ""
        )
        context = {
            "article": article,
            "feed": feed,
            "title": article.title_ko or article.title,
            "show_original_title": bool(article.title_ko and article.title_ko != article.title),
            "published": article.published_dt.astimezone(zone).strftime("%Y-%m-%d %H:%M"),
            "topic_matches": reader.topics_of(article.id),
            "memberships": {m.topic_id: m for m in topics.memberships(article.id)},
            "enabled_topics": topics.list_enabled(),
            "body": sanitize_html(article.content_html, article.link),
            "lang": detect_language(f"{article.title} {plain}"),
            "has_original": is_web_link(article.link),
            "back": checked_back or f"/reader/feed/{feed.id}",
            "here": here,
            "bookmarked": article.bookmarked_at is not None,
        }
        return templates.TemplateResponse(request, "article.html", context)

    return router


def _snippet(summary: str | None) -> str:
    if not summary:
        return ""
    text = " ".join(summary.split())
    return text if len(text) <= SNIPPET_LENGTH else text[: SNIPPET_LENGTH - 1] + "…"
