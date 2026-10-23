"""31_mobile_reading.feature: 모바일 글 화면과 읽음 처리 규칙."""

import html as html_module
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from pytest_bdd import given, then, when

from rss_hub.services.settings import SETTING_BY_KEY
from tests.bdd.binding import bind
from tests.fakes.delivery_env import DeliveryEnv
from tests.keywords.browser import BROWSER

bind(globals(), "31_mobile_reading.feature", [f"MOB-{n:02d}" for n in range(1, 17)])

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


def narrow_css(world):
    """좁은 화면(820px 이하) 규칙들."""
    css = world.get("/static/app.css").text
    return " ".join(block.split("\n}")[0] for block in css.split("@media (max-width: 820px)")[1:])


@then("북마크와 읽지 않음 버튼이 RSS Hub 바에 있다")
def _bar_actions(ctx):
    bar = ctx.html.split('class="mobilebar"')[1].split("</header>")[0]
    assert "data-mobile-actions" in bar
    assert 'action="/a/' in bar and "/bookmark" in bar and "/read" in bar


@then("좁은 화면에서는 따로 있던 위쪽 막대와 목록으로 버튼이 보이지 않는다")
def _detailbar_hidden(world, ctx):
    assert 'class="back"' in ctx.html  # 데스크톱의 목록으로 버튼과 스와이프가 쓴다
    assert ".article-page .detailbar { display: none" in narrow_css(world)


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


READ_FORM = re.compile(
    r'<form method="post" action="/a/(\d+)/read">'
    r'\s*<input type="hidden" name="state" value="(\w+)">'
    r'\s*<input type="hidden" name="next" value="([^"]+)">'
)


@given("읽은 글이 있다")
def _read_article(world, ctx):
    ctx.article = world.article(title="읽은 글")
    assert world.get(f"/a/{ctx.article}?back=/reader").status_code == 200  # 열면 읽음이 된다
    assert world.articles.get(ctx.article).read_at is not None


def mobile_read_form(html):
    bar = html.split('class="mobilebar"')[1].split("</header>")[0]
    article_id, state, next_value = READ_FORM.search(bar).groups()
    return article_id, state, html_module.unescape(next_value)  # 브라우저가 보내는 값


@when("글 화면에서 읽지 않음 버튼을 누른다")
def _press_unread(world, ctx):
    page = world.get(f"/a/{ctx.article}?back=/reader").text
    article_id, state, next_value = mobile_read_form(page)
    assert state == "unread"
    sent = world.client.post(
        f"/a/{article_id}/read", data={"state": state, "next": next_value}, headers=BROWSER
    )
    assert sent.status_code == 303
    ctx.location = sent.headers["location"]
    ctx.html = world.get(ctx.location).text


@then("같은 글 화면으로 돌아오고 글은 읽지 않음으로 남는다")
def _stays(world, ctx):
    assert ctx.location.startswith(f"/a/{ctx.article}")
    assert (
        world.articles.get(ctx.article).read_at is None
    )  # 돌아온 화면을 열어도 읽음이 되지 않는다


@then("버튼은 읽음으로로 바뀌고 그것을 누르면 읽음이 된다")
def _toggle_to_read(world, ctx):
    article_id, state, next_value = mobile_read_form(ctx.html)
    assert state == "read" and "읽음으로" in ctx.html.split('class="mobilebar"')[1]
    world.client.post(
        f"/a/{article_id}/read", data={"state": state, "next": next_value}, headers=BROWSER
    )
    assert world.articles.get(ctx.article).read_at is not None


@then("좁은 화면의 글 화면은 머리 영역을 고정하지 않고 하나의 영역이 스크롤된다")
def _one_scroll_area(world):
    css = narrow_css(world)
    assert ".article-page .detail-scroll { overflow-y: auto" in css
    assert ".article-page .doc-fixed { max-height: none; overflow: visible" in css
    assert ".article-page .doc-scroll { overflow: visible" in css


@then("좁은 화면의 글 화면에서 RSS Hub 바는 본문 위에 겹쳐 있고 스크롤하면 숨는다")
def _overlay_bar(world):
    css = narrow_css(world)
    assert ".article-page .mobilebar { position: fixed" in css
    assert ".article-page .mobilebar.bar-hidden { transform: translateY(-100%)" in css


