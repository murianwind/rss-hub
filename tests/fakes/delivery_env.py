"""발송 테스트 환경: 실제 SQLite + 가짜 시계, 가짜 웹훅 전송기, 가짜 알림 수신기."""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from rss_hub.domain.keywords import DEFAULT_OTT_KEYWORDS
from rss_hub.domain.topics import TopicFields
from rss_hub.services.alerts import AlertService
from rss_hub.services.deliver import DeliveryService
from rss_hub.services.ports import SendResult
from rss_hub.services.settings import SettingsService
from rss_hub.storage.alerts import AlertRepository
from rss_hub.storage.articles import ArticleRepository, NewArticle
from rss_hub.storage.database import Database
from rss_hub.storage.deliveries import DeliveryRepository
from rss_hub.storage.feeds import STATUS_ACTIVE, FeedRepository
from rss_hub.storage.topics import TopicRepository
from tests.fakes.clock import FakeClock
from tests.fakes.llm_client import FakeNotifier

KST_14_00 = datetime(2026, 10, 16, 5, 0, tzinfo=UTC)
BASE_URL = "https://rss.example.com"
WEBHOOK_NAMES = ("rss", "ott", "gizmodo", "dev", "시스템")


def webhook_url(name: str) -> str:
    index = WEBHOOK_NAMES.index(name) + 1
    return f"https://discord.com/api/webhooks/{index}00/TOKEN{index}SECRET"


def ok(
    message_id: str = "m", remaining: int | None = 4, reset_after: float | None = 1.0
) -> SendResult:
    return SendResult(
        200, rate_remaining=remaining, rate_reset_after=reset_after, message_id=message_id
    )


@dataclass
class SentMessage:
    url: str
    content: str


@dataclass
class FakeWebhookSender:
    """웹훅 주소마다 "다음에 돌려줄 결과"를 줄 세워 둔다. 줄이 비면 성공을 돌려준다."""

    queues: dict[str, list[SendResult | Exception]] = field(default_factory=dict)
    calls: list[SentMessage] = field(default_factory=list)
    counter: int = 0

    def will(self, url: str, *results: SendResult | Exception) -> None:
        self.queues.setdefault(url, []).extend(results)

    def send(self, webhook_url: str, content: str) -> SendResult:
        self.calls.append(SentMessage(webhook_url, content))
        queue = self.queues.get(webhook_url)
        if queue:
            outcome = queue.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        self.counter += 1
        return ok(f"message-{self.counter}", remaining=4, reset_after=1.0)

    def to(self, name: str) -> list[str]:
        return [c.content for c in self.calls if c.url == webhook_url(name)]


class DeliveryEnv:
    def __init__(self, tmp_path, *, register_webhooks: bool = True, system_webhook: bool = True):
        self.db = Database(tmp_path / "rss_hub.db")
        self.clock = FakeClock(KST_14_00)
        self.settings = SettingsService(self.db, self.clock)
        self.feeds = FeedRepository(self.db, self.clock)
        self.articles = ArticleRepository(self.db, self.clock)
        self.deliveries = DeliveryRepository(self.db, self.clock)
        self.topics = TopicRepository(self.db, self.clock)
        self.sender = FakeWebhookSender()
        self.notifier = FakeNotifier()
        self.sleeps: list[float] = []
        self.stop_flag = False  # True가 되면 발송 서비스가 다음 글부터 보내지 않는다
        self.alerts = AlertService(
            alerts=AlertRepository(self.db, self.clock),
            settings=self.settings,
            notifier=self.notifier,
            clock=self.clock,
        )
        self.service = DeliveryService(
            articles=self.articles,
            feeds=self.feeds,
            deliveries=self.deliveries,
            settings=self.settings,
            topics=self.topics,
            sender=self.sender,
            alerts=self.alerts,
            clock=self.clock,
            sleep=self.sleeps.append,
            stop_requested=lambda: self.stop_flag,
        )
        self.webhooks: dict[str, int] = {}
        self.settings.update({"service_base_url": BASE_URL})
        if register_webhooks:
            for name in WEBHOOK_NAMES:
                self.webhooks[name] = self.settings.add_webhook(name, webhook_url(name))
            self.settings.set_webhook_roles(
                default_id=self.webhooks["rss"],
                system_id=self.webhooks["시스템"] if system_webhook else None,
            )
            # 기본 주제 "OTT": 기본 키워드, 웹훅은 "ott"
            self.add_topic(
                "OTT", (*DEFAULT_OTT_KEYWORDS.ko, *DEFAULT_OTT_KEYWORDS.en), webhook="ott"
            )
        self.feed_id = self.add_feed()
        self._counter = 0

    def add_topic(self, name, keywords=(), *, webhook=None, enabled=True, description=""):
        webhook_id = self.webhooks[webhook] if webhook else None
        return self.topics.add(
            TopicFields(name, description, tuple(keywords)), webhook_id=webhook_id, enabled=enabled
        )

    def topic_id(self, name):
        return next(t.id for t in self.topics.list_all() if t.name == name)

    def add_feed(self, name="Blog", *, emoji="📢", category=None, webhook=None):
        options = {"emoji": emoji, "status": STATUS_ACTIVE}
        if webhook:
            options["webhook_id"] = self.webhooks[webhook]
        if category is not None:
            options["category_id"] = category
        url = f"https://{name.lower()}.example.com/rss"
        return self.feeds.add(url, name, **options)

    def add_ready_article(
        self,
        *,
        feed_id: int | None = None,
        title: str = "Original title",
        title_ko: str = "새 아이폰 배터리",
        summary_ko: str = "배터리가 커졌다.",
        topics: tuple[str, ...] = (),
        content: str = "<p>plain text</p>",
        published: datetime | None = None,
        status: str = "ready",
    ) -> int:
        self._counter += 1
        article_id = self.articles.add(
            NewArticle(
                feed_id=feed_id or self.feed_id,
                guid=f"guid-{self._counter}",
                title=title,
                link=f"https://example.com/original/{self._counter}",
                content_html=content,
                published_raw="",
                published_dt=published or datetime(2026, 10, 16, 5, 32, tzinfo=UTC),
                published_date="2026-10-16",
            )
        )
        assert article_id is not None
        if status == "ready":
            self.articles.mark_ready(
                article_id,
                title_ko=title_ko,
                summary_ko=summary_ko,
                topics=[self.topic_id(name) for name in topics],
                model="model-a",
            )
        return article_id

    def article(self, article_id: int):
        return self.articles.get(article_id)

    def statuses(self, article_id: int) -> dict[str, str]:
        """ "웹훅이름:용도" -> 상태. 주제 용도는 "topic:주제이름"으로 보여 준다."""
        names = {v: k for k, v in self.webhooks.items()}
        topic_names = {t.id: t.name for t in self.topics.list_all()}
        result = {}
        for d in self.deliveries.for_article(article_id):
            purpose = d.purpose
            if purpose.startswith("topic:"):
                purpose = f"topic:{topic_names[int(purpose.split(':')[1])]}"
            result[f"{names[d.webhook_id]}:{purpose}"] = d.status
        return result
