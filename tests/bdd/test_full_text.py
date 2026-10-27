"""18_full_text.feature: 원문 페이지의 전문 보기."""

# ruff: noqa: E501  (HTML 견본은 한 줄로 두는 편이 읽기 쉽다)

import re
from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, then, when

from tests.bdd.binding import bind
from tests.fakes.discovery_fetcher import FakeDiscoveryFetcher
from tests.fakes.viewer_world import open_world
from tests.keywords.browser import BROWSER
from tests.keywords.page import body

bind(globals(), "18_full_text.feature", [f"FTX-{n:02d}" for n in range(1, 29)])

LINK = "https://blog.example.com/post/1"
FULL = "원문 전체에만 있는 본문 문장입니다. " * 30
PAGE = (
    f"<html><body><nav>메뉴</nav><article><p>{FULL}</p></article>"
    "<footer>하단 안내</footer></body></html>"
)


@pytest.fixture
def world(tmp_path):
    with open_world(tmp_path, fetcher=FakeDiscoveryFetcher()) as opened:
        yield opened


@pytest.fixture
def ctx():
    return SimpleNamespace(article=None, response=None)


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


YES24 = "https://www.yes24.com/Product/Goods/197780287"
KYOBO = "https://product.kyobobook.co.kr/detail/S000221581752"


def _og_card(title, desc, url):
    return (
        f'<div class="wrap_item item_type_opengraph" data-app="{{}}"><a class="inner_wrap #opengraph" '
        f'href="{url}" target="_blank" rel="noreferrer"><div class="inner_wrap_text">'
        f'<strong class="title">{title}</strong><p class="desc">{desc}</p><p class="url">{url}</p>'
        "</div></a></div>"
    )


@given(
    "원문 페이지에 본문 뒤로 책 소개 줄과 상품 주소 줄과 링크 미리보기 카드가 붙어 있는 글이 있다"
)
def _brunch_like(world, ctx):
    promo = (
        '<p class="wrap_item"><span><b><u><span>[2027년 사업전략을 위한 책]</span></u></b></span></p>'
        f'<p class="wrap_item"><span><a class="link" href="{YES24}"><u><span>{YES24}</span></u></a></span></p>'
        + _og_card("IT 트렌드 2027 - 예스24", "AI를 쓰는 것만으로는 부족하다", YES24)
        + '<p class="wrap_item"><span><br/></span></p>'
        f'<p class="wrap_item"><span><a class="link" href="{KYOBO}"><span>{KYOBO}</span></a></span></p>'
        + _og_card("IT 트렌드 2027 - 교보문고", "일하는 방식을 바꿔야 돈의 흐름이 보인다", KYOBO)
        + '<p class="wrap_item"><span><b>➯ 저자의 다른 책 소개</b></span></p>'
    )
    page = (
        f'<html><body><div class="wrap_body"><p class="wrap_item">{FULL}</p>'
        f'<p class="wrap_item">마지막 본문 문단입니다. {FULL}</p>{promo}</div></body></html>'
    )
    world.fetcher.page(LINK, page)
    ctx.article = world.article(link=LINK)


@then("본문의 글은 남고 책 소개 줄과 상품 주소와 미리보기 카드는 하나도 없다")
def _promo_gone(ctx):
    html = body(ctx.response.text)
    assert "마지막 본문 문단입니다" in _plain(html)
    for noise in (
        "2027년 사업전략",
        "yes24",
        "kyobobook",
        "예스24",
        "교보문고",
        "AI를 쓰는 것만으로는",
        "저자의 다른 책",
    ):
        assert noise not in html, noise


@given('원문 페이지에 문장 속 링크와 "출처: 주소" 줄이 들어 있는 글이 있다')
def _inline_links(world, ctx):
    page = (
        f"<html><body><article><p>{FULL}</p>"
        "<p>자세한 내용은 <a href='https://a.example.com/x'>공식 문서</a>를 보면 된다.</p>"
        "<p>출처: <a href='https://b.example.com/y'>https://b.example.com/y</a></p>"
        "</article></body></html>"
    )
    world.fetcher.page(LINK, page)
    ctx.article = world.article(link=LINK)


@then("문장 속 링크와 출처 줄이 그대로 남는다")
def _inline_links_kept(ctx):
    html = body(ctx.response.text)
    assert "공식 문서" in html and "출처:" in html and "https://b.example.com/y" in html


