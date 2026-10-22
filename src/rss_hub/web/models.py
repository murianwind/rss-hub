"""모델 화면: 키와 호출 한도, 스캔, 벤치마크(진행 상황), 추천, 끌어다 놓아 바꾸는 체인."""

from collections.abc import Sequence
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from rss_hub.domain.benchmark import (
    SAMPLES,
    describe_error,
    explain_score,
    format_tokens,
    recommend,
)
from rss_hub.services.model_benchmark import MAX_MODELS, BenchmarkRunner
from rss_hub.services.model_chain import MAX_CHAIN, ModelChainService
from rss_hub.services.model_scan import ModelScanService
from rss_hub.services.ports import KeyCheck, LlmClient
from rss_hub.services.settings import SETTING_BY_KEY, SettingsService
from rss_hub.storage.models import (
    CALL_FAILED,
    CALL_OK,
    CALL_SKIPPED,
    RUN_RUNNING,
    CallRecord,
    ModelRepository,
    RunInfo,
)
from rss_hub.web.setting_groups import keys_of, sections
from rss_hub.web.ui import done

CONFIRM_MESSAGE = "교체하려면 확인란을 선택해 주세요"
DELETE_CONFIRM_MESSAGE = "삭제 확인이 필요합니다"


def _cell(index: int, record: CallRecord | None, *, running: bool) -> dict[str, Any]:
    """시험 글 하나의 칸. 기록이 없으면 대기, 지금 부르는 칸이면 진행 중이다."""
    title = SAMPLES[index].title
    if record is None:
        return {
            "n": index + 1,
            "title": title,
            "state": "running" if running else "pending",
            "latency_ms": None,
            "reason": "",
            "detail": "",
        }
    info = describe_error(record.error) if record.state != CALL_OK else None
    state = {CALL_OK: "ok", CALL_FAILED: "failed", CALL_SKIPPED: "skipped"}[record.state]
    return {
        "n": index + 1,
        "title": title,
        "state": state,
        "latency_ms": record.latency_ms,
        "reason": "" if info is None else info.label,
        "detail": "" if info is None else info.explanation,
    }


def progress_view(run: RunInfo | None, calls: Sequence[CallRecord]) -> dict[str, Any]:
    """진행 패널과 /models/benchmark/progress가 함께 쓰는 모양(모델마다 시험 글 칸)."""
    if run is None:
        return {"running": False, "status": "", "done": 0, "total": 0, "note": "", "models": []}
    by_cell = {(c.model, c.index): c for c in calls}
    running = run.status == RUN_RUNNING
    marked = False  # 진행 중 칸은 전체에서 하나만
    models = []
    for model in run.models:
        cells = []
        for index in range(len(SAMPLES)):
            record = by_cell.get((model, index))
            current = running and record is None and not marked
            marked = marked or current
            cells.append(_cell(index, record, running=current))
        models.append({"model": model, "cells": cells})
    return {
        "running": running,
        "status": run.status,
        "done": run.done,
        "total": run.total,
        "note": run.note,
        "models": models,
    }


def _key_result(check: KeyCheck) -> tuple[str, str]:
    """저장 전에 키를 확인한 결과(채팅 호출이 아니라서 호출 한도를 쓰지 않는다)."""
    if check.valid:
        usage = (
            f"(오늘 무료 모델 호출 {check.used}/{check.limit})"
            if check.used is not None and check.limit is not None
            else ""
        )
        return "ok", f"저장했습니다 · 키가 유효합니다{usage}"
    kind = "error" if check.valid is False else "warn"
    return kind, f"키 확인에 실패해 저장하지 않았습니다: {check.reason}"


