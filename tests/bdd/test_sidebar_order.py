"""33_sidebar_order.feature: 사이드바 RSS 피드의 자동 정렬과 펼침."""

import re
from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, then, when

from tests.bdd.binding import bind
from tests.keywords.page import feed_ids, rss_section

bind(globals(), "33_sidebar_order.feature", [f"ORD-{n:02d}" for n in range(1, 7)])

OLDEST, NEWEST = 0, 600


@pytest.fixture
def ctx():
    return SimpleNamespace(html="", state={}, ids={}, articles={})


def _site(world, ctx, name, minutes=None, *, read=False):
    ctx.ids[name] = world.feeds.add(f"https://{len(ctx.ids)}.example.com/rss", name)
    if minutes is not None:
        article = world.article(ctx.ids[name], minutes)
        ctx.articles[name] = [article]
        if read:
            world.articles.mark_read(article)


def _order(ctx, ids):
    """주어진 사이트 이름들만 뽑은, 사이드바에 나온 순서."""
    by_id = {v: k for k, v in ctx.ids.items()}
    return [by_id[i] for i in ids if i in by_id]


def _names(text):
    return re.findall(r'"([^"]+)"', text)


@given("사이트가 둘 있다")
def _two_sites(world):
    assert world.f_news and world.f_free


@given(parsers.parse('사이트 "{name}"에 읽지 않은 글이 있고 발행이 가장 오래되었다'))
def _unread_oldest(world, ctx, name):
    _site(world, ctx, name, OLDEST)


@given(parsers.parse('사이트 "{name}"에 읽지 않은 글이 있고 발행이 가장 최근이다'))
def _unread_newest(world, ctx, name):
    _site(world, ctx, name, NEWEST)


@given(parsers.parse('사이트 "{name}"은 모든 글을 읽었고 발행이 가장 최근이다'))
def _read_newest(world, ctx, name):
    _site(world, ctx, name, NEWEST + 60, read=True)


@given(parsers.parse('글이 없는 사이트 "{first}", "{second}"가 있다'))
def _empty_sites(world, ctx, first, second):
    _site(world, ctx, first)
    _site(world, ctx, second)


@when(parsers.parse('"{name}"의 글을 모두 읽는다'))
def _read_all(world, ctx, name):
    for article in ctx.articles[name]:
        world.articles.mark_read(article)


@when("읽기 화면을 연다")
def _open_reader(world, ctx):
    ctx.html = world.get("/reader").text


@when("화면 상태를 가져온다")
def _fetch_state(world, ctx):
    ctx.state = world.get("/ui/state").json()


@then("RSS 피드 구역은 펼쳐져 있다")
def _rss_open(ctx):
    assert '<details class="sec" id="sec-rss" open>' in ctx.html


@then(parsers.re(r"사이드바 사이트 순서는 (?P<names>.+)(이다|입니다)$"))
def _sidebar_order(ctx, names):
    assert _order(ctx, feed_ids(rss_section(ctx.html))) == _names(names)


@then(parsers.re(r"상태의 사이트 순서는 (?P<names>.+)이다$"))
def _state_order(ctx, names):
    assert _order(ctx, ctx.state["feed_order"]) == _names(names)


@given("화면 스크립트가 있다")
def _script(world, ctx):
    ctx.html = world.client.get("/static/app.js").text


@then("스크립트는 상태의 순서대로 사이트 줄을 옮긴다")
def _js_reorders(ctx):
    assert "state.feed_order" in ctx.html and "function sortFeeds" in ctx.html


@then("옮긴 뒤 보고 있는 사이트 줄이 목록에서 보이게 한다")
def _js_keeps_visible(ctx):
    body = ctx.html.split("function sortFeeds")[1].split("function applyState")[0]
    assert "showCurrent" in body
