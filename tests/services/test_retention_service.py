from datetime import UTC, datetime

import pytest

from rss_hub.services.retention import RetentionService
from rss_hub.services.settings import SettingsService
from rss_hub.storage.articles import ArticleRepository, NewArticle
from rss_hub.storage.database import Database
from rss_hub.storage.feeds import FeedRepository
from tests.fakes.clock import FakeClock


@pytest.fixture
def env(tmp_path):
    db = Database(tmp_path / "rss_hub.db")
    clock = FakeClock()
    articles = ArticleRepository(db, clock)
    settings = SettingsService(db, clock)
    feed_id = FeedRepository(db, clock).add("https://a.example.com/rss", "A")
    service = RetentionService(articles=articles, settings=settings, clock=clock)
    return service, articles, settings, clock, feed_id


def add(articles, feed_id, guid):
    published = datetime(2026, 10, 16, 1, 0, tzinfo=UTC)
    return articles.add(
        NewArticle(feed_id, guid, "t", "https://x/1", "c", "", published, "2026-10-16")
    )


def test_articles_older_than_the_default_ninety_days_are_deleted(env):
    service, articles, _, clock, feed_id = env
    add(articles, feed_id, "old")
    clock.advance(days=91)
    add(articles, feed_id, "new")
    assert service.run() == 1
    assert [a.guid for a in articles.list_by_status("collected")] == ["new"]


def test_nothing_is_deleted_inside_the_period(env):
    service, articles, _, clock, feed_id = env
    add(articles, feed_id, "a")
    clock.advance(days=89)
    assert service.run() == 0


def test_the_period_is_read_from_the_setting_each_time(env):
    service, articles, settings, clock, feed_id = env
    add(articles, feed_id, "a")
    clock.advance(days=10)
    assert service.run() == 0
    settings.update({"article_retention_days": "7"})
    assert service.run() == 1


def test_zero_keeps_everything_forever(env):
    service, articles, settings, clock, feed_id = env
    settings.update({"article_retention_days": "0"})
    add(articles, feed_id, "a")
    clock.advance(days=5000)
    assert service.run() == 0 and articles.count_by_status() == {"collected": 1}


@pytest.mark.parametrize(
    ("value", "message"), [("-1", "0~3650"), ("3651", "0~3650"), ("abc", "숫자")]
)
def test_invalid_periods_are_refused(env, value, message):
    result = env[2].update({"article_retention_days": value})
    assert any(message in text for text in result.errors.values())


def test_the_archive_count_setting_accepts_zero_to_twenty(env):
    settings = env[2]
    assert not settings.update({"baseline_archive_count": "0"}).errors
    assert not settings.update({"baseline_archive_count": "20"}).errors
    assert settings.update({"baseline_archive_count": "21"}).errors
    assert settings.snapshot().baseline_archive_count == 20
    assert settings.snapshot().article_retention_days == 90
