"""OpenRouter 키 없이 쓰는 환경: 요약 서비스와 발송 서비스를 같은 데이터베이스에 묶는다."""

from rss_hub.domain.topics import TopicFields
from rss_hub.services.deliver import DeliveryService
from rss_hub.storage.deliveries import DeliveryRepository
from tests.fakes.delivery_env import FakeWebhookSender
from tests.fakes.llm_env import DEFAULT_WEBHOOK, LlmEnv

GAME_WEBHOOK = "https://discord.com/api/webhooks/333/GAMETOKEN"


class PlainEnv(LlmEnv):
    def __init__(self, tmp_path):
        super().__init__(tmp_path, configured=False)
        self.configure(key=False)
        self.sender = FakeWebhookSender()
        self.sleeps_sent: list[float] = []
        self.deliverer = DeliveryService(
            articles=self.articles,
            feeds=self.feeds,
            deliveries=DeliveryRepository(self.db, self.clock),
            settings=self.settings,
            topics=self.topics,
            sender=self.sender,
            alerts=self.alerts,
            clock=self.clock,
            sleep=self.sleeps_sent.append,
            stop_requested=lambda: False,
        )

    def add_topic(self, name, keywords, *, webhook_url=GAME_WEBHOOK):
        webhook_id = self.settings.add_webhook(name, webhook_url)
        return self.topics.add(TopicFields(name, "", tuple(keywords)), webhook_id=webhook_id)

    def run_pipeline(self):
        self.summarizer.run()
        self.deliverer.run()

    def sent_to(self, url):
        return [c.content for c in self.sender.calls if c.url == url]


__all__ = ["DEFAULT_WEBHOOK", "GAME_WEBHOOK", "PlainEnv"]
