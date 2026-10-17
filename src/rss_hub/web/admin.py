"""관리 화면: 상태, 설정. 서버에서 HTML을 만든다(스크립트 없음)."""

import re
from datetime import datetime, tzinfo
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from rss_hub.domain.delivery import describe_send_failure
from rss_hub.domain.settings_rules import SettingError, normalize_base_url
from rss_hub.services.clock import Clock
from rss_hub.services.ports import LlmClient, WebhookSender
from rss_hub.services.settings import SETTING_BY_KEY, SETTING_DEFS, SettingsService
from rss_hub.storage.articles import STATUS_COLLECTED, STATUS_READY, ArticleRepository
from rss_hub.storage.feeds import FeedRepository
from rss_hub.storage.job_runs import JobRunRepository
from rss_hub.storage.llm_usage import LlmUsageRepository
from rss_hub.version import get_version

CONFIRM_MESSAGE = "삭제하려면 확인란을 선택하세요"
_HOST = re.compile(r"^(\[[0-9a-fA-F:.]+\]|[A-Za-z0-9.-]+)(:\d{1,5})?$")

SETTING_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("일반", ("service_base_url", "service_timezone")),
    (
        "주기",
        ("collect_interval_minutes", "summarize_interval_seconds", "deliver_interval_seconds"),
    ),
    ("수집", ("slot_batch_size", "default_max_entries")),
    (
        "LLM",
        (
            "model_chain",
            "llm_daily_cap",
            "llm_warn_percent",
            "llm_rpm_cap",
            "llm_reserve_calls",
            "llm_wait_limit_minutes",
            "summarize_batch",
        ),
    ),
    ("알림", ("alert_cooldown_hours",)),
)


def _suggest_base_url(request: Request) -> str | None:
    """지금 접속한 주소를 서비스 주소 후보로 만든다. 프록시가 넘긴 헤더를 우선한다."""
    forwarded_host = request.headers.get("x-forwarded-host")
    host = (
        forwarded_host.split(",")[0].strip() if forwarded_host else request.headers.get("host", "")
    )
    proto = request.headers.get("x-forwarded-proto")
    scheme = proto.split(",")[0].strip() if proto else request.url.scheme
    if not _HOST.match(host):
        return None
    try:
        return normalize_base_url(f"{scheme}://{host}")
    except SettingError:
        return None


def _parse_role(raw: str) -> int | None:
    value = raw.strip()
    if not value:
        return None
    if not value.isdigit():
        raise SettingError("올바르지 않은 웹훅 선택")
    return int(value)


def _local(moment: datetime | None, zone: tzinfo) -> str:
    return "" if moment is None else moment.astimezone(zone).strftime("%m-%d %H:%M:%S")


JOB_LABELS = {"collect": "수집", "summarize": "요약", "deliver": "발송"}


