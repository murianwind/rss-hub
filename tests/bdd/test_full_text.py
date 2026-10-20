"""18_full_text.feature: 원문 페이지의 전문 보기."""

from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, then, when

from tests.bdd.binding import bind
from tests.fakes.discovery_fetcher import FakeDiscoveryFetcher
from tests.fakes.viewer_world import World
from tests.fakes.web_parts import start_app

bind(globals(), "18_full_text.feature", [f"FTX-{n:02d}" for n in range(1, 7)])

BROWSER = {"origin": "null", "sec-fetch-site": "same-origin"}
LINK = "https://blog.example.com/post/1"
FULL = "원문 전체에만 있는 본문 문장입니다. " * 30
PAGE = (
    f"<html><body><nav>메뉴</nav><article><p>{FULL}</p></article>"
    "<footer>하단 안내</footer></body></html>"
)


@pytest.fixture
def world(tmp_path):
    fetcher = FakeDiscoveryFetcher()
    parts, client = start_app(tmp_path, feed_fetcher=fetcher)
    with client:
        w = World(parts)
        w.fetcher = fetcher
        yield w


@pytest.fixture
def ctx():
    return SimpleNamespace(article=None, response=None)


def body(html):
    return html.split('class="article-body"')[1].split('<div class="doc-foot">')[0]


@given('사이트 "자유 블로그"가 있다')
def _background(world):
    assert world.f_free


@given("원문 페이지에는 메뉴와 하단 안내와 긴 본문이 있고 RSS에는 요약만 있는 글이 있다")
def _normal_article(world, ctx):
    world.fetcher.page(LINK, PAGE)
    ctx.article = world.article(link=LINK, content="<p>RSS 요약뿐입니다</p>")


@when("그 글을 연다")
def _open(world, ctx):
    ctx.response = world.get(f"/a/{ctx.article}")


@when("그 글을 두 번 연다")
def _open_twice(world, ctx):
    world.get(f"/a/{ctx.article}")
    ctx.response = world.get(f"/a/{ctx.article}")


@given("그 글을 열었다")
def _opened(world, ctx):
    world.get(f"/a/{ctx.article}")


@then("본문에는 원문의 긴 본문이 보이고 메뉴와 하단 안내와 RSS 요약은 없다")
def _full_text(ctx):
    text = body(ctx.response.text)
    assert "원문 전체에만 있는 본문" in text
    assert "메뉴" not in text and "하단 안내" not in text and "RSS 요약뿐" not in text


@then("원문 페이지에서 가져온 전문이라는 안내와 다시 가져오기 버튼이 있다")
def _notice(ctx):
    assert "원문 페이지에서 가져온 전문입니다" in ctx.response.text
    assert "전문 다시 가져오기" in ctx.response.text


@then("원문 페이지는 한 번만 요청했다")
def _once(world):
    assert world.fetcher.page_calls == [LINK]


@given(parsers.re(r"원문 페이지가 (?P<case>시간 초과로 실패한다|본문이 없는 페이지다)인 글이 있다"))
def _bad_page_article(world, ctx, case):
    _set_bad_page(world, case)
    ctx.article = world.article(link=LINK, content="<p>RSS 본문입니다</p>")


@given("원문 페이지가 시간 초과로 실패한다")
def _timeout_page(world, ctx):
    _set_bad_page(world, "시간 초과로 실패한다")
    ctx.article = world.article(link=LINK, content="<p>RSS 본문입니다</p>")


def _set_bad_page(world, case):
    if case.startswith("시간 초과"):
        world.fetcher.page_errors[LINK] = "ReadTimeout"
    else:
        world.fetcher.page(LINK, "<html><body><nav>메뉴만</nav></body></html>")


@then(parsers.re(r'RSS 본문과 "(?P<reason>[^"]+)" 이유가 보이고 원문 페이지는 한 번만 요청했다'))
def _fallback(world, ctx, reason):
    assert "RSS 본문입니다" in body(ctx.response.text) and reason in ctx.response.text
    assert world.fetcher.page_calls == [LINK]


@when("원문 페이지가 복구된 뒤 다시 가져오기 버튼을 누른다")
def _recovered_refetch(world, ctx):
    world.fetcher.page_errors.pop(LINK, None)
    world.fetcher.page(LINK, PAGE)
    ctx.response = world.client.post(
        f"/a/{ctx.article}/fulltext", data={"next": f"/a/{ctx.article}"}, headers=BROWSER
    )


@then(parsers.re(r'글 페이지로 돌아와 "(?P<message>[^"]+)" 알림이 보이고 전문이 보인다'))
def _back_with_full_text(world, ctx, message):
    assert ctx.response.headers["location"] == f"/a/{ctx.article}?toast=fulltext"
    page = world.get(ctx.response.headers["location"]).text
    assert message in page and "원문 전체에만 있는 본문" in body(page)


@given(parsers.re(r'원문 주소가 "(?P<link>[^"]*)"인 글이 있다'))
def _link_article(world, ctx, link):
    ctx.article = world.article(link=link.strip(), content="<p>RSS 본문입니다</p>")


@then("원문 페이지는 한 번도 요청하지 않았고 RSS 본문이 보인다")
def _never_requested(world, ctx):
    assert world.fetcher.page_calls == [] and "RSS 본문입니다" in body(ctx.response.text)


@given("원문 페이지에 스크립트와 이벤트 속성과 위험한 링크와 iframe이 들어 있는 글이 있다")
def _hostile(world, ctx):
    evil = PAGE.replace(
        "<p>", "<p onclick='x()'><script>window.__pwned=1</script><img src=x onerror='alert(1)'>", 1
    )
    evil = evil.replace(
        "</article>",
        "<a href='javascript:alert(1)'>클릭</a><iframe src='https://evil.example.com'></iframe></article>",
    )
    world.fetcher.page(LINK, evil)
    ctx.article = world.article(link=LINK)


@then("본문에는 정상 문장만 남고 위험한 요소는 하나도 없다")
def _clean(ctx):
    text = body(ctx.response.text)
    assert "원문 전체에만 있는 본문" in text
    for danger in ("<script", "onclick", "onerror", "javascript:", "<iframe", "__pwned"):
        assert danger not in text
