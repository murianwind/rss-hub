from datetime import UTC, datetime

import pytest

from rss_hub.domain.activity import FeedMeasurement
from rss_hub.domain.feed_url import feed_url_key
from rss_hub.domain.schedule import PRIORITY_EVERY_SLOT, Activity
from rss_hub.services.settings import SettingsService
from rss_hub.storage.articles import ArticleRepository, NewArticle
from rss_hub.storage.database import Database
from rss_hub.storage.feeds import (
    STATUS_ACTIVE,
    STATUS_BASELINE,
    DuplicateFeedError,
    FeedRepository,
)
from tests.fakes.clock import FakeClock
from tests.keywords.store import create_category, raw_connection, set_poll_priority, stored_stats

URL = "https://a.example.com/feed"


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "rss_hub.db")


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def feeds(db, clock):
    return FeedRepository(db, clock)


def test_new_feed_has_sensible_defaults(feeds):
    feed = feeds.get(feeds.add(URL, "A 블로그"))
    assert feed is not None
    assert (feed.url, feed.name, feed.html_url) == (URL, "A 블로그", "")
    assert feed.status == STATUS_BASELINE
    assert (feed.emoji, feed.poll_priority) == ("📢", "normal")
    assert (feed.max_entries, feed.category_id) == (None, None)
    assert (feed.fail_count, feed.last_error, feed.etag, feed.last_modified) == (
        0,
        None,
        None,
        None,
    )


def test_options_are_stored(feeds):
    feed_id = feeds.add(
        URL,
        "Gizmodo",
        html_url="https://gizmodo.com",
        emoji="🧪",
        poll_priority=PRIORITY_EVERY_SLOT,
        max_entries=120,
    )
    feed = feeds.get(feed_id)
    assert feed is not None
    assert (feed.emoji, feed.poll_priority, feed.max_entries) == (
        "🧪",
        PRIORITY_EVERY_SLOT,
        120,
    )
    assert feed.html_url == "https://gizmodo.com"


@pytest.mark.parametrize(
    "duplicate",
    [
        URL,
        "https://A.Example.com/feed",
        "https://a.example.com/feed/",
        "HTTPS://a.example.com/feed",
    ],
)
def test_the_same_feed_cannot_be_added_twice(feeds, duplicate):
    feeds.add(URL, "A")
    with pytest.raises(DuplicateFeedError):
        feeds.add(duplicate, "again")
    assert len(feeds.list_all()) == 1


def test_get_returns_none_for_unknown_feed(feeds):
    assert feeds.get(999) is None


def test_list_all_is_ordered_by_creation(feeds):
    ids = [feeds.add(f"https://x{i}.example.com/rss", f"f{i}") for i in range(3)]
    assert [f.id for f in feeds.list_all()] == ids


def test_success_records_validators_clears_failures_and_can_activate(feeds):
    feed_id = feeds.add(URL, "A")
    feeds.record_failure(feed_id, "Timeout")
    feeds.record_success(
        feed_id, etag='"abc"', last_modified="Fri, 16 Oct 2026 00:00:00 GMT", activate=True
    )
    feed = feeds.get(feed_id)
    assert feed is not None
    assert (feed.fail_count, feed.last_error) == (0, None)
    assert (feed.etag, feed.last_modified) == ('"abc"', "Fri, 16 Oct 2026 00:00:00 GMT")
    assert feed.status == STATUS_ACTIVE


def test_success_without_activation_keeps_the_status(feeds):
    feed_id = feeds.add(URL, "A")
    feeds.record_success(feed_id, etag=None, last_modified=None, activate=False)
    feed = feeds.get(feed_id)
    assert feed is not None
    assert feed.status == STATUS_BASELINE


def test_failures_are_counted_with_the_latest_reason(feeds):
    feed_id = feeds.add(URL, "A")
    feeds.record_failure(feed_id, "Timeout")
    feeds.record_failure(feed_id, "HTTP 404")
    feed = feeds.get(feed_id)
    assert feed is not None
    assert (feed.fail_count, feed.last_error) == (2, "HTTP 404")


def test_stats_are_saved_and_exposed_as_activity_by_feed_key(feeds):
    first = feeds.add(URL, "A")
    second = feeds.add("https://b.example.com/rss", "B")
    latest = datetime(2026, 10, 16, 1, 0, tzinfo=UTC)
    feeds.save_stats(
        first, FeedMeasurement(Activity(recent_count_7d=5, target_date_count=2), latest)
    )
    assert feeds.activity_by_key() == {str(first): Activity(5, 2)}
    feeds.save_stats(first, FeedMeasurement(Activity(1, 0), None))  # 덮어쓰기
    assert feeds.activity_by_key() == {str(first): Activity(1, 0)}
    assert str(second) not in feeds.activity_by_key()