def build_admin_router(
    service: SettingsService,
    templates: Jinja2Templates,
    articles: ArticleRepository,
    *,
    feeds: FeedRepository,
    job_runs: JobRunRepository,
    usage: LlmUsageRepository,
    clock: Clock,
    sender: WebhookSender,
    llm_client: LlmClient,
) -> APIRouter:
    router = APIRouter()

    def render_settings(
        request: Request,
        *,
        status_code: int = 200,
        form_values: dict[str, str] | None = None,
        errors: dict[str, str] | None = None,
        section_error: tuple[str, str] | None = None,
        notice: str = "",
        webhook_name: str = "",
        test_result: tuple[str, str] | None = None,
    ) -> HTMLResponse:
        snapshot = service.snapshot()
        values = {**service.raw_values(), **(form_values or {})}
        by_key = {d.key: d for d in SETTING_DEFS}
        groups = [(title, [by_key[key] for key in keys]) for title, keys in SETTING_GROUPS]
        audit = [
            {
                "time": e.changed_at.astimezone(snapshot.timezone).strftime("%Y-%m-%d %H:%M"),
                "summary": e.summary,
            }
            for e in service.audit_log()
        ]
        suggestion = None if snapshot.base_url else _suggest_base_url(request)
        context: dict[str, Any] = {
            "groups": groups,
            "values": values,
            "errors": errors or {},
            "section_error": section_error,
            "notice": notice,
            "has_key": service.has_openrouter_key(),
            "webhooks": service.list_webhooks(),
            "roles": {
                "default_id": snapshot.webhook_default_id,
                "system_id": snapshot.webhook_system_id,
            },
            "suggestion": suggestion,
            "audit": audit,
            "webhook_name": webhook_name,
            "test_result": test_result,
        }
        return templates.TemplateResponse(
            request, "settings.html", context, status_code=status_code
        )

    def error_page(
        request: Request, section: str, message: str, webhook_name: str = ""
    ) -> HTMLResponse:
        return render_settings(
            request,
            status_code=400,
            section_error=(section, message),
            webhook_name=webhook_name,
        )

    @router.get("/", response_class=HTMLResponse)
    @router.get("/status", response_class=HTMLResponse)
    def status_page(request: Request) -> HTMLResponse:
        checklist = service.setup_checklist()
        waiting = (
            0 if service.snapshot().base_url else articles.count_by_status().get(STATUS_READY, 0)
        )
        config = service.snapshot()
        counts = articles.count_by_status()
        runs = job_runs.all()
        failing = sorted(
            (f for f in feeds.list_all() if f.fail_count > 0), key=lambda f: -f.fail_count
        )
        context: dict[str, Any] = {
            "ready_count": counts.get(STATUS_READY, 0),
            "collected_count": counts.get(STATUS_COLLECTED, 0),
            "llm_calls_today": usage.count_day(clock.now().astimezone(config.timezone).date()),
            "failing_feeds": failing,
            "jobs": [
                {
                    "label": label,
                    "last_ok": _local(runs[name].last_ok_at, config.timezone)
                    if name in runs
                    else "",
                    "status": runs[name].last_status if name in runs else "",
                    "skipped": runs[name].skipped_count if name in runs else 0,
                }
                for name, label in JOB_LABELS.items()
            ],
            "waiting_for_address": waiting,
            "checklist": checklist,
            "all_ready": all(item.ready for item in checklist),
            "version": get_version(),
        }
        return templates.TemplateResponse(request, "status.html", context)

    @router.get("/settings", response_class=HTMLResponse)
    def settings_page(request: Request, saved: str = "") -> HTMLResponse:
        return render_settings(request, notice="저장했습니다" if saved else "")

    @router.post("/settings", response_class=HTMLResponse)
    async def save_settings(request: Request) -> Response:
        form = await request.form()
        submitted = {k: str(v) for k, v in form.items() if k in SETTING_BY_KEY}
        result = service.update(submitted)
        if result.errors:
            return render_settings(
                request, status_code=400, form_values=submitted, errors=result.errors
            )
        return RedirectResponse("/settings?saved=1", status_code=303)

    @router.post("/settings/openrouter-key", response_class=HTMLResponse)
    async def save_key(request: Request) -> Response:
        form = await request.form()
        try:
            service.set_openrouter_key(str(form.get("openrouter_key", "")))
        except SettingError as error:
            return error_page(request, "openrouter_key", error.message)
        return RedirectResponse("/settings?saved=1", status_code=303)

    @router.post("/settings/openrouter-key/delete", response_class=HTMLResponse)
    async def delete_key(request: Request) -> Response:
        form = await request.form()
        if form.get("confirm") != "yes":
            return error_page(request, "openrouter_key", CONFIRM_MESSAGE)
        service.delete_openrouter_key()
        return RedirectResponse("/settings?saved=1", status_code=303)

    @router.post("/settings/webhooks", response_class=HTMLResponse)
    async def add_webhook(request: Request) -> Response:
        form = await request.form()
        name = str(form.get("name", ""))
        try:
            service.add_webhook(name, str(form.get("url", "")))
        except SettingError as error:
            return error_page(request, "webhook", error.message, webhook_name=name)
        return RedirectResponse("/settings?saved=1", status_code=303)

    @router.post("/settings/webhooks/{webhook_id}/delete", response_class=HTMLResponse)
    async def delete_webhook(request: Request, webhook_id: int) -> Response:
        form = await request.form()
        if form.get("confirm") != "yes":
            return error_page(request, "webhook", CONFIRM_MESSAGE)
        service.delete_webhook(webhook_id)
        return RedirectResponse("/settings?saved=1", status_code=303)

    @router.post("/settings/webhooks/{webhook_id}/test", response_class=HTMLResponse)
    async def test_webhook(request: Request, webhook_id: int) -> Response:
        """선택한 웹훅으로 시험 메시지 한 건만 보낸다. 결과 화면에 웹훅 주소는 나타나지 않는다."""
        url = service.get_webhook_url(webhook_id)
        name = next((w.name for w in service.list_webhooks() if w.id == webhook_id), "")
        if url is None:
            return render_settings(
                request, status_code=404, test_result=("error", "웹훅을 찾을 수 없습니다")
            )
        result = sender.send(
            url, f"✅ RSS Hub 시험 메시지입니다. 웹훅 '{name}'이 정상으로 연결되었습니다."
        )
        if 200 <= result.status < 300:
            return render_settings(
                request, test_result=("ok", f"성공: '{name}'으로 시험 메시지를 보냈습니다")
            )
        reason = describe_send_failure(result.status, result.error)
        return render_settings(request, test_result=("error", f"실패: '{name}' {reason}"))

    @router.post("/settings/openrouter-key/check", response_class=HTMLResponse)
    async def check_key(request: Request) -> Response:
        """키 정보만 조회한다(채팅 호출이 아니라서 호출 한도와 오늘 호출 수를 쓰지 않는다)."""
        check = llm_client.check_key()
        if check.valid:
            usage_text = (
                f" · 오늘 무료 모델 호출 {check.used}/{check.limit}"
                if check.used is not None and check.limit is not None
                else ""
            )
            return render_settings(request, test_result=("ok", f"키가 유효합니다{usage_text}"))
        kind = "error" if check.valid is False else "warn"
        return render_settings(request, test_result=(kind, check.reason))

    @router.post("/settings/webhook-roles", response_class=HTMLResponse)
    async def save_roles(request: Request) -> Response:
        form = await request.form()
        try:
            service.set_webhook_roles(
                default_id=_parse_role(str(form.get("default_id", ""))),
                system_id=_parse_role(str(form.get("system_id", ""))),
            )
        except SettingError as error:
            return error_page(request, "roles", error.message)
        return RedirectResponse("/settings?saved=1", status_code=303)

    return router
