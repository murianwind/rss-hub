"""슬라이드 패널: 추가(+), 설정(톱니바퀴), 삭제 확인(−)을 본문 위에 내려오는 패널로 보여 준다.

- 패널은 서버가 그려 주는 HTML 조각이다. 스크립트가 받아서 끼워 넣고, 스크립트가 없으면
  같은 주소가 전체 화면(패널이 열린 읽기 화면)으로 열린다.
- 패널 안의 폼은 기존 관리 경로(/feeds/..., /categories/..., /topics/...)로 보낸다.
  돌아갈 곳(next)을 함께 보내서 일을 마치면 보던 화면으로 돌아오고 토스트가 뜬다.
- 삭제는 확인란을 선택해야만 보낼 수 있다(서버도 확인한다).
"""

import re

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates

from rss_hub.services.settings import SettingsService, WebhookInfo
from rss_hub.storage.feeds import FeedRepository
from rss_hub.storage.topics import TopicRepository
from rss_hub.web.reader import Scope
from rss_hub.web.ui import safe_return

KINDS = ("feed", "category", "topic")
DELETE_NOTES = {
    "feed": "이 피드와 이 피드에서 수집한 글, 발송 기록이 모두 지워집니다. 되돌릴 수 없습니다.",
    "category": "카테고리만 지워집니다. 안에 있던 피드와 글은 남고 카테고리 없이 보입니다.",
    "topic": "주제와 그 주제에 모은 기록(싫어요, 주제로 표시)이 지워집니다. 글은 남습니다.",
}
_OWN_LIST = re.compile(r"^/reader/(feed|category|topic)/(\d+)")


def render_panel(
    templates: Jinja2Templates,
    request: Request,
    panel: dict[str, object],
    webhooks: list[WebhookInfo],
    *,
    status_code: int = 200,
    next_path: str | None = None,
) -> Response:
    """패널을 조각(스크립트 요청)이나 전체 화면(스크립트 없이 연 경우)으로 그린다."""
    chosen = safe_return(next_path or request.query_params.get("next"), "/reader")
    context = {"panel": panel, "next": chosen, "webhooks": webhooks}
    template = "_panel.html" if request.headers.get("x-panel") else "panel_page.html"
    request.state.scope = Scope("all")
    return templates.TemplateResponse(request, template, context, status_code=status_code)


def build_panel_router(
    *,
    feeds: FeedRepository,
    topics: TopicRepository,
    settings: SettingsService,
    templates: Jinja2Templates,
) -> APIRouter:
    router = APIRouter()

    def render(request: Request, panel: dict[str, object]) -> Response:
        return render_panel(templates, request, panel, settings.list_webhooks())

    def missing() -> Response:
        return PlainTextResponse("찾을 수 없습니다", status_code=404)

    def lookup(kind: str, item_id: int) -> object | None:
        if kind == "feed":
            return feeds.get(item_id)
        if kind == "category":
            return next((c for c in feeds.list_categories() if c.id == item_id), None)
        return topics.get(item_id)

    @router.get("/panel/add/{kind}", response_class=HTMLResponse)
    def add_panel(request: Request, kind: str) -> Response:
        if kind not in KINDS:
            return missing()
        extra: dict[str, object] = {}
        if kind == "feed":
            extra = {
                "url": "",
                "error": "",
                "discovery": None,
                "categories": feeds.list_categories(),
            }
        return render(request, {"mode": "add", "kind": kind, **extra})

    @router.get("/panel/settings/{kind}/{item_id}", response_class=HTMLResponse)
    def settings_panel(request: Request, kind: str, item_id: int) -> Response:
        item = lookup(kind, item_id) if kind in KINDS else None
        if item is None:
            return missing()
        extra: dict[str, object] = {}
        if kind == "feed":
            extra = {
                "categories": feeds.list_categories(),
                "default_max_entries": settings.snapshot().default_max_entries,
            }
        return render(request, {"mode": "settings", "kind": kind, "item": item, **extra})

    @router.get("/panel/delete/{kind}/{item_id}", response_class=HTMLResponse)
    def delete_panel(request: Request, kind: str, item_id: int) -> Response:
        item = lookup(kind, item_id) if kind in KINDS else None
        if item is None:
            return missing()
        # 지금 보고 있는 목록 자체를 지우면 그 목록은 사라지므로 전체 글로 돌아간다
        own = _OWN_LIST.match(safe_return(request.query_params.get("next"), "/reader"))
        after = "/reader" if own and own.group(1) == kind and int(own.group(2)) == item_id else None
        return render(
            request,
            {
                "mode": "delete",
                "kind": kind,
                "item": item,
                "note": DELETE_NOTES[kind],
                "after": after,
            },
        )

    return router
