"""37_model_usage_time.feature: 모델 잔여 사용량의 갱신 시각."""

import re
from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, then, when

from rss_hub.services.ports import ServerUsage
from tests.bdd.binding import bind
from tests.fakes.viewer_world import open_world
from tests.keywords.browser import post

bind(globals(), "37_model_usage_time.feature", [f"UTM-{n:02d}" for n in range(1, 5)])

KEY = "sk-or-v1-" + "a" * 32


@pytest.fixture
def world(tmp_path):
    with open_world(tmp_path) as opened:
        yield opened


@pytest.fixture
def ctx():
    return SimpleNamespace(html="", response=None, js="")


def usage_stamp(html):
    found = re.search(r'<span class="model-usage-at"[^>]*>(.*?)</span>', html, re.S)
    return re.sub(r"<[^>]+>", "", found.group(1)).strip() if found else None


@given("모델이 설정되어 있고 서버는 오늘 33회 사용했다고 알린다")
def _configured(world):
    world.parts.settings.set_openrouter_key(KEY)
    world.parts.llm.usage = ServerUsage(used=33, limit=1000)


@given("읽기 화면을 열어 잔여 사용량을 불러왔다")
@when("읽기 화면을 연다")
def _open(world, ctx):
    ctx.html = world.get("/reader").text


@when("10초가 지난 뒤 읽기 화면을 다시 연다")
def _reopen_later(world, ctx):
    world.parts.clock.advance(seconds=10)
    ctx.html = world.get("/reader").text


@when("10초가 지난 뒤 잔여 사용량을 새로고침한다")
def _refresh_later(world, ctx):
    world.parts.clock.advance(seconds=10)
    ctx.response = post(world, "/ui/model-usage/refresh")


@then(parsers.parse('사이드바의 잔여 사용량 아래에 "{text}"이 보인다'))
def _stamp(ctx, text):
    assert usage_stamp(ctx.html) == text


@then(parsers.parse('새로고침 응답의 갱신 시각은 "{stamp}"이고 숫자는 그대로다'))
def _refreshed(ctx, stamp):
    assert ctx.response.json() == {"remaining": 967, "cap": 1000, "updated": stamp}


@given("화면 스크립트가 있다")
def _script(world, ctx):
    ctx.js = world.client.get("/static/app.js").text


@then("스크립트는 상태와 새로고침 응답의 갱신 시각을 data-model-usage-at 자리에 쓴다")
def _js(ctx):
    assert "data-model-usage-at" in ctx.js and "function showUsageTime" in ctx.js
    assert "showUsageTime(state.model_usage.updated)" in ctx.js
    assert "showUsageTime(data.updated)" in ctx.js
