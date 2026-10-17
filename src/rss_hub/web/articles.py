"""글 주소(/a/{id}): 디스코드 알림의 링크. 뷰어가 생기기 전(M4)에는 원문으로 보낸다."""

from urllib.parse import urlsplit

from fastapi import APIRouter, Response
from fastapi.responses import PlainTextResponse, RedirectResponse

from rss_hub.storage.articles import ArticleRepository

NOT_FOUND = "글을 찾을 수 없습니다"


def is_web_link(link: str) -> bool:
    """http, https 주소만 이동시킨다(javascript:, file:, data: 주소와 제어 문자는 막는다)."""
    if not link or any(ord(c) < 33 for c in link):
        return False
    parts = urlsplit(link)
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def build_article_router(articles: ArticleRepository) -> APIRouter:
    router = APIRouter()

    @router.get("/a/{article_id}")
    def open_article(article_id: int) -> Response:
        article = articles.get(article_id)
        if article is None or not is_web_link(article.link):
            return PlainTextResponse(NOT_FOUND, status_code=404)
        return RedirectResponse(article.link, status_code=302)

    return router
