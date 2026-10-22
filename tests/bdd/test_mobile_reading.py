"""31_mobile_reading.feature: 모바일 글 화면과 읽음 처리 규칙."""

import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from pytest_bdd import given, then, when

from rss_hub.services.settings import SETTING_BY_KEY
from tests.bdd.binding import bind
from tests.fakes.delivery_env import DeliveryEnv

bind(globals(), "31_mobile_reading.feature", [f"MOB-{n:02d}" for n in range(1, 8)])

APP_JS = Path("src/rss_hub/web/static/app.js")


@pytest.fixture
def ctx():
    return SimpleNamespace(html="", article=None, ids=[], env=None, article_id=None)


@given("요약이 있는 글이 있다")
def _with_summary(world, ctx):
    ctx.article = world.article(title="요약 있는 글", ko="요약 있는 글", summary="요약입니다.")


@given("요약이 없는 글이 있다")
def _without_summary(world, ctx):
    ctx.article = world.article(title="요약 없는 글")


@when("글 화면을 연다")
def _open_article(world, ctx):
    response = world.get(f"/a/{ctx.article}?back=/reader")
    assert response.status_code == 200
    ctx.html = response.text


@then("위쪽 막대의 버튼은 좁은 화면에서 줄바꿈하지 않고 짧은 이름으로 바뀐다")
def _one_line_bar(world, ctx):
    bar = ctx.html.split('<header class="detailbar">')[1].split("</header>")[0]
    for short in ("목록", "읽지 않음"):
        assert f'<span class="label-short">{short}</span>' in bar
    assert 'class="label-long"' in bar
    css = world.get("/static/app.css").text
    narrow = css.split("@media (max-width: 820px)")
    rules = " ".join(block.split("}")[0] for block in narrow[1:])
    assert ".detailbar" in css and "flex-wrap: nowrap" in " ".join(narrow)
    assert ".label-long { display: none" in " ".join(narrow) and ".label-short" in css
    assert rules  # 좁은 화면 규칙이 있다


@then("요약은 접이식이고 스크립트가 없으면 펼쳐진 채로 보인다")
def _summary_accordion(ctx):
    assert re.search(
        r'<details class="panel doc-summary"[^>]* open>\s*<summary>요약</summary>', ctx.html
    )


@then("화면 스크립트는 좁은 화면에서 요약을 접는다")
def _script_collapses(world):
    script = world.get("/static/app.js").text
    assert 'matchMedia("(max-width: 820px)")' in script and ".doc-summary" in script


@then("요약 영역이 없다")
def _no_summary(ctx):
    assert "doc-summary" not in ctx.html


@then("화면 스크립트는 글의 아래쪽 끝이 목록 위로 넘어간 글만 읽음으로 처리한다")
def _bottom_rule(world):
    script = world.get("/static/app.js").text
    assert "getBoundingClientRect().bottom <= area.top" in script


@then("목록이 한 화면에 들어오거나 화면 위쪽 절반에 보인다는 이유로는 읽음 처리하지 않는다")
def _no_fits_rule(world):
    inspect = world.get("/static/app.js").text.split("var inspect = function")[1].split("};")[0]
    assert "fits" not in inspect and "middle" not in inspect and "scrollHeight" not in inspect


@given("읽지 않은 글이 세 개 있다")
def _three_unread(world, ctx):
    ctx.ids = [world.article(title=f"글 {n}") for n in range(3)]


@when("읽기 목록을 연다")
def _open_list(world):
    assert world.get("/reader").status_code == 200


@then("세 글은 모두 읽지 않음이다")
def _all_unread(world, ctx):
    assert all(world.articles.get(i).read_at is None for i in ctx.ids)


@given("발송을 기다리는 글이 하나 있다")
def _ready_article(tmp_path, ctx):
    ctx.env = DeliveryEnv(tmp_path)
    ctx.article_id = ctx.env.add_ready_article()


@when("발송 작업이 한 번 실행된다")
def _deliver(ctx):
    ctx.env.service.run()


@then("그 글은 발송되었고 여전히 읽지 않음이다")
def _delivered_unread(ctx):
    article = ctx.env.articles.get(ctx.article_id)
    assert article.status == "delivered" and article.read_at is None


@then("자동 읽음 설정의 설명에 화면 위로 스크롤해 지나간 글만이라고 적혀 있다")
def _help_text():
    assert "화면 위로 스크롤해 지나간 글만" in SETTING_BY_KEY["ui_auto_read"].help
