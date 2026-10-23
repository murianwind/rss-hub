"""34_mobile_mark_all.feature: 모바일 RSS Hub 바의 모두 읽음 버튼."""

import re
from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, then, when

from tests.bdd.binding import bind
from tests.bdd.test_mobile_reading import narrow_css
from tests.keywords.browser import post

bind(globals(), "34_mobile_mark_all.feature", [f"MKA-{n:02d}" for n in range(1, 7)])

BAR = re.compile(r'<header class="mobilebar">(.*?)</header>', re.S)


@pytest.fixture
def ctx():
    return SimpleNamespace(html="", articles=[], js="")


@given("읽지 않은 글이 있는 목록이다")
def _unread(world, ctx):
    ctx.articles = [world.article(title=f"글 {n}") for n in range(2)]


@given("모든 글을 읽은 목록이다")
def _all_read(world, ctx):
    ctx.articles = [world.article(title="읽은 글")]
    world.articles.mark_read(ctx.articles[0])


@when("읽기 목록을 연다")
def _open(world, ctx):
    ctx.html = world.get("/reader").text


@then("RSS Hub 바에 모두 읽음 버튼이 보이고 좁은 화면의 머리줄에는 보이지 않는다")
def _in_bar(world, ctx):
    bar = BAR.search(ctx.html).group(1)
    assert "모두 읽음" in bar and "data-mark-all" in bar
    assert not re.search(r"data-mark-all[^>]* hidden>", bar)
    assert ".viewbar .mark-all { display: none; }" in narrow_css(world)


@then("RSS Hub 바의 모두 읽음 버튼은 숨겨져 있다")
def _hidden(ctx):
    assert re.search(r"data-mark-all[^>]* hidden>", BAR.search(ctx.html).group(1))


@given("화면 스크립트가 있다")
def _script(world, ctx):
    ctx.js = world.client.get("/static/app.js").text


@then("스크립트는 상태의 읽지 않은 글 수로 모두 읽음 버튼을 보이거나 숨긴다")
def _js(ctx):
    assert "function showMarkAll" in ctx.js and "data-mark-all" in ctx.js
    assert "showMarkAll(state)" in ctx.js


@when("RSS Hub 바의 모두 읽음 버튼을 누른다")
def _press(world):
    bar = BAR.search(world.get("/reader").text).group(1)
    fields = dict(re.findall(r'name="(\w+)" value="([^"]*)"', bar))
    assert post(world, "/reader/mark-read", **fields).status_code in (200, 303)


@then("목록의 글은 모두 읽음이다")
def _read(world, ctx):
    assert all(world.articles.get(a).read_at is not None for a in ctx.articles)


@given("뉴스 블로그 사이트에 읽지 않은 글이 있다")
def _news_unread(world, ctx):
    ctx.articles = [world.article(world.f_news)]


def _path(world, where):
    return (
        f"/reader/feed/{world.f_news}"
        if where == "사이트 목록"
        else f"/reader/category/{world.news}"
    )


@when(parsers.re(r"(?P<where>사이트 목록|카테고리 목록)을 연다"))
def _open_scope(world, ctx, where):
    ctx.html = world.get(_path(world, where)).text


@then("RSS Hub 바의 모두 읽음 버튼이 보인다")
def _bar_visible(ctx):
    bar = BAR.search(ctx.html).group(1)
    assert "data-mark-all" in bar and not re.search(r"data-mark-all[^>]* hidden>", bar)


@when(parsers.re(r"그 사이트의 글을 모두 읽고 (?P<where>사이트 목록|카테고리 목록)을 다시 연다"))
def _read_then_reopen(world, ctx, where):
    for article in ctx.articles:
        world.articles.mark_read(article)
    ctx.html = world.get(_path(world, where)).text


@then("머리줄의 모두 읽음 버튼도 같은 조건으로 숨겨져 있다")
def _viewbar_hidden(ctx):
    viewbar = ctx.html.split('<header class="viewbar">')[1].split("</header>")[0]
    assert re.search(r'class="mark-all" data-mark-all="[^"]*" hidden>', viewbar)


@then("머리줄의 모두 읽음 버튼이 보인다")
def _viewbar_visible(ctx):
    viewbar = ctx.html.split('<header class="viewbar">')[1].split("</header>")[0]
    assert (
        'class="mark-all" data-mark-all' in viewbar
        and " hidden>" not in viewbar.split("<button")[0]
    )


@when("목록의 글을 모두 읽고 읽기 목록을 다시 연다")
def _read_all_and_reopen(world, ctx):
    for article in ctx.articles:
        world.articles.mark_read(article)
    ctx.html = world.get("/reader").text
