"""피드 화면: 개별 등록(주소 확인과 자동 탐색), 편집, 삭제, 카테고리와 웹훅 지정, OPML 내보내기.

카테고리에 속한 피드는 웹훅을 지정할 수 없고, 웹훅이 지정된 피드는 카테고리에 넣을 수 없다.
카테고리에서 빠지면 피드 웹훅을 다시 지정할 수 있다.
"""

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from rss_hub.domain.feed_edit import FeedEditError, validate_feed_edit
from rss_hub.domain.feed_url import FeedUrlError, feed_url_key, validate_feed_url
from rss_hub.domain.opml_export import ExportFeed, build_opml
from rss_hub.domain.schedule import FeedRef, build_schedule, describe_cycle, feed_cycles, next_check
from rss_hub.services.clock import Clock
from rss_hub.services.feed_registration import DiscoveryResult, FeedRegistrationService
from rss_hub.services.settings import SettingsService
from rss_hub.storage.feeds import (
    RULE_FEED_WEBHOOK_BLOCKS_CATEGORY,
    DuplicateFeedError,
    FeedRepository,
    FeedRuleError,
)
from rss_hub.storage.overview import OverviewRepository
from rss_hub.web.panels import render_panel
from rss_hub.web.ui import done, safe_return

CONFIRM_MESSAGE = "삭제하려면 확인란을 선택해 주세요"


def _id_or_none(value: object) -> int | None:
    text = str(value or "").strip()
    return int(text) if text.isdigit() else None


STATE_FILTERS = ("ok", "error", "never")


