"""관리 화면: 상태, 설정, Discord. 서버에서 HTML을 만든다(스크립트 없음)."""

import re
from collections.abc import Callable
from datetime import UTC, datetime, tzinfo
from typing import Any, Protocol

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from rss_hub.domain.delivery import describe_send_failure
from rss_hub.domain.error_log import KIND_LABELS, SORT_LABELS, SORT_RECENT
from rss_hub.domain.settings_rules import SettingError, normalize_base_url
from rss_hub.services.clock import Clock
from rss_hub.services.ports import WebhookSender
from rss_hub.services.settings import SettingsService
from rss_hub.storage.articles import STATUS_COLLECTED, STATUS_READY, Article, ArticleRepository
from rss_hub.storage.error_log import ErrorLogRepository
from rss_hub.storage.feeds import FeedRepository
from rss_hub.storage.job_runs import STATUS_RUNNING, JobRunRepository
from rss_hub.storage.llm_usage import LlmUsageRepository
from rss_hub.web.setting_groups import SETTINGS_ACCORDIONS, keys_of, sections
from rss_hub.web.ui import done

CONFIRM_MESSAGE = "삭제 확인이 필요합니다"
_HOST = re.compile(r"^(\[[0-9a-fA-F:.]+\]|[A-Za-z0-9.-]+)(:\d{1,5})?$")


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
    if not value.isdecimal():
        raise SettingError("올바르지 않은 웹훅 선택")
    return int(value)


def _llm_today(usage: LlmUsageRepository, clock: Clock) -> dict[str, int]:
    """오늘(UTC) 모델 호출 수. 호출 한도와 같은 하루 기준이다."""
    by_outcome = usage.count_day_by_outcome(clock.now().astimezone(UTC).date())
    ok = by_outcome.get("success", 0)
    total = sum(by_outcome.values())
    return {"llm_calls_today": total, "llm_calls_ok": ok, "llm_calls_failed": total - ok}


def _run_notice(run: str) -> str:
    name, _, result = run.partition(".")
    template = RUN_NOTICES.get(result, "")
    return template.format(label=RUNNABLE_JOBS.get(name, "")) if name in RUNNABLE_JOBS else ""


def _local(moment: datetime | None, zone: tzinfo) -> str:
    return "" if moment is None else moment.astimezone(zone).strftime("%m-%d %H:%M:%S")


PENDING_SHOWN = 8  # 상태 화면에 보여 줄 대기 글 수(종류마다)
RUNNABLE_JOBS = {"collect": "수집", "summarize": "요약", "deliver": "발송"}
RUN_NOTICES = {
    "started": "{label} 작업을 시작했습니다. 결과는 작업 기록에 남습니다.",
    "busy": "{label} 작업은 이미 실행 중입니다. 끝난 뒤에 다시 눌러 주세요.",
    "unavailable": "작업 실행기가 꺼져 있어 지금 실행할 수 없습니다.",
}


JOB_UNITS = {"collect": "개", "summarize": "건", "deliver": "건"}  # 진행 "2/5건"의 단위


class JobStarter(Protocol):
    def run_now(self, name: str) -> str: ...

    def progress_of(self, name: str) -> tuple[int, int] | None: ...


def _progress_text(starter: JobStarter | None, name: str) -> str:
    """실행 중인 작업이 알린 진행("2/5건"). 알리지 않았으면 빈 글자."""
    found = None if starter is None else starter.progress_of(name)
    return "" if found is None else f"{found[0]}/{found[1]}{JOB_UNITS.get(name, '')}"


def _why_waiting(
    article: Article, *, sending: bool, base_url: str, has_default: bool, has_key: bool
) -> str:
    """대기 중인 글이 왜 아직 안 나갔는지 한 줄로."""
    if sending:
        if not base_url:
            return "서비스 주소가 없어 발송을 기다립니다"
        if not has_default:
            return "기본 웹훅이 없어 발송을 기다립니다"
        return "발송 차례를 기다립니다"
    if article.retry_count:
        return f"요약을 {article.retry_count}번 다시 시도했습니다"
    if not has_key:
        return "OpenRouter 키가 없어 원문 제목으로 곧 확정합니다"
    return "요약 차례를 기다립니다"


