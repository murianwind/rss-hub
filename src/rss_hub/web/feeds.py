"""피드 화면: 개별 등록(주소 확인과 자동 탐색), 편집, 삭제, 카테고리와 웹훅 지정, OPML 내보내기.

카테고리에 속한 피드는 웹훅을 지정할 수 없고, 웹훅이 지정된 피드는 카테고리에 넣을 수 없다.
카테고리에서 빠지면 피드 웹훅을 다시 지정할 수 있다.
"""

from datetime import datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit

from fastapi import APIRouter, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from rss_hub.domain.feed_edit import FeedEditError, validate_feed_edit
from rss_hub.domain.feed_url import FeedUrlError, feed_url_key, validate_feed_url
from rss_hub.domain.opml_export import ExportFeed, build_opml
from rss_hub.domain.schedule import (
    FeedCycle,
    FeedRef,
    build_schedule,
    describe_cycle,
    feed_cycles,
    next_check,
)
from rss_hub.services.clock import Clock
from rss_hub.services.feed_registration import DiscoveryResult, FeedRegistrationService
from rss_hub.services.settings import SettingsService
from rss_hub.storage.feeds import (
    KIND_FEED,
    KIND_PAGE,
    RULE_FEED_WEBHOOK_BLOCKS_CATEGORY,
    DuplicateFeedError,
    FeedRepository,
    FeedRuleError,
)
from rss_hub.storage.overview import OverviewRepository
from rss_hub.web.forms import id_or_none
from rss_hub.web.panels import render_panel
from rss_hub.web.ui import done, done_after_delete, safe_return

CONFIRM_MESSAGE = "삭제 확인이 필요합니다"


STATE_FILTERS = ("ok", "error", "never")
CYCLE_FILTERS = (("1", "시간당 1회"), ("2", "시간당 2회"), ("3", "시간당 3회"))  # 3은 3회 이상
_DAY = timedelta(days=1)
# 마지막 게시 필터는 서로 겹치지 않는 구간이다: (키, 이름, 이 길이 초과, 이 길이 이하)
LAST_FILTERS = (
    ("day", "하루 이내", timedelta(0), _DAY),
    ("week", "1주일 이내(하루 초과)", _DAY, timedelta(days=7)),
    ("month", "1달 이내(1주일 초과)", timedelta(days=7), timedelta(days=30)),
    ("year", "1년 이내(1달 초과)", timedelta(days=30), timedelta(days=365)),
)
LAST_OLDER = "older"  # 1년 넘게 게시가 없거나 게시 기록이 없는 피드


def _carried(next_value: str) -> dict[str, str]:
    """돌아갈 주소(next)에 담긴 검색과 필터 조건. 오류로 화면을 다시 그릴 때 이어받는다."""
    parts = urlsplit(next_value)
    ours = parts.path == "/feeds" and not parts.scheme and not parts.netloc
    values = dict(parse_qsl(parts.query)) if ours else {}
    return {key: values.get(key, "") for key in ("q", "state", "cycle", "last")}


def _cycle_matches(cycle: FeedCycle | None, wanted: str) -> bool:
    """수집 주기 필터: 시간당 N회(3은 3회 이상). 아직 배정 전인 피드는 어느 조건에도 안 맞는다."""
    if not wanted:
        return True
    if cycle is None:
        return False
    return cycle.checks_per_hour >= 3 if wanted == "3" else cycle.checks_per_hour == int(wanted)


def _last_matches(published: datetime | None, now: datetime, wanted: str) -> bool:
    """마지막 게시 필터: 고른 구간에 든 피드만. 1달 이내는 1주일 초과 1달 이하다.

    "1년 넘게 없음"은 1년을 넘었거나 게시 기록이 없는 피드다.
    """
    if not wanted:
        return True
    if wanted == LAST_OLDER:
        return published is None or now - published > timedelta(days=365)
    if published is None:
        return False
    age = now - published
    for key, _, over, up_to in LAST_FILTERS:
        if key == wanted:
            return over < age <= up_to if over > timedelta(0) else age <= up_to
    return False


def _feeds_url(**params: str) -> str:
    """조건을 모두 담은 피드 관리 주소(값의 /도 인코딩해 프록시의 차단 규칙에 걸리지 않게 한다)."""
    pairs = [(key, value) for key, value in params.items() if value]
    return "/feeds?" + urlencode(pairs) if pairs else "/feeds"


