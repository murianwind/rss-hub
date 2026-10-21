"""21_plain_mode.feature: OpenRouter 키 없이 Discord 웹훅만으로 쓰기."""

from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, then, when

from rss_hub.storage.articles import STATUS_COLLECTED
from tests.bdd.binding import bind
from tests.fakes.llm_env import KEY
from tests.fakes.plain_env import DEFAULT_WEBHOOK, GAME_WEBHOOK, PlainEnv
from tests.keywords.page import text_of

bind(globals(), "21_plain_mode.feature", [f"PLN-{n:02d}" for n in range(1, 7)])


@pytest.fixture
def env(tmp_path):
    return PlainEnv(tmp_path)


@pytest.fixture
def ctx():
    return SimpleNamespace(ids={}, response=None)


@given("OpenRouter 키는 설정하지 않았다")
def _no_key(env):
    assert not env.settings.has_openrouter_key()


@given("기본 웹훅과 서비스 주소는 설정했다")
def _webhook_and_url(env):
    snapshot = env.settings.snapshot()
    assert snapshot.webhook_default_id and snapshot.base_url


@given("기본 웹훅 지정을 해제했다")
def _no_default_webhook(env):
    env.settings.set_webhook_roles(default_id=None, system_id=None)


@given(parsers.parse('새 글 "{title}"이 수집되었다'))
def _collected(env, ctx, title):
    ctx.ids[title] = env.add_article(title=title, content="<p>body text</p>")


@given(parsers.parse('키워드 "{keyword}"이 있고 웹훅 "{name}"이 지정된 주제 "{topic}"이 있다'))
def _keyword_topic(env, keyword, name, topic):
    env.add_topic(topic, [keyword])


@given(parsers.parse('키워드가 없고 웹훅 "{name}"이 지정된 주제 "{topic}"이 있다'))
def _keywordless_topic(env, name, topic):
    env.add_topic(topic, [])


@given("요약 잡과 발송 잡이 차례로 실행되었다")
@when("요약 잡과 발송 잡이 차례로 실행된다")
def _run(env):
    env.run_pipeline()


@when("OpenRouter 키를 설정한다")
def _set_key(env):
    env.settings.set_openrouter_key(KEY)


@when(parsers.parse('새 글 "{title}"이 수집되고 요약 잡이 실행된다'))
def _second_story(env, ctx, title):
    ctx.ids[title] = env.add_article(title=title, content="<p>second body</p>")
    env.summarizer.run()


@then("LLM 호출은 없다")
def _no_calls(env):
    assert env.client.calls == []


@then(parsers.parse('기본 웹훅으로 "{title}"과 서비스 글 링크가 든 메시지가 한 건 간다'))
def _one_message(env, ctx, title):
    (message,) = env.sent_to(DEFAULT_WEBHOOK)
    assert title in message
    assert f"https://rss.example.com/a/{ctx.ids[title]}" in message
    ctx.message = message


@then("메시지에 요약 줄은 없다")
def _no_summary(ctx):
    lines = ctx.message.split("\n")
    assert len(lines) == 3  # 머리말, 제목, 링크


@then("글은 수집된 상태로 남고 아무것도 보내지 않는다")
def _waiting(env, ctx):
    (article_id,) = ctx.ids.values()
    assert env.articles.get(article_id).status == STATUS_COLLECTED
    assert env.sender.calls == []


@then('기본 웹훅과 웹훅 "게임"으로 한 건씩 간다')
def _both(env):
    assert len(env.sent_to(DEFAULT_WEBHOOK)) == 1
    assert len(env.sent_to(GAME_WEBHOOK)) == 1


@then("기본 웹훅으로만 한 건 간다")
def _default_only(env):
    assert len(env.sent_to(DEFAULT_WEBHOOK)) == 1
    assert env.sent_to(GAME_WEBHOOK) == []


@then("첫 글은 다시 요약되지 않고 LLM 호출은 두 번째 글에 대해서만 한 번 있다")
def _only_second(env, ctx):
    assert len(env.client.calls) == 1
    assert env.articles.get(ctx.ids["Apple unveils new phone"]).llm_model == "plain"
    assert env.articles.get(ctx.ids["Second story"]).llm_model != "plain"


@when("상태 화면을 연다")
def _status(world, ctx):
    """배경의 설정은 같은 데이터베이스 파일에 들어 있으므로 앱이 그대로 읽는다."""
    ctx.response = world.get("/status")


@then('"OpenRouter 키"는 "선택"으로 표시되고 필요한 설정이 모두 채워졌다고 안내한다')
def _status_text(ctx):
    text = text_of(ctx.response)
    assert "OpenRouter 키 선택" in text or "OpenRouter 키 (선택)" in text
    assert "필요한 설정이 모두 채워졌습니다" in text