JOB_LABELS = {
    "collect": "수집",
    "summarize": "요약",
    "deliver": "발송",
    "retention": "정리",
    "model_scan": "모델 스캔",
}


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
    error_log: ErrorLogRepository,
    runner: Callable[[], JobStarter | None] = lambda: None,
) -> APIRouter:
    router = APIRouter()
    settings_keys = keys_of(*(group for _, _, groups in SETTINGS_ACCORDIONS for group in groups))
    alert_keys = keys_of("알림")

    def render_settings(
        request: Request,
        *,
        status_code: int = 200,
        form_values: dict[str, str] | None = None,
        errors: dict[str, str] | None = None,
        notice: str = "",
    ) -> HTMLResponse:
        snapshot = service.snapshot()
        accordions = [
            (acc_id, title, sections(*groups, titled=len(groups) > 1))
            for acc_id, title, groups in SETTINGS_ACCORDIONS
        ]
        # 항목은 하나만 펼쳐진다: 오류가 있는 항목이 있으면 그것, 없으면 첫 항목
        opened = next(
            (
                acc_id
                for acc_id, _, groups in SETTINGS_ACCORDIONS
                if any(key in (errors or {}) for key in keys_of(*groups))
            ),
            "general",
        )
        context: dict[str, Any] = {
            "values": {**service.raw_values(), **(form_values or {})},
            "errors": errors or {},
            "section_error": None,
            "notice": notice,
            "suggestion": None if snapshot.base_url else _suggest_base_url(request),
            "accordions": accordions,
            "opened": opened,
        }
        return templates.TemplateResponse(
            request, "settings.html", context, status_code=status_code
        )

    def render_discord(
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
        context: dict[str, Any] = {
            "values": {**service.raw_values(), **(form_values or {})},
            "errors": errors or {},
            "sections": sections("알림"),
            "section_error": section_error,
            "notice": notice,
            "webhooks": service.list_webhooks(),
            "roles": {
                "default_id": snapshot.webhook_default_id,
                "system_id": snapshot.webhook_system_id,
            },
            "webhook_name": webhook_name,
            "test_result": test_result,
        }
        return templates.TemplateResponse(request, "discord.html", context, status_code=status_code)

    def error_page(
        request: Request, section: str, message: str, webhook_name: str = ""
    ) -> HTMLResponse:
        return render_discord(
            request,
            status_code=400,
            section_error=(section, message),
            webhook_name=webhook_name,
        )

    @router.get("/status", response_class=HTMLResponse)
    def status_page(
        request: Request, run: str = "", kind: str = "", sort: str = ""
    ) -> HTMLResponse:
        checklist = service.setup_checklist()
        waiting = (
            0 if service.snapshot().base_url else articles.count_by_status().get(STATUS_READY, 0)
        )
        config = service.snapshot()
        counts = articles.count_by_status()
        runs = job_runs.all()
        has_key = service.has_openrouter_key()
        feed_names = {f.id: f.name for f in feeds.list_all()}
        pending = {
            kind: [
                {
                    "title": a.title_ko or a.title,
                    "feed": feed_names.get(a.feed_id, ""),
                    "why": _why_waiting(
                        a,
                        sending=kind == STATUS_READY,
                        base_url=config.base_url,
                        has_default=config.webhook_default_id is not None,
                        has_key=has_key,
                    ),
                }
                for a in articles.list_by_status(kind, PENDING_SHOWN)
            ]
            for kind in (STATUS_READY, STATUS_COLLECTED)
        }
        failing = sorted(
            (f for f in feeds.list_all() if f.fail_count > 0), key=lambda f: -f.fail_count
        )
        audit = [
            {
                "time": e.changed_at.astimezone(config.timezone).strftime("%Y-%m-%d %H:%M"),
                "summary": e.summary,
            }
            for e in service.audit_log()
        ]
        context: dict[str, Any] = {
            "ready_count": counts.get(STATUS_READY, 0),
            "collected_count": counts.get(STATUS_COLLECTED, 0),
            **_llm_today(usage, clock),
            "feed_count": len(feed_names),
            "jobs_running": any(
                name in runs and runs[name].last_status == STATUS_RUNNING for name in JOB_LABELS
            ),
            "pending": pending,
            "run_notice": _run_notice(run),
            "failing_feeds": failing,
            "jobs": [
                {
                    "name": name,
                    "label": label,
                    "runnable": name in RUNNABLE_JOBS,
                    "last_ok": _local(runs[name].last_ok_at, config.timezone)
                    if name in runs
                    else "",
                    "status": runs[name].last_status if name in runs else "",
                    "running": name in runs and runs[name].last_status == STATUS_RUNNING,
                    "progress": _progress_text(runner(), name),
                    "result": runs[name].last_result if name in runs else "",
                    "skipped": runs[name].skipped_count if name in runs else 0,
                }
                for name, label in JOB_LABELS.items()
            ],
            "waiting_for_address": waiting,
            "checklist": checklist,
            "all_ready": all(item.ready for item in checklist if item.required),
            "audit": audit,
            **_error_log_context(error_log, config.timezone, kind, sort),
        }
        return templates.TemplateResponse(request, "status.html", context)

    @router.post("/status/jobs/{name}/run")
    def run_job(name: str) -> Response:
        """요약, 발송 같은 작업을 차례를 기다리지 않고 지금 실행한다."""
        if name not in RUNNABLE_JOBS:
            return PlainTextResponse("알 수 없는 작업입니다", status_code=404)
        starter = runner()
        result = "unavailable" if starter is None else starter.run_now(name)
        return RedirectResponse(f"/status?run={name}.{result}", status_code=303)

    @router.get("/settings", response_class=HTMLResponse)
    def settings_page(request: Request, saved: str = "") -> HTMLResponse:
        return render_settings(request, notice="저장했습니다" if saved else "")

    @router.post("/settings", response_class=HTMLResponse)
    async def save_settings(request: Request) -> Response:
        form = await request.form()
        submitted = {k: str(v) for k, v in form.items() if k in settings_keys}
        result = service.update(submitted)
        if result.errors:
            return render_settings(
                request, status_code=400, form_values=submitted, errors=result.errors
            )
        return done(form, "/settings?saved=1", "saved")

    @router.get("/discord", response_class=HTMLResponse)
    def discord_page(request: Request, saved: str = "") -> HTMLResponse:
        return render_discord(request, notice="저장했습니다" if saved else "")

    @router.post("/discord/settings", response_class=HTMLResponse)
    async def save_alert_settings(request: Request) -> Response:
        form = await request.form()
        submitted = {k: str(v) for k, v in form.items() if k in alert_keys}
        result = service.update(submitted)
        if result.errors:
            return render_discord(
                request, status_code=400, form_values=submitted, errors=result.errors
            )
        return done(form, "/discord?saved=1", "saved")

    @router.post("/settings/webhooks", response_class=HTMLResponse)
    async def add_webhook(request: Request) -> Response:
        form = await request.form()
        name = str(form.get("name", ""))
        try:
            service.add_webhook(name, str(form.get("url", "")))
        except SettingError as error:
            return error_page(request, "webhook", error.message, webhook_name=name)
        return done(form, "/discord?saved=1", "saved")

    @router.post("/settings/webhooks/{webhook_id}/delete", response_class=HTMLResponse)
    async def delete_webhook(request: Request, webhook_id: int) -> Response:
        form = await request.form()
        if form.get("confirm") != "yes":
            return error_page(request, "webhook", CONFIRM_MESSAGE)
        service.delete_webhook(webhook_id)
        return done(form, "/discord?saved=1", "saved")

    @router.post("/settings/webhooks/{webhook_id}/test", response_class=HTMLResponse)
    async def test_webhook(request: Request, webhook_id: int) -> Response:
        """선택한 웹훅으로 시험 메시지 한 건만 보낸다. 결과 화면에 웹훅 주소는 나타나지 않는다."""
        url = service.get_webhook_url(webhook_id)
        name = next((w.name for w in service.list_webhooks() if w.id == webhook_id), "")
        if url is None:
            return render_discord(
                request, status_code=404, test_result=("error", "웹훅을 찾을 수 없습니다")
            )
        result = sender.send(
            url, f"✅ RSS Hub 시험 메시지입니다. 웹훅 '{name}'이 정상으로 연결되었습니다."
        )
        if 200 <= result.status < 300:
            return render_discord(
                request, test_result=("ok", f"성공: '{name}'으로 시험 메시지를 보냈습니다")
            )
        reason = describe_send_failure(result.status, result.error)
        return render_discord(request, test_result=("error", f"실패: '{name}' {reason}"))

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
        return done(form, "/discord?saved=1", "saved")

    return router


def _error_log_context(
    error_log: ErrorLogRepository, zone: tzinfo, kind: str, sort: str
) -> dict[str, Any]:
    """상태 화면의 오류 기록: 유형별 횟수, 거른 목록, 줄마다 복사할 글자."""
    chosen_kind = kind if kind in KIND_LABELS else ""
    chosen_sort = sort if sort in SORT_LABELS else SORT_RECENT
    counts = error_log.counts_by_kind()

    def stamp(moment: datetime) -> str:
        return moment.astimezone(zone).strftime("%m-%d %H:%M:%S")

    rows = []
    for e in error_log.list(kind=chosen_kind, sort=chosen_sort):
        times = stamp(e.last_at) if e.count == 1 else f"{stamp(e.first_at)} ~ {stamp(e.last_at)}"
        label = KIND_LABELS.get(e.kind, e.kind)
        lines = [f"[{label}] {e.source}", e.message, f"{times} · {e.count}회"]
        rows.append(
            {
                "kind": e.kind,
                "label": label,
                "source": e.source,
                "message": e.message,
                "detail": e.detail,
                "count": e.count,
                "time": stamp(e.last_at),
                "clip": "\n".join([*lines, e.detail] if e.detail else lines),
            }
        )
    return {
        "error_rows": rows,
        "error_total": sum(counts.values()),
        "error_kinds": [(k, KIND_LABELS[k], counts.get(k, 0)) for k in KIND_LABELS],
        "error_kind": chosen_kind,
        "error_sort": chosen_sort,
        "error_sorts": list(SORT_LABELS.items()),
    }
