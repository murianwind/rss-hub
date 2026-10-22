"""읽음, 북마크, 검색과 필터, 사이드바 개수(새 뷰어 화면의 저장 계층)."""

from datetime import timedelta

import pytest

from rss_hub.domain.topics import TopicFields
from rss_hub.storage.articles import ArticleRepository, NewArticle
from rss_hub.storage.database import Database
from rss_hub.storage.feeds import FeedRepository
from rss_hub.storage.reader import ReaderRepository
from rss_hub.storage.topics import TopicRepository
from tests.fakes.clock import FakeClock
from tests.keywords.store import create_category, raw_connection


class Env:
    def __init__(self, tmp_path):
        self.db = Database(tmp_path / "rss_hub.db")
        self.clock = FakeClock()
        self.feeds = FeedRepository(self.db, self.clock)
        self.articles = ArticleRepository(self.db, self.clock)
        self.topics = TopicRepository(self.db, self.clock)
        self.reader = ReaderRepository(self.db, self.clock)
        self.news = create_category(self.feeds, "뉴스")
        self.a = self.feeds.add("https://a.example.com/rss", "A 블로그", category_id=self.news)
        self.b = self.feeds.add("https://b.example.com/rss", "B 블로그")
        self.ott = self.topics.add(TopicFields("OTT", "", ("netflix",)))
        self.n = 0

    def article(self, feed=None, minutes=0, *, title=None, ko=None, summary=None):
        self.n += 1
        article_id = self.articles.add(
            NewArticle(
                feed or self.b,
                f"g{self.n}",
                title or f"Title {self.n}",
                f"https://x/{self.n}",
                "<p>c</p>",
                "",
                self.clock.now() + timedelta(minutes=minutes),
                "2026-10-16",
            )
        )
        if ko or summary:
            self.articles.mark_ready(
                article_id, title_ko=ko or "t", summary_ko=summary or "s", topics=[], model="m"
            )
        return article_id

    def titles(self, **kwargs):
        return [i.title for i in self.reader.list_articles(**kwargs).items]


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


# ---------- 읽음 ----------


def test_a_new_article_is_unread_and_can_be_marked_read_and_unread(env):
    article = env.article()
    assert env.articles.get(article).read_at is None
    assert env.articles.mark_read(article) is True
    assert env.articles.get(article).read_at == env.clock.now()
    assert env.articles.mark_unread(article) is True
    assert env.articles.get(article).read_at is None


def test_marking_read_twice_keeps_the_first_time_and_reports_no_change(env):
    article = env.article()
    env.articles.mark_read(article)
    first = env.articles.get(article).read_at
    env.clock.advance(minutes=5)
    assert env.articles.mark_read(article) is False
    assert env.articles.get(article).read_at == first


def test_marking_an_unknown_article_changes_nothing(env):
    assert env.articles.mark_read(999) is False and env.articles.mark_unread(999) is False
    assert env.articles.auto_mark_read([999]) == 0


def test_archived_articles_start_as_read_so_old_back_catalog_does_not_inflate_the_counts(env):
    article = env.articles.add_archived(
        NewArticle(env.a, "old", "Old", "https://x/old", "c", "", env.clock.now(), "2026-10-16")
    )
    assert env.articles.get(article).read_at == env.clock.now()


# ---------- 북마크 ----------


def test_an_article_can_be_bookmarked_and_unbookmarked(env):
    article = env.article()
    assert env.articles.set_bookmark(article, True) is True
    assert env.articles.get(article).bookmarked_at == env.clock.now()
    assert env.articles.set_bookmark(article, False) is True
    assert env.articles.get(article).bookmarked_at is None


def test_bookmarking_twice_is_a_no_op_and_unknown_articles_are_refused(env):
    article = env.article()
    env.articles.set_bookmark(article, True)
    first = env.articles.get(article).bookmarked_at
    env.clock.advance(minutes=1)
    assert env.articles.set_bookmark(article, True) is False
    assert env.articles.get(article).bookmarked_at == first
    assert env.articles.set_bookmark(999, True) is False
    assert (
        env.articles.set_bookmark(article, False) is True
        and env.articles.set_bookmark(article, False) is False
    )