def build_model_router(
    *,
    models: ModelRepository,
    scanner: ModelScanService,
    runner: BenchmarkRunner,
    chain: ModelChainService,
    settings: SettingsService,
    templates: Jinja2Templates,
    llm_client: LlmClient,
) -> APIRouter:
    router = APIRouter()
    limit_keys = keys_of("모델 체인과 호출 한도")

    def page(
        request: Request,
        *,
        notice: str = "",
        error: str = "",
        status_code: int = 200,
        form_values: dict[str, str] | None = None,
        errors: dict[str, str] | None = None,
        test_result: tuple[str, str] | None = None,
    ) -> HTMLResponse:
        config = settings.snapshot()
        catalog = models.catalog()
        scores = models.latest_scores()
        in_catalog = {e.id for e in catalog}
        scored = [score for model, (score, _) in scores.items() if model in in_catalog]
        run = models.latest_run()
        explained = {
            m: {
                "explanation": explain_score(s),
                "when": t.astimezone(config.timezone).strftime("%m-%d %H:%M"),
            }
            for m, (s, t) in scores.items()
        }
        context = {
            "chain": config.model_chain,
            "catalog": [
                {
                    "id": e.id,
                    "context": format_tokens(e.context_length),
                    "json": e.supports_json,
                    "result": explained.get(e.id),
                }
                for e in catalog
            ],
            "chain_hints": {m: explained[m] for m in config.model_chain if m in explained},
            "progress": progress_view(run, models.calls(run.id) if run else ()),
            "max_chain": MAX_CHAIN,
            "recommendation": recommend(scored, config.model_chain) if scored else None,
            "run": run,
            "running": run is not None and run.status == RUN_RUNNING,
            "max_models": MAX_MODELS,
            "calls_per_model": len(SAMPLES),
            "notice": notice,
            "error": error,
            "test_result": test_result,
            "has_key": settings.has_openrouter_key(),
            "chain_sections": [("", [SETTING_BY_KEY["model_chain"]])],
            "limit_sections": [
                ("", [d for d in sections("모델 체인과 호출 한도")[0][1] if d.key != "model_chain"])
            ],
            "values": {**settings.raw_values(), **(form_values or {})},
            "errors": errors or {},
        }
        return templates.TemplateResponse(request, "models.html", context, status_code=status_code)

    @router.get("/models", response_class=HTMLResponse)
    def model_page(
        request: Request, started: str = "", applied: str = "", saved: str = ""
    ) -> HTMLResponse:
        notice = (
            "벤치마크를 시작했습니다. 진행 상황은 아래 패널에서 바로 볼 수 있습니다."
            if started
            else "모델 체인을 바꿨습니다."
            if applied
            else "저장했습니다"
            if saved
            else ""
        )
        return page(request, notice=notice)

    @router.get("/models/benchmark/progress")
    def benchmark_progress() -> dict[str, Any]:
        run = models.latest_run()
        return progress_view(run, models.calls(run.id) if run else ())

    @router.post("/models/settings", response_class=HTMLResponse)
    async def save_limits(request: Request) -> Response:
        form = await request.form()
        submitted = {k: str(v) for k, v in form.items() if k in limit_keys}
        result = settings.update(submitted)
        if result.errors:
            return page(request, status_code=400, form_values=submitted, errors=result.errors)
        return done(form, "/models?saved=1", "saved")

    @router.post("/settings/openrouter-key", response_class=HTMLResponse)
    async def save_key(request: Request) -> Response:
        form = await request.form()
        candidate = str(form.get("openrouter_key", "")).strip()
        wants_json = "application/json" in request.headers.get("accept", "")
        kind, message = (
            ("error", "값이 비어 있음")
            if not candidate
            else _key_result(llm_client.check_key(candidate))
        )
        saved = kind == "ok"
        if saved:
            settings.set_openrouter_key(candidate)
        if wants_json:
            return JSONResponse({"ok": saved, "kind": kind, "message": message})
        if not candidate:
            return page(request, error=message, status_code=400)
        return page(request, test_result=(kind, message))

    @router.post("/settings/openrouter-key/delete", response_class=HTMLResponse)
    async def delete_key(request: Request) -> Response:
        form = await request.form()
        if form.get("confirm") != "yes":
            return page(request, error=DELETE_CONFIRM_MESSAGE, status_code=400)
        settings.delete_openrouter_key()
        return done(form, "/models?saved=1", "saved")

    @router.post("/models/scan", response_class=HTMLResponse)
    async def scan(request: Request) -> Response:
        report = scanner.scan()
        if not report.ok:
            return page(request, error=report.error, status_code=502)
        parts = [f"무료 텍스트 모델 {len(report.models)}개"]
        if report.first_scan:
            parts.append("처음 스캔했습니다")
        else:
            parts.append(
                f"새로 보인 모델 {len(report.diff.new)}개, 사라진 모델 {len(report.diff.gone)}개"
            )
        notice = " · ".join(parts)
        if report.chain_missing:
            notice += " · 지금 체인의 모델이 무료 목록에 없습니다: " + ", ".join(
                report.chain_missing
            )
        return page(request, notice=notice)

    @router.post("/models/benchmark", response_class=HTMLResponse)
    async def benchmark(request: Request) -> Response:
        form = await request.form()
        result = runner.start([str(v) for v in form.getlist("models")])
        if result.status == "started":
            return RedirectResponse("/models?started=1", status_code=303)
        return page(
            request, error=result.message, status_code=409 if result.status == "busy" else 400
        )

    @router.post("/models/apply", response_class=HTMLResponse)
    async def apply(request: Request) -> Response:
        form = await request.form()
        if form.get("confirm") != "yes":
            return page(request, error=CONFIRM_MESSAGE, status_code=400)
        result = chain.apply([str(v) for v in form.getlist("chain")])
        if not result.ok:
            return page(request, error=result.error, status_code=400)
        return RedirectResponse("/models?applied=1", status_code=303)

    return router
