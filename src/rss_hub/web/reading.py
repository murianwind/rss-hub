"""읽음과 북마크 동작: 글 하나의 북마크, 읽음 표시, 목록 전체 읽음 표시."""

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse

from rss_hub.storage.articles import ArticleRepository
from rss_hub.storage.reader import ONLY_BOOKMARKS, ReaderRepository
from rss_hub.web.live import sidebar_state
from rss_hub.web.ui import safe_path, with_toast

SCOPE_KINDS = ("all", "feed", "category", "topic", "bookmarks")
MAX_AUTO_READ = 200


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
        unread = form.get("state") == "unread"
        if unread:
            articles.mark_unread(article_id)
        else:
            articles.mark_read(article_id)
        return back(
            form.get("next"), f"/a/{article_id}", "marked_unread" if unread else "marked_read"
        )

    @router.post("/ui/read-state")
    async def read_state_json(request: Request) -> Response:
        """목록의 읽음 버튼: 화면을 다시 불러오지 않고 상태만 바꾸고 사이드바 개수를 돌려준다."""
        form = await request.form()
        raw, state = str(form.get("id", "")), str(form.get("state", ""))
        if not (raw.isascii() and raw.isdigit()) or state not in ("read", "unread"):
            return JSONResponse({"ok": False}, status_code=400)
        if articles.get(int(raw)) is None:
            return JSONResponse({"ok": False}, status_code=404)
        if state == "unread":
            articles.mark_unread(int(raw))
        else:
            articles.mark_read(int(raw))
        return JSONResponse(
            {"ok": True, "read": state == "read", "state": sidebar_state(reader.sidebar())}
        )

    @router.post("/ui/auto-read")
    async def auto_read(request: Request) -> Response:
        """스크롤로 지나간 글을 읽음 처리한다. 읽지 않음으로 고정한 글은 건드리지 않는다."""
        form = await request.form()
        parts = [p.strip() for p in str(form.get("ids", "")).split(",") if p.strip()]
        if (
            not parts
            or len(parts) > MAX_AUTO_READ
            or not all(p.isascii() and p.isdigit() for p in parts)
        ):
            return JSONResponse({"ok": False}, status_code=400)
        marked = articles.auto_mark_read([int(p) for p in parts])
        return JSONResponse(
            {"ok": True, "marked": marked, "state": sidebar_state(reader.sidebar())}
        )

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
