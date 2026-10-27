"""42_status_tabs.feature: 상태 화면의 탭 카드."""

import re
from types import SimpleNamespace

import pytest
from pytest_bdd import given, then, when

from rss_hub.domain.error_log import KIND_COLLECT
from rss_hub.storage.error_log import ErrorLogRepository
from tests.bdd.binding import bind
from tests.fakes.viewer_world import open_world

bind(globals(), "42_status_tabs.feature", [f"TAB-{n:02d}" for n in range(1, 6)])


@pytest.fixture
def world(tmp_path):
    with open_world(tmp_path) as opened:
        yield opened


@pytest.fixture
def ctx():
    return SimpleNamespace(html="", js="")


def groups(html):
    return re.findall(
        r'<div class="status-tabs" data-tabs>(.*?)(?=<div class="status-tabs"|\{%|\Z)', html, re.S
    )


@when("상태 화면을 연다")
def _open(world, ctx):
    ctx.html = world.get("/status").text


def tab_labels(group):
    bar = group.split("</div>")[0]
    return [
        re.sub(r"<[^>]+>", "", t).strip() for t in re.findall(r'role="tab"[^>]*>(.*?)</a>', bar)
    ]


@then(
    "첫 카드의 탭은 현재 상태, 작업 기록, 설정 점검이고 둘째 카드의 탭은 오류 기록, 변경 이력이다"
)
def _tabs(ctx):
    first, second = groups(ctx.html)
    assert tab_labels(first) == ["현재 상태", "작업 기록", "설정 점검"]
    assert [label.split()[0] for label in tab_labels(second)] == ["오류", "변경"]
    assert tab_labels(second)[1] == "변경 이력"


@then("탭마다 같은 이름의 패널이 같은 카드 안에 있다")
def _panels(ctx):
    for group in groups(ctx.html):
        ids = re.findall(r'data-tab="([^"]+)"', group)
        panels = re.findall(
            r'<section class="status-card panel tab-panel[^"]*" id="([^"]+)"', group
        )
        assert ids and ids == panels


@given("수집 오류가 두 번 기록되어 있다")
def _two_errors(world):
    log = ErrorLogRepository(world.parts.db, world.parts.clock)
    log.record(KIND_COLLECT, "피드", "시간 초과")
    world.parts.clock.advance(days=1)
    log.record(KIND_COLLECT, "피드", "시간 초과")


@then("오류 기록 탭에 건수 2가 나오고 칩과 정렬 링크는 오류 기록 탭을 가리킨다")
def _error_tab(ctx):
    assert 'data-tab="error-log">오류 기록 <b class="tab-count warn">2</b>' in ctx.html
    links = re.findall(r'<a class="chip-link[^"]*" href="(/status[^"]*)"', ctx.html)
    assert links and all(link.endswith("#error-log") for link in links)


@given("화면 스크립트가 있다")
def _script(world, ctx):
    ctx.js = world.client.get("/static/app.js").text


@then("스크립트는 탭을 눌러 패널을 바꾸고 해시와 기억해 둔 탭으로 처음 탭을 고른다")
def _tab_script(world, ctx):
    js = ctx.js
    assert "function activate(group, id)" in js and "panel.hidden = panel.id !== id" in js
    assert "window.location.hash.replace" in js and "rsshub.status.tab" in js
    css = world.get("/static/app.css").text
    assert ".status-tabs.tabs-ready .tab-panel > h2 { display: none; }" in css
    assert (
        ".tab-panel[hidden] { display: none; }" in css
    )  # tabs-ready일 때만 스크립트가 hidden을 건다


@then("현재 상태 패널은 상태 영역과 대기 글 영역으로 나뉘고 대기 글 목록은 펼쳐져 있다")
def _current_split(world, ctx):
    world.article(title="요약 대기 글")
    html = world.get("/status").text
    panel = html.split('id="panel-current"')[1].split("</section>")[0]
    assert '<div class="current-main">' in panel and '<div class="current-pending">' in panel
    assert '<details class="pending-box" open>' in panel


@then("넓은 화면 규칙은 현재 상태 패널을 두 칸으로 나눈다")
def _wide_css(world):
    css = world.get("/static/app.css").text
    assert "#panel-current { display: grid; grid-template-columns:" in css


@then("스크립트는 쉬는 동안 다음 실행 시각만 고치고 실행 중이면 표를 바꾸고 숨겨지면 쉰다")
def _poll_script(ctx):
    js = ctx.js
    assert "function refreshNextRuns(doc)" in js and "[data-next-run]" in js
    assert "var RUNNING_MS = 1500;" in js and "var IDLE_MS = 10000;" in js
    assert "if (running || nowRunning)" in js and "swap(current, nextCurrent)" in js
    assert 'document.visibilityState === "hidden"' in js