def test_poll_priority_can_be_changed(feeds):
    feed_id = feeds.add(URL, "A")
    set_poll_priority(feeds, feed_id, PRIORITY_EVERY_SLOT)
    feed = feeds.get(feed_id)
    assert feed is not None
    assert feed.poll_priority == PRIORITY_EVERY_SLOT


def test_deleting_a_feed_removes_its_stats_and_articles_but_not_the_seen_record(db, clock, feeds):
    articles = ArticleRepository(db, clock)
    feed_id = feeds.add(URL, "A")
    feeds.save_stats(feed_id, FeedMeasurement(Activity(1, 1), None))
    articles.add(
        NewArticle(feed_id, "g1", "t", "https://x/1", "<p>c</p>", "raw", clock.now(), "2026-10-16")
    )
    feeds.delete(feed_id)
    assert feeds.get(feed_id) is None
    assert feeds.activity_by_key() == {}
    assert articles.count_by_status() == {}
    assert (
        articles.is_seen("g1") is True
    )  # 지운 피드의 글이 구독을 다시 추가했을 때 되살아나지 않게


def test_stored_stats_can_be_read_back(db, feeds):
    feed_id = feeds.add(URL, "A")
    assert stored_stats(db, feed_id) is None
    latest = datetime(2026, 10, 16, 1, 0, tzinfo=UTC)
    feeds.save_stats(feed_id, FeedMeasurement(Activity(5, 2), latest))
    stats = stored_stats(db, feed_id)
    assert stats is not None
    assert (stats.recent_count_7d, stats.target_date_count, stats.last_published) == (5, 2, latest)
    feeds.save_stats(feed_id, FeedMeasurement(Activity(0, 0), None))
    assert stored_stats(db, feed_id).last_published is None


def test_last_checked_time_is_recorded_on_success_and_on_failure(feeds, clock):
    feed_id = feeds.add(URL, "A")
    assert feeds.get(feed_id).last_checked_at is None
    feeds.record_success(feed_id, etag=None, last_modified=None, activate=True)
    assert feeds.get(feed_id).last_checked_at == clock.now()
    clock.advance(minutes=5)
    feeds.record_failure(feed_id, "Timeout")
    assert feeds.get(feed_id).last_checked_at == clock.now()


# ---------- 카테고리 ----------


def test_a_category_can_have_a_webhook(feeds, db, clock):
    settings = SettingsService(db, clock)
    webhook_id = settings.add_webhook("dev", "https://discord.com/api/webhooks/1/abc")
    category_id = create_category(feeds, "뉴스", webhook_id=webhook_id)
    assert feeds.category_webhook_id(category_id) == webhook_id
    assert feeds.category_webhook_id(create_category(feeds, "기타")) is None
    assert feeds.category_webhook_id(None) is None
    assert feeds.category_webhook_id(999) is None


def test_deleting_a_webhook_clears_the_category_reference(feeds, db, clock):
    settings = SettingsService(db, clock)
    webhook_id = settings.add_webhook("dev", "https://discord.com/api/webhooks/1/abc")
    category_id = create_category(feeds, "뉴스", webhook_id=webhook_id)
    settings.delete_webhook(webhook_id)
    assert feeds.category_webhook_id(category_id) is None


# ---------- 가져오기를 위한 조회 ----------


def test_existing_url_keys_are_normalized_so_duplicates_can_be_found(feeds):
    feeds.add("https://A.Example.com/feed/", "A")
    feeds.add("https://b.example.com/rss", "B")
    assert feeds.existing_url_keys() == {"https://a.example.com/feed", "https://b.example.com/rss"}


def test_get_or_create_category_reuses_an_existing_name(feeds):
    first_id, first_created = feeds.get_or_create_category("IT")
    second_id, second_created = feeds.get_or_create_category("IT")
    assert (first_created, second_created) == (True, False)
    assert first_id == second_id
    assert feeds.category_names() == {"IT"}


def test_category_names_lists_all_of_them(feeds):
    create_category(feeds, "뉴스")
    feeds.get_or_create_category("IT")
    assert feeds.category_names() == {"뉴스", "IT"}


# ---------- 카테고리 목록과 웹훅 지정 ----------


