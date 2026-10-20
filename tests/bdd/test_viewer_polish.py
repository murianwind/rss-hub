"""19_viewer_polish.feature: 첫 화면, 글 화면, 사이드바, 모델 사용량, 피드 검색."""

import html as html_module
import re
from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, then, when

from rss_hub.storage.llm_usage import LlmUsageRepository
from tests.bdd.binding import bind
from tests.fakes.viewer_world import World
from tests.fakes.web_parts import start_app

bind(globals(), "19_viewer_polish.feature", [f"VPL-{n:02d}" for n in range(1, 8)])

BROWSER = {"origin": "null", "sec-fetch-site": "same-origin"}
KEY = "sk-or-v1-abcdefghijklmnop"
ENGLISH = "This is a long English article body about software design and testing. " * 12
KOREAN = "이것은 한국어로 쓴 충분히 긴 본문입니다. " * 20
WAF_SHAPE = re.compile(r"[?&;][A-Za-z0-9_]+=/")


@pytest.fixture
def world(tmp_path):
    parts, client = start_app(tmp_path)
    with client:
        yield World(parts)


@pytest.fixture
def ctx():
    return SimpleNamespace(response=None, article=None, articles=[])


def post(world, path, **data):
    return world.client.post(path, data=data, headers=BROWSER)


@given('사이트 "뉴스 블로그"(카테고리 "뉴스")와 사이트 "자유 블로그"가 있다')
def _background(world):
    assert world.feeds.get(world.f_news).category_id == world.news and world.f_free


# ---------- 첫 화면과 사이드바 ----------


@when("사이트 주소의 맨 앞으로 접속한다")
def _root(world, ctx):
    ctx.root = world.client.get("/", follow_redirects=False)
    ctx.response = world.client.get("/", follow_redirects=True)


@then("글 목록 화면으로 이동하고 사이드바의 구역은 모두 접혀 있다")
def _landing(ctx):
    assert ctx.root.status_code == 307 and ctx.root.headers["location"] == "/reader"
    assert not re.findall(r'<details class="sec" id="sec-\w+" open>', ctx.response.text)


@then("북마크 항목은 RSS 피드 구역과 카테고리 구역 사이에 있다")
def _bookmark_between(ctx):
    html = ctx.response.text
    assert (
        html.index('id="sec-rss"')
        < html.index('href="/reader/bookmarks"')
        < html.index('id="sec-categories"')
    )


@given(parsers.re(r'사이트 "뉴스 블로그"에 새 글 (?P<n>\d+)개가 있다'))
def _news_articles(world, ctx, n):
    ctx.articles = [world.article(world.f_news, minutes=i) for i in range(int(n))]


def bubble(html, feed_id):
    found = re.search(
        rf'<span class="count[^"]*" data-count="feed:{feed_id}"[^>]*>([^<]*)</span>', html
    )
    return None if found is None or "hidden" in found.group(0) else found.group(1).strip()


@then(parsers.re(r'사이드바의 "뉴스 블로그" 옆에는 숫자 (?P<n>\d+)가 보인다'))
def _bubble_shows(world, n):
    assert bubble(world.get("/reader").text, world.f_news) == n


@when("그 글을 모두 읽는다")
def _read_all(world, ctx):
    for article in ctx.articles:
        world.get(f"/a/{article}")


@then('사이드바의 "뉴스 블로그" 옆에는 숫자가 보이지 않는다')
def _bubble_hidden(world):
    assert bubble(world.get("/reader").text, world.f_news) is None


# ---------- 프록시 차단 규칙 ----------


@given('사이트 "뉴스 블로그"에 새 글이 있다')
def _one_article(world, ctx):
    ctx.article = world.article(world.f_news)


@when(parsers.re(r'"(?P<page>[^"]+)" 화면을 연다'))
def _open_page(world, ctx, page):
    paths = {
        "글 목록": "/reader",
        "글 화면": f"/a/{ctx.article}?back=%2Freader",
        "피드 관리": "/feeds",
        "설정": "/settings",
        "설정 패널": f"/panel/settings/feed/{world.f_news}?next=%2Fa%2F{ctx.article}",
    }
    ctx.response = world.get(paths[page])


