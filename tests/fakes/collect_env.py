"""수집 서비스 테스트에 쓰는 환경: 실제 SQLite 임시 파일 + 가짜 시계와 가짜 수집기."""

from datetime import UTC, datetime

from rss_hub.services.collect import CollectService
from rss_hub.services.settings import SettingsService
from rss_hub.storage.articles import STATUS_COLLECTED, ArticleRepository
from rss_hub.storage.database import Database
from rss_hub.storage.feeds import STATUS_ACTIVE, FeedRepository
from tests.fakes.clock import FakeClock
from tests.fakes.feed_fetcher import FakeFeedFetcher

KST_14_00 = datetime(2026, 10, 16, 5, 0, tzinfo=UTC)  # 서비스 시간대(Asia/Seoul)로 14:00


class CollectEnv:
    def __init__(self, tmp_path):
        self.db = Database(tmp_path / "rss_hub.db")
        self.clock = FakeClock(KST_14_00)
        self.settings = SettingsService(self.db, self.clock)
        self.feeds = FeedRepository(self.db, self.clock)
        self.articles = ArticleRepository(self.db, self.clock)
        self.fetcher = FakeFeedFetcher()
        self.service = CollectService(
            feeds=self.feeds,
            articles=self.articles,
            fetcher=self.fetcher,
            settings=self.settings,
            clock=self.clock,
        )

    def add_feed(self, n=1, *, status=STATUS_ACTIVE, **options):
        url = f"https://feed{n}.example.com/rss"
        feed_id = self.feeds.add(url, f"피드{n}", status=status, **options)
        return feed_id, url

    def collect(self, *feed_ids):
        feeds = [self.feeds.get(i) for i in feed_ids]
        return self.service.collect_feeds([f for f in feeds if f is not None])

    def collected(self):
        return self.articles.list_by_status(STATUS_COLLECTED)