@given(
    "원문 페이지에 본문 문단 뒤로 이미지와 책 소개 줄과 인용 줄과 상품 주소 줄과 미리보기 카드가 이어지는 글이 있다"
)
def _brunch_lead_before_url(world, ctx):
    promo = (
        '<div class="wrap_item item_type_img"><img alt="book.png" src="https://img.example.com/b.png"/></div>'
        '<p class="wrap_item"><span><br/></span></p>'
        '<p class="wrap_item"><b>➯ 저자의 책 소개 줄입니다</b></p>'
        '<p class="wrap_item">AI 관련 기업 29곳 상세 분석!</p>'
        '<p class="wrap_item">“64개 기업 사례를 통해 돈의 흐름을 읽는다.”</p>'
        f'<p class="wrap_item"><a class="link" href="{YES24}">{YES24}</a></p>'
        + _og_card("빅테크로 살아남기 - 예스24", "신간 소개", YES24)
    )
    page = (
        f'<html><body><div class="wrap_body"><p class="wrap_item">{FULL}</p>'
        f'<p class="wrap_item">마지막 본문 문단입니다. {FULL}</p>{promo}</div></body></html>'
    )
    world.fetcher.page(LINK, page)
    ctx.article = world.article(link=LINK)


@then("마지막 본문 문단은 남고 이미지와 책 소개와 인용과 상품 주소와 카드는 하나도 없다")
def _lead_gone(ctx):
    html = body(ctx.response.text)
    assert "마지막 본문 문단입니다" in _plain(html)
    for noise in ("book.png", "➯", "책 소개", "29곳", "64개", "yes24", "빅테크로"):
        assert noise not in html, noise


MOBILE = "https://m.blog.example.com/PostView?no=1"


def _shell(target):
    return f"<script>\n\ttop.location.replace('{target.replace('/', chr(92) + '/')}');\n</script>"


@given(
    "글 주소가 스크립트로 모바일 글 주소로 보내는 짧은 페이지이고 모바일 주소에 본문이 있는 글이 있다"
)
def _naver_like(world, ctx):
    world.fetcher.page(LINK, _shell(MOBILE))
    world.fetcher.page(MOBILE, PAGE)
    ctx.article = world.article(link=LINK)


@then("모바일 주소의 본문이 전문으로 보이고 두 주소를 한 번씩 요청했다")
def _followed(world, ctx):
    assert "원문 전체에만 있는 본문 문장입니다" in body(ctx.response.text)
    assert world.fetcher.page_calls == [LINK, MOBILE]


@given(parsers.parse('글 주소가 "{target}"으로 보내는 짧은 페이지인 글이 있다'))
def _bad_shell(world, ctx, target):
    world.fetcher.page(LINK, _shell(LINK if target == "자기 자신" else target))
    ctx.article = world.article(link=LINK)


@then("전문을 가져오지 못했다고 알리고 요청은 세 번을 넘지 않았다")
def _not_followed(world, ctx):
    assert "원문 페이지에서 본문을 찾지 못했습니다" in ctx.response.text
    assert len(world.fetcher.page_calls) <= 3


@given(
    "원문 페이지에 AI 요약 상자와 오디오 재생기와 저절로 반복되는 영상과 글 중간의 관련 글 상자와 글 끝의 분류 줄이 있는 글이 있다"
)
def _blog_google_like(world, ctx):
    ai_box = (
        '<div class="article-container__ai-box"><div class="uni-ai-summary">'
        "<small>Summaries were generated by Google AI.</small><p>AI가 만든 요약 문장입니다.</p>"
        '<h4>Explore other styles:</h4></div><div class="audio-player-tts">'
        '<audio class="player" src="https://cdn.example.com/tts.mp3"></audio></div></div>'
    )
    loop_video = (
        '<video class="clip" autoplay loop muted src="https://cdn.example.com/a.mp4"></video>'
    )
    related = (
        '<section class="uni-related-content-tout"><h2>5 amazing visuals of the fruit fly brain</h2>'
        '<div class="cta">See more</div></section>'
    )
    page = (
        '<html><body><article class="uni-article-wrapper">'
        f"<p>첫 문단: {FULL}</p>{ai_box}{loop_video}<p>둘째 문단: {FULL}</p>{related}"
        f"<h2>이어지는 소제목</h2><p>관련 글 상자 뒤의 문단: {FULL}</p>"
        "<p>Posted in:</p></article></body></html>"
    )
    world.fetcher.page(LINK, page)
    ctx.article = world.article(link=LINK)


@then(
    "본문은 관련 글 상자 뒤의 문단까지 끝까지 보이고 AI 요약과 오디오와 장식 영상과 관련 글 상자와 분류 줄은 없다"
)
def _blog_google_result(ctx):
    html = body(ctx.response.text)
    assert "관련 글 상자 뒤의 문단" in _plain(html) and "이어지는 소제목" in html
    for noise in (
        "Summaries were generated",
        "AI가 만든 요약",
        "Explore other styles",
        "오디오 듣기",
        "영상 보기",
        "5 amazing visuals",
        "See more",
        "Posted in",
    ):
        assert noise not in html, noise


