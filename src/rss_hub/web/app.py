"""FastAPI 앱: 상태, 설정 화면과 /healthz.

설정은 환경 변수가 아니라 화면에서 하고 DB에 저장한다. 앱을 만들 때는 디스크를 건드리지 않고,
DB는 처음 필요할 때 만들어진다.
"""

import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from rss_hub.adapters.discord_webhook import RequestsWebhookSender
from rss_hub.adapters.http_feed_fetcher import RequestsFeedFetcher
from rss_hub.adapters.openrouter_client import OpenRouterClient
from rss_hub.jobs.runner import JobRunner, start_thread
from rss_hub.runtime import build_llm_services
from rss_hub.services.backup import BackupService
from rss_hub.services.clock import Clock, SystemClock
from rss_hub.services.collect import CollectService
from rss_hub.services.feed_registration import FeedRegistrationService
from rss_hub.services.fulltext import FullTextService
from rss_hub.services.importer import ImportService
from rss_hub.services.model_benchmark import BenchmarkRunner, BenchmarkService
from rss_hub.services.model_chain import ModelChainService
from rss_hub.services.model_scan import ModelScanService
from rss_hub.services.page_source import PageFeedSource
from rss_hub.services.ports import DiscoveryFetcher, LlmClient, PageFetcher, WebhookSender
from rss_hub.services.settings import SettingsService
from rss_hub.services.topic_probe import TopicProbe
from rss_hub.storage.articles import ArticleRepository
from rss_hub.storage.backup import BackupRepository
from rss_hub.storage.database import Database
from rss_hub.storage.feeds import FeedRepository
from rss_hub.storage.import_staging import ImportStagingRepository
from rss_hub.storage.job_runs import JobRunRepository
from rss_hub.storage.llm_usage import LlmUsageRepository
from rss_hub.storage.models import ModelRepository
from rss_hub.storage.ordering import OrderRepository
from rss_hub.storage.overview import OverviewRepository
from rss_hub.storage.reader import ReaderRepository
from rss_hub.storage.topics import TopicRepository
from rss_hub.version import get_version
from rss_hub.web.admin import build_admin_router
from rss_hub.web.articles import build_article_router
from rss_hub.web.backup import build_backup_router
from rss_hub.web.categories import build_category_router
from rss_hub.web.feedback import build_feedback_router
from rss_hub.web.feeds import build_feed_router
from rss_hub.web.health import data_dir_is_writable
from rss_hub.web.importer import build_import_router
from rss_hub.web.live import build_live_router
from rss_hub.web.models import build_model_router
from rss_hub.web.ordering import build_ordering_router
from rss_hub.web.panels import build_panel_router
from rss_hub.web.reader import build_reader_router
from rss_hub.web.reading import build_reading_router
from rss_hub.web.security import SAFE_METHODS, SECURITY_HEADERS, request_is_same_origin
from rss_hub.web.topics import build_topic_router
from rss_hub.web.ui import (
    DELETE_NOTES,
    FAIL_NOTES,
    ModelUsageView,
    ago,
    build_ui_context,
    icon,
    qs,
    sprite,
)

logger = logging.getLogger(__name__)

STALE_MINUTES = 15  # 수집이 이만큼 멈춰 있으면 /healthz가 503으로 답한다
SHUTDOWN_WAIT_SECONDS = 30.0
DEFAULT_DATA_DIR = Path("/data")
DATABASE_FILENAME = "rss_hub.db"
TEMPLATE_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"
REJECTED_MESSAGE = "요청이 거부되었습니다(출처가 다릅니다)."


