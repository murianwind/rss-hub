"""카테고리 화면: 목록, 추가, 카테고리별 웹훅 지정."""

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from rss_hub.domain.categories import CategoryInputError, validate_category_name
from rss_hub.services.settings import SettingsService
from rss_hub.storage.feeds import FeedRepository, FeedRuleError
from rss_hub.web.ui import done, done_after_delete


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
        return done(form, "/categories?saved=1", "saved")

    @router.post("/categories/{category_id}/webhook", response_class=HTMLResponse)
    async def set_webhook(request: Request, category_id: int) -> Response:
        form = await request.form()
        text = str(form.get("webhook_id", "")).strip()
        webhook_id = int(text) if text.isdigit() else None
        if webhook_id is not None and webhook_id not in {w.id for w in settings.list_webhooks()}:
            return page(request, error="웹훅을 찾을 수 없음", status_code=400)
        if not feeds.set_category_webhook(category_id, webhook_id):
            return page(request, error="카테고리를 찾을 수 없음", status_code=404)
        return done(form, "/categories?saved=1", "saved")

    @router.post("/categories/{category_id}/rename", response_class=HTMLResponse)
    async def rename_category(request: Request, category_id: int) -> Response:
        form = await request.form()
        try:
            name = validate_category_name(str(form.get("name", "")))
            found = feeds.rename_category(category_id, name)
        except (CategoryInputError, FeedRuleError) as error:
            return page(request, error=error.message, status_code=400)
        if not found:
            return page(request, error="카테고리를 찾을 수 없음", status_code=404)
        return done(form, "/categories?saved=1", "saved")

    @router.post("/categories/{category_id}/settings", response_class=HTMLResponse)
    async def save_category_settings(request: Request, category_id: int) -> Response:
        """이름과 웹훅을 한 번에 저장한다. 웹훅이 없는 번호면 아무것도 바꾸지 않는다."""
        form = await request.form()
        text = str(form.get("webhook_id", "")).strip()
        webhook_id = int(text) if text.isdigit() else None
        if webhook_id is not None and webhook_id not in {w.id for w in settings.list_webhooks()}:
            return page(request, error="웹훅을 찾을 수 없음", status_code=400)
        try:
            name = validate_category_name(str(form.get("name", "")))
            found = feeds.rename_category(category_id, name)
        except (CategoryInputError, FeedRuleError) as error:
            return page(request, error=error.message, status_code=400)
        if not found:
            return page(request, error="카테고리를 찾을 수 없음", status_code=404)
        feeds.set_category_webhook(category_id, webhook_id)
        return done(form, "/categories?saved=1", "saved")

    @router.post("/categories/{category_id}/delete", response_class=HTMLResponse)
    async def delete_category(request: Request, category_id: int) -> Response:
        form = await request.form()
        if form.get("confirm") != "yes":
            return page(request, error="삭제 확인이 필요합니다", status_code=400)
        if not feeds.delete_category(category_id):
            return page(request, error="카테고리를 찾을 수 없음", status_code=404)
        return done_after_delete(form, "/categories?saved=1", "deleted", "category", category_id)

    return router