@given("글 페이지의 용량 한도가 피드와 같은 5MB다")
def _limit_given():
    pass


@then("페이지 가져오기의 용량 한도는 1MB보다 크다")
def _limit_value():
    from rss_hub.adapters.http_feed_fetcher import DEFAULT_MAX_BYTES, MAX_PAGE_BYTES

    assert MAX_PAGE_BYTES > 1_000_000 and MAX_PAGE_BYTES <= DEFAULT_MAX_BYTES


def _sentences(tag, count):
    return " ".join(
        f"{tag} {n}번째로 나오는 문장이고 다른 문장과 겹치지 않도록 충분히 길게 씁니다."
        for n in range(count)
    )


@given(
    "본문 중간에 관련 글 제목 줄이 있고 그 뒤의 짧은 본문이 끝 안내 규칙에 잘리는 글이 있고 RSS가 그 글 전체를 담고 있다"
)
def _cut_by_marker(world, ctx):
    before, after = _sentences("앞쪽", 5), _sentences("뒤쪽", 6)
    page = (
        "<html><body><article>"
        f"<p>{before}</p><h3>Related Articles</h3><p>{after}</p></article></body></html>"
    )
    world.fetcher.page(LINK, page)
    ctx.article = world.article(link=LINK, content=f"<p>{before}</p><p>{after}</p>")
    ctx.last = "뒤쪽 5번째로 나오는 문장"


@then("관련 글 제목 줄 뒤의 본문까지 모두 보인다")
def _all_text(ctx):
    assert ctx.last in body(ctx.response.text) and "Related Articles" in body(ctx.response.text)


@given("RSS 본문이 전문이고 원문 페이지는 전혀 다른 내용의 글이 있다")
def _different_page(world, ctx):
    rss = _sentences("RSS에만 있는", 12)
    world.fetcher.page(
        LINK,
        f"<html><body><article><p>{_sentences('전혀 다른 글의', 8)}</p></article></body></html>",
    )
    ctx.article = world.article(link=LINK, content=f"<p>{rss}</p>")
    ctx.rss_marker = "RSS에만 있는 11번째로 나오는 문장"


@then(parsers.re(r'RSS 본문이 보이고 "(?P<reason>[^"]+)" 이유가 보인다'))
def _rss_shown_with_reason(ctx, reason):
    assert ctx.rss_marker in ctx.response.text and reason in ctx.response.text
    assert "전혀 다른 글의" not in body(ctx.response.text)


@given('RSS 본문이 "[…]"로 끝나는 짧은 요약이고 원문 페이지는 다른 표현의 글이 있다')
def _teaser_rss(world, ctx):
    teaser = _sentences("요약에만 있는", 3) + " […]"
    world.fetcher.page(
        LINK,
        f"<html><body><article><p>{_sentences('원문에만 있는', 8)}</p></article></body></html>",
    )
    ctx.article = world.article(link=LINK, content=f"<p>{teaser}</p>")


@then("원문 페이지에서 뽑은 글이 보이고 실패 안내는 없다")
def _page_text_shown(ctx):
    assert "원문에만 있는 7번째로 나오는 문장" in body(ctx.response.text)
    assert "맞지 않습니다" not in ctx.response.text


@given("글 주소가 본문 없는 짧은 페이지를 돌려주는 글이 있다")
def _empty_page(world, ctx):
    world.fetcher.page(LINK, "<html><body><p>로그인이 필요합니다.</p></body></html>")
    ctx.article = world.article(link=LINK)


@then("실패 안내에 받은 글자 수와 주소와 이동 횟수가 들어 있다")
def _failure_detail(ctx):
    page = "<html><body><p>로그인이 필요합니다.</p></body></html>"
    assert (
        f"(받은 페이지 {len(page)}자, blog.example.com, 다른 주소로 0번 이동)" in ctx.response.text
    )


FRAME_TARGET = "https://blog.example.com/PostView?no=1&frame=1"


@given(
    "글 주소가 mainFrame 프레임으로 본문 주소를 가리키는 짧은 페이지이고 그 주소에 본문이 있는 글이 있다"
)
def _frame_shell(world, ctx):
    shell = (
        "<html><head><title>블로그</title></head><body>"
        '<iframe id="ad" src="https://ads.example.com/x"></iframe>'
        '<iframe id="mainFrame" name="mainFrame" src="/PostView?no=1&amp;frame=1"></iframe>'
        "</body></html>"
    )
    world.fetcher.page(LINK, shell)
    world.fetcher.page(FRAME_TARGET.replace("&frame", "&amp;frame"), PAGE)
    ctx.article = world.article(link=LINK)