def _lifespan(
    topics: TopicRepository, models: ModelRepository, runner: JobRunner | None
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    """서버 시작과 종료 때 할 일: 기본 주제 만들기, 끊긴 벤치마크 정리, 잡 시작과 종료."""

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # 서버가 실제로 시작될 때 처음 설치용 기본 주제(OTT)를 만든다.
        # 앱을 만드는 것만으로는 디스크를 건드리지 않는다(/healthz가 파일을 만들지 않게).
        try:
            topics.ensure_defaults()
        except Exception:
            logger.exception(
                "기본 주제를 만들지 못했습니다"
            )  # 데이터 폴더 문제는 /healthz가 알린다
        try:
            models.interrupt_stale_runs()  # 서비스가 꺼지면서 끝나지 못한 벤치마크를 정리한다
        except Exception:
            logger.exception("중단된 벤치마크를 정리하지 못했습니다")
        if runner is not None:
            runner.start()
        try:
            yield
        finally:
            if runner is not None:  # 진행 중인 작업(발송 등)을 끝내고 멈춘다
                runner.shutdown(SHUTDOWN_WAIT_SECONDS)

    return lifespan


def _install_protection(app: FastAPI) -> None:
    """다른 사이트에서 온 상태 변경 요청을 막고, 응답에 캐시 규칙과 보안 헤더를 붙인다."""

    @app.middleware("http")
    async def protect(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method not in SAFE_METHODS and not request_is_same_origin(request.headers):
            response: Response = PlainTextResponse(REJECTED_MESSAGE, status_code=403)
        else:
            response = await call_next(request)
        if request.url.path.startswith("/static/"):
            # 주소에 버전(?v=)이 붙어 있어서 오래 캐시해도 새 버전이 나오면 새로 받는다
            response.headers["Cache-Control"] = "public, max-age=3600"
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response


def _add_service_routes(
    app: FastAPI,
    *,
    data_dir: Path,
    runner: JobRunner | None,
    job_runs: JobRunRepository,
    service: SettingsService,
    clock: Clock,
    created_at: datetime,
) -> None:
    """첫 화면 이동(/)과 상태 확인(/healthz)."""

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        """처음 접속하면 글 목록을 보여 준다(상태 화면은 /status)."""
        return RedirectResponse("/reader", status_code=307)

    @app.get("/healthz")
    def healthz(response: Response) -> dict[str, str | None]:
        if not data_dir_is_writable(data_dir):
            response.status_code = 503
            return {"status": "error", "reason": "data_dir_not_writable"}
        body: dict[str, str | None] = {"status": "ok", "version": get_version()}
        if runner is None:
            return body
        runs = job_runs.all()
        for name in ("collect", "summarize", "deliver"):
            ok_at = runs[name].last_ok_at if name in runs else None
            body[f"last_{name}"] = None if ok_at is None else ok_at.isoformat()
        # 수집이 오래 멈춰 있으면 컨테이너를 비정상으로 표시한다.
        # 방금 시작해서 아직 한 번도 안 돌았다면 시작 시각을 기준으로 한다.
        interval = service.snapshot().collect_interval_minutes
        limit = timedelta(minutes=max(STALE_MINUTES, 3 * interval))
        last_ok = runs["collect"].last_ok_at if "collect" in runs else None
        if clock.now() - (last_ok or created_at) > limit:
            response.status_code = 503
            body["status"] = "stale"
        return body


def create_app(
    data_dir: Path = DEFAULT_DATA_DIR,
    clock: Clock | None = None,
    *,
    runner_factory: Callable[[Database, Clock], JobRunner] | None = None,
    webhook_sender: WebhookSender | None = None,
    llm_client: LlmClient | None = None,
    feed_fetcher: DiscoveryFetcher | None = None,
    page_fetcher: PageFetcher | None = None,
    benchmark_spawn: Callable[[Callable[[], None]], object] | None = None,
    benchmark_sleep: Callable[[float], None] | None = None,
) -> FastAPI:
    # 인증 없이 외부에 열리는 서비스라서 API 문서 화면과 스키마는 내놓지 않는다
    app = FastAPI(title="RSS Hub", docs_url=None, redoc_url=None, openapi_url=None)

    database = Database(data_dir / DATABASE_FILENAME)
    app_clock = clock or SystemClock()
    service = SettingsService(database, app_clock)
    app.state.settings_service = service
    templates = Jinja2Templates(directory=TEMPLATE_DIR)
    templates.env.globals.update(
        icon=icon, sprite=sprite, delete_notes=DELETE_NOTES, fail_notes=FAIL_NOTES
    )
    templates.env.filters["ago"] = ago
    templates.env.filters["qs"] = qs
    articles = ArticleRepository(database, app_clock)
    feeds = FeedRepository(database, app_clock)
    job_runs = JobRunRepository(database, app_clock)
    sender = webhook_sender or RequestsWebhookSender()
    client = llm_client or OpenRouterClient(service.get_openrouter_key)
    topics = TopicRepository(database, app_clock)
    llm = build_llm_services(database, app_clock, service, client=client, sender=sender)
    app.include_router(
        build_admin_router(
            service,
            templates,
            articles,
            feeds=feeds,
            job_runs=job_runs,
            usage=LlmUsageRepository(database, app_clock),
            clock=app_clock,
            sender=sender,
            runner=lambda: app.state.runner,
        )
    )
    app.include_router(build_article_router(articles))
    app.include_router(
        build_backup_router(
            BackupService(BackupRepository(database, app_clock), app_clock, get_version()),
            templates,
        )
    )
    models = ModelRepository(database, app_clock)
    benchmark_runner = BenchmarkRunner(
        service=BenchmarkService(
            gateway=llm.gateway, models=models, sleep=benchmark_sleep or time.sleep
        ),
        models=models,
        spawn=benchmark_spawn or start_thread,
    )
    app.include_router(
        build_model_router(
            models=models,
            scanner=ModelScanService(
                client=client, models=models, settings=service, alerts=llm.alerts
            ),
            runner=benchmark_runner,
            chain=ModelChainService(settings=service, models=models, alerts=llm.alerts),
            settings=service,
            templates=templates,
            llm_client=client,
        )
    )
    app.include_router(build_feedback_router(topics=topics, articles=articles))
    reader = ReaderRepository(database, app_clock)
    model_usage = ModelUsageView(
        usage=LlmUsageRepository(database, app_clock),
        settings=service,
        clock=app_clock,
        client=client,
    )
    templates.context_processors.append(
        build_ui_context(
            reader=reader,
            settings=service,
            clock=app_clock,
            version=get_version(),
            model_usage=model_usage,
        )
    )
    app.include_router(build_reading_router(articles=articles, reader=reader))
    app.include_router(build_ordering_router(orders=OrderRepository(database), feeds=feeds))
    app.include_router(
        build_panel_router(feeds=feeds, topics=topics, settings=service, templates=templates)
    )
    fetcher = feed_fetcher or RequestsFeedFetcher()
    fulltext = FullTextService(articles=articles, pages=page_fetcher or fetcher)
    app.include_router(
        build_reader_router(
            reader=reader,
            feeds=feeds,
            topics=topics,
            articles=articles,
            settings=service,
            templates=templates,
            fulltext=fulltext,
        )
    )
    importer = ImportService(
        feeds=feeds, staging=ImportStagingRepository(database, app_clock), clock=app_clock
    )
    app.state.importer = importer
    app.state.topics = topics
    runner = runner_factory(database, app_clock) if runner_factory else None
    app.state.runner = runner
    created_at = app_clock.now()

    app.router.lifespan_context = _lifespan(topics, models, runner)
    app.include_router(build_import_router(importer, templates))
    probe = TopicProbe(
        gateway=llm.gateway,
        topics=topics,
        clock=app_clock,
        examples_count=lambda: service.snapshot().topic_feedback_examples,
    )
    app.include_router(build_topic_router(topics, service, templates, probe))
    app.include_router(build_category_router(feeds, service, templates))
    registration = FeedRegistrationService(fetcher=fetcher, feeds=feeds)
    page_source = PageFeedSource(pages=page_fetcher or fetcher, clock=app_clock)
    collector = CollectService(
        feeds=feeds,
        articles=articles,
        fetcher=fetcher,
        settings=service,
        clock=app_clock,
        pages=page_source,
    )
    app.include_router(
        build_live_router(reader=reader, feeds=feeds, collector=collector, model_usage=model_usage)
    )
    app.include_router(
        build_feed_router(
            feeds, service, templates, registration, OverviewRepository(database), app_clock
        )
    )

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    _install_protection(app)

    _add_service_routes(
        app,
        data_dir=data_dir,
        runner=runner,
        job_runs=job_runs,
        service=service,
        clock=app_clock,
        created_at=created_at,
    )
    return app