def test_bookmarked_articles_survive_the_retention_cleanup(env):
    keep, drop = env.article(title="Keep"), env.article(title="Drop")
    env.articles.set_bookmark(keep, True)
    env.clock.advance(days=100)
    assert env.articles.delete_older_than(env.clock.now() - timedelta(days=90)) == 1
    assert env.articles.get(keep) is not None and env.articles.get(drop) is None


# ---------- 목록의 읽음, 북마크 표시와 필터 ----------


def test_listed_articles_say_whether_they_are_read_and_bookmarked(env):
    read, marked = env.article(title="Read", minutes=2), env.article(title="Marked", minutes=1)
    env.articles.mark_read(read)
    env.articles.set_bookmark(marked, True)
    items = {i.title: i for i in env.reader.list_articles().items}
    assert (items["Read"].read, items["Read"].bookmarked) == (True, False)
    assert (items["Marked"].read, items["Marked"].bookmarked) == (False, True)


def test_the_unread_filter_hides_read_articles(env):
    read = env.article(title="Read", minutes=1)
    env.article(title="Fresh", minutes=2)
    env.articles.mark_read(read)
    assert env.titles(only="unread") == ["Fresh"] and sorted(env.titles()) == ["Fresh", "Read"]


def test_the_bookmark_filter_shows_only_bookmarked_articles(env):
    env.articles.set_bookmark(env.article(title="Saved", minutes=1), True)
    env.article(title="Other", minutes=2)
    assert env.titles(only="bookmarks") == ["Saved"]


def test_filters_combine_with_the_scope(env):
    env.article(env.a, 1, title="A fresh")
    read = env.article(env.a, 2, title="A read")
    env.article(env.b, 3, title="B fresh")
    env.articles.mark_read(read)
    assert env.titles(feed_id=env.a, only="unread") == ["A fresh"]
    assert env.titles(category_id=env.news, only="unread") == ["A fresh"]


@pytest.mark.parametrize("only", ["", "weird", "UNREAD; DROP TABLE articles"])
def test_an_unknown_filter_means_everything(env, only):
    env.article(title="One")
    assert env.titles(only=only) == ["One"]


# ---------- 검색 ----------


def test_search_matches_the_original_title_the_translated_title_and_the_summary(env):
    env.article(title="Squid Game news", minutes=1)
    env.article(title="Other", ko="오징어 게임 소식", minutes=2)
    env.article(title="Third", summary="스트리밍 요약 문장", minutes=3)
    assert env.titles(query="squid") == ["Squid Game news"]
    # 번역 제목이 있는 글은 목록에 번역 제목으로 나온다
    assert env.titles(query="오징어") == ["오징어 게임 소식"]
    assert env.titles(query="스트리밍") == ["t"]


def test_search_ignores_case_and_surrounding_spaces_and_combines_with_filters(env):
    read = env.article(title="Squid read", minutes=1)
    env.article(title="Squid fresh", minutes=2)
    env.articles.mark_read(read)
    assert env.titles(query="  SQUID ") == ["Squid fresh", "Squid read"]
    assert env.titles(query="squid", only="unread") == ["Squid fresh"]


@pytest.mark.parametrize("query", ["50%", "a_b", "x\\y", "'; DROP TABLE articles; --", "%", "_"])
def test_search_treats_wildcards_and_quotes_as_plain_text(env, query):
    env.article(title="Plain title")
    assert env.titles(query=query) == []
    env.article(title=f"Has {query} inside", minutes=1)
    assert env.titles(query=query) == [f"Has {query} inside"]


def test_a_blank_or_very_long_query_is_harmless(env):
    env.article(title="One")
    assert env.titles(query="   ") == ["One"]
    assert env.titles(query="x" * 5000) == []


# ---------- 개수 ----------


def test_the_page_knows_the_total_number_of_matching_articles(env):
    for n in range(35):
        env.article(minutes=n)
    page = env.reader.list_articles()
    assert (len(page.items), page.total) == (30, 35)
    assert env.reader.list_articles(page=2).total == 35
    assert env.reader.list_articles(query="nothing").total == 0


