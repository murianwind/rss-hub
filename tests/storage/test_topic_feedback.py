"""사용자가 정한 주제 소속(M5): 싫어요, 되돌리기, 주제로, 자동 판정과의 관계."""

import pytest

from rss_hub.domain.topics import TopicFields
from rss_hub.storage.articles import ArticleRepository, NewArticle
from rss_hub.storage.database import Database
from rss_hub.storage.feeds import FeedRepository
from rss_hub.storage.reader import ReaderRepository
from rss_hub.storage.topics import TopicRepository
from tests.fakes.clock import FakeClock


class Env:
    def __init__(self, tmp_path):
        self.db = Database(tmp_path / "rss_hub.db")
        self.clock = FakeClock()
        self.topics = TopicRepository(self.db, self.clock)
        self.articles = ArticleRepository(self.db, self.clock)
        self.reader = ReaderRepository(self.db)
        self.feed = FeedRepository(self.db, self.clock).add("https://a.example.com/rss", "A")
        self.ott = self.topics.add(TopicFields("OTT", "스트리밍", ("netflix",)))
        self.game = self.topics.add(TopicFields("게임", "게임", ("steam",)))
        self.n = 0

    def article(self, title="글"):
        self.n += 1
        return self.articles.add(
            NewArticle(
                self.feed,
                f"g{self.n}",
                title,
                f"https://x/{self.n}",
                "c",
                "",
                self.clock.now(),
                "2026-10-16",
            )
        )


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def listed(env, topic_id):
    return [item.id for item in env.reader.list_articles(topic_id=topic_id).items]


def test_a_rejected_article_leaves_that_topics_list_but_stays_everywhere_else(env):
    article = env.article()
    env.topics.record_matches(article, {env.ott: ("netflix",)})
    assert env.topics.reject(article, env.ott) is True
    assert listed(env, env.ott) == []
    assert [i.id for i in env.reader.list_articles().items] == [article]
    assert [i.id for i in env.reader.list_articles(feed_id=env.feed).items] == [article]


def test_a_rejected_topic_is_no_longer_a_badge_in_the_list(env):
    article = env.article()
    env.topics.record_matches(article, {env.ott: (), env.game: ()})
    env.topics.reject(article, env.ott)
    assert env.reader.list_articles().items[0].topics == ("게임",)
    assert [m.name for m in env.reader.topics_of(article)] == ["게임"]


def test_rejecting_can_be_undone(env):
    article = env.article()
    env.topics.record_matches(article, {env.ott: ("netflix",)})
    env.topics.reject(article, env.ott)
    assert env.topics.restore(article, env.ott) is True
    assert listed(env, env.ott) == [article]


def test_rejecting_or_restoring_something_that_is_not_there_changes_nothing(env):
    article = env.article()
    assert env.topics.reject(article, env.ott) is False  # 속해 있지 않다
    env.topics.record_matches(article, {env.ott: ()})
    assert env.topics.restore(article, env.ott) is False  # 뺀 적이 없다
    env.topics.reject(article, env.ott)
    assert env.topics.reject(article, env.ott) is False  # 이미 뺐다


def test_adding_by_hand_puts_the_article_in_the_topic_list(env):
    article = env.article("게임 소식")
    assert env.topics.add_manual(article, env.game) is True
    assert listed(env, env.game) == [article]
    (membership,) = env.topics.memberships(article)
    assert (membership.name, membership.source, membership.rejected, membership.keywords) == (
        "게임",
        "manual",
        False,
        (),
    )


def test_adding_by_hand_twice_changes_nothing(env):
    article = env.article()
    env.topics.add_manual(article, env.game)
    first = env.topics.memberships(article)
    assert env.topics.add_manual(article, env.game) is True
    assert env.topics.memberships(article) == first


def test_adding_an_article_the_user_rejected_brings_it_back_and_keeps_it_automatic(env):
    article = env.article()
    env.topics.record_matches(article, {env.ott: ("netflix",)})
    env.topics.reject(article, env.ott)
    assert env.topics.add_manual(article, env.ott) is True
    (membership,) = env.topics.memberships(article)
    assert (membership.source, membership.rejected, membership.keywords) == (
        "auto",
        False,
        ("netflix",),
    )


@pytest.mark.parametrize(("article", "topic"), [(999, "ott"), ("a", 999)])
def test_adding_a_missing_article_or_topic_is_refused(env, article, topic):
    real = env.article()
    article_id = real if article == "a" else article
    topic_id = env.ott if topic == "ott" else topic
    assert env.topics.add_manual(article_id, topic_id) is False
    assert env.topics.memberships(real) == []


def test_a_later_automatic_judgement_does_not_undo_what_the_user_decided(env):
    article = env.article()
    env.topics.record_matches(article, {env.ott: ("netflix",)})
    env.topics.reject(article, env.ott)
    env.topics.add_manual(article, env.game)
    env.topics.record_matches(article, {env.ott: ("netflix", "trailer"), env.game: ("steam",)})
    by_name = {m.name: m for m in env.topics.memberships(article)}
    assert by_name["OTT"].rejected is True and by_name["OTT"].keywords == ("netflix", "trailer")
    assert by_name["게임"].source == "manual" and by_name["게임"].keywords == ("steam",)


def test_flags_tell_delivery_what_the_user_chose(env):
    article = env.article()
    env.topics.record_matches(article, {env.ott: ("netflix",)})
    env.topics.reject(article, env.ott)
    env.topics.add_manual(article, env.game)
    assert env.topics.flags_for(article) == {env.ott: ("auto", True), env.game: ("manual", False)}
    assert env.topics.flags_for(999) == {}


def test_feedback_samples_list_manual_and_rejected_articles_newest_first(env):
    first, second, third = env.article("첫 글"), env.article("둘째 글"), env.article("셋째 글")
    env.topics.record_matches(first, {env.ott: ("netflix",)})
    env.topics.record_matches(
        third, {env.ott: ("netflix",)}
    )  # 사용자가 건드리지 않은 글은 나오지 않는다
    env.topics.add_manual(second, env.ott)
    env.clock.advance(minutes=5)
    env.topics.reject(first, env.ott)
    samples = env.topics.feedback_samples(env.ott)
    assert [(s.title, s.source, s.rejected) for s in samples] == [
        ("첫 글", "auto", True),
        ("둘째 글", "manual", False),
    ]
    assert [s.title for s in env.topics.feedback_samples(env.ott, limit=1)] == ["첫 글"]


def test_keyword_outcomes_count_only_automatic_matches(env):
    kept, dropped, manual = env.article(), env.article(), env.article()
    env.topics.record_matches(kept, {env.ott: ("netflix",)})
    env.topics.record_matches(dropped, {env.ott: ("netflix", "trailer")})
    env.topics.reject(dropped, env.ott)
    env.topics.add_manual(manual, env.ott)
    assert sorted(env.topics.keyword_outcomes(env.ott)) == [
        (("netflix",), False),
        (("netflix", "trailer"), True),
    ]


def test_a_deleted_article_takes_its_feedback_with_it(env):
    article = env.article()
    env.topics.add_manual(article, env.ott)
    with env.db.connect() as conn:
        conn.execute("DELETE FROM articles WHERE id = ?", (article,))
    assert env.topics.memberships(article) == [] and env.topics.feedback_samples(env.ott) == []


def test_a_deleted_topic_takes_its_feedback_with_it(env):
    article = env.article()
    env.topics.add_manual(article, env.game)
    env.topics.delete(env.game)
    assert env.topics.memberships(article) == []
