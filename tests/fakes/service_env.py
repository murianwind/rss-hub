"""웹 서비스 엔드포인트 시험 환경: 가짜 실행기를 단 앱, 데이터베이스, 작업 실행 기록."""

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from rss_hub.storage.articles import ArticleRepository, NewArticle
from rss_hub.storage.database import Database
from rss_hub.storage.feeds import FeedRepository
from rss_hub.storage.job_runs import JobRunRepository
from rss_hub.web.app import create_app
from tests.fakes.clock import FakeClock

BASE = "https://rss.example.com"
WEBHOOK = "https://discord.com/api/webhooks/9/SECRETWEBHOOKTOKEN"
KEY = "sk-or-v1-SECRETAPIKEYVALUE"


class FakeRunner:
    def __init__(self):
        self.started = 0
        self.shutdowns: list[float] = []

    def start(self):
        self.started += 1

    def shutdown(self, timeout):
        self.shutdowns.append(timeout)
        return True

    def progress_of(self, name):
        return None

    def next_run_of(self, name):
        return None

    def run_now(self, name):
        return "started"


class Env:
    def __init__(self, tmp_path):
        self.clock = FakeClock()
        self.runner = FakeRunner()
        self.app = create_app(
            data_dir=tmp_path, clock=self.clock, runner_factory=lambda *_: self.runner
        )
        self.client = TestClient(self.app, base_url=BASE, follow_redirects=False)
        self.db = Database(tmp_path / "rss_hub.db")
        self.runs = JobRunRepository(self.db, self.clock)
        self.articles = ArticleRepository(self.db, self.clock)
        self.feeds = FeedRepository(self.db, self.clock)
        self.settings = self.app.state.settings_service

    def ran(self, job, minutes_ago):
        self.clock.advance(minutes=-minutes_ago)
        self.runs.mark_started(job)
        self.runs.mark_finished(job)
        self.clock.advance(minutes=minutes_ago)

    def article(self, link="https://example.com/original", ready=False):
        feed_id = (
            self.feeds.list_all()[0].id
            if self.feeds.list_all()
            else self.feeds.add("https://f.example.com/rss", "피드")
        )
        article_id = self.articles.add(
            NewArticle(feed_id, f"g{link}", "t", link, "c", "", datetime.now(UTC), "2026-10-16")
        )
        if ready:
            self.articles.mark_ready(article_id, title_ko="t", summary_ko="s", topics=[], model="m")
        return article_id
