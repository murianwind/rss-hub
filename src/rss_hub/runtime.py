"""실제 부품을 조립해서 잡 실행기를 만든다.

테스트에서는 client, sender, fetcher, spawn을 가짜로 바꿔 끼운다.
서비스는 실행할 때마다 설정을 새로 읽으므로, 설정 화면에서 바꾼 값이 재시작 없이 반영된다.
"""

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from rss_hub.adapters.discord_webhook import DiscordNotifier, RequestsWebhookSender
from rss_hub.adapters.http_feed_fetcher import RequestsFeedFetcher
from rss_hub.adapters.openrouter_client import OpenRouterClient
from rss_hub.jobs.runner import IntervalJob, Job, JobRunner, SlotJob, start_thread
from rss_hub.services.alerts import AlertService
from rss_hub.services.clock import Clock
from rss_hub.services.collect import CollectService
from rss_hub.services.deliver import DeliveryService
from rss_hub.services.llm_gateway import LlmGateway
from rss_hub.services.ports import FeedFetcher, LlmClient, WebhookSender
from rss_hub.services.settings import SettingsService
from rss_hub.services.summarize import SummarizeService
from rss_hub.storage.alerts import AlertRepository
from rss_hub.storage.articles import ArticleRepository
from rss_hub.storage.database import Database
from rss_hub.storage.deliveries import DeliveryRepository
from rss_hub.storage.feeds import FeedRepository
from rss_hub.storage.job_runs import JobRunRepository
from rss_hub.storage.llm_usage import LlmUsageRepository
from rss_hub.storage.topics import TopicRepository

JOB_COLLECT = "collect"
JOB_SUMMARIZE = "summarize"
JOB_DELIVER = "deliver"


@dataclass(frozen=True)
class LlmServices:
    alerts: AlertService
    gateway: LlmGateway


def build_llm_services(
    database: Database,
    clock: Clock,
    settings: SettingsService,
    *,
    client: LlmClient,
    sender: WebhookSender,
) -> LlmServices:
    """시스템 알림과 LLM 게이트웨이(호출 예산 포함). 실행기와 웹 화면이 같은 방식으로 쓴다."""
    alerts = AlertService(
        alerts=AlertRepository(database, clock),
        settings=settings,
        notifier=DiscordNotifier(sender),
        clock=clock,
    )
    gateway = LlmGateway(
        client=client,
        usage=LlmUsageRepository(database, clock),
        settings=settings,
        alerts=alerts,
        clock=clock,
    )
    return LlmServices(alerts=alerts, gateway=gateway)


def build_runner(
    database: Database,
    clock: Clock,
    *,
    client: LlmClient | None = None,
    sender: WebhookSender | None = None,
    fetcher: FeedFetcher | None = None,
    spawn: Callable[[Callable[[], None]], Any] = start_thread,
    tick_seconds: float = 1.0,
) -> JobRunner:
    settings = SettingsService(database, clock)
    feeds = FeedRepository(database, clock)
    articles = ArticleRepository(database, clock)
    topics = TopicRepository(database, clock)
    stop = threading.Event()  # 서비스 종료 요청. 실행기와 발송 서비스가 함께 본다

    webhook_sender = sender or RequestsWebhookSender()
    llm = build_llm_services(
        database,
        clock,
        settings,
        client=client or OpenRouterClient(settings.get_openrouter_key),
        sender=webhook_sender,
    )
    alerts, gateway = llm.alerts, llm.gateway
    collector = CollectService(
        feeds=feeds,
        articles=articles,
        fetcher=fetcher or RequestsFeedFetcher(),
        settings=settings,
        clock=clock,
    )
    summarizer = SummarizeService(
        articles=articles, gateway=gateway, settings=settings, topics=topics, clock=clock
    )
    deliverer = DeliveryService(
        articles=articles,
        feeds=feeds,
        deliveries=DeliveryRepository(database, clock),
        settings=settings,
        topics=topics,
        sender=webhook_sender,
        alerts=alerts,
        clock=clock,
        stop_requested=stop.is_set,
    )
    jobs: list[Job] = [
        SlotJob(
            JOB_COLLECT, collector.run_slot, lambda: settings.snapshot().collect_interval_minutes
        ),
        IntervalJob(
            JOB_SUMMARIZE, summarizer.run, lambda: settings.snapshot().summarize_interval_seconds
        ),
        IntervalJob(
            JOB_DELIVER, deliverer.run, lambda: settings.snapshot().deliver_interval_seconds
        ),
    ]
    return JobRunner(
        jobs=jobs,
        clock=clock,
        records=JobRunRepository(database, clock),
        timezone=lambda: settings.snapshot().timezone,
        spawn=spawn,
        stop_event=stop,
        tick_seconds=tick_seconds,
    )
