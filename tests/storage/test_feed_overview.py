import sqlite3

import pytest

from rss_hub.domain.activity import FeedMeasurement
from rss_hub.domain.schedule import Activity
from rss_hub.storage.articles import ArticleRepository, NewArticle
from rss_hub.storage.database import Database
from rss_hub.storage.feeds import FeedRepository
from rss_hub.storage.migrations import MIGRATIONS
from rss_hub.storage.overview import OverviewRepository
from tests.fakes.clock import FakeClock


@pytest.fixture
def env(tmp_path):
    db, clock = Database(tmp_path / "rss_hub.db"), FakeClock()
    feeds, articles = FeedRepository(db, clock), ArticleRepository(db, clock)
    category = feeds.add_category("뉴스")
    a = feeds.add(
        "https://a.example.com/rss",
        "가 피드",
        category_id=category,
        html_url="https://a.example.com/",
    )
    b = feeds.add("https://b.example.com/rss", "나 피드")
    return feeds, articles, OverviewRepository(db), clock, a, b, category


def article(articles, clock, feed, n):
    return articles.add(
        NewArticle(feed, f"g{n}", f"t{n}", f"https://x/{n}", "c", "", clock.now(), "2026-10-16")
    )


def test_a_new_feed_has_no_activity_and_is_gray_with_every_field_filled(env):
    _, _, overview, _, a, _, category = env
    first = overview.feeds()[0]
    assert (first.id, first.name, first.site_url, first.category_name) == (
        a,
        "가 피드",
        "https://a.example.com/",
        "뉴스",
    )
    assert (first.state, first.status, first.fail_count, first.last_error) == (
        "never",
        "baseline_pending",
        0,
        "",
    )
    assert (
        first.recent_count_7d,
        first.today_count,
        first.last_published,
        first.total,
        first.unread,
    ) == (0, 0, None, 0, 0)
    assert first.category_id == category and first.webhook_id is None and first.max_entries is None


def test_state_activity_and_counts_come_from_the_real_data(env):
    feeds, articles, overview, clock, a, b, _ = env
    feeds.record_failure(a, "ReadTimeout")
    feeds.save_stats(b, FeedMeasurement(Activity(5, 2), clock.now()))
    feeds.record_success(b, etag=None, last_modified=None, activate=True)
    read = article(articles, clock, b, 1)
    article(articles, clock, b, 2)
    articles.mark_read(read)
    by_id = {f.id: f for f in overview.feeds()}
    assert (by_id[a].state, by_id[a].fail_count, by_id[a].last_error) == ("error", 1, "ReadTimeout")
    mine = by_id[b]
    assert (mine.state, mine.status, mine.recent_count_7d, mine.today_count) == (
        "ok",
        "active",
        5,
        2,
    )
    assert (
        (mine.total, mine.unread) == (2, 1)
        and mine.last_published is not None
        and mine.last_checked_at is not None
    )


def test_the_order_is_the_saved_order_then_the_name(env):
    _, _, overview, _, a, b, _ = env
    with overview._db.connect() as conn:
        conn.execute("UPDATE feeds SET sort_order = 1 WHERE id = ?", (b,))
        conn.execute("UPDATE feeds SET sort_order = 5 WHERE id = ?", (a,))
    assert [f.id for f in overview.feeds()] == [b, a]


def test_an_empty_service_has_no_feeds(tmp_path):
    assert OverviewRepository(Database(tmp_path / "rss_hub.db")).feeds() == []


def test_the_migration_returns_every_slot_feeds_to_the_automatic_schedule(tmp_path):
    conn = sqlite3.connect(tmp_path / "old.db")
    for script in MIGRATIONS[:10]:
        conn.executescript(script)
    for n, priority in enumerate(("normal", "every_slot", "every_slot"), start=1):
        conn.execute(
            "INSERT INTO feeds(url, url_key, name, emoji, poll_priority, status, created_at) "
            "VALUES(?, ?, 'n', 'x', ?, 'active', '2026-01-01')",
            (f"u{n}", f"k{n}", priority),
        )
    conn.executescript(MIGRATIONS[10])
    assert [r[0] for r in conn.execute("SELECT poll_priority FROM feeds ORDER BY id")] == [
        "normal"
    ] * 3
