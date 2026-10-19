from datetime import UTC, datetime, timedelta

import pytest

from rss_hub.domain.topics import TopicFields
from rss_hub.storage.articles import ArticleRepository, NewArticle
from rss_hub.storage.database import Database
from rss_hub.storage.feeds import FeedRepository
from rss_hub.storage.reader import PER_PAGE, ReaderRepository
from rss_hub.storage.topics import TopicRepository
from tests.fakes.clock import FakeClock

BASE = datetime(2026, 10, 16, 1, 0, tzinfo=UTC)


class Env:
    def __init__(self, tmp_path):
        self.db = Database(tmp_path / "rss_hub.db")
        self.clock = FakeClock()
        self.feeds = FeedRepository(self.db, self.clock)
        self.articles = ArticleRepository(self.db, self.clock)
        self.topics = TopicRepository(self.db, self.clock)
        self.reader = ReaderRepository(self.db)
        self.news = self.feeds.add_category("뉴스")
        self.a = self.feeds.add("https://a.example.com/rss", "A 블로그", category_id=self.news)
        self.b = self.feeds.add("https://b.example.com/rss", "B 블로그")
        self.n = 0

    def article(self, feed, minutes=0, *, title=None, status="collected", ko=None, summary=None):
        self.n += 1
        article_id = self.articles.add(
            NewArticle(
                feed,
                f"g{self.n}",
                title or f"글 {self.n}",
                f"https://x/{self.n}",
                "<p>c</p>",
                "",
                BASE + timedelta(minutes=minutes),
                "2026-10-16",
            )
        )
        if status == "ready" or ko or summary:
            self.articles.mark_ready(
                article_id, title_ko=ko or "t", summary_ko=summary or "s", topics=[], model="m"
            )
        if status == "delivered":
            self.articles.mark_delivered(article_id)
        if status == "archived":
            with self.db.connect() as conn:
                conn.execute("UPDATE articles SET status = 'archived' WHERE id = ?", (article_id,))
        return article_id


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def titles(page):
    return [item.title for item in page.items]


def test_the_newest_published_article_comes_first(env):
    env.article(env.a, 0, title="오래된 글")
    env.article(env.b, 20, title="최신 글")
    env.article(env.a, 10, title="중간 글")
    assert titles(env.reader.list_articles()) == ["최신 글", "중간 글", "오래된 글"]


def test_articles_published_at_the_same_time_show_the_later_stored_one_first(env):
    env.article(env.a, 5, title="먼저 저장")
    env.article(env.a, 5, title="나중 저장")
    assert titles(env.reader.list_articles()) == ["나중 저장", "먼저 저장"]


@pytest.mark.parametrize("status", ["collected", "ready", "delivered", "archived"])
def test_every_viewable_status_is_listed(env, status):
    env.article(env.a, 0, status=status)
    assert len(env.reader.list_articles().items) == 1


def test_the_translated_title_is_shown_when_there_is_one(env):
    env.article(env.a, 0, title="Original title", ko="번역된 제목", summary="요약입니다")
    item = env.reader.list_articles().items[0]
    assert (item.title, item.summary) == ("번역된 제목", "요약입니다")
    env.article(env.a, 1, title="Only original")
    assert (
        env.reader.list_articles().items[0].title == "Only original"
        and env.reader.list_articles().items[0].summary is None
    )


def test_a_feed_filter_shows_only_that_site(env):
    env.article(env.a, 0, title="A의 글")
    env.article(env.b, 1, title="B의 글")
    assert titles(env.reader.list_articles(feed_id=env.b)) == ["B의 글"]


def test_a_category_filter_shows_only_feeds_in_that_category(env):
    env.article(env.a, 0, title="A의 글")
    env.article(env.b, 1, title="B의 글")
    assert titles(env.reader.list_articles(category_id=env.news)) == ["A의 글"]


