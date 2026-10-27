"""39_new_articles.feature: 수집 뒤 새 글을 목록 맨 위에 끼워 넣는다."""

import re
from types import SimpleNamespace

import pytest
from pytest_bdd import given, then, when

from tests.bdd.binding import bind
from tests.fakes.viewer_world import open_world

bind(globals(), "39_new_articles.feature", [f"NEW-{n:02d}" for n in range(1, 3)])


@pytest.fixture
def world(tmp_path):
    with open_world(tmp_path) as opened:
        yield opened


@pytest.fixture
def ctx():
    return SimpleNamespace(old=None, new=None, before=0, js="")


def total(world):
    feeds = world.client.get("/ui/state").json()["feeds"]
    return sum(feed["total"] for feed in feeds.values())


@given("글이 하나 있는 목록을 열어 두었다")
def _open_list(world, ctx):
    ctx.old = world.article(title="먼저 있던 글", minutes=0)
    ctx.before = total(world)
    assert "먼저 있던 글" in world.get("/reader").text


@when("수집으로 새 글이 들어온다")
def _collected(world, ctx):
    ctx.new = world.article(title="새로 들어온 글", minutes=30)


@then("상태의 전체 글 수가 하나 늘어 있다")
def _total_grew(world, ctx):
    assert total(world) == ctx.before + 1


@then("목록을 다시 받으면 새 글 카드가 맨 위에 있고 게시물 수가 늘어 있다")
def _new_card_first(world, ctx):
    html = world.get("/reader").text
    ids = re.findall(r'<article class="card[^"]*" data-id="(\d+)"', html)
    assert ids[:2] == [str(ctx.new), str(ctx.old)]
    assert "2개의 게시물" in html


@given("화면 스크립트가 있다")
def _script(world, ctx):
    ctx.js = world.client.get("/static/app.js").text


@then("스크립트는 글 수의 증가를 알아채 새 카드만 맨 위에 끼워 넣고 아래를 보고 있으면 기다린다")
def _js(ctx):
    js = ctx.js
    assert "function noteArticles" in js and "total > knownArticles" in js
    assert 'fetch("/ui/state"' in js and "noteArticles(state)" in js  # 열자마자 기준을 잡는다
    assert "list.insertBefore(document.importNode(card, true), anchor)" in js
    assert "box.scrollTop > TOP_NEAR" in js and "box.scrollTop <= TOP_NEAR" in js
    assert "article.card[data-id=" in js  # 이미 있는 카드는 다시 넣지 않는다