def test_the_total_follows_the_filters(env):
    read = env.article(env.a, 1)
    env.article(env.a, 2)
    env.articles.mark_read(read)
    assert env.reader.list_articles(only="unread").total == 1
    assert env.reader.list_articles(feed_id=env.b).total == 0


# ---------- 모두 읽음 ----------


def test_mark_all_read_in_a_scope_touches_only_that_scope(env):
    a1, a2, b1 = env.article(env.a, 1), env.article(env.a, 2), env.article(env.b, 3)
    assert env.reader.mark_all_read(feed_id=env.a) == 2
    assert (
        env.articles.get(a1).read_at
        and env.articles.get(a2).read_at
        and env.articles.get(b1).read_at is None
    )


def test_mark_all_read_by_category_topic_and_bookmarks(env):
    in_news = env.article(env.a, 1)
    topical = env.article(env.b, 2)
    saved = env.article(env.b, 3)
    env.topics.record_matches(topical, {env.ott: ()})
    env.articles.set_bookmark(saved, True)
    assert env.reader.mark_all_read(category_id=env.news) == 1
    assert env.reader.mark_all_read(topic_id=env.ott) == 1
    assert env.reader.mark_all_read(only="bookmarks") == 1
    assert all(env.articles.get(i).read_at for i in (in_news, topical, saved))


def test_mark_all_read_skips_what_is_already_read_and_reports_the_count(env):
    first = env.article(env.a, 1)
    env.article(env.a, 2)
    env.articles.mark_read(first)
    assert env.reader.mark_all_read() == 1 and env.reader.mark_all_read() == 0


def test_rejected_topic_articles_are_not_marked_by_the_topic_scope(env):
    article = env.article()
    env.topics.record_matches(article, {env.ott: ()})
    env.topics.reject(article, env.ott)
    assert env.reader.mark_all_read(topic_id=env.ott) == 0


# ---------- 사이드바 ----------


def test_the_sidebar_lists_feeds_categories_and_topics_with_total_and_unread_counts(env):
    read = env.article(env.a, 1)
    env.article(env.a, 2)
    env.article(env.b, 3)
    env.articles.mark_read(read)
    side = env.reader.sidebar()
    feeds = {f.name: (f.total, f.unread) for f in side.feeds}
    assert feeds == {"A 블로그": (2, 1), "B 블로그": (1, 1)}
    (category,) = side.categories
    assert (category.name, category.total, category.unread, [f.name for f in category.feeds]) == (
        "뉴스",
        2,
        1,
        ["A 블로그"],
    )
    assert (side.all_unread, side.bookmarks) == (2, 0)


def test_topic_counts_ignore_articles_the_user_rejected(env):
    kept, dropped = env.article(), env.article()
    env.topics.record_matches(kept, {env.ott: ()})
    env.topics.record_matches(dropped, {env.ott: ()})
    env.topics.reject(dropped, env.ott)
    (topic,) = env.reader.sidebar().topics
    assert (topic.name, topic.total, topic.unread) == ("OTT", 1, 1)


def test_the_bookmark_count_and_empty_items_are_reported(env):
    env.articles.set_bookmark(env.article(), True)
    side = env.reader.sidebar()
    assert side.bookmarks == 1 and {f.name: f.total for f in side.feeds}["A 블로그"] == 0
    assert [t.total for t in side.topics] == [0]


def test_the_sidebar_orders_empty_feeds_by_name(env):
    assert [f.name for f in env.reader.sidebar().feeds] == ["A 블로그", "B 블로그"]


def test_an_empty_service_has_an_empty_sidebar(tmp_path):
    side = ReaderRepository(Database(tmp_path / "rss_hub.db"), FakeClock()).sidebar()
    assert (side.feeds, side.categories, side.topics, side.all_unread, side.bookmarks) == (
        (),
        (),
        (),
        0,
        0,
    )