def test_categories_are_listed_by_name_with_their_feed_counts(feeds):
    news = create_category(feeds, "뉴스")
    empty = create_category(feeds, "가나다")
    feeds.add("https://a.example.com/rss", "A", category_id=news)
    feeds.add("https://b.example.com/rss", "B", category_id=news)
    feeds.add("https://c.example.com/rss", "C")
    listed = feeds.list_categories()
    assert [(c.name, c.feed_count) for c in listed] == [("가나다", 0), ("뉴스", 2)]
    assert (listed[0].id, listed[1].id) == (empty, news)


def test_a_category_webhook_can_be_set_and_cleared(feeds, db, clock):
    settings = SettingsService(db, clock)
    webhook_id = settings.add_webhook("dev", "https://discord.com/api/webhooks/1/abc")
    category_id = create_category(feeds, "뉴스")
    assert feeds.set_category_webhook(category_id, webhook_id) is True
    assert feeds.list_categories()[0].webhook_id == webhook_id
    assert feeds.set_category_webhook(category_id, None) is True
    assert feeds.list_categories()[0].webhook_id is None


def test_setting_the_webhook_of_an_unknown_category_reports_it(feeds):
    assert feeds.set_category_webhook(999, None) is False


# ---------- 피드 웹훅과 카테고리: 둘 중 하나만 ----------

from rss_hub.storage.feeds import (  # noqa: E402
    RULE_CATEGORY_FEED_WEBHOOK,
    RULE_FEED_WEBHOOK_BLOCKS_CATEGORY,
    FeedRuleError,
)


@pytest.fixture
def webhook_id(db, clock):
    return SettingsService(db, clock).add_webhook("dev", "https://discord.com/api/webhooks/1/abc")


def test_a_new_feed_has_no_webhook_by_default(feeds):
    assert feeds.get(feeds.add(URL, "A")).webhook_id is None


def test_a_feed_outside_any_category_can_be_added_with_a_webhook(feeds, webhook_id):
    assert feeds.get(feeds.add(URL, "A", webhook_id=webhook_id)).webhook_id == webhook_id


def test_a_feed_cannot_be_added_with_both_a_category_and_a_webhook(feeds, webhook_id):
    category = create_category(feeds, "뉴스")
    with pytest.raises(FeedRuleError) as info:
        feeds.add(URL, "A", category_id=category, webhook_id=webhook_id)
    assert info.value.message == RULE_CATEGORY_FEED_WEBHOOK
    assert feeds.list_all() == []


def test_adding_a_feed_with_a_missing_webhook_is_a_rule_error_not_a_duplicate(feeds):
    with pytest.raises(FeedRuleError) as info:
        feeds.add(URL, "A", webhook_id=999)
    assert info.value.message == "웹훅을 찾을 수 없음"


def test_a_feed_webhook_can_be_set_and_cleared(feeds, webhook_id):
    feed_id = feeds.add(URL, "A")
    assert feeds.set_feed_webhook(feed_id, webhook_id) is True
    assert feeds.get(feed_id).webhook_id == webhook_id
    assert feeds.set_feed_webhook(feed_id, None) is True
    assert feeds.get(feed_id).webhook_id is None


def test_the_webhook_of_a_feed_in_a_category_cannot_be_set_but_can_be_cleared(feeds, webhook_id):
    category = create_category(feeds, "뉴스")
    feed_id = feeds.add(URL, "A", category_id=category)
    with pytest.raises(FeedRuleError) as info:
        feeds.set_feed_webhook(feed_id, webhook_id)
    assert info.value.message == RULE_CATEGORY_FEED_WEBHOOK
    assert feeds.set_feed_webhook(feed_id, None) is True


def test_an_unknown_feed_or_webhook_is_reported(feeds):
    assert feeds.set_feed_webhook(999, None) is False
    feed_id = feeds.add(URL, "A")
    with pytest.raises(FeedRuleError) as info:
        feeds.set_feed_webhook(feed_id, 999)
    assert info.value.message == "웹훅을 찾을 수 없음"


def test_a_feed_with_a_webhook_cannot_join_a_category_until_the_webhook_is_cleared(
    feeds, webhook_id
):
    category = create_category(feeds, "뉴스")
    feed_id = feeds.add(URL, "A", webhook_id=webhook_id)
    with pytest.raises(FeedRuleError) as info:
        feeds.set_feed_category(feed_id, category)
    assert info.value.message == RULE_FEED_WEBHOOK_BLOCKS_CATEGORY
    assert feeds.get(feed_id).category_id is None
    feeds.set_feed_webhook(feed_id, None)
    assert feeds.set_feed_category(feed_id, category) is True
    assert feeds.get(feed_id).category_id == category