def build_feed_router(
    feeds: FeedRepository,
    settings: SettingsService,
    templates: Jinja2Templates,
    registration: FeedRegistrationService,
    overview: OverviewRepository,
    clock: Clock,
) -> APIRouter:
    router = APIRouter()

    def rows(state: str) -> tuple[list[dict[str, object]], dict[str, int]]:
        """피드 관리 화면의 행들과 상태별 개수. 수집 주기는 스케줄러가 실제로 배정한 값이다."""
        config = settings.snapshot()
        listed = overview.feeds()
        refs = [FeedRef(str(f.id), f.poll_priority) for f in feeds.list_all()]
        activity = feeds.activity_by_key()
        schedule = build_schedule(
            refs, activity, config.collect_interval_minutes, config.slot_batch_size
        )
        cycles = feed_cycles(
            schedule, config.collect_interval_minutes, activity, [str(f.id) for f in listed]
        )
        now = clock.now().astimezone(config.timezone)
        names = {w.id: w.name for w in settings.list_webhooks()}
        counts = {"all": len(listed), "ok": 0, "error": 0, "never": 0}
        out: list[dict[str, object]] = []
        for item in listed:
            counts[item.state] += 1
            if state and item.state != state:
                continue
            cycle = cycles.get(str(item.id))
            following = None if cycle is None else next_check(now, cycle.minutes)
            if item.category_id:
                alert = f"카테고리 '{item.category_name}'의 웹훅을 따름"
            elif item.webhook_id:
                alert = f"개별 웹훅 '{names.get(item.webhook_id, '?')}'"
            else:
                alert = "기본 웹훅"
            out.append(
                {
                    "feed": item,
                    "alert": alert,
                    "cycle": None if cycle is None else describe_cycle(cycle),
                    "minutes": ""
                    if cycle is None
                    else ", ".join(f"{m:02d}분" for m in cycle.minutes),
                    "short": cycle is not None and cycle.checks_per_hour < cycle.wanted,
                    "wanted": 0 if cycle is None else cycle.wanted,
                    "next": "" if following is None else following.strftime("%H:%M"),
                }
            )
        return out, counts

    def page(
        request: Request,
        *,
        error: str = "",
        notice: str = "",
        status_code: int = 200,
        state: str = "",
    ) -> HTMLResponse:
        config = settings.snapshot()
        listed, counts = rows(state if state in STATE_FILTERS else "")
        context = {
            "rows": listed,
            "counts": counts,
            "state": state if state in STATE_FILTERS else "",
            "interval": config.collect_interval_minutes,
            "default_max_entries": config.default_max_entries,
            "error": error,
            "notice": notice,
        }
        return templates.TemplateResponse(request, "feeds.html", context, status_code=status_code)

    def add_panel(
        request: Request,
        *,
        url: str = "",
        error: str = "",
        discovery: DiscoveryResult | None = None,
        status_code: int = 200,
        next_path: str = "/feeds",
    ) -> Response:
        panel: dict[str, object] = {
            "mode": "add",
            "kind": "feed",
            "url": url,
            "error": error,
            "discovery": discovery,
            "categories": feeds.list_categories(),
        }
        return render_panel(
            templates,
            request,
            panel,
            settings.list_webhooks(),
            status_code=status_code,
            next_path=next_path,
        )

    @router.get("/feeds", response_class=HTMLResponse)
    def feed_page(
        request: Request, saved: str = "", added: str = "", deleted: str = "", state: str = ""
    ) -> HTMLResponse:
        notice = (
            "피드를 추가했습니다. 첫 점검에서 지금 있는 글은 기록만 하고, 새 글부터 알림이 갑니다."
            if added
            else "삭제했습니다."
            if deleted
            else "저장했습니다."
            if saved
            else ""
        )
        return page(request, notice=notice, state=state)

    # ---------- 개별 등록 ----------

    @router.post("/feeds/discover", response_class=HTMLResponse)
    async def discover(request: Request) -> Response:
        form = await request.form()
        url = str(form.get("url", ""))
        result = registration.discover(url)
        return add_panel(
            request,
            url=url,
            error=result.error,
            discovery=result,
            status_code=400 if result.error else 200,
            next_path=safe_return(form.get("next"), "/feeds"),
        )

    @router.post("/feeds/register", response_class=HTMLResponse)
    async def register(request: Request) -> Response:
        form = await request.form()
        url = str(form.get("url", ""))
        result = registration.register(
            url,
            name=str(form.get("name", "")),
            category_id=_id_or_none(form.get("category_id")),
            webhook_id=_id_or_none(form.get("webhook_id")),
        )
        if result.error:
            return add_panel(
                request,
                url=url,
                error=result.error,
                status_code=400,
                next_path=safe_return(form.get("next"), "/feeds"),
            )
        return done(form, "/feeds?added=1", "added")

    # ---------- 설정 한 번에 저장(패널) ----------

    @router.post("/feeds/{feed_id}/settings", response_class=HTMLResponse)
    async def save_settings(request: Request, feed_id: int) -> Response:
        """이름, 주소, 이모지, 최대 항목 수, 카테고리, 웹훅을 한 번에 저장한다.

        바꾸기 전에 입력과 규칙을 모두 확인해서, 규칙에 어긋나면 아무것도 바꾸지 않는다.
        """
        form = await request.form()
        feed = feeds.get(feed_id)
        if feed is None:
            return page(request, error="피드를 찾을 수 없음", status_code=404)
        category_id = _id_or_none(form.get("category_id"))
        webhook_id = _id_or_none(form.get("webhook_id"))
        try:
            values = validate_feed_edit(
                str(form.get("name", "")),
                str(form.get("emoji", "")),
                feed.poll_priority,
                str(form.get("max_entries", "")),
            )
            url = validate_feed_url(str(form.get("url", "")))
        except (FeedEditError, FeedUrlError) as error:
            return page(request, error=error.message, status_code=400)
        if category_id is not None and webhook_id is not None:
            return page(request, error=RULE_FEED_WEBHOOK_BLOCKS_CATEGORY, status_code=400)
        url_changed = feed_url_key(url) != feed_url_key(feed.url)
        if url_changed and feed_url_key(url) in feeds.existing_url_keys():
            return page(request, error="이미 구독 중인 피드입니다", status_code=400)
        try:
            feeds.update_feed(feed_id, values)
            # 규칙에 걸리지 않도록 비우는 쪽을 먼저 처리한다
            if category_id is None:
                feeds.set_feed_category(feed_id, None)
                feeds.set_feed_webhook(feed_id, webhook_id)
            else:
                feeds.set_feed_webhook(feed_id, None)
                feeds.set_feed_category(feed_id, category_id)
            if url_changed:
                feeds.change_feed_url(feed_id, url)
        except (FeedRuleError, DuplicateFeedError) as error:
            message = (
                error.message if isinstance(error, FeedRuleError) else "이미 구독 중인 피드입니다"
            )
            return page(request, error=message, status_code=400)
        return done(form, "/feeds?saved=1", "saved")

    # ---------- 편집, 삭제 ----------

    @router.post("/feeds/{feed_id}/edit", response_class=HTMLResponse)
    async def edit(request: Request, feed_id: int) -> Response:
        form = await request.form()
        try:
            values = validate_feed_edit(
                str(form.get("name", "")),
                str(form.get("emoji", "")),
                str(form.get("priority", "")),
                str(form.get("max_entries", "")),
            )
        except FeedEditError as error:
            return page(request, error=error.message, status_code=400)
        if not feeds.update_feed(feed_id, values):
            return page(request, error="피드를 찾을 수 없음", status_code=404)
        return done(form, "/feeds?saved=1", "saved")

    @router.post("/feeds/{feed_id}/delete", response_class=HTMLResponse)
    async def delete(request: Request, feed_id: int) -> Response:
        form = await request.form()
        if form.get("confirm") != "yes":
            return page(request, error=CONFIRM_MESSAGE, status_code=400)
        if not feeds.delete(feed_id):
            return page(request, error="피드를 찾을 수 없음", status_code=404)
        return done(form, "/feeds?deleted=1", "deleted")

    # ---------- 카테고리, 웹훅 ----------

    @router.post("/feeds/{feed_id}/category", response_class=HTMLResponse)
    async def set_category(request: Request, feed_id: int) -> Response:
        form = await request.form()
        try:
            found = feeds.set_feed_category(feed_id, _id_or_none(form.get("category_id")))
        except FeedRuleError as error:
            return page(request, error=error.message, status_code=400)
        if not found:
            return page(request, error="피드를 찾을 수 없음", status_code=404)
        return done(form, "/feeds?saved=1", "saved")

    @router.post("/feeds/{feed_id}/webhook", response_class=HTMLResponse)
    async def set_webhook(request: Request, feed_id: int) -> Response:
        form = await request.form()
        try:
            found = feeds.set_feed_webhook(feed_id, _id_or_none(form.get("webhook_id")))
        except FeedRuleError as error:
            return page(request, error=error.message, status_code=400)
        if not found:
            return page(request, error="피드를 찾을 수 없음", status_code=404)
        return done(form, "/feeds?saved=1", "saved")

    # ---------- 내보내기 ----------

    @router.get("/feeds/export.opml")
    def export_opml() -> Response:
        names = {c.id: c.name for c in feeds.list_categories()}
        items = [
            ExportFeed(
                f.name, f.url, f.html_url, names.get(f.category_id) if f.category_id else None
            )
            for f in sorted(feeds.list_all(), key=lambda f: f.name.lower())
        ]
        return Response(
            build_opml(items),
            media_type="text/x-opml; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="rss-hub-subscriptions.opml"'},
        )

    return router
