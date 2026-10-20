"""화면 공통: 아이콘, 상대 시간, 모든 화면에 들어가는 사이드바 데이터와 토스트 문구."""

import re
from collections.abc import Callable
from datetime import datetime, tzinfo
from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import RedirectResponse
from markupsafe import Markup, escape

from rss_hub.services.clock import Clock
from rss_hub.services.settings import SettingsService
from rss_hub.storage.reader import ReaderRepository

# 24x24 선 아이콘(선 속성은 CSS의 .icon이 정한다). 외부 아이콘 글꼴을 쓰지 않는다.
ICONS: dict[str, str] = {
    "rss": (
        '<path d="M4 11a9 9 0 0 1 9 9"/><path d="M4 4a16 16 0 0 1 16 16"/>'
        '<circle cx="5" cy="19" r="1"/>'
    ),
    "folder": (
        '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>'
    ),
    "hash": '<path d="M5 9h14M5 15h14M10 4 8 20M16 4l-2 16"/>',
    "gear": (
        '<circle cx="12" cy="12" r="3"/>'
        '<path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9 7 7"/>'
        '<path d="M17 17l2.1 2.1M19.1 4.9 17 7M7 17l-2.1 2.1"/>'
    ),
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "minus": '<path d="M5 12h14"/>',
    "chevron-down": '<path d="m6 9 6 6 6-6"/>',
    "chevron-right": '<path d="m9 6 6 6-6 6"/>',
    "chevron-left": '<path d="m15 6-6 6 6 6"/>',
    "bookmark": '<path d="M6 3h12v18l-6-4-6 4z"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/>',
    "arrow-left": '<path d="M19 12H5M11 6l-6 6 6 6"/>',
    "menu": '<path d="M4 6h16M4 12h16M4 18h16"/>',
    "x": '<path d="M6 6l12 12M18 6 6 18"/>',
    "check": '<path d="m5 12 5 5 9-10"/>',
    "list": '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
    "external": '<path d="M14 4h6v6M20 4l-9 9M18 14v5H5V6h5"/>',
    "grip": (
        '<circle cx="9" cy="6" r="1"/><circle cx="15" cy="6" r="1"/><circle cx="9" cy="12" r="1"/>'
        '<circle cx="15" cy="12" r="1"/><circle cx="9" cy="18" r="1"/>'
        '<circle cx="15" cy="18" r="1"/>'
    ),
    "refresh": '<path d="M20 11a8 8 0 0 0-14.9-3M4 5v4h4M4 13a8 8 0 0 0 14.9 3M20 19v-4h-4"/>',
    "inbox": '<path d="M3 13h5l1 3h6l1-3h5M5 5h14l2 8v6H3v-6z"/>',
}

TOASTS = {
    "read_all": "모두 읽음으로 표시했습니다.",
    "bookmarked": "북마크에 추가했습니다.",
    "unbookmarked": "북마크를 해제했습니다.",
    "marked_unread": "안 읽음으로 표시했습니다.",
    "marked_read": "읽음으로 표시했습니다.",
    "fulltext": "원문에서 전문을 다시 가져왔습니다.",
    "fulltext_failed": "원문에서 전문을 가져오지 못했습니다.",
    "saved": "저장했습니다.",
    "added": "추가했습니다.",
    "deleted": "삭제했습니다.",
    "moved": "옮겼습니다.",
}

SETTINGS_PATHS = ("/settings", "/feeds", "/categories", "/topics", "/models", "/status", "/import")
SIDEBAR_COOKIE = "sidebar"
SIDEBAR_WIDTH_COOKIE = "sbw"
SIDEBAR_MIN, SIDEBAR_MAX, SIDEBAR_STEP = 220, 480, 10  # 폭 조절의 범위와 단위(px)
SETTINGS_ITEMS = (
    ("/settings", "설정"),
    ("/feeds", "피드 관리"),
    ("/topics", "주제 관리"),
    ("/models", "모델"),
    ("/status", "상태"),
)
# 같은 메뉴 항목으로 묶이는 화면들
SETTINGS_ALIASES = {"/": "/status", "/import": "/feeds", "/categories": "/feeds"}

_SAFE_PATH = re.compile(
    r"^/(?:reader(?:/(?:feed|category|topic)/\d+|/bookmarks)?|a/\d+|topics/\d+/suggestions)"
    r"(?:\?[0-9A-Za-z_=&%+.\-]{0,300})?$"
)


_SAFE_RETURN = re.compile(
    r"^/(?:reader(?:/(?:feed|category|topic)/\d+|/bookmarks)?|a/\d+|topics/\d+/suggestions"
    r"|settings(?:/(?:general|notifications|llm|display))?|feeds|topics|categories|models|status|import)"
    r"(?:\?[0-9A-Za-z_=&%+.\-]{0,300})?$"
)


def icon(name: str, css: str = "") -> Markup:
    """이름으로 아이콘 하나를 그린다(스프라이트의 심볼을 가리킨다)."""
    extra = f" {css}" if css else ""
    return Markup(
        f'<svg class="icon{extra}" aria-hidden="true" focusable="false">'
        f'<use href="#i-{escape(name)}"></use></svg>'
    )


