from datetime import timedelta

import pytest

from rss_hub.domain.routing import PRIMARY, Target, topic_purpose
from rss_hub.services.settings import SettingsService
from rss_hub.storage.articles import ArticleRepository, NewArticle
from rss_hub.storage.database import Database
from rss_hub.storage.deliveries import (
    STATUS_FAILED_PERMANENT,
    STATUS_PENDING,
    STATUS_SENT,
    DeliveryRepository,
)
from rss_hub.storage.feeds import FeedRepository
from tests.fakes.clock import FakeClock

URL_A = "https://discord.com/api/webhooks/1/AAA"
URL_B = "https://discord.com/api/webhooks/2/BBB"


class Env:
    def __init__(self, tmp_path):
        self.db = Database(tmp_path / "rss_hub.db")
        self.clock = FakeClock()
        self.settings = SettingsService(self.db, self.clock)
        self.feeds = FeedRepository(self.db, self.clock)
        self.articles = ArticleRepository(self.db, self.clock)
        self.deliveries = DeliveryRepository(self.db, self.clock)
        self.web_a = self.settings.add_webhook("a", URL_A)
        self.web_b = self.settings.add_webhook("b", URL_B)
        feed_id = self.feeds.add("https://f.example.com/rss", "피드")
        self.article_id = self.articles.add(
            NewArticle(feed_id, "g1", "t", "https://x/1", "c", "", self.clock.now(), "2026-10-16")
        )


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def test_ensure_creates_one_pending_row_per_target_in_target_order(env):
    rows = env.deliveries.ensure(
        env.article_id, [Target(env.web_b, PRIMARY), Target(env.web_a, topic_purpose(1))]
    )
    assert [(r.webhook_id, r.purpose, r.status, r.attempts) for r in rows] == [
        (env.web_b, PRIMARY, STATUS_PENDING, 0),
        (env.web_a, topic_purpose(1), STATUS_PENDING, 0),
    ]


def test_ensure_is_idempotent_and_keeps_existing_progress(env):
    first = env.deliveries.ensure(env.article_id, [Target(env.web_a, PRIMARY)])[0]
    env.deliveries.mark_sent(first.id, "m1")
    again = env.deliveries.ensure(env.article_id, [Target(env.web_a, PRIMARY)])
    assert [(r.id, r.status) for r in again] == [(first.id, STATUS_SENT)]
    assert len(env.deliveries.for_article(env.article_id)) == 1


def test_the_same_webhook_with_a_different_purpose_is_a_separate_row(env):
    env.deliveries.ensure(
        env.article_id, [Target(env.web_a, PRIMARY), Target(env.web_a, topic_purpose(1))]
    )
    assert len(env.deliveries.for_article(env.article_id)) == 2


def test_a_failed_attempt_counts_and_keeps_the_delivery_pending(env):
    row = env.deliveries.ensure(env.article_id, [Target(env.web_a, PRIMARY)])[0]
    env.deliveries.record_attempt_failure(row.id, "HTTP 503")
    env.deliveries.record_attempt_failure(row.id, "ReadTimeout")
    updated = env.deliveries.for_article(env.article_id)[0]
    assert (updated.status, updated.attempts, updated.last_error) == (
        STATUS_PENDING,
        2,
        "ReadTimeout",
    )


def test_a_sent_delivery_remembers_the_time_and_message_and_clears_the_error(env):
    row = env.deliveries.ensure(env.article_id, [Target(env.web_a, PRIMARY)])[0]
    env.deliveries.record_attempt_failure(row.id, "HTTP 503")
    env.clock.advance(minutes=1)
    env.deliveries.mark_sent(row.id, "1234567890")
    sent = env.deliveries.for_article(env.article_id)[0]
    assert (sent.status, sent.attempts, sent.last_error) == (STATUS_SENT, 2, None)
    assert (sent.message_id, sent.sent_at) == ("1234567890", env.clock.now())


def test_a_sent_delivery_without_a_message_id_is_fine(env):
    row = env.deliveries.ensure(env.article_id, [Target(env.web_a, PRIMARY)])[0]
    env.deliveries.mark_sent(row.id, None)
    assert env.deliveries.for_article(env.article_id)[0].message_id is None


def test_a_permanent_failure_is_final_and_counted(env):
    row = env.deliveries.ensure(env.article_id, [Target(env.web_a, PRIMARY)])[0]
    env.deliveries.mark_permanent(row.id, "HTTP 404")
    failed = env.deliveries.for_article(env.article_id)[0]
    assert (failed.status, failed.attempts, failed.last_error) == (
        STATUS_FAILED_PERMANENT,
        1,
        "HTTP 404",
    )


def test_counts_by_status(env):
    rows = env.deliveries.ensure(
        env.article_id, [Target(env.web_a, PRIMARY), Target(env.web_b, topic_purpose(1))]
    )
    env.deliveries.mark_sent(rows[0].id, None)
    assert env.deliveries.count_by_status() == {STATUS_SENT: 1, STATUS_PENDING: 1}


def test_deleting_a_webhook_removes_its_deliveries(env):
    env.deliveries.ensure(
        env.article_id, [Target(env.web_a, PRIMARY), Target(env.web_b, topic_purpose(1))]
    )
    env.settings.delete_webhook(env.web_a)
    assert [r.webhook_id for r in env.deliveries.for_article(env.article_id)] == [env.web_b]


def test_deleting_an_article_removes_its_deliveries(env):
    env.deliveries.ensure(env.article_id, [Target(env.web_a, PRIMARY)])
    env.feeds.delete(env.feeds.list_all()[0].id)
    assert env.deliveries.count_by_status() == {}


def test_rows_know_when_they_were_created(env):
    env.deliveries.ensure(env.article_id, [Target(env.web_a, PRIMARY)])
    env.clock.advance(hours=1)
    env.deliveries.ensure(env.article_id, [Target(env.web_b, topic_purpose(1))])
    first, second = env.deliveries.for_article(env.article_id)
    assert second.created_at - first.created_at == timedelta(hours=1)
