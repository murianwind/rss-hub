"""요약과 호출 예산 테스트 환경: 실제 SQLite + 가짜 시계, 가짜 LLM, 가짜 알림 수신기."""

from datetime import UTC, datetime, timedelta

from rss_hub.services.alerts import AlertService
from rss_hub.services.llm_gateway import LlmGateway
from rss_hub.services.settings import SettingsService
from rss_hub.services.summarize import SummarizeService
from rss_hub.storage.alerts import AlertRepository
from rss_hub.storage.articles import ArticleRepository, NewArticle
from rss_hub.storage.database import Database
from rss_hub.storage.feeds import STATUS_ACTIVE, FeedRepository
from rss_hub.storage.llm_usage import LlmUsageRepository
from rss_hub.storage.topics import TopicRepository
from tests.fakes.clock import FakeClock
from tests.fakes.llm_client import FakeLlmClient, FakeNotifier, good

NOON_UTC = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
KEY = "sk-or-test-1234567890"
SYSTEM_WEBHOOK = "https://discord.com/api/webhooks/111/SYSTEMTOKEN"
DEFAULT_WEBHOOK = "https://discord.com/api/webhooks/222/DEFAULTTOKEN"


class LlmEnv:
    def __init__(self, tmp_path, *, configured: bool = True, progress=lambda done, total: None):
        self.db = Database(tmp_path / "rss_hub.db")
        self.clock = FakeClock(NOON_UTC)
        self.settings = SettingsService(self.db, self.clock)
        self.feeds = FeedRepository(self.db, self.clock)
        self.articles = ArticleRepository(self.db, self.clock)
        self.usage = LlmUsageRepository(self.db, self.clock)
        self.alert_log = AlertRepository(self.db, self.clock)
        self.client = FakeLlmClient(default=good())
        self.notifier = FakeNotifier()
        self.sleeps: list[float] = []
        self.alerts = AlertService(
            alerts=self.alert_log, settings=self.settings, notifier=self.notifier, clock=self.clock
        )
        self.gateway = LlmGateway(
            client=self.client,
            usage=self.usage,
            settings=self.settings,
            alerts=self.alerts,
            clock=self.clock,
            sleep=self.sleeps.append,
        )
        self.topics = TopicRepository(self.db, self.clock)
        self.summarizer = SummarizeService(
            articles=self.articles,
            gateway=self.gateway,
            settings=self.settings,
            topics=self.topics,
            clock=self.clock,
            progress=progress,
        )
        self.settings.update({"model_chain": "model-a,model-b"})
        self.feed_id = self.feeds.add("https://feed.example.com/rss", "피드", status=STATUS_ACTIVE)
        self._counter = 0
        if configured:
            self.configure()

    def configure(self, *, key: bool = True) -> None:
        """요약에 필요한 설정(키, 기본 웹훅, 서비스 주소)과 시스템 알림 웹훅을 채운다.

        key=False이면 OpenRouter 키만 빼고 채운다.
        """
        if key:
            self.settings.set_openrouter_key(KEY)
        default_id = self.settings.add_webhook("기본", DEFAULT_WEBHOOK)
        system_id = self.settings.add_webhook("시스템", SYSTEM_WEBHOOK)
        self.settings.set_webhook_roles(default_id=default_id, system_id=system_id)
        self.settings.update({"service_base_url": "https://rss.example.com"})

    def add_article(
        self,
        *,
        title: str = "Apple unveils new phone",
        content: str = "<p>The phone lasts longer.</p>",
        retry_count: int = 0,
        published: datetime | None = None,
    ) -> int:
        self._counter += 1
        article_id = self.articles.add(
            NewArticle(
                feed_id=self.feed_id,
                guid=f"guid-{self._counter}",
                title=title,
                link=f"https://example.com/{self._counter}",
                content_html=content,
                published_raw="",
                published_dt=published or datetime(2026, 10, 16, 1, 0, self._counter, tzinfo=UTC),
                published_date="2026-10-16",
            )
        )
        assert article_id is not None
        for _ in range(retry_count):
            self.articles.bump_retry(article_id)
        return article_id

    def set_content(self, article_id: int, content_html: str) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE articles SET content_html = ? WHERE id = ?", (content_html, article_id)
            )

    def record_calls(self, count: int, *, model: str = "model-a") -> None:
        """오늘 이미 이만큼 호출했다고 기록한다.

        분당 상한에 걸리지 않게 두 시간 전의 호출로 남긴다. 한 번에 넣어서 빠르다.
        """
        moment = (self.clock.now() - timedelta(hours=2)).astimezone(UTC)
        row = (moment.isoformat(), moment.date().isoformat(), model, "success", 200)
        with self.db.connect() as conn:
            conn.executemany(
                "INSERT INTO llm_usage(called_at, day, model, outcome, status) "
                "VALUES(?, ?, ?, ?, ?)",
                [row] * count,
            )