def test_the_migration_marks_existing_articles_as_read(tmp_path):

    from rss_hub.storage.migrations import MIGRATIONS

    with raw_connection(tmp_path / "old.db") as conn:
        for script in MIGRATIONS[:9]:
            conn.executescript(script)
        conn.execute(
            "INSERT INTO feeds(url, url_key, name, emoji, poll_priority, status, created_at) "
            "VALUES('u', 'k', 'n', 'x', 'normal', 'active', '2026-01-01')"
        )
        conn.execute(
            "INSERT INTO articles(feed_id, guid, title, link, content_html, published_raw, "
            "published_dt, published_date, discovered_at, status) "
            "VALUES(1, 'g', 't', 'l', 'c', '', "
            "'2026-01-01T00:00:00+00:00', '2026-01-01', '2026-01-02T00:00:00+00:00', 'collected')"
        )
        conn.executescript(MIGRATIONS[9])
        row = conn.execute("SELECT read_at, bookmarked_at FROM articles").fetchone()
        assert row["read_at"] == "2026-01-02T00:00:00+00:00" and row["bookmarked_at"] is None
        assert conn.execute("SELECT sort_order FROM feeds").fetchone()["sort_order"] == 0


def test_a_search_text_is_cut_at_one_hundred_characters(env):
    env.article(title="a" * 100)
    assert env.titles(query="a" * 100 + "zzz") == ["a" * 100]  # 뒤의 글자는 잘려서 무시된다
    assert env.titles(query="a" * 99 + "b") == []


# ---------- 읽지 않음으로 고정(자동 읽음 처리에서 빠진다) ----------


def keep(env, article):
    with env.db.connect() as conn:
        return bool(
            conn.execute("SELECT keep_unread FROM articles WHERE id = ?", (article,)).fetchone()[0]
        )


def test_auto_read_marks_only_unread_articles_that_are_not_pinned(env):
    free, pinned, read = env.article(minutes=1), env.article(minutes=2), env.article(minutes=3)
    env.articles.mark_read(read)
    env.articles.mark_unread(pinned)
    assert env.articles.auto_mark_read([free, pinned, read]) == 1
    assert env.articles.get(free).read_at is not None and env.articles.get(pinned).read_at is None
    assert env.articles.get(read).read_at is not None


def test_auto_read_keeps_the_first_read_time_and_ignores_empty_and_repeated_calls(env):
    article = env.article()
    assert env.articles.auto_mark_read([]) == 0
    assert env.articles.auto_mark_read([article, article]) == 1
    first = env.articles.get(article).read_at
    env.clock.advance(minutes=5)
    assert (
        env.articles.auto_mark_read([article]) == 0 and env.articles.get(article).read_at == first
    )


def test_marking_unread_pins_the_article_even_when_it_was_never_read(env):
    article = env.article()
    assert keep(env, article) is False
    assert env.articles.mark_unread(article) is True  # 아직 읽지 않은 글도 고정된다
    assert keep(env, article) is True
    assert env.articles.mark_unread(article) is False  # 이미 고정되어 바뀔 것이 없다


def test_reading_it_myself_releases_the_pin_and_makes_it_auto_readable_again(env):
    article = env.article()
    env.articles.mark_unread(article)
    assert env.articles.mark_read(article) is True
    assert keep(env, article) is False and env.articles.get(article).read_at is not None
    env.articles.mark_unread(article)
    assert keep(env, article) is True and env.articles.get(article).read_at is None


def test_the_read_all_button_is_an_explicit_action_and_releases_pins_too(env):
    pinned = env.article(env.a)
    env.articles.mark_unread(pinned)
    assert env.reader.mark_all_read(feed_id=env.a) == 1
    assert env.articles.get(pinned).read_at is not None and keep(env, pinned) is False


def test_listed_articles_report_the_pin(env):
    pinned = env.article(title="Pinned", minutes=1)
    env.article(title="Free", minutes=2)
    env.articles.mark_unread(pinned)
    items = {i.title: i for i in env.reader.list_articles().items}
    assert (items["Pinned"].keep_unread, items["Free"].keep_unread) == (True, False)


def test_a_pinned_article_stays_unread_in_the_counts(env):
    article = env.article(env.a)
    env.articles.mark_read(article)
    env.articles.mark_unread(article)
    assert next(f for f in env.reader.sidebar().feeds if f.id == env.a).unread == 1