@then("모든 링크의 쿼리 값에서 슬래시가 인코딩되어 있다")
def _encoded(ctx):
    links = re.findall(r'(?:href|action)="([^"]*\?[^"]*)"', ctx.response.text)
    assert links and not [link for link in links if WAF_SHAPE.search(link.replace("&amp;", "&"))]


# ---------- 글 화면 ----------


@given('사이트 "뉴스 블로그"에 원문 주소가 있는 새 글이 있다')
def _article_with_link(world, ctx):
    ctx.article = world.article(world.f_news, link="https://blog.example.com/p/1")


@when("그 글을 연다")
def _open(world, ctx):
    ctx.response = world.get(f"/a/{ctx.article}")


@then('출처 표시가 없고 "목록으로 돌아가기"는 한 개이며 "읽지 않음으로" 버튼이 있다')
def _top_bar(ctx):
    html = ctx.response.text
    assert "출처" not in html and html.count("목록으로 돌아가기") == 1
    assert ">읽지 않음으로</button>" in html


@then('글 아래에는 "전문 다시 가져오기"와 "원문 보기" 버튼만 같은 모양으로 있다')
def _bottom_buttons(ctx):
    foot = ctx.response.text.split('<div class="doc-foot">')[1].split("</article>")[0]
    labels = re.findall(r'<(?:button|a) [^>]*class="button"[^>]*>\s*([^<]+)', foot)
    assert [label.strip() for label in labels] == ["전문 다시 가져오기", "원문 보기"]
    assert "목록으로 돌아가기" not in foot and "link-btn" not in foot


@then("글 카드는 격자 배경 없이 위아래 여백이 같은 영역을 채운다")
def _layout(world):
    css = world.client.get("/static/app.css").text
    assert "linear-gradient" not in css
    assert (
        ".detail-scroll { display: flex; flex-direction: column; overflow: hidden; padding: 24px; }"
        in css
    )
    assert ".detail-scroll .doc { flex: 1; min-height: 0;" in css


@given(parsers.re(r'사이트 "뉴스 블로그"에 (?P<language>영어|한국어) 본문의 글이 있다'))
def _language_article(world, ctx, language):
    body = ENGLISH if language == "영어" else KOREAN
    ctx.article = world.article(world.f_news, title="Post", content=f"<p>{body}</p>")


@then(parsers.re(r'페이지 언어는 "(?P<lang>[a-z]+)"이다'))
def _page_language(ctx, lang):
    assert f'<html lang="{lang}"' in ctx.response.text


# ---------- 모델 사용량 ----------


def model_text(html):
    found = re.search(r"모델 잔여 사용량 <b data-model-usage>([^<]+)</b>", html)
    return found.group(1) if found else None


@given("모델이 설정되어 있지 않다")
def _no_model(world):
    assert not world.parts.settings.has_openrouter_key()


@then("사이드바에는 모델 잔여 사용량이 없다")
def _no_usage(world):
    assert model_text(world.get("/reader").text) is None


@when("모델 키를 설정한다")
def _set_key(world):
    post(world, "/settings/openrouter-key", openrouter_key=KEY, next="/settings")


@then(parsers.re(r'사이드바에는 "모델 잔여 사용량 (?P<shown>\d+/\d+)"이 보인다'))
def _usage_shown(world, shown):
    assert model_text(world.get("/reader").text) == shown


@when(parsers.re(r"모델이 (?P<calls>\d+)번 호출되었다"))
def _model_calls(world, calls):
    usage = LlmUsageRepository(world.parts.db, world.parts.clock)
    for _ in range(int(calls)):
        usage.record(model="m/free", outcome="success", status=200)


# ---------- 피드 관리 검색 ----------


@when(parsers.re(r'피드 관리에서 "(?P<query>[^"]+)"를 검색한다'))
def _search_feeds(world, ctx, query):
    ctx.response = world.client.get("/feeds", params={"q": query})


def feed_list(html):
    return html_module.unescape(html.split('<ul class="feed-list">')[1].split("</ul>")[0])


@then(parsers.re(r'"(?P<name>[^"]+)"만 보인다'))
def _only_one(ctx, name):
    shown = feed_list(ctx.response.text)
    others = {"뉴스 블로그", "자유 블로그"} - {name}
    assert name in shown and not any(other in shown for other in others)


@then("맞는 피드가 없다는 안내가 보인다")
def _none_found(ctx):
    assert "맞는 피드가 없습니다" in ctx.response.text
