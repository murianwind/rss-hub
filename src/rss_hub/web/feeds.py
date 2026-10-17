"""피드 화면: 등록된 피드 목록과 피드별 카테고리, 웹훅 지정.

카테고리에 속한 피드는 웹훅을 지정할 수 없고, 웹훅이 지정된 피드는 카테고리에 넣을 수 없다.
카테고리에서 빠지면 피드 웹훅을 다시 지정할 수 있다.
"""

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from rss_hub.services.settings import SettingsService
from rss_hub.storage.feeds import FeedRepository, FeedRuleError


def _id_or_none(value: object) -> int | None:
    text = str(value or "").strip()
    return int(text) if text.isdigit() else None


def build_feed_router(
    feeds: FeedRepository, settings: SettingsService, templates: Jinja2Templates
) -> APIRouter:
    router = APIRouter()

    def page(
        request: Request, *, error: str = "", notice: str = "", status_code: int = 200
    ) -> HTMLResponse:
        categories = feeds.list_categories()
        context = {
            "feeds": sorted(feeds.list_all(), key=lambda f: f.name.lower()),
            "categories": categories,
            "category_names": {c.id: c.name for c in categories},
            "webhooks": settings.list_webhooks(),
            "error": error,
            "notice": notice,
        }
        return templates.TemplateResponse(request, "feeds.html", context, status_code=status_code)

    @router.get("/feeds", response_class=HTMLResponse)
    def feed_page(request: Request, saved: str = "") -> HTMLResponse:
        return page(request, notice="저장했습니다." if saved else "")

    @router.post("/feeds/{feed_id}/category", response_class=HTMLResponse)
    async def set_category(request: Request, feed_id: int) -> Response:
        form = await request.form()
        try:
            found = feeds.set_feed_category(feed_id, _id_or_none(form.get("category_id")))
        except FeedRuleError as error:
            return page(request, error=error.message, status_code=400)
        if not found:
            return page(request, error="피드를 찾을 수 없음", status_code=404)
        return RedirectResponse("/feeds?saved=1", status_code=303)

    @router.post("/feeds/{feed_id}/webhook", response_class=HTMLResponse)
    async def set_webhook(request: Request, feed_id: int) -> Response:
        form = await request.form()
        try:
            found = feeds.set_feed_webhook(feed_id, _id_or_none(form.get("webhook_id")))
        except FeedRuleError as error:
            return page(request, error=error.message, status_code=400)
        if not found:
            return page(request, error="피드를 찾을 수 없음", status_code=404)
        return RedirectResponse("/feeds?saved=1", status_code=303)

    return router