def sprite() -> Markup:
    symbols = "".join(
        f'<symbol id="i-{name}" viewBox="0 0 24 24">{inner}</symbol>'
        for name, inner in ICONS.items()
    )
    return Markup(f'<svg class="sprite" aria-hidden="true" focusable="false">{symbols}</svg>')


def safe_path(value: object, default: str) -> str:
    """돌아갈 곳은 이 서비스의 읽기 화면 경로(쿼리는 영숫자와 일부 기호만)만 허용한다."""
    text = str(value or "")
    return text if _SAFE_PATH.fullmatch(text) else default


def safe_return(value: object, default: str) -> str:
    """관리 폼이 일을 마치고 돌아갈 곳: 읽기 화면과 관리 화면의 정해진 경로만 허용한다."""
    text = str(value or "")
    return text if _SAFE_RETURN.fullmatch(text) else default


def done(form: object, default: str, toast: str) -> RedirectResponse:
    """폼에 돌아갈 곳(next)이 있고 안전하면 거기로 토스트와 함께, 없으면 기본 화면으로 보낸다."""
    target = safe_return(form.get("next"), "")  # type: ignore[attr-defined]
    return RedirectResponse(with_toast(target, toast) if target else default, status_code=303)


def with_toast(path: str, key: str) -> str:
    return f"{path}{'&' if '?' in path else '?'}toast={key}"


def list_url(base: str, *, page: int = 1, query: str = "", only: str = "") -> str:
    """목록 주소. 기본값(1쪽, 빈 검색어, 전체)은 쓰지 않는다."""
    params = {"page": page if page > 1 else "", "q": query, "only": only}
    text = urlencode({k: v for k, v in params.items() if v})
    return f"{base}?{text}" if text else base


def ago(moment: datetime, now: datetime, zone: tzinfo) -> str:
    """ "10분 전"처럼 읽기 쉬운 상대 시간. 일주일이 넘으면 날짜."""
    seconds = int((now - moment).total_seconds())
    if seconds < 60:
        return "방금"
    if seconds < 3600:
        return f"{seconds // 60}분 전"
    if seconds < 86400:
        return f"{seconds // 3600}시간 전"
    if seconds < 7 * 86400:
        return f"{seconds // 86400}일 전"
    return moment.astimezone(zone).strftime("%Y-%m-%d")


def _open_sections(request: Request, scope_kind: str) -> set[str]:
    path = request.url.path
    if path.startswith(SETTINGS_PATHS):
        return {"settings"}
    sections = {"feed": {"rss"}, "category": {"categories"}, "topic": {"topics"}}
    sections.update({"all": {"rss"}, "bookmarks": {"rss"}})
    return sections.get(scope_kind, set())


def sidebar_width(raw: object) -> int:
    """쿠키의 사이드바 폭(px)을 범위 안의 10px 단위로 맞춘다. 없거나 이상하면 0(기본 폭)."""
    text = str(raw or "")
    if not (text.isascii() and text.isdigit()) or len(text) > 5:
        return 0
    snapped = (int(text) + SIDEBAR_STEP // 2) // SIDEBAR_STEP * SIDEBAR_STEP  # 반올림(5는 올림)
    return min(SIDEBAR_MAX, max(SIDEBAR_MIN, snapped))


def _current(request: Request) -> str:
    """지금 화면의 주소(패널 폼이 일을 마치고 돌아갈 곳). 알려진 쿼리만 남긴다."""
    params = request.query_params
    keep = {key: params[key] for key in ("page", "q", "only") if params.get(key)}
    if request.url.path.startswith("/a/") and safe_path(params.get("back"), ""):
        keep["back"] = params["back"]
    query = urlencode(keep)
    return request.url.path + (f"?{query}" if query else "")


def build_ui_context(
    *, reader: ReaderRepository, settings: SettingsService, clock: Clock, version: str
) -> Callable[[Request], dict[str, object]]:
    """모든 화면에 사이드바와 공통 값을 넣는다. 키는 ui_로 시작해서 화면 값과 겹치지 않는다."""

    def context(request: Request) -> dict[str, object]:
        scope = getattr(request.state, "scope", None)
        kind = "" if scope is None else scope.kind
        side = reader.sidebar()
        config = settings.snapshot()
        return {
            "ui_side": side,
            "ui_scope": scope,
            "ui_open": _open_sections(request, kind),
            "ui_path": request.url.path,
            "ui_settings_items": SETTINGS_ITEMS,
            "ui_settings_tab": SETTINGS_ALIASES.get(request.url.path, request.url.path),
            "ui_next": safe_return(_current(request), "/reader"),
            "ui_collapsed": request.cookies.get(SIDEBAR_COOKIE) == "collapsed",
            "ui_sbw": sidebar_width(request.cookies.get(SIDEBAR_WIDTH_COOKIE)),
            "ui_toast": TOASTS.get(request.query_params.get("toast", ""), ""),
            "ui_now": clock.now(),
            "ui_zone": config.timezone,
            "ui_theme": config.ui_theme,
            "ui_auto_read": config.ui_auto_read,
            "ui_font": config.ui_font_size,
            "ui_version": version,
        }

    return context
