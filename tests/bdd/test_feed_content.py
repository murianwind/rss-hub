"""36_feed_content.feature: 요약과 전체 본문 중 더 완전한 쪽을 RSS 본문으로 저장한다."""

from types import SimpleNamespace

import pytest
from pytest_bdd import given, then, when

from tests.bdd.binding import bind
from tests.fakes.collect_env import CollectEnv
from tests.fakes.entries import entry

bind(globals(), "36_feed_content.feature", [f"FCT-{n:02d}" for n in range(1, 5)])

TEASER = "<p>앞부분만 보이는 요약입니다 […]</p>"
FULL = "<p>앞부분만 보이는 요약입니다.</p><p>둘째 문단까지 이어지는 전체 본문입니다.</p>"
LONG_SUMMARY = "<p>" + "긴 요약 문장입니다. " * 10 + "</p>"


@pytest.fixture
def env(tmp_path):
    return CollectEnv(tmp_path)


@pytest.fixture
def ctx():
    return SimpleNamespace(feed=None, expected="")


def _serve(env, **fields):
    feed, url = env.add_feed()
    item = {k: v for k, v in entry().items() if k != "summary"}
    env.fetcher.serve(url, [{**item, **fields}])
    return feed


@given("피드가 잘린 요약과 전체 본문을 함께 보낸다")
def _teaser_and_full(env, ctx):
    ctx.feed = _serve(env, summary=TEASER, content=[{"type": "text/html", "value": FULL}])
    ctx.expected = FULL


@given("피드가 요약만 보낸다")
def _summary_only(env, ctx):
    ctx.feed = _serve(env, summary=TEASER)
    ctx.expected = TEASER


@given("피드가 긴 요약과 짧은 본문을 함께 보낸다")
def _long_summary(env, ctx):
    ctx.feed = _serve(
        env, summary=LONG_SUMMARY, content=[{"type": "text/html", "value": "<p>짧음</p>"}]
    )
    ctx.expected = LONG_SUMMARY


@given("피드가 설명(description)만 보낸다")
def _description_only(env, ctx):
    ctx.feed = _serve(env, description="<p>설명입니다.</p>")
    ctx.expected = "<p>설명입니다.</p>"


@when("수집한다")
def _collect(env, ctx):
    env.collect(ctx.feed)


@then("저장된 RSS 본문은 전체 본문이다")
@then("저장된 RSS 본문은 요약이다")
@then("저장된 RSS 본문은 설명이다")
def _stored_body(env, ctx):
    assert [a.content_html for a in env.collected()] == [ctx.expected]
