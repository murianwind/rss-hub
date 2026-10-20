"""18_full_text.feature: 원문 페이지의 전문 보기."""

# ruff: noqa: E501  (HTML 견본은 한 줄로 두는 편이 읽기 쉽다)

import re
from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, then, when

from tests.bdd.binding import bind
from tests.fakes.discovery_fetcher import FakeDiscoveryFetcher
from tests.fakes.viewer_world import World
from tests.fakes.web_parts import start_app

bind(globals(), "18_full_text.feature", [f"FTX-{n:02d}" for n in range(1, 14)])

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


@then(
    '제목 아래 고정 영역에 전문 다시 가져오기 버튼이 있고 "원문 페이지에서 가져온 전문입니다" 안내는 없다'
)
def _notice(ctx):
    html = ctx.response.text
    assert "원문 페이지에서 가져온 전문입니다" not in html
    assert "전문 다시 가져오기" in html.split('<div class="doc-scroll">')[0]


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


# ---------- 영상 ----------


def _article_with_media(world, ctx, media):
    page = f"<html><body><article><p>{FULL}</p>{media}<p>영상 뒤 문단</p></article></body></html>"
    world.fetcher.page(LINK, page)
    ctx.article = world.article(link=LINK)


@given("원문 페이지의 본문 중간에 유튜브 영상이 들어 있는 글이 있다")
def _youtube_article(world, ctx):
    _article_with_media(
        world, ctx, "<iframe src='https://www.youtube.com/embed/dQw4w9WgXcQ' width='560'></iframe>"
    )


@then('영상이 있던 자리에 "영상 보기" 링크가 있고 화면 글자에는 영상 주소가 보이지 않는다')
def _link_in_place(ctx):
    import re

    text = body(ctx.response.text)
    assert text.index("원문 전체에만 있는") < text.index("영상 보기") < text.index("영상 뒤 문단")
    shown = re.sub(r"<[^>]*>", " ", text)
    assert "youtube" not in shown and "dQw4w9WgXcQ" not in shown and "http" not in shown


@then("그 링크는 새 창으로 열리고 영상 페이지 주소를 가리킨다")
def _opens_in_new_window(ctx):
    link = next(a for a in body(ctx.response.text).split("<a ") if "영상 보기" in a)
    assert 'target="_blank"' in link and "noopener" in link
    assert 'href="https://www.youtube.com/watch?v=dQw4w9WgXcQ"' in link


@given(parsers.re(r'원문 페이지에 "(?P<frame>[^"]+)" 주소의 프레임이 들어 있는 글이 있다'))
def _frame_article(world, ctx, frame):
    _article_with_media(world, ctx, f"<iframe src='{frame}'></iframe>")


@then('본문에는 "영상 보기" 링크도 프레임도 없다')
def _no_link_no_frame(ctx):
    text = body(ctx.response.text)
    assert "영상 보기" not in text and "<iframe" not in text and "영상 뒤 문단" in text


# ---------- 군더더기 정리 ----------


def _plain(html):
    return re.sub(r"<[^>]*>", " ", html)


@given(
    "원문 페이지에 본문 뒤로 가이드 링크 목록과 태그 줄과 팔로우와 뉴스레터와 관련 글이 붙어 있는 글이 있다"
)
def _noisy_tail(world, ctx):
    guides = "".join(
        f"<li><a href='/vpn/{n}'>Best VPNs for Place {n} in 2026</a></li>" for n in range(5)
    )
    tail = (
        f"<h4>Cybersecurity Guides</h4><ul>{guides}</ul>"
        "<p>Explore more on these topics</p><div><a href='/t/a'>Crypto</a><a href='/t/b'>Privacy</a></div>"
        "<p>Share this story</p><p><a href='/f'>Follow Us</a></p>"
        "<h3>Sign up for our newsletters</h3><h3>Related Articles</h3>"
    )
    page = (
        f"<html><body><article><p>{FULL}</p><p>마지막 본문 문단</p>{tail}</article></body></html>"
    )
    world.fetcher.page(LINK, page)
    ctx.article = world.article(link=LINK)


@then("본문의 글은 남고 링크 목록과 태그 줄과 하단 안내는 하나도 없다")
def _tail_gone(ctx):
    text = _plain(body(ctx.response.text))
    assert "마지막 본문 문단" in text
    for noise in (
        "Cybersecurity",
        "VPN",
        "Explore more",
        "Crypto",
        "Share this",
        "Follow Us",
        "newsletters",
        "Related",
    ):
        assert noise not in text, noise


@given(
    "원문 페이지가 로고와 같은 제목과 잘린 요약과 날짜와 공유 막대로 시작하고 출처 줄로 끝나는 글이 있다"
)
def _noisy_head(world, ctx):
    share = (
        "<ul><li><a href='http://twitter.com/x'>Post</a></li><li><a href='http://facebook.com/x'>Post</a></li>"
        "<li><a href='https://linkedin.com/x'>Share</a></li><li>Annotate</li><li><a href='#'>Save</a></li><li>Print</li></ul>"
    )
    title = "Build a Board That Challenges Your Thinking"
    page = (
        "<html><body><article><img src='https://hbr.org/logo.svg' alt='Harvard Business Review'>"
        f"<h1>{title}</h1><p>An effective board should challenge the forces shaping decision-making. Define what your […]</p>"
        f"<p>October 20, 2026</p>{share}<p>{FULL}</p>"
        "<p>Source: <a href='https://hbr.org/2026/11/building'>This tip is adapted from a book.</a></p>"
        f"{share}</article></body></html>"
    )
    world.fetcher.page(LINK, page)
    ctx.article = world.article(link=LINK, title=title)