@then("화면 스크립트는 스크롤이 멈추면 바를 다시 보인다")
def _bar_returns(world):
    script = world.get("/static/app.js").text
    assert "bar-hidden" in script and "setTimeout" in script.split("bar-hidden")[1][:400]


@then(
    "숨겨진 목록으로 링크가 남아 있고 화면 스크립트는 왼쪽 가장자리 스와이프로 그 주소로 이동한다"
)
def _swipe(world, ctx):
    assert re.search(r'<a class="back" href="[^"]+">', ctx.html)
    script = world.get("/static/app.js").text
    assert "touchstart" in script and "a.back" in script and "EDGE_SWIPE" in script


@then("특정 주제로 메뉴 버튼은 좁은 화면에서 점 세 개 아이콘만 보인다")
def _more_menu(world, ctx):
    summary = ctx.html.split('<summary class="menu-button')[1].split("</summary>")[0]
    assert 'aria-label="특정 주제로"' in summary and 'class="menu-label"' in summary
    assert "i-more" in summary
    assert ".menu-label { display: none" in narrow_css(world)


@given("전문을 가져온 글이 있다")
def _with_fulltext(world, ctx):
    ctx.article = world.article(title="전문 글")
    world.articles.save_full_text(ctx.article, "<p>전문 본문입니다.</p>")


@then("점 세 개 메뉴 안에 전문 다시 가져오기가 있고 따로 보이던 버튼은 좁은 화면에서 숨는다")
def _refetch_in_menu(world, ctx):
    menu = ctx.html.split('<details class="menu">')[1].split("</details>")[0]
    assert f'action="/a/{ctx.article}/fulltext" class="menu-mobile-only"' in menu
    assert "전문 다시 가져오기" in menu and "menu-desktop-only" in ctx.html
    css = world.client.get("/static/app.css").text
    assert ".menu-desktop-only { display: none; }" in css
    assert ".menu-mobile-only { display: none; }" in css


@then("메뉴 목록은 버튼의 오른쪽 끝에 맞춰 열려 화면 밖으로 잘리지 않는다")
def _menu_right_aligned(world):
    css = world.client.get("/static/app.css").text
    assert ".menu-list { left: auto; right: 0; max-width: calc(100vw - 32px); }" in css


@then("점 세 개 메뉴는 메타 줄의 오른쪽 끝을 기준으로 열린다")
def _menu_anchored_to_meta_row(world):
    narrow = narrow_css(world)
    assert ".doc-meta { position: relative; }" in narrow
    assert ".doc-meta .menu { position: static; margin-left: auto; }" in narrow


@then("메타 줄은 좁은 화면에서 사이트 이름 뒤에서 줄이 바뀌고 점 구분 글자는 숨는다")
def _meta_two_lines(world, ctx):
    meta = ctx.html.split('<div class="doc-meta">')[1]
    assert re.search(r'class="chip"[^>]*>[^<]*</a><span class="meta-break"></span>', meta)
    assert '<span class="meta-dot">·</span>' in meta
    narrow = narrow_css(world)
    assert (
        ".meta-break { display: block; flex-basis: 100%; height: 0; margin-top: -6px; }" in narrow
    )
    assert ".meta-dot { display: none; }" in narrow
    css = world.get("/static/app.css").text
    # 기본 숨김 규칙이 좁은 화면 규칙보다 뒤에 있으면 같은 우선순위에서 이겨서 줄바꿈이 사라진다
    assert css.index(".meta-break { display: none; }") < css.index(".meta-break { display: block;")


@given("사이트 목록에서 연 글이 있다")
def _from_feed_list(world, ctx):
    ctx.article = world.article(world.f_news, title="뉴스 글")


@then("스와이프로 돌아갈 곳은 전체 글 목록이고 스크립트가 그 주소로 이동한다")
def _swipe_to_all(world, ctx):
    response = world.get(f"/a/{ctx.article}?back=/reader/feed/{world.f_news}")
    assert 'class="doc" data-swipe-back="/reader"' in response.text
    script = world.get("/static/app.js").text
    assert 'swipeTarget.getAttribute("data-swipe-back")' in script
    assert "window.location.href = back;" in script