def test_a_topic_filter_shows_only_articles_that_belong_to_the_topic(env):
    ott = env.topics.add(TopicFields("OTT", "", ()))
    game = env.topics.add(TopicFields("게임", "", ()))
    first = env.article(env.a, 0, title="OTT 글")
    second = env.article(env.b, 1, title="게임 글")
    env.article(env.a, 2, title="일반 글")
    env.topics.record_matches(first, {ott: ("netflix",)})
    env.topics.record_matches(second, {game: ()})
    assert titles(env.reader.list_articles(topic_id=ott)) == ["OTT 글"]
    assert titles(env.reader.list_articles(topic_id=game)) == ["게임 글"]


def test_a_topic_article_appears_regardless_of_delivery(env):
    ott = env.topics.add(TopicFields("OTT", "", ()))
    waiting = env.article(env.a, 0, title="아직 안 보낸 글")
    sent = env.article(env.a, 1, title="보낸 글", status="delivered")
    env.topics.record_matches(waiting, {ott: ()})
    env.topics.record_matches(sent, {ott: ()})
    assert sorted(titles(env.reader.list_articles(topic_id=ott))) == ["보낸 글", "아직 안 보낸 글"]


def test_each_listed_article_carries_its_topic_names(env):
    ott = env.topics.add(TopicFields("OTT", "", ()))
    game = env.topics.add(TopicFields("게임", "", ()))
    article_id = env.article(env.a, 0)
    env.topics.record_matches(article_id, {game: (), ott: ("x",)})
    assert env.reader.list_articles().items[0].topics == ("OTT", "게임")


def test_filters_combine_with_and(env):
    ott = env.topics.add(TopicFields("OTT", "", ()))
    in_category = env.article(env.a, 0, title="뉴스의 OTT 글")
    elsewhere = env.article(env.b, 1, title="다른 곳의 OTT 글")
    env.topics.record_matches(in_category, {ott: ()})
    env.topics.record_matches(elsewhere, {ott: ()})
    assert titles(env.reader.list_articles(category_id=env.news, topic_id=ott)) == ["뉴스의 OTT 글"]


def test_pages_have_thirty_items_and_say_whether_more_follow(env):
    for number in range(PER_PAGE + 5):
        env.article(env.a, number)
    first = env.reader.list_articles()
    assert (len(first.items), first.page, first.has_next) == (PER_PAGE, 1, True)
    second = env.reader.list_articles(page=2)
    assert (len(second.items), second.page, second.has_next) == (5, 2, False)
    assert not set(titles(first)) & set(titles(second))


def test_exactly_one_full_page_has_no_next_page(env):
    for number in range(PER_PAGE):
        env.article(env.a, number)
    assert env.reader.list_articles().has_next is False


def test_a_page_past_the_end_is_empty_and_page_zero_means_the_first(env):
    env.article(env.a, 0)
    assert (
        env.reader.list_articles(page=5).items == ()
        and env.reader.list_articles(page=5).has_next is False
    )
    assert (
        env.reader.list_articles(page=0).page == 1 and env.reader.list_articles(page=-3).page == 1
    )


def test_an_empty_list_is_fine(env):
    page = env.reader.list_articles()
    assert page.items == () and page.has_next is False


def test_deleting_a_feed_removes_its_articles_from_the_list(env):
    env.article(env.a, 0)
    env.feeds.delete(env.a)
    assert env.reader.list_articles().items == ()


def test_the_topics_of_one_article_come_with_the_matched_keywords(env):
    ott = env.topics.add(TopicFields("OTT", "", ()))
    game = env.topics.add(TopicFields("게임", "", ()))
    article_id = env.article(env.a, 0)
    env.topics.record_matches(article_id, {game: ("steam",), ott: ("netflix", "drama")})
    found = env.reader.topics_of(article_id)
    assert [(m.name, m.keywords) for m in found] == [
        ("OTT", ("netflix", "drama")),
        ("게임", ("steam",)),
    ]
    assert env.reader.topics_of(999) == []


def test_a_small_page_size_can_be_asked_for(env):
    for number in range(5):
        env.article(env.a, number)
    page = env.reader.list_articles(per_page=2)
    assert len(page.items) == 2 and page.has_next is True


def test_each_listed_article_names_its_site(env):
    env.article(env.a, 0)
    env.article(env.b, 1)
    assert [item.feed_name for item in env.reader.list_articles().items] == ["B 블로그", "A 블로그"]