def test_leaving_the_category_makes_the_feed_webhook_available_again(feeds, webhook_id):
    category = create_category(feeds, "뉴스")
    feed_id = feeds.add(URL, "A", category_id=category)
    assert feeds.set_feed_category(feed_id, None) is True
    assert feeds.set_feed_webhook(feed_id, webhook_id) is True
    assert feeds.get(feed_id).webhook_id == webhook_id


def test_an_unknown_feed_or_category_is_reported_when_moving_a_feed(feeds):
    assert feeds.set_feed_category(999, None) is False
    feed_id = feeds.add(URL, "A")
    with pytest.raises(FeedRuleError) as info:
        feeds.set_feed_category(feed_id, 999)
    assert info.value.message == "카테고리를 찾을 수 없음"


def test_deleting_a_webhook_clears_it_from_the_feeds_that_used_it(feeds, db, clock, webhook_id):
    feed_id = feeds.add(URL, "A", webhook_id=webhook_id)
    SettingsService(db, clock).delete_webhook(webhook_id)
    assert feeds.get(feed_id).webhook_id is None


# ---------- 피드 편집과 삭제(M2) ----------


def test_a_feed_can_be_edited_and_the_rest_stays(feeds):
    from rss_hub.domain.feed_edit import FeedEdit

    feed_id = feeds.add(URL, "A", html_url="https://a.example.com")
    assert feeds.update_feed(feed_id, FeedEdit("새 이름", "🧪", "every_slot", 120)) is True
    feed = feeds.get(feed_id)
    assert (feed.name, feed.emoji, feed.poll_priority, feed.max_entries) == (
        "새 이름",
        "🧪",
        "every_slot",
        120,
    )
    assert (feed.url, feed.html_url, feed.status) == (
        URL,
        "https://a.example.com",
        "baseline_pending",
    )
    assert feeds.update_feed(feed_id, FeedEdit("새 이름", "🧪", "normal", None)) is True
    assert feeds.get(feed_id).max_entries is None


def test_editing_an_unknown_feed_reports_it(feeds):
    from rss_hub.domain.feed_edit import FeedEdit

    assert feeds.update_feed(999, FeedEdit("x", "📢", "normal", None)) is False


def test_deleting_reports_whether_a_feed_was_removed(feeds):
    feed_id = feeds.add(URL, "A")
    assert feeds.delete(feed_id) is True
    assert feeds.delete(feed_id) is False


# ---------- 구독 종류(feed, page) ----------


def test_the_subscription_kind_defaults_to_feed_and_page_is_remembered(tmp_path):
    from rss_hub.storage.feeds import KIND_FEED, KIND_PAGE

    db, clock = Database(tmp_path / "rss_hub.db"), FakeClock()
    feeds = FeedRepository(db, clock)
    plain = feeds.add("https://a.example.com/rss", "피드")
    page = feeds.add("https://b.example.com/news", "페이지", kind=KIND_PAGE)
    assert (feeds.get(plain).kind, feeds.get(page).kind) == (KIND_FEED, KIND_PAGE)
    assert {f.id: f.kind for f in feeds.list_all()} == {plain: KIND_FEED, page: KIND_PAGE}


def test_upgrading_from_the_previous_schema_keeps_old_feeds_as_plain_feeds(tmp_path):

    from rss_hub.storage.migrations import MIGRATIONS, apply_migrations

    with raw_connection(tmp_path / "old.db") as conn:
        for number, script in enumerate(MIGRATIONS[:13], start=1):  # 13번까지만 적용한 예전 DB
            conn.executescript(script)
            conn.execute(f"PRAGMA user_version = {number}")
        conn.execute(
            "INSERT INTO feeds(url, url_key, name, created_at) "
            "VALUES('https://old.example.com/rss', 'old', '옛 피드', '2026-01-01T00:00:00+00:00')"
        )
        apply_migrations(conn)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS) >= 14
        assert conn.execute("SELECT kind FROM feeds").fetchone()[0] == "feed"


def test_the_page_subscription_keys_list_only_web_page_feeds(tmp_path):
    from rss_hub.storage.feeds import KIND_PAGE

    feeds = FeedRepository(Database(tmp_path / "rss_hub.db"), FakeClock())
    feeds.add("https://a.example.com/rss", "피드")
    feeds.add("https://b.example.com/news/", "페이지", kind=KIND_PAGE)
    assert feeds.page_url_keys() == {feed_url_key("https://b.example.com/news/")}
    assert len(feeds.existing_url_keys()) == 2
