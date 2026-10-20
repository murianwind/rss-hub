"""드래그로 바꾼 순서와 피드의 카테고리 이동을 받는다(스크립트가 보낸다)."""

from fastapi import APIRouter, Request, Response
from fastapi.responses import PlainTextResponse

from rss_hub.storage.feeds import FeedRepository, FeedRuleError
from rss_hub.storage.ordering import OrderRepository


def _ids(raw: object) -> list[int]:
    parts = [part.strip() for part in str(raw or "").split(",") if part.strip()]
    return [int(part) for part in parts] if all(p.isascii() and p.isdigit() for p in parts) else []


def build_ordering_router(*, orders: OrderRepository, feeds: FeedRepository) -> APIRouter:
    router = APIRouter()

    @router.post("/ui/reorder")
    async def reorder(request: Request) -> Response:
        form = await request.form()
        if not orders.set_order(str(form.get("kind", "")), _ids(form.get("ids"))):
            return PlainTextResponse("순서를 저장하지 못했습니다", status_code=400)
        return PlainTextResponse("ok")

    @router.post("/ui/move-feed")
    async def move_feed(request: Request) -> Response:
        form = await request.form()
        feed_raw, category_raw = str(form.get("feed_id", "")), str(form.get("category_id", ""))
        if not feed_raw.isascii() or not feed_raw.isdigit():
            return PlainTextResponse("피드를 찾을 수 없음", status_code=400)
        category = int(category_raw) if category_raw.isascii() and category_raw.isdigit() else None
        try:
            found = feeds.set_feed_category(int(feed_raw), category)  # 기존 규칙을 그대로 따른다
        except FeedRuleError as error:
            return PlainTextResponse(error.message, status_code=400)
        return (
            PlainTextResponse("ok")
            if found
            else PlainTextResponse("피드를 찾을 수 없음", status_code=404)
        )

    return router