@then("본문 프레임 주소의 본문이 전문으로 보이고 두 주소를 한 번씩 요청했다")
def _frame_followed(world, ctx):
    assert "원문 전체에만 있는 본문 문장입니다" in body(ctx.response.text)
    assert len(world.fetcher.page_calls) == 2 and world.fetcher.page_calls[0] == LINK


@given("글 주소가 제목이 있고 본문은 없는 짧은 페이지를 돌려주는 글이 있다")
def _titled_empty(world, ctx):
    world.fetcher.page(
        LINK,
        "<html><head><title>접근 제한 | 블로그</title></head><body><p>로그인이 필요합니다.</p></body></html>",
    )
    ctx.article = world.article(link=LINK)


@then("실패 안내에 받은 페이지의 제목이 들어 있다")
def _title_in_failure(ctx):
    assert ', 제목 "접근 제한 / 블로그")' in ctx.response.text.replace("&#34;", '"')


NAVER_MOBILE = "https://m.blog.naver.com/PostView.naver?blogId=skim209&logNo=224358894904"


@given(parsers.parse('글 주소가 "{link}"이고 모바일 글 주소에만 본문이 있는 글이 있다'))
def _naver_link(world, ctx, link):
    world.fetcher.page(NAVER_MOBILE, PAGE)  # 다른 주소는 가져오지 않는다(없으면 404 오류)
    ctx.article = world.article(link=link)


@then("모바일 글 주소를 한 번만 요청했고 본문이 전문으로 보인다")
def _naver_direct(world, ctx):
    assert world.fetcher.page_calls == [NAVER_MOBILE]
    assert "원문 전체에만 있는 본문 문장입니다" in body(ctx.response.text)


WP_BODY = (
    '<div class="wp-block-group"><div class="wp-block-group__inner-container">'
    '<figure class="wp-block-image"><img src="https://jv.example.com/a.webp" alt="로봇"/></figure>'
    '<p class="wp-block-paragraph">최근 1년간 다양한 생성형 AI를 이용하면서 느낀 점은<br>'
    "AI의 진정한 가치는 단순한 생성이 아닌<br><strong>생성+편집+제어</strong>에서 만들어진다는 것입니다.</p>"
    '<p class="wp-block-paragraph">즉, AI가 만들어낸 1차적 생성물을<br>사용자가 수정하고 편집해서<br>'
    "원하는 방향으로 조정할 수 있을 때<br>더 큰 가치가 만들어지게 됩니다.</p>"
    "<h2>[프롬프트]</h2><ul>"
    "<li>로봇 SVG 파일을 받았다. 보이냐?</li>"
    "<li>파일을 열어서 로봇이 어떤 구조로 되어 있는지 분석해 줘</li>"
    "<li>로봇을 분리해서 부품별 이름과 관절 회전 중심을 설정한 애니메이션용 SVG 파일을 만들어 줘.</li>"
    "<li>이 로봇이 다양한 행동을 하는 애니메이션을 만들어줘.</li>"
    "<li>AWS에 배포하고 URL 알려줘</li></ul>"
    '<h2>[웹에서 보기]</h2><p><a href="https://jv.example.org/2D/Robot/">https://jv.example.org/2D/Robot/</a></p>'
    '<p class="wp-block-paragraph">비전공자도 생성은 할 수 있지만<br>전공자는 편집+제어를 할 수 있기 때문에<br>'
    "전공자의 생성형 AI 활용이 더 큰 가치를 만들어 낼 수 있습니다.</p>"
    "<h2>[1줄 요약]</h2><p><strong>생성형 AI의 진정한 가치는<br>생성 이후에 만들어진다.</strong></p>"
    "</div></div>"
)
WP_FOOTER = (
    '<p>The post <a href="https://jv.example.com/blog/p/1">생성형 AI의 가치는 생성 이후에 만들어진다</a> '
    'appeared first on <a href="https://jv.example.com/blog">Jinho&#039;s AI Studio</a>.</p>'
)


@given(
    "RSS 본문이 제목, 문장 부호 없는 목록, 주소 줄, 피드의 자동 문구를 담은 전문이고 원문 페이지도 같은 글인 글이 있다"
)
def _wordpress_like(world, ctx):
    page = (
        '<html><body><div id="content"><article class="post"><div class="entry-content">'
        f"{WP_BODY}</div></article></div></body></html>"
    )
    world.fetcher.page(LINK, page)
    ctx.article = world.article(link=LINK, content=WP_BODY + WP_FOOTER)


@then("원문 페이지의 전문이 보이고 맞지 않는다는 안내는 없다")
def _wordpress_ok(ctx):
    text = ctx.response.text
    assert "RSS 내용과 맞지 않습니다" not in text
    assert "전공자의 생성형 AI 활용이 더 큰 가치를" in body(text)
    assert "AWS에 배포하고 URL 알려줘" in body(text)  # 제목과 목록은 덜 자르기로 되살린다
