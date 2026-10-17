"""카테고리 화면: 목록, 추가, 카테고리별 웹훅 지정."""

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from rss_hub.domain.categories import CategoryInputError, validate_category_name
from rss_hub.services.settings import SettingsService
from rss_hub.storage.feeds import FeedRepository


def build_category_router(
    feeds: FeedRepository, settings: SettingsService, templates: Jinja2Templates
) -> APIRouter:
    router = APIRouter()

    def page(
        request: Request, *, error: str = "", notice: str = "", status_code: int = 200
    ) -> HTMLResponse:
        context = {
            "categories": feeds.list_categories(),
            "webhooks": settings.list_webhooks(),
            "error": error,
            "notice": notice,
        }
        return templates.TemplateResponse(
            request, "categories.html", context, status_code=status_code
        )

    @router.get("/categories", response_class=HTMLResponse)
    def category_page(request: Request, saved: str = "") -> HTMLResponse:
        return page(request, notice="저장했습니다." if saved else "")

    @router.post("/categories/add", response_class=HTMLResponse)
    async def add_category(request: Request) -> Response:
        form = await request.form()
        try:
            name = validate_category_name(str(form.get("name", "")))
        except CategoryInputError as error:
            return page(request, error=error.message, status_code=400)
        _, created = feeds.get_or_create_category(name)
        if not created:
            return page(request, error="같은 이름의 카테고리가 이미 있음", status_code=400)
        return RedirectResponse("/categories?saved=1", status_code=303)

    @router.post("/categories/{category_id}/webhook", response_class=HTMLResponse)
    async def set_webhook(request: Request, category_id: int) -> Response:
        form = await request.form()
        text = str(form.get("webhook_id", "")).strip()
        webhook_id = int(text) if text.isdigit() else None
        if webhook_id is not None and webhook_id not in {w.id for w in settings.list_webhooks()}:
            return page(request, error="웹훅을 찾을 수 없음", status_code=400)
        if not feeds.set_category_webhook(category_id, webhook_id):
            return page(request, error="카테고리를 찾을 수 없음", status_code=404)
        return RedirectResponse("/categories?saved=1", status_code=303)

    return router
