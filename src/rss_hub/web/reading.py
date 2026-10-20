"""읽음과 북마크 동작: 글 하나의 북마크, 읽음 표시, 목록 전체 읽음 표시."""

from fastapi import APIRouter, Request, Response
from fastapi.responses import PlainTextResponse, RedirectResponse

from rss_hub.storage.articles import ArticleRepository
from rss_hub.storage.reader import ONLY_BOOKMARKS, ReaderRepository
from rss_hub.web.ui import safe_path, with_toast

SCOPE_KINDS = ("all", "feed", "category", "topic", "bookmarks")


def build_reading_router(*, articles: ArticleRepository, reader: ReaderRepository) -> APIRouter:
    router = APIRouter()

    def back(next_value: object, default: str, toast: str) -> RedirectResponse:
        return RedirectResponse(with_toast(safe_path(next_value, default), toast), status_code=303)

    @router.post("/a/{article_id}/bookmark")
    async def bookmark(request: Request, article_id: int) -> Response:
        if articles.get(article_id) is None:
            return PlainTextResponse("글을 찾을 수 없습니다", status_code=404)
        form = await request.form()
        on = form.get("on") == "1"
        articles.set_bookmark(article_id, on)
        return back(form.get("next"), f"/a/{article_id}", "bookmarked" if on else "unbookmarked")

    @router.post("/a/{article_id}/read")
    async def read_state(request: Request, article_id: int) -> Response:
        if articles.get(article_id) is None:
            return PlainTextResponse("글을 찾을 수 없습니다", status_code=404)
        form = await request.form()
        if form.get("state") == "unread":
            articles.mark_unread(article_id)
        else:
            articles.mark_read(article_id)
        return back(form.get("next"), f"/a/{article_id}", "marked_unread")

    @router.post("/reader/mark-read")
    async def mark_all_read(request: Request) -> Response:
        form = await request.form()
        kind = str(form.get("kind", "all"))
        ident = str(form.get("ident", ""))
        if kind not in SCOPE_KINDS or (
            kind in ("feed", "category", "topic") and not ident.isdigit()
        ):
            return PlainTextResponse("알 수 없는 목록입니다", status_code=400)
        number = int(ident) if ident.isdigit() else None
        reader.mark_all_read(
            feed_id=number if kind == "feed" else None,
            category_id=number if kind == "category" else None,
            topic_id=number if kind == "topic" else None,
            only=ONLY_BOOKMARKS if kind == "bookmarks" else "",
        )
        return back(form.get("next"), "/reader", "read_all")

    return router
