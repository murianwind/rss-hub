"""조립한 잡 실행기(runtime.build_runner)를 가짜 어댑터로 시험하는 환경.

수집, 요약, 발송이 실제 서비스와 저장소로 이어져서 한 틱 안에 글 하나가 끝까지 흘러간다.
"""

from datetime import UTC, datetime, timedelta, timezone

from rss_hub.domain.schedule import PRIORITY_EVERY_SLOT
from rss_hub.runtime import build_runner
from rss_hub.services.settings import SettingsService
from rss_hub.storage.articles import ArticleRepository
from rss_hub.storage.database import Database
from rss_hub.storage.feeds import STATUS_ACTIVE, FeedRepository
from rss_hub.storage.job_runs import JobRunRepository
from rss_hub.storage.topics import TopicRepository
from tests.fakes.clock import FakeClock
from tests.fakes.delivery_env import FakeWebhookSender, webhook_url
from tests.fakes.entries import entry
from tests.fakes.feed_fetcher import FakeFeedFetcher
from tests.fakes.llm_client import FakeLlmClient, reply

KST = timezone(timedelta(hours=9))
START = datetime(2026, 10, 16, 14, 0, 0, tzinfo=KST).astimezone(UTC)  # 14:00 KST
FEED_URL = "https://feed.example.com/rss"
BASE_URL = "https://rss.example.com"


class RuntimeEnv:
    def __init__(
        self, tmp_path, *, configured=True, start=START, priority=PRIORITY_EVERY_SLOT, spawn=None
    ):
        self.db = Database(tmp_path / "rss_hub.db")
        self.clock = FakeClock(start)
        self.settings = SettingsService(self.db, self.clock)
        self.feeds = FeedRepository(self.db, self.clock)
        self.articles = ArticleRepository(self.db, self.clock)
        self.topics = TopicRepository(self.db, self.clock)
        self.records = JobRunRepository(self.db, self.clock)
        self.fetcher = FakeFeedFetcher()
        self.client = FakeLlmClient(default=reply("애플, 새 폰 공개", "애플이 새 폰을 공개했다."))
        self.sender = FakeWebhookSender()
        self.webhooks: dict[str, int] = {}
        # 기본은 작업을 그 자리에서 실행한다. 실행 중인 채로 남기려면 spawn에 다른 방식을 준다
        self._spawn = spawn or (lambda fn: fn())
        self.runner = self.new_runner()
        self.settings.update({"model_chain": "model-a"})
        if configured:
            self.configure()
        # 기본은 "매 슬롯 점검" 피드: 보통 피드는 한 시간에 한 번(자기 슬롯)만 점검된다
        self.feed_id = self.feeds.add(
            FEED_URL, "예시 블로그", status=STATUS_ACTIVE, poll_priority=priority
        )

    def new_runner(self):
        return build_runner(
            self.db,
            self.clock,
            client=self.client,
            sender=self.sender,
            fetcher=self.fetcher,
            spawn=self._spawn,
        )

    def restart(self):
        """서비스를 다시 시작한다: 같은 데이터베이스로 새 실행기를 만든다."""
        self.runner = self.new_runner()
        return self.runner

    def configure(self) -> None:
        """요약과 발송에 필요한 설정(키, 기본 웹훅, 서비스 주소)을 채운다."""
        self.settings.set_openrouter_key("sk-or-test-key-123456")
        self.webhooks["rss"] = self.settings.add_webhook("rss", webhook_url("rss"))
        self.webhooks["시스템"] = self.settings.add_webhook("시스템", webhook_url("시스템"))
        self.settings.set_webhook_roles(
            default_id=self.webhooks["rss"], system_id=self.webhooks["시스템"]
        )
        self.settings.update({"service_base_url": BASE_URL})

    def serve_new_article(self, guid="new-1", title="Apple unveils new phone"):
        item = entry(guid=guid, title=title)
        self.fetcher.serve(FEED_URL, [item])
        return item

    def tick(self, *, seconds=0, minutes=0):
        self.clock.advance(seconds=seconds, minutes=minutes)
        return self.runner.tick()
