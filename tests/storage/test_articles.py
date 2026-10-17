from datetime import UTC, datetime

import pytest

from rss_hub.storage.articles import (
    MODEL_FALLBACK,
    STATUS_COLLECTED,
    STATUS_READY,
    ArticleRepository,
    NewArticle,
)
from rss_hub.storage.database import Database
from rss_hub.storage.feeds import FeedRepository
from tests.fakes.clock import FakeClock


@pytest.fixture
def env(tmp_path):
    db = Database(tmp_path / "rss_hub.db")
    clock = FakeClock()
    feeds = FeedRepository(db, clock)
    articles = ArticleRepository(db, clock)
    feed_a = feeds.add("https://a.example.com/rss", "A")
    feed_b = feeds.add("https://b.example.com/rss", "B")
    return articles, clock, feed_a, feed_b


def new(feed_id, guid="g1", *, published=None, title="제목"):
    published = published or datetime(2026, 10, 16, 1, 0, tzinfo=UTC)
    return NewArticle(
        feed_id, guid, title, f"https://x/{guid}", "<p>본문</p>", "raw", published, "2026-10-16"
    )


def test_added_article_is_stored_as_collected_with_all_fields(env):
    articles, clock, feed_a, _ = env
    article_id = articles.add(new(feed_a))
    assert article_id is not None
    article = articles.get(article_id)
    assert article is not None
    assert article.status == STATUS_COLLECTED
    assert (article.feed_id, article.guid, article.title) == (feed_a, "g1", "제목")
    assert (article.link, article.content_html) == ("https://x/g1", "<p>본문</p>")
    assert article.published_dt == datetime(2026, 10, 16, 1, 0, tzinfo=UTC)
    assert article.published_date == "2026-10-16"
    assert article.discovered_at == clock.now()
    assert article.retry_count == 0


def test_adding_the_same_guid_again_is_ignored(env):
    articles, _, feed_a, _ = env
    assert articles.add(new(feed_a)) is not None
    assert articles.add(new(feed_a)) is None
    assert articles.count_by_status() == {STATUS_COLLECTED: 1}


def test_the_same_guid_from_another_feed_is_ignored_too(env):
    articles, _, feed_a, feed_b = env
    articles.add(new(feed_a, "same"))
    assert articles.add(new(feed_b, "same")) is None


def test_adding_an_article_marks_its_guid_as_seen(env):
    articles, _, feed_a, _ = env
    assert articles.is_seen("g1") is False
    articles.add(new(feed_a))
    assert articles.is_seen("g1") is True


def test_marking_seen_blocks_later_additions_and_counts_new_ones_only(env):
    articles, _, feed_a, _ = env
    assert articles.mark_seen(["a", "b", "a"], "baseline") == 2
    assert articles.mark_seen(["b", "c"], "baseline") == 1
    assert articles.add(new(feed_a, "a")) is None
    assert articles.count_by_status() == {}  # 기록만 했고 글은 만들지 않았다


def test_list_by_status_is_ordered_by_publication_time(env):
    articles, _, feed_a, _ = env
    late = datetime(2026, 10, 16, 3, 0, tzinfo=UTC)
    early = datetime(2026, 10, 16, 1, 0, tzinfo=UTC)
    articles.add(new(feed_a, "late", published=late))
    articles.add(new(feed_a, "early", published=early))
    assert [a.guid for a in articles.list_by_status(STATUS_COLLECTED)] == ["early", "late"]


def test_get_unknown_article_returns_none(env):
    assert env[0].get(999) is None


# ---------- 요약 결과 ----------


def test_a_new_article_has_no_summary_yet(env):
    articles, _, feed_a, _ = env
    article = articles.get(articles.add(new(feed_a)))
    assert (article.title_ko, article.summary_ko, article.llm_topics, article.llm_model) == (
        None,
        None,
        None,
        None,
    )


def test_marking_ready_stores_the_summary_and_clears_retries(env):
    articles, _, feed_a, _ = env
    article_id = articles.add(new(feed_a))
    articles.bump_retry(article_id)
    articles.mark_ready(
        article_id, title_ko="애플, 새 폰 공개", summary_ko="요약", topics=[2, 5], model="model-a"
    )
    article = articles.get(article_id)
    assert article.status == STATUS_READY
    assert (article.title_ko, article.summary_ko, article.llm_topics, article.llm_model) == (
        "애플, 새 폰 공개",
        "요약",
        (2, 5),
        "model-a",
    )
    assert article.retry_count == 0


def test_the_topics_the_llm_chose_are_stored_as_numbers_in_order(env):
    articles, _, feed_a, _ = env
    article_id = articles.add(new(feed_a))
    articles.mark_ready(article_id, title_ko="t", summary_ko="s", topics=[3, 1], model="m")
    assert articles.get(article_id).llm_topics == (3, 1)

    article_id = articles.add(new(feed_a, "g-none"))
    articles.mark_ready(article_id, title_ko="t", summary_ko="s", topics=[], model="m")
    assert articles.get(article_id).llm_topics == ()  # 판별했고 해당 주제가 없다


def test_bump_retry_returns_the_new_count(env):
    articles, _, feed_a, _ = env
    article_id = articles.add(new(feed_a))
    assert [articles.bump_retry(article_id) for _ in range(3)] == [1, 2, 3]
    assert articles.get(article_id).retry_count == 3
    assert articles.get(article_id).status == STATUS_COLLECTED


def test_fallback_finalization_marks_the_article_ready_with_the_fallback_model(env):
    articles, _, feed_a, _ = env
    article_id = articles.add(new(feed_a))
    articles.finalize_fallback(article_id, title_ko="원문 제목", summary_ko="원문 발췌...")
    article = articles.get(article_id)
    assert article.status == STATUS_READY
    assert article.llm_model == MODEL_FALLBACK == "fallback-final"
    assert (article.title_ko, article.summary_ko, article.llm_topics) == (
        "원문 제목",
        "원문 발췌...",
        None,  # 요약하지 못해서 주제를 판별하지 않았다
    )
    assert articles.list_by_status(STATUS_COLLECTED) == []


# ---------- 발송 완료 ----------


def test_marking_delivered_changes_the_status_and_labels_the_seen_record(env):

    articles, _, feed_a, _ = env
    article_id = articles.add(new(feed_a, "g-delivered"))
    articles.mark_ready(article_id, title_ko="t", summary_ko="s", topics=[], model="m")
    articles.mark_delivered(article_id)
    assert articles.get(article_id).status == "delivered"
    assert articles.is_seen("g-delivered") is True
    assert articles.list_by_status(STATUS_READY) == []


def test_ready_articles_are_listed_oldest_published_first(env):
    articles, _, feed_a, _ = env
    late = datetime(2026, 10, 16, 3, 0, tzinfo=UTC)
    early = datetime(2026, 10, 16, 1, 0, tzinfo=UTC)
    ids = [
        articles.add(new(feed_a, "late", published=late)),
        articles.add(new(feed_a, "early", published=early)),
    ]
    for article_id in ids:
        articles.mark_ready(article_id, title_ko="t", summary_ko="s", topics=[], model="m")
    assert [a.guid for a in articles.list_by_status(STATUS_READY)] == ["early", "late"]
