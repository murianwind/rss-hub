import pytest

from rss_hub.domain.prompts import TopicExamples
from rss_hub.domain.topics import TopicFields
from rss_hub.services.topic_examples import load_examples
from rss_hub.storage.articles import ArticleRepository, NewArticle
from rss_hub.storage.database import Database
from rss_hub.storage.feeds import FeedRepository
from rss_hub.storage.topics import TopicRepository
from tests.fakes.clock import FakeClock


@pytest.fixture
def env(tmp_path):
    db, clock = Database(tmp_path / "rss_hub.db"), FakeClock()
    topics, articles = TopicRepository(db, clock), ArticleRepository(db, clock)
    feed = FeedRepository(db, clock).add("https://a.example.com/rss", "A")
    ott = topics.add(TopicFields("OTT", "", ("netflix",)))
    game = topics.add(TopicFields("게임", "", ("steam",)))

    def article(title):
        return articles.add(
            NewArticle(feed, title, title, f"https://x/{title}", "c", "", clock.now(), "2026-10-16")
        )

    return topics, clock, ott, game, article


def test_zero_or_negative_means_no_examples(env):
    topics, _, ott, _, article = env
    topics.add_manual(article("a"), ott)
    candidates = topics.list_all()
    assert (
        load_examples(topics, candidates, 0) == {} and load_examples(topics, candidates, -1) == {}
    )


def test_examples_are_split_by_kind_newest_first_and_limited(env):
    topics, clock, ott, _, article = env
    for name in ("m1", "m2", "m3"):
        topics.add_manual(article(name), ott)
        clock.advance(minutes=1)
    for name in ("r1", "r2"):
        item = article(name)
        topics.record_matches(item, {ott: ("netflix",)})
        topics.reject(item, ott)
        clock.advance(minutes=1)
    found = load_examples(topics, topics.list_all(), 2)
    assert found == {ott: TopicExamples(("m3", "m2"), ("r2", "r1"))}


def test_only_topics_with_examples_appear_and_only_candidates_are_loaded(env):
    topics, _, ott, game, article = env
    topics.add_manual(article("a"), ott)
    topics.add_manual(article("b"), game)
    only_game = [t for t in topics.list_all() if t.id == game]
    assert list(load_examples(topics, only_game, 3)) == [game]


def test_an_automatic_match_nobody_touched_is_not_an_example(env):
    topics, _, ott, _, article = env
    topics.record_matches(article("a"), {ott: ("netflix",)})
    assert load_examples(topics, topics.list_all(), 3) == {}


def test_a_negative_count_gives_nothing_even_when_many_examples_exist(env):
    topics, _, ott, _, article = env
    for name in ("a", "b", "c"):
        topics.add_manual(article(name), ott)
    assert load_examples(topics, topics.list_all(), -1) == {}
