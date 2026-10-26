"""38_retranslate.feature: 제목 번역과 요약을 모델에 다시 요청한다."""

from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from pytest_bdd import given, parsers, then, when

from rss_hub.services.ports import LlmErrorKind
from tests.bdd.binding import bind
from tests.fakes.llm_client import failure, good, reply
from tests.fakes.viewer_world import open_world
from tests.keywords.browser import post

bind(globals(), "38_retranslate.feature", [f"RTR-{n:02d}" for n in range(1, 7)])

KEY = "sk-or-v1-" + "a" * 32
BUTTON = "제목 번역·요약 다시 요청"
ENGLISH = "<p>Being authentic as a leader often means showing vulnerability. " * 3 + "</p>"
OLD_TITLE, OLD_SUMMARY = "이전 제목", "이전 요약"


@pytest.fixture
def world(tmp_path):
    with open_world(tmp_path) as opened:
        opened.parts.settings.set_openrouter_key(KEY)
        yield opened


@pytest.fixture
def ctx():
    return SimpleNamespace(article=None, html="", response=None, before=None)


def _english(world, ctx):
    ctx.article = world.article(
        title="Share More Authentically as a Leader",
        content=ENGLISH,
        ko=OLD_TITLE,
        summary=OLD_SUMMARY,
    )


@given("번역되지 않은 영어 글이 있다")
def _english_article(world, ctx):
    _english(world, ctx)


@given("번역되지 않은 영어 글이 있고 그 글은 북마크되어 있다")
def _bookmarked(world, ctx):
    _english(world, ctx)
    world.articles.set_bookmark(ctx.article, True)
    ctx.before = world.articles.get(ctx.article)


@given("번역되지 않은 영어 글이 있고 원문 전문이 저장되어 있다")
def _with_fulltext(world, ctx):
    _english(world, ctx)
    world.articles.save_full_text(ctx.article, "<p>FULLTEXT-MARKER 전문에만 있는 문장입니다.</p>")


@given("한국어 글이 있다")
def _korean(world, ctx):
    ctx.article = world.article(title="한국어 제목입니다", content="<p>한국어로 쓴 본문입니다.</p>")


@given(parsers.parse('모델이 제목 "{title}"와 요약 "{summary}"을 돌려준다'))
@given(parsers.parse('모델이 제목 "{title}"와 요약 "{summary}"를 돌려준다'))
def _model_answers(world, title, summary):
    world.parts.llm.default = reply(title, summary, topics=[])


@given(parsers.parse('상황은 "{situation}"이다'))
def _situation(world, situation):
    llm = world.parts.llm
    if situation == "키가 없다":
        world.parts.settings.delete_openrouter_key()
    elif situation == "모델이 응답하지 않는다":
        llm.default = failure(LlmErrorKind.UNAUTHORIZED, status=401)
    else:
        llm.default = good("JSON이 아닌 응답")


@when("글 화면을 연다")
def _open(world, ctx):
    ctx.html = world.get(f"/a/{ctx.article}?back=/reader").text


@when("다시 요청을 보낸다")
def _request(world, ctx):
    ctx.response = post(world, f"/a/{ctx.article}/retranslate", next=f"/a/{ctx.article}")
    assert ctx.response.status_code == 303


@when("다른 사이트에서 다시 요청을 보낸다")
def _cross_site(world, ctx):
    cross = {"origin": "https://evil.example.com", "sec-fetch-site": "cross-site"}
    ctx.response = world.client.post(f"/a/{ctx.article}/retranslate", headers=cross)


def _toast_text(world, ctx):
    location = ctx.response.headers["location"]
    assert "toast=" in location and parse_qs(urlsplit(location).query)["toast"]
    return world.get(location).text


@then(parsers.parse('글 화면의 PC 도구줄과 점 세 개 메뉴에 "{label}" 버튼이 있다'))
def _buttons(ctx, label):
    action = f'action="/a/{ctx.article}/retranslate"'
    tools = ctx.html.split('<div class="doc-tools menu-desktop-only">')[1].split("</div>")[0]
    menu = ctx.html.split('<details class="menu">')[1].split("</details>")[0]
    assert action in tools and label in tools
    assert tools.index("/fulltext") < tools.index("/retranslate")  # 전문 다시 가져오기 옆
    assert f'{action} class="menu-mobile-only"' in menu and label in menu


@then(parsers.parse('"{label}" 버튼이 없다'))
def _no_button(ctx, label):
    assert label not in ctx.html and "/retranslate" not in ctx.html


@then(parsers.re(r'모델은 부르지 않았고 "(?P<text>[^"]+)"가 알려진다'))
def _korean_refused(world, ctx, text):
    assert world.parts.llm.calls == []
    assert text in _toast_text(world, ctx)


@then(parsers.parse('글 제목은 "{title}"이고 요약은 "{summary}"이다'))
def _translated(world, ctx, title, summary):
    article = world.articles.get(ctx.article)
    assert (article.title_ko, article.summary_ko) == (title, summary)


@then("글은 여전히 북마크되어 있고 상태는 그대로다")
def _unchanged(world, ctx):
    now = world.articles.get(ctx.article)
    assert now.bookmarked_at == ctx.before.bookmarked_at and now.status == ctx.before.status
    assert now.read_at == ctx.before.read_at


@then(parsers.parse('"{text}"가 알려진다'))
@then(parsers.parse('"{text}"이 알려진다'))
def _toast(world, ctx, text):
    assert text in _toast_text(world, ctx)


@then("글 제목과 요약은 바뀌지 않았다")
def _not_changed(world, ctx):
    article = world.articles.get(ctx.article)
    assert (article.title_ko, article.summary_ko) == (OLD_TITLE, OLD_SUMMARY)


@then("모델에 보낸 내용에는 원문 전문이 들어 있다")
def _prompt_has_fulltext(world):
    assert "FULLTEXT-MARKER" in world.parts.llm.calls[-1].prompt


@then("요청은 거부되고 모델은 부르지 않았다")
def _refused(world, ctx):
    assert ctx.response.status_code == 403 and world.parts.llm.calls == []


@then("없는 글에 보낸 요청은 404이다")
def _missing(world):
    assert post(world, "/a/999/retranslate").status_code == 404
