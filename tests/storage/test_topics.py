import pytest

from rss_hub.domain.topics import MAX_TOPICS, TopicFields, TopicInputError
from rss_hub.services.settings import SettingsService
from rss_hub.storage.articles import ArticleRepository, NewArticle
from rss_hub.storage.database import Database
from rss_hub.storage.feeds import FeedRepository
from rss_hub.storage.topics import (
    DEFAULT_TOPIC_DESCRIPTION,
    SEEDED_KEY,
    TopicRepository,
)
from tests.fakes.clock import FakeClock
from tests.keywords.store import topic_matches

WEBHOOK = "https://discord.com/api/webhooks/9/abc"


class Env:
    def __init__(self, tmp_path):
        self.db = Database(tmp_path / "rss_hub.db")
        self.clock = FakeClock()
        self.settings = SettingsService(self.db, self.clock)
        self.topics = TopicRepository(self.db, self.clock)
        self.feeds = FeedRepository(self.db, self.clock)
        self.articles = ArticleRepository(self.db, self.clock)

    def article(self):
        feed_id = self.feeds.add("https://f.example.com/rss", "피드")
        return self.articles.add(
            NewArticle(feed_id, "g1", "t", "https://x/1", "c", "", self.clock.now(), "2026-10-16")
        )


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def fields(name="게임", description="게임 소식", keywords=("steam", "스팀")):
    return TopicFields(name, description, tuple(keywords))


# ---------- 기본 동작 ----------


def test_a_topic_is_stored_and_read_back_with_korean_text(env):
    topic_id = env.topics.add(fields())
    topic = env.topics.get(topic_id)
    assert (topic.name, topic.description, topic.keywords) == (
        "게임",
        "게임 소식",
        ("steam", "스팀"),
    )
    assert (topic.webhook_id, topic.enabled) == (None, True)


def test_unknown_topics_are_not_found(env):
    assert env.topics.get(999) is None


def test_topics_are_listed_in_creation_order_and_enabled_ones_separately(env):
    first = env.topics.add(fields("가"))
    second = env.topics.add(fields("나"), enabled=False)
    third = env.topics.add(fields("다"))
    assert [t.id for t in env.topics.list_all()] == [first, second, third]
    assert [t.id for t in env.topics.list_enabled()] == [first, third]


def test_a_topic_may_have_a_webhook(env):
    webhook_id = env.settings.add_webhook("dev", WEBHOOK)
    topic_id = env.topics.add(fields(), webhook_id=webhook_id)
    assert env.topics.get(topic_id).webhook_id == webhook_id


def test_a_missing_webhook_is_refused(env):
    with pytest.raises(TopicInputError) as info:
        env.topics.add(fields(), webhook_id=999)
    assert info.value.message == "웹훅을 찾을 수 없음"


def test_names_must_be_unique_ignoring_case(env):
    env.topics.add(fields("Game"))
    with pytest.raises(TopicInputError) as info:
        env.topics.add(fields("GAME"))
    assert info.value.message == "같은 이름의 주제가 이미 있음"


def test_at_most_twenty_topics_can_exist(env):
    for number in range(MAX_TOPICS):
        env.topics.add(fields(f"주제{number}"))
    with pytest.raises(TopicInputError) as info:
        env.topics.add(fields("하나 더"))
    assert info.value.message == "주제는 20개까지"


# ---------- 수정과 삭제 ----------


def test_a_topic_can_be_edited(env):
    webhook_id = env.settings.add_webhook("dev", WEBHOOK)
    topic_id = env.topics.add(fields())
    assert env.topics.update(
        topic_id, fields("만화", "", ("anime",)), webhook_id=webhook_id, enabled=False
    )
    topic = env.topics.get(topic_id)
    assert (topic.name, topic.description, topic.keywords) == ("만화", "", ("anime",))
    assert (topic.webhook_id, topic.enabled) == (webhook_id, False)


def test_editing_an_unknown_topic_reports_it(env):
    assert env.topics.update(999, fields(), webhook_id=None, enabled=True) is False


def test_renaming_to_an_existing_name_is_refused(env):
    env.topics.add(fields("가"))
    other = env.topics.add(fields("나"))
    with pytest.raises(TopicInputError) as info:
        env.topics.update(other, fields("가"), webhook_id=None, enabled=True)
    assert info.value.message == "같은 이름의 주제가 이미 있음"


def test_editing_with_a_missing_webhook_is_refused(env):
    topic_id = env.topics.add(fields())
    with pytest.raises(TopicInputError):
        env.topics.update(topic_id, fields(), webhook_id=999, enabled=True)