def build_feed_router(
    feeds: FeedRepository,
    settings: SettingsService,
    templates: Jinja2Templates,
    registration: FeedRegistrationService,
    overview: OverviewRepository,
    clock: Clock,
) -> APIRouter:
    router = APIRouter()

    def rows(
        state: str, query: str, cycle_filter: str, last_filter: str
    ) -> tuple[list[dict[str, object]], dict[str, int]]:
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
        counts = {"all": 0, "ok": 0, "error": 0, "never": 0}  # 검색 결과 안에서의 개수
        out: list[dict[str, object]] = []
        needle = query.strip().lower()[:100]
        for item in listed:
            haystack = f"{item.name} {item.url} {item.site_url} {item.category_name}".lower()
            if needle and needle not in haystack:
                continue
            cycle = cycles.get(str(item.id))
            if not _cycle_matches(cycle, cycle_filter) or not _last_matches(
                item.last_published, now, last_filter
            ):
                continue
            counts["all"] += 1  # 상태 칩의 개수는 검색과 수집 주기, 마지막 게시 조건 안에서 센다
            counts[item.state] += 1
            if state and item.state != state:
                continue
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
        q: str = "",
        cycle: str = "",
        last: str = "",
    ) -> HTMLResponse:
        config = settings.snapshot()
        carried = _carried(getattr(request.state, "feeds_next", ""))  # 작업 뒤에도 필터를 지킨다
        q, state = q or carried["q"], state or carried["state"]
        cycle, last = cycle or carried["cycle"], last or carried["last"]
        state = state if state in STATE_FILTERS else ""
        cycle = cycle if cycle in dict(CYCLE_FILTERS) else ""
        last = last if last in {key for key, *_ in LAST_FILTERS} | {LAST_OLDER} else ""
        listed, counts = rows(state, q, cycle, last)
        context = {
            "rows": listed,
            "counts": counts,
            "state": state,
            "q": q.strip()[:100],
            "here": _feeds_url(state=state, q=q.strip()[:100], cycle=cycle, last=last),
            "cycle": cycle,
            "last": last,
            "cycle_options": CYCLE_FILTERS,
            "last_options": [(key, label) for key, label, *_ in LAST_FILTERS]
            + [(LAST_OLDER, "1년 넘게 없음")],
            "filtered": bool(q.strip() or cycle or last),
            "chips": {
                name: _feeds_url(state=name, q=q.strip()[:100], cycle=cycle, last=last)
                for name in ("", *STATE_FILTERS)
            },
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
        request: Request,
        saved: str = "",
        added: str = "",
        deleted: str = "",
        state: str = "",
        q: str = "",
        cycle: str = "",
        last: str = "",
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
        return page(request, notice=notice, state=state, q=q, cycle=cycle, last=last)

    # ---------- 개별 등록 ----------

    @router.post("/feeds/discover", response_class=HTMLResponse)
    async def discover(request: Request) -> Response:
        form = await request.form()
        request.state.feeds_next = str(form.get("next", ""))  # 오류 화면도 같은 필터로
        url = str(form.get("url", ""))
        result = registration.discover(url)
        if form.get("pick"):  # 피드 설정의 주소 "변경": 후보만 조각으로 돌려준다(등록하지 않는다)
            return templates.TemplateResponse(request, "_pick_results.html", {"result": result})
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
        request.state.feeds_next = str(form.get("next", ""))  # 오류 화면도 같은 필터로
        url = str(form.get("url", ""))
        result = registration.register(
            url,
            name=str(form.get("name", "")),
            category_id=id_or_none(form.get("category_id")),
            webhook_id=id_or_none(form.get("webhook_id")),
            kind=KIND_PAGE if form.get("kind") == KIND_PAGE else KIND_FEED,
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
        request.state.feeds_next = str(form.get("next", ""))  # 오류 화면도 같은 필터로
        feed = feeds.get(feed_id)
        if feed is None:
            return page(request, error="피드를 찾을 수 없음", status_code=404)
        category_id = id_or_none(form.get("category_id"))
        webhook_id = id_or_none(form.get("webhook_id"))
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
        new_site: str | None = None
        new_kind: str | None = None
        if url_changed:  # RSS가 있는지 먼저 보고, 없으면 글 목록 페이지로 본다(바꾸기 전에)
            resolved = await run_in_threadpool(registration.resolve, url, str(form.get("kind", "")))
            if resolved.error:
                message = f"새 주소를 확인하지 못했습니다: {resolved.error}"
                return page(request, error=message, status_code=400)
            new_site, new_kind = resolved.site_url, resolved.kind
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
                feeds.change_feed_url(feed_id, url, site_url=new_site, kind=new_kind)
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
        request.state.feeds_next = str(form.get("next", ""))  # 오류 화면도 같은 필터로
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
        request.state.feeds_next = str(form.get("next", ""))  # 오류 화면도 같은 필터로
        if form.get("confirm") != "yes":
            return page(request, error=CONFIRM_MESSAGE, status_code=400)
        if not feeds.delete(feed_id):
            return page(request, error="피드를 찾을 수 없음", status_code=404)
        return done_after_delete(form, "/feeds?deleted=1", "deleted", "feed", feed_id)

    # ---------- 카테고리, 웹훅 ----------

    @router.post("/feeds/{feed_id}/category", response_class=HTMLResponse)
    async def set_category(request: Request, feed_id: int) -> Response:
        form = await request.form()
        request.state.feeds_next = str(form.get("next", ""))  # 오류 화면도 같은 필터로
        try:
            found = feeds.set_feed_category(feed_id, id_or_none(form.get("category_id")))
        except FeedRuleError as error:
            return page(request, error=error.message, status_code=400)
        if not found:
            return page(request, error="피드를 찾을 수 없음", status_code=404)
        return done(form, "/feeds?saved=1", "saved")

    @router.post("/feeds/{feed_id}/webhook", response_class=HTMLResponse)
    async def set_webhook(request: Request, feed_id: int) -> Response:
        form = await request.form()
        request.state.feeds_next = str(form.get("next", ""))  # 오류 화면도 같은 필터로
        try:
            found = feeds.set_feed_webhook(feed_id, id_or_none(form.get("webhook_id")))
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
            if f.kind == KIND_FEED  # 웹페이지 구독은 피드가 아니라서 내보내지 않는다
        ]
        return Response(
            build_opml(items),
            media_type="text/x-opml; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="rss-hub-subscriptions.opml"'},
        )

    return router
