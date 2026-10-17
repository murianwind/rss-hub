"""10_topics_and_categories.feature: 주제와 카테고리 관리."""

from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, then, when

from rss_hub.domain.topics import MAX_TOPICS, TopicFields, TopicInputError, validate_topic_fields
from rss_hub.services.importer import ImportService
from rss_hub.services.settings import SettingsService
from rss_hub.storage.database import Database
from rss_hub.storage.feeds import FeedRepository, FeedRuleError
from rss_hub.storage.import_staging import ImportStagingRepository
from rss_hub.storage.topics import TopicRepository
from tests.bdd.binding import bind
from tests.fakes.clock import FakeClock

bind(globals(), "10_topics_and_categories.feature", [f"TOP-{n:02d}" for n in range(1, 15)])

WEBHOOK_URL = "https://discord.com/api/webhooks/9/abc"
TOKENS = {
    "(빈 값)": "",
    "(41자)": "가" * 41,
    "(201자)": "가" * 201,
    "(키워드 41자)": "가" * 41,
    "(키워드 101개)": ",".join(f"k{i}" for i in range(101)),
}


class Env:
    def __init__(self, tmp_path):
        self.db = Database(tmp_path / "rss_hub.db")
        self.clock = FakeClock()
        self.settings = SettingsService(self.db, self.clock)
        self.feeds = FeedRepository(self.db, self.clock)
        self.topics = TopicRepository(self.db, self.clock)
        self.importer = ImportService(
            feeds=self.feeds, staging=ImportStagingRepository(self.db, self.clock), clock=self.clock
        )
        self.webhooks = {}

    def topic(self, name):
        return next(t for t in self.topics.list_all() if t.name == name)

    def category(self, name):
        return next(c for c in self.feeds.list_categories() if c.name == name)


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


@pytest.fixture
def ctx():
    return SimpleNamespace(error=None, feed_error=None)


def webhook_name(env, webhook_id):
    return next((n for n, i in env.webhooks.items() if i == webhook_id), None)


@given(parsers.parse('웹훅 "{name}"가 등록되어 있다'))
def _webhook(env, name):
    env.webhooks[name] = env.settings.add_webhook(name, WEBHOOK_URL)


# ---------- 처음 설치 ----------


@given('이전 설정에서 웹훅 "dev"가 OTT 웹훅이었다')
def _legacy_role(env):
    with env.db.connect() as conn:
        conn.execute(
            "INSERT INTO settings(key, value, updated_at) VALUES('webhook_ott_id', ?, 'x')",
            (str(env.webhooks["dev"]),),
        )


@when("서비스를 처음 시작한다")
@given("서비스를 처음 시작했다")
def _first_start(env):
    env.topics.ensure_defaults()


@when('주제 "OTT"를 지우고 서비스를 다시 시작한다')
def _delete_and_restart(env):
    env.topics.delete(env.topic("OTT").id)
    env.topics.ensure_defaults()


@then('주제는 "OTT" 하나뿐이다')
def _only_ott(env):
    assert [t.name for t in env.topics.list_all()] == ["OTT"]


@then("주제는 하나도 없다")
def _no_topics(env):
    assert env.topics.list_all() == []


@then(parsers.parse('주제 "OTT"의 키워드에 "{first}"와 "{second}"가 들어 있다'))
def _ott_keywords(env, first, second):
    assert {first, second} <= set(env.topic("OTT").keywords)


@then(parsers.parse('주제 "{name}"의 웹훅은 지정되어 있지 않다'))
def _topic_no_webhook(env, name):
    assert env.topic(name).webhook_id is None


@then(parsers.parse('주제 "{name}"의 웹훅은 "{webhook}"이다'))
def _topic_webhook(env, name, webhook):
    assert env.topic(name).webhook_id == env.webhooks[webhook]


# ---------- 입력 규칙 ----------


@given(parsers.parse('주제 "{name}"이 있다'))
def _topic_exists(env, name):
    env.topics.add(TopicFields(name, "", ()))


@given("주제가 20개 있다")
def _twenty_topics(env):
    for number in range(MAX_TOPICS):
        env.topics.add(TopicFields(f"주제{number}", "", ()))


ADD_TOPIC = (
    r'이름 "(?P<name>.*)", 설명 "(?P<description>.*)", '
    r'키워드 "(?P<keywords>.*)"로 주제를 추가한다'
)


@when(parsers.re(ADD_TOPIC))
def _add_topic(env, ctx, name, description, keywords):
    try:
        fields = validate_topic_fields(
            TOKENS.get(name, name),
            TOKENS.get(description, description),
            TOKENS.get(keywords, keywords),
        )
        env.topics.add(fields)
    except TopicInputError as error:
        ctx.error = error.message


@then(parsers.parse('오류 "{message}"가 표시된다'))
@then(parsers.parse('오류 "{message}"이 표시된다'))
def _error_shown(ctx, message):
    assert ctx.error == message


# ---------- 웹훅과 카테고리 ----------


@given(parsers.parse('카테고리 "{name}"와 주제 "{topic}"이 웹훅 "{webhook}"를 쓰고 있다'))
def _category_and_topic_use_webhook(env, name, topic, webhook):
    env.feeds.add_category(name, webhook_id=env.webhooks[webhook])
    env.topics.add(TopicFields(topic, "", ()), webhook_id=env.webhooks[webhook])