def test_saving_a_topic_under_its_own_name_is_fine(env):
    topic_id = env.topics.add(fields("가"))
    assert env.topics.update(topic_id, fields("가", "새 설명"), webhook_id=None, enabled=True)


def test_a_topic_can_be_deleted_once(env):
    topic_id = env.topics.add(fields())
    assert env.topics.delete(topic_id) is True
    assert env.topics.delete(topic_id) is False
    assert env.topics.get(topic_id) is None


def test_deleting_a_webhook_clears_it_from_the_topics_that_used_it(env):
    webhook_id = env.settings.add_webhook("dev", WEBHOOK)
    topic_id = env.topics.add(fields(), webhook_id=webhook_id)
    env.settings.delete_webhook(webhook_id)
    topic = env.topics.get(topic_id)
    assert topic is not None and topic.webhook_id is None


# ---------- 글이 해당한 주제 ----------


def test_matches_are_recorded_with_their_keywords_and_replaced_when_recorded_again(env):
    topic_id = env.topics.add(fields())
    article_id = env.article()
    env.topics.record_matches(article_id, {topic_id: ("steam",)})
    assert topic_matches(env.db, article_id) == {topic_id: ("steam",)}
    env.topics.record_matches(article_id, {topic_id: ("스팀", "steam")})
    assert topic_matches(env.db, article_id) == {topic_id: ("스팀", "steam")}


def test_a_match_without_keywords_is_recorded_as_empty(env):
    topic_id = env.topics.add(fields(keywords=()))
    article_id = env.article()
    env.topics.record_matches(article_id, {topic_id: ()})
    assert topic_matches(env.db, article_id) == {topic_id: ()}


def test_an_article_without_matches_has_none(env):
    assert topic_matches(env.db, env.article()) == {}


def test_matches_disappear_with_their_topic_or_article(env):
    topic_id = env.topics.add(fields())
    article_id = env.article()
    env.topics.record_matches(article_id, {topic_id: ("steam",)})
    env.topics.delete(topic_id)
    assert topic_matches(env.db, article_id) == {}
    other = env.topics.add(fields("다른"))
    env.topics.record_matches(article_id, {other: ()})
    env.feeds.delete(env.feeds.list_all()[0].id)
    assert topic_matches(env.db, article_id) == {}


# ---------- 처음 설치할 때의 기본 주제 ----------


def test_the_first_start_creates_the_ott_topic_with_the_default_keywords(env):
    assert env.topics.ensure_defaults() is True
    (topic,) = env.topics.list_all()
    assert (topic.name, topic.description) == ("OTT", DEFAULT_TOPIC_DESCRIPTION)
    assert {"넷플릭스", "드라마", "netflix", "disney+", "trailer"} <= set(topic.keywords)
    assert (topic.webhook_id, topic.enabled) == (None, True)


def test_the_default_topic_is_created_only_once(env):
    env.topics.ensure_defaults()
    assert env.topics.ensure_defaults() is False
    assert len(env.topics.list_all()) == 1


def test_a_deleted_default_topic_is_not_created_again(env):
    env.topics.ensure_defaults()
    env.topics.delete(env.topics.list_all()[0].id)
    assert env.topics.ensure_defaults() is False
    assert env.topics.list_all() == []


def test_topics_that_already_exist_stop_the_default_from_being_created(env):
    env.topics.add(fields("내가 만든 주제"))
    assert env.topics.ensure_defaults() is False
    assert [t.name for t in env.topics.list_all()] == ["내가 만든 주제"]
    assert env.topics.ensure_defaults() is False  # 표시를 남겼으므로 이후에도 만들지 않는다


def _legacy_ott_role(env, value):
    with env.db.connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings(key, value, updated_at) "
            "VALUES('webhook_ott_id', ?, 'x')",
            (value,),
        )


def test_the_webhook_of_the_old_ott_role_becomes_the_default_topics_webhook(env):
    webhook_id = env.settings.add_webhook("ott", WEBHOOK)
    _legacy_ott_role(env, str(webhook_id))
    env.topics.ensure_defaults()
    assert env.topics.list_all()[0].webhook_id == webhook_id


@pytest.mark.parametrize("value", ["", "abc", "999"])
def test_an_unusable_old_ott_role_is_ignored(env, value):
    _legacy_ott_role(env, value)
    env.topics.ensure_defaults()
    assert env.topics.list_all()[0].webhook_id is None


def test_the_seeded_mark_is_a_setting_the_settings_service_does_not_mind(env):
    env.topics.ensure_defaults()
    with env.db.connect() as conn:
        assert conn.execute("SELECT value FROM settings WHERE key = ?", (SEEDED_KEY,)).fetchone()
    assert env.settings.snapshot().timezone is not None
