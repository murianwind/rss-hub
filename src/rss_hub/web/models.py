"""모델 화면: 무료 모델 스캔, 벤치마크, 추천, 승인 후 체인 교체."""

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from rss_hub.domain.benchmark import SAMPLES, recommend
from rss_hub.services.model_benchmark import MAX_MODELS, BenchmarkRunner
from rss_hub.services.model_chain import ModelChainService
from rss_hub.services.model_scan import ModelScanService
from rss_hub.services.settings import SettingsService
from rss_hub.storage.models import RUN_RUNNING, ModelRepository

CONFIRM_MESSAGE = "교체하려면 확인란을 선택해 주세요"


def build_model_router(
    *,
    models: ModelRepository,
    scanner: ModelScanService,
    runner: BenchmarkRunner,
    chain: ModelChainService,
    settings: SettingsService,
    templates: Jinja2Templates,
) -> APIRouter:
    router = APIRouter()

    def page(
        request: Request, *, notice: str = "", error: str = "", status_code: int = 200
    ) -> HTMLResponse:
        config = settings.snapshot()
        catalog = models.catalog()
        scores = models.latest_scores()
        in_catalog = {e.id for e in catalog}
        scored = [score for model, (score, _) in scores.items() if model in in_catalog]
        run = models.latest_run()
        context = {
            "chain": config.model_chain,
            "catalog": catalog,
            "scores": {
                m: (s, t.astimezone(config.timezone).strftime("%m-%d %H:%M"))
                for m, (s, t) in scores.items()
            },
            "recommendation": recommend(scored, config.model_chain) if scored else None,
            "run": run,
            "running": run is not None and run.status == RUN_RUNNING,
            "max_models": MAX_MODELS,
            "calls_per_model": len(SAMPLES),
            "notice": notice,
            "error": error,
        }
        return templates.TemplateResponse(request, "models.html", context, status_code=status_code)

    @router.get("/models", response_class=HTMLResponse)
    def model_page(request: Request, started: str = "", applied: str = "") -> HTMLResponse:
        notice = (
            "벤치마크를 시작했습니다. 이 화면은 5초마다 새로고침됩니다."
            if started
            else "모델 체인을 바꿨습니다."
            if applied
            else ""
        )
        return page(request, notice=notice)

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