@when(parsers.parse('웹훅 "{name}"를 지운다'))
def _delete_webhook(env, name):
    env.settings.delete_webhook(env.webhooks[name])


@given(parsers.re(r'카테고리 "(?P<name>[^"]+)"가 있다'))
def _category_exists(env, name):
    env.feeds.add_category(name)


@when(parsers.parse('카테고리 "{name}"의 웹훅을 "{webhook}"로 지정한다'))
def _set_category_webhook(env, name, webhook):
    env.feeds.set_category_webhook(env.category(name).id, env.webhooks[webhook])


@when(parsers.parse('카테고리 "{name}"의 웹훅 지정을 해제한다'))
def _clear_category_webhook(env, name):
    env.feeds.set_category_webhook(env.category(name).id, None)


@then(parsers.parse('카테고리 "{name}"의 웹훅은 지정되어 있지 않다'))
def _category_no_webhook(env, name):
    assert env.category(name).webhook_id is None


@then(parsers.parse('카테고리 "{name}"의 웹훅은 "{webhook}"이다'))
def _category_webhook(env, name, webhook):
    assert env.category(name).webhook_id == env.webhooks[webhook]


@given(parsers.parse('OPML의 "{folder}" 폴더 아래 피드 2개를 가져왔다'))
def _import_folder(env, folder):
    body = (
        f'<outline text="{folder}"><outline text="a" xmlUrl="https://a.example.com/rss"/>'
        '<outline text="b" xmlUrl="https://b.example.com/rss"/></outline>'
    )
    data = f'<?xml version="1.0"?><opml version="2.0"><body>{body}</body></opml>'.encode()
    env.importer.confirm(env.importer.preview("subscriptions.opml", data).token)


@then(parsers.parse('카테고리 "{name}"는 피드 {count:d}개를 가진다'))
def _category_feed_count(env, name, count):
    assert env.category(name).feed_count == count


# ---------- 피드 웹훅 (TOP-10 ~ 14) ----------


def feed_by_name(env, name):
    return next(f for f in env.feeds.list_all() if f.name == name)


def new_feed(env, name, **options):
    return env.feeds.add(f"https://{name.encode().hex()}.example.com/rss", name, **options)


@given(parsers.re(r'카테고리에 속하지 않은 피드 "(?P<name>[^"]+)"가 있다'))
def _free_feed(env, name):
    new_feed(env, name)


@given(parsers.re(r'카테고리 "(?P<category>[^"]+)"에 속한 피드 "(?P<name>[^"]+)"가 있다'))
def _category_feed(env, category, name):
    new_feed(env, name, category_id=env.feeds.get_or_create_category(category)[0])


@given(parsers.re(r'웹훅 "(?P<webhook>[^"]+)"를 쓰는 피드 "(?P<name>[^"]+)"가 있다'))
def _feed_with_webhook(env, webhook, name):
    new_feed(env, name, webhook_id=env.webhooks[webhook])


def attempt(ctx, action):
    ctx.feed_error = None
    try:
        action()
    except FeedRuleError as error:
        ctx.feed_error = error.message


@when(parsers.re(r'피드 "(?P<name>[^"]+)"의 웹훅을 "(?P<webhook>[^"]+)"로 지정한다'))
def _set_feed_webhook(env, ctx, name, webhook):
    attempt(
        ctx, lambda: env.feeds.set_feed_webhook(feed_by_name(env, name).id, env.webhooks[webhook])
    )


@when(parsers.re(r'피드 "(?P<name>[^"]+)"의 웹훅 지정을 해제한다'))
def _clear_feed_webhook(env, ctx, name):
    attempt(ctx, lambda: env.feeds.set_feed_webhook(feed_by_name(env, name).id, None))


@when(parsers.re(r'피드 "(?P<name>[^"]+)"를 카테고리 "(?P<category>[^"]+)"에 넣는다'))
def _put_feed_in_category(env, ctx, name, category):
    attempt(
        ctx,
        lambda: env.feeds.set_feed_category(feed_by_name(env, name).id, env.category(category).id),
    )


@when(parsers.re(r'피드 "(?P<name>[^"]+)"를 카테고리에서 뺀다'))
def _remove_feed_from_category(env, ctx, name):
    attempt(ctx, lambda: env.feeds.set_feed_category(feed_by_name(env, name).id, None))


@then(parsers.re(r'피드 "(?P<name>[^"]+)"의 웹훅은 "(?P<webhook>[^"]+)"이다'))
def _feed_webhook_is(env, name, webhook):
    assert feed_by_name(env, name).webhook_id == env.webhooks[webhook]


@then(parsers.re(r'피드 "(?P<name>[^"]+)"의 웹훅은 지정되어 있지 않다'))
def _feed_has_no_webhook(env, name):
    assert feed_by_name(env, name).webhook_id is None


@then(parsers.re(r'피드 규칙 오류 "(?P<message>.+)"이 표시된다'))
def _feed_rule_error(ctx, message):
    assert ctx.feed_error == message


@then(parsers.re(r'피드 "(?P<name>[^"]+)"는 카테고리 "(?P<category>[^"]+)"에 속한다'))
def _feed_in_category(env, name, category):
    assert feed_by_name(env, name).category_id == env.category(category).id