@then("본문의 글과 출처 줄은 남고 로고와 제목과 요약과 날짜와 공유 막대는 없다")
def _head_gone(ctx):
    raw = body(ctx.response.text)
    text = _plain(raw)
    assert "원문 전체에만 있는 본문" in text and "Source:" in text
    assert "<img" not in raw
    for noise in ("Build a Board", "Define what your", "October 20", "Annotate", "Print", "Save"):
        assert noise not in text, noise


# ---------- 실제 페이지(Gizmodo, InfoQ, HBR) 검토에서 나온 시나리오 ----------


def visible_text(html):
    """본문 영역의 화면 글자(태그를 빼고 공백을 하나로)."""
    inner = body(html).split(">", 1)[1]  # 본문 요소의 여는 태그 뒤부터
    return re.sub(r"\s+", " ", _plain(inner)).strip()


@given(
    "원문 페이지에 본문 영역 바깥의 머리 영역과 본문 속 기울임 글자와 글 끝의 홍보 문단이 있는 글이 있다"
)
def _gizmodo_like(world, ctx):
    hero = (
        "<div class='hero'><span class='cat'><a href='/c/tv'>Television</a></span>"
        "<h1>Star Felt Like Season 3 Might Be the End</h1><div class='post-excerpt'>According to Woll, the ending felt different.</div>"
        "<div class='meta'><span>By</span><a href='/a/jen'>Jen Lennon</a><time>Published October 20, 2026, 8:00 am ET</time></div>"
        "<p>Reading time 2 minutes</p></div>"
    )
    paragraphs = "".join(f"<p>{FULL}{n}</p>" for n in range(6))
    promo = "<blockquote><p>Want more io9 news? Check out <a href='/best'>the best movies</a> and <a href='/b'>books</a> on your radar.</p></blockquote>"
    inline = "<p>The news that <i>Daredevil: Born Again</i> would end came as a shock to fans of the show.</p>"
    page = f"<html><body><main>{hero}<div class='wrap'><article class='post'><div class='entry-content'>{inline}{paragraphs}{promo}</div></article></div></main></body></html>"
    world.fetcher.page(LINK, page)
    ctx.article = world.article(link=LINK, title="Star Felt Like Season 3 Might Be the End")


@then("본문은 문단 속 기울임 글자까지 온전하고 머리 영역과 홍보 문단은 없다")
def _giz_result(ctx):
    text = visible_text(ctx.response.text)
    assert (
        "The news that Daredevil: Born Again would end" in text
        and "원문 전체에만 있는 본문" in text
    )
    for noise in (
        "Television",
        "According to Woll",
        "Jen Lennon",
        "Published October",
        "Reading time",
        "Want more",
        "radar",
    ):
        assert noise not in text, noise


@given(
    "원문 페이지에 본문 앞에 이동 경로와 분류와 제목과 날짜와 재생기 문구와 읽기 목록이 붙은 글이 있다"
)
def _infoq_like(world, ctx):
    title = "GitHub Actions Runner Controller 0.15.0 Targets Reliability at Scale"
    lead = (
        f"<p>InfoQ HomepageNews{title}</p><div>DevOps</div><h1>{title}</h1>"
        "<div>Oct 20, 2026 3 min read</div><div>Listen to this article - 0:00</div><div>Audio ready to play</div>"
        "<div>0:00</div><div>Reading list</div>"
    )
    page = (
        f"<html><body><article>{lead}<p>{FULL}</p><p>둘째 문단입니다.</p></article></body></html>"
    )
    world.fetcher.page(LINK, page)
    ctx.article = world.article(link=LINK, title=title)


@then("본문의 첫 문단부터 시작하고 앞머리 군더더기는 하나도 없다")
def _infoq_result(ctx):
    text = visible_text(ctx.response.text)
    assert text.startswith("원문 전체에만 있는 본문")
    for noise in (
        "InfoQ",
        "DevOps",
        "min read",
        "Listen to this",
        "Audio ready",
        "0:00",
        "Reading list",
        "Runner Controller",
    ):
        assert noise not in text, noise


@given("RSS 본문이 전문이고 원문 페이지는 유료 벽으로 앞부분만 있는 글이 있다")
def _hbr_like(world, ctx):
    full = "".join(
        f"<p>RSS가 이미 전문을 담고 있는 {n}번째 문단입니다. "
        + "긴 문장이 이어집니다. " * 8
        + "</p>"
        for n in range(6)
    )
    ctx.rss_first = "RSS가 이미 전문을 담고 있는 0번째 문단입니다."
    ctx.rss_last = "RSS가 이미 전문을 담고 있는 5번째 문단입니다."
    world.fetcher.page(
        LINK,
        f"<html><body><article>{ctx.rss_first} {'긴 문장이 이어집니다. ' * 26}</article></body></html>",
    )
    ctx.article = world.article(link=LINK, content=full)


@then(
    parsers.re(
        r'RSS 본문 전체가 보이고 "(?P<reason>[^"]+)" 이유가 보이며 원문 페이지는 한 번만 요청했다'
    )
)
def _hbr_result(world, ctx, reason):
    text = visible_text(ctx.response.text)
    assert ctx.rss_first in text and ctx.rss_last in text and reason in ctx.response.text
    assert world.fetcher.page_calls == [LINK]
