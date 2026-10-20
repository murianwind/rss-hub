"""뷰어: 사이드바(RSS, 카테고리, 주제), 글 목록, 글 페이지.

- 사이드바는 RSS, 카테고리, 주제 세 그룹이 같은 레벨이다. RSS 아래에는 등록된 사이트 전체,
  카테고리 아래에는 카테고리별 사이트, 주제 아래에는 주제 이름만 있다.
- 글 본문은 외부 사이트가 준 HTML이라 항상 정제해서 보여 준다(domain/sanitize).
- 번역은 브라우저(Safari)의 페이지 번역에 맡긴다. 글 영역에 lang을 붙여서 번역이 동작하게 한다.
"""

from dataclasses import dataclass

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from rss_hub.domain.language import detect_language
from rss_hub.domain.sanitize import sanitize_html
from rss_hub.domain.text import strip_html
from rss_hub.services.settings import SettingsService
from rss_hub.storage.articles import ArticleRepository
from rss_hub.storage.feeds import FeedRepository
from rss_hub.storage.reader import ReaderRepository
from rss_hub.storage.topics import TopicRepository
from rss_hub.web.articles import is_web_link

SNIPPET_LENGTH = 140
MAX_PAGE = 10_000


@dataclass(frozen=True)
class Scope:
    kind: str  # all, feed, category, topic
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

    def sidebar() -> dict[str, object]:
        listed = sorted(feeds.list_all(), key=lambda f: f.name.lower())
        categories = [
            {"id": c.id, "name": c.name, "feeds": [f for f in listed if f.category_id == c.id]}
            for c in sorted(feeds.list_categories(), key=lambda c: c.name.lower())
        ]
        return {
            "side_feeds": listed,
            "side_categories": categories,
            "side_topics": topics.list_all(),
        }

    def not_found(request: Request, scope: Scope) -> HTMLResponse:
        context = {
            **sidebar(),
            "scope": scope,
            "heading": "찾을 수 없음",
            "page": None,
            "snippets": {},
        }
        return templates.TemplateResponse(request, "reader.html", context, status_code=404)

    def listing(
        request: Request, scope: Scope, heading: str, page_text: str, base_path: str
    ) -> Response:
        page = reader.list_articles(
            feed_id=scope.ident if scope.kind == "feed" else None,
            category_id=scope.ident if scope.kind == "category" else None,
            topic_id=scope.ident if scope.kind == "topic" else None,
            page=_page_number(page_text),
        )
        zone = settings.snapshot().timezone
        context = {
            **sidebar(),
            "scope": scope,
            "heading": heading,
            "page": page,
            "base_path": base_path,
            "times": {
                i.id: i.published_dt.astimezone(zone).strftime("%m-%d %H:%M") for i in page.items
            },
            "snippets": {i.id: _snippet(i.summary) for i in page.items},
        }
        return templates.TemplateResponse(request, "reader.html", context)

    @router.get("/reader", response_class=HTMLResponse)
    def all_articles(request: Request, page: str = "1") -> Response:
        return listing(request, Scope("all"), "전체 글", page, "/reader")

    @router.get("/reader/feed/{feed_id}", response_class=HTMLResponse)
    def feed_articles(request: Request, feed_id: int, page: str = "1") -> Response:
        feed = feeds.get(feed_id)
        if feed is None:
            return not_found(request, Scope("feed", feed_id))
        return listing(request, Scope("feed", feed_id), feed.name, page, f"/reader/feed/{feed_id}")

    @router.get("/reader/category/{category_id}", response_class=HTMLResponse)
    def category_articles(request: Request, category_id: int, page: str = "1") -> Response:
        category = next((c for c in feeds.list_categories() if c.id == category_id), None)
        if category is None:
            return not_found(request, Scope("category", category_id))
        return listing(
            request,
            Scope("category", category_id),
            category.name,
            page,
            f"/reader/category/{category_id}",
        )

    @router.get("/reader/topic/{topic_id}", response_class=HTMLResponse)
    def topic_articles(request: Request, topic_id: int, page: str = "1") -> Response:
        topic = next((t for t in topics.list_all() if t.id == topic_id), None)
        if topic is None:
            return not_found(request, Scope("topic", topic_id))
        return listing(
            request, Scope("topic", topic_id), topic.name, page, f"/reader/topic/{topic_id}"
        )

    @router.get("/a/{article_id}", response_class=HTMLResponse)
    def article_page(request: Request, article_id: int) -> Response:
        article = articles.get(article_id)
        feed = None if article is None else feeds.get(article.feed_id)
        if article is None or feed is None:
            return not_found(request, Scope("all"))
        zone = settings.snapshot().timezone
        plain = strip_html(article.content_html)
        context = {
            **sidebar(),
            "scope": Scope("feed", feed.id),
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
        }
        return templates.TemplateResponse(request, "article.html", context)

    return router


def _snippet(summary: str | None) -> str:
    if not summary:
        return ""
    text = " ".join(summary.split())
    return text if len(text) <= SNIPPET_LENGTH else text[: SNIPPET_LENGTH - 1] + "…"
