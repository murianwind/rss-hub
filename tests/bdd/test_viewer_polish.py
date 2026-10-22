"""19_viewer_polish.feature: 첫 화면, 글 화면, 사이드바, 모델 사용량, 피드 검색."""

# ruff: noqa: E501  (HTML 견본과 긴 정규식은 한 줄이 읽기 쉽다)

import html as html_module
import re
from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, then, when

from rss_hub.storage.llm_usage import LlmUsageRepository
from tests.bdd.binding import bind
from tests.keywords.page import category_section, feed_ids, heading_link, rss_section

bind(globals(), "19_viewer_polish.feature", [f"VPL-{n:02d}" for n in range(1, 17)])

KEY = "sk-or-v1-abcdefghijklmnop"
ENGLISH = "This is a long English article body about software design and testing. " * 12
KOREAN = "이것은 한국어로 쓴 충분히 긴 본문입니다. " * 20
WAF_SHAPE = re.compile(r"[?&;][A-Za-z0-9_]+=/")


@pytest.fixture
def ctx():
    return SimpleNamespace(response=None, article=None, articles=[])


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


@then('제목은 원문으로 가는 새 창 링크이고 "원문 보기" 버튼과 가져온 전문 안내 문구는 없다')
def _title_link(ctx):
    html = ctx.response.text
    link = re.search(r'<h1><a class="title-link"[^>]*>', html).group(0)
    assert 'target="_blank"' in link and 'rel="noopener noreferrer"' in link and "/original" in link
    assert "원문 보기" not in html and "원문 페이지에서 가져온 전문입니다" not in html


@then('분류, 제목, 요약, "전문 다시 가져오기" 버튼은 고정 영역에 있고 본문만 스크롤 영역에 있다')
def _fixed_header(ctx):
    html = ctx.response.text
    fixed = html.split('<div class="doc-fixed">')[1].split('<div class="doc-scroll">')[0]
    scroll = html.split('<div class="doc-scroll">')[1]
    assert 'class="doc-meta"' in fixed and "<h1>" in fixed and 'class="back"' in fixed
    assert (
        'class="article-body"' in scroll
        and "<h1>" not in scroll
        and "전문 다시 가져오기" not in scroll
    )


@then("글 카드는 격자 배경 없이 위아래 여백이 같은 영역을 채운다")
def _layout(world):
    css = world.client.get("/static/app.css").text
    assert "linear-gradient" not in css
    assert (
        ".detail-scroll { display: flex; flex-direction: column; overflow: hidden; padding: 24px; }"
        in css
    )
    assert (
        ".detail-scroll .doc { display: flex; flex: 1; flex-direction: column; min-height: 0;"
        in css
    )


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


def server_says(world, used, limit=1000):
    from rss_hub.services.ports import ServerUsage

    world.parts.llm.usage = ServerUsage(used=used, limit=limit)


@when("모델 키를 설정하고 서버가 오늘 무료 호출 33회를 알려 준다")
@given("모델 키가 설정되어 있고 서버가 오늘 무료 호출 33회를 알려 준다")
def _set_key(world):
    world.parts.settings.set_openrouter_key(KEY)
    server_says(world, 33)


@then(parsers.re(r'사이드바에는 "모델 잔여 사용량 (?P<shown>\d+/\d+)"이 보인다'))
def _usage_shown(world, shown):
    assert model_text(world.get("/reader").text) == shown


@when(parsers.re(r"모델이 (?P<calls>\d+)번 호출되어 서버의 오늘 호출 수가 그만큼 늘었다"))
def _model_calls(world, calls):
    usage = LlmUsageRepository(world.parts.db, world.parts.clock)
    for _ in range(int(calls)):
        usage.record(model="m/free", outcome="success", status=200)
    server_says(world, 33 + int(calls))


@when("다른 프로그램이 호출해서 서버의 오늘 호출 수가 600이 되고 시간이 지난다")
def _other_programs(world):
    server_says(world, 600)
    world.parts.clock.advance(minutes=2)


@when("서버에 닿지 못하고 시간이 지난다")
def _server_unreachable(world):
    world.parts.llm.usage = None
    world.parts.clock.advance(minutes=2)


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


# ---------- 사이트 링크, 진하게/연하게, 쪽 이동 ----------


@given(
    parsers.re(
        r'사이트 "블로그"의 피드 주소는 "(?P<feed>[^"]+)"이고 사이트 주소는 "(?P<site>[^"]*)"이다'
    )
)
def _site_feed(world, ctx, feed, site):
    ctx.feed_id = world.feeds.add(feed, "블로그")
    with world.parts.db.connect() as conn:
        conn.execute("UPDATE feeds SET html_url = ? WHERE id = ?", (site, ctx.feed_id))


@when('사이트 "블로그"의 목록을 연다')
def _open_site_list(world, ctx):
    ctx.response = world.get(f"/reader/feed/{ctx.feed_id}")


@then(parsers.re(r'제목은 "(?P<goes>[^"]+)"로 가는 새 창 링크다'))
def _title_link(ctx, goes):
    href, rel = heading_link(ctx.response.text)
    assert href == goes and "noopener" in rel and "noreferrer" in rel


@when("전체 글, 북마크, 카테고리 목록을 차례로 연다")
def _open_lists(world, ctx):
    ctx.pages = [
        world.get(p).text
        for p in ("/reader", "/reader/bookmarks", f"/reader/category/{world.news}")
    ]


@then("어느 제목에도 사이트로 가는 링크가 없다")
def _no_site_links(ctx):
    assert all(heading_link(page) is None for page in ctx.pages)


def feed_rows(html):
    found = re.findall(
        r'<li class="nav-row( has-unread)?" draggable="true" data-drag-kind="feed" data-drag-id="(\d+)"',
        html,
    )
    return {int(feed): bool(flag) for flag, feed in found}


@given('사이트 "뉴스 블로그"에 새 글이 하나 있고 사이트 "자유 블로그"에는 글이 없다')
def _one_news_article(world, ctx):
    ctx.article = world.article(world.f_news)


@then('사이드바에서 "뉴스 블로그"는 진하게, "자유 블로그"는 연하게 표시된다')
def _bold_and_light(world):
    rows = feed_rows(world.get("/reader").text)
    assert rows[world.f_news] is True and rows[world.f_free] is False


@when("그 글을 읽는다")
def _read_it(world, ctx):
    world.get(f"/a/{ctx.article}")


@then("사이드바에서 두 사이트 모두 연하게 표시된다")
def _both_light(world):
    assert not any(feed_rows(world.get("/reader").text).values())


@given("전체 글이 65개 있다")
def _sixty_five(world):
    for number in range(65):
        world.article(minutes=number)


@when("전체 글의 2쪽을 연다")
def _second_page(world, ctx):
    ctx.response = world.get("/reader?page=2")


@then('"2 / 3" 쪽 표시와 이전, 다음 버튼이 있다')
def _pager(ctx):
    html = ctx.response.text
    assert (
        '<span class="pager-info">2 / 3</span>' in html
        and "data-prev" in html
        and "data-next" in html
    )


@then("스크립트는 끝에 다가가면 다음 쪽을 이어 붙이고 실패하면 버튼으로 돌아간다")
def _script(world):
    js = world.client.get("/static/app.js").text
    assert "IntersectionObserver" in js and "a[data-next]" in js
    assert 'pagerBox.classList.add("auto")' in js and 'pagerBox.classList.remove("auto")' in js


# ---------- 설정 패널 토글 ----------


@when("사이드바의 설정 버튼들을 본다")
def _panel_buttons(world, ctx):
    ctx.response = world.get("/reader")


@then("모든 버튼은 패널을 여는 버튼이다")
def _panel_openers(ctx):
    links = re.findall(r'<a [^>]*href="(/panel/[^"]+)"[^>]*data-panel', ctx.response.text)
    assert len(links) >= 6 and all(link.startswith("/panel/") for link in links)


@then("스크립트는 같은 버튼으로 연 패널이 열려 있으면 닫고 다른 버튼이면 내용을 바꾼다")
def _toggle_script(world):
    js = world.client.get("/static/app.js").text
    toggle = js.split('slot.getAttribute("data-open") === opener.href')[1].split(
        "openPanel(opener.href)"
    )[0]
    assert "closePanel()" in toggle and 'slot.setAttribute("data-open", url)' in js
    assert js.count("openPanel(opener.href)") == 1  # 같은 버튼이 아니면 열면서 내용이 바뀐다


# ---------- 카테고리 소속 피드, 한 화면 ----------


@then('사이드바의 RSS 피드에는 "자유 블로그"만 있고 "뉴스 블로그"는 카테고리 "뉴스" 아래에만 있다')
def _rss_only_free(world):
    html = world.get("/reader").text
    assert feed_ids(rss_section(html)) == [world.f_free]
    assert feed_ids(category_section(html)) == [world.f_news]


@when('사이트 "뉴스 블로그"를 카테고리에서 뺀다')
def _remove_category(world):
    world.feeds.set_feed_category(world.f_news, None)


@then('사이드바의 RSS 피드에는 "뉴스 블로그"와 "자유 블로그"가 있고 카테고리 아래에는 없다')
def _rss_has_both(world):
    html = world.get("/reader").text
    assert set(feed_ids(rss_section(html))) == {world.f_news, world.f_free}
    assert not feed_ids(category_section(html))


@when("모든 사이트를 카테고리에 넣는다")
def _all_in_category(world):
    for feed in (world.f_news, world.f_free):
        world.feeds.set_feed_category(feed, world.news)


@then(parsers.re(r'RSS 피드에는 "(?P<note>[^"]+)" 안내가 있다'))
def _rss_note(world, note):
    assert note in rss_section(world.get("/reader").text)


@then("열린 구역이 둘 이상이면 구역별 높이를 나누고 목록은 안에서 스크롤되는 스타일이 있다")
def _share_css(world):
    css = world.client.get("/static/app.css").text
    assert ".sb-body:has(#sec-rss[open]):has(#sec-categories[open]):has(#sec-topics[open])" in css
    assert (
        "overflow-y: auto; overscroll-behavior: contain;" in css and "max-height: max(110px" in css
    )


@then("RSS 피드 목록은 카테고리에서 끌어다 놓으면 카테고리를 빼는 드롭 대상이다")
def _rss_drop_target(world):
    assert (
        '<ul class="sec-body" data-reorder="feed" data-drop-category="">'
        in world.get("/reader").text
    )
    assert "target.contains(dragged)" in world.client.get("/static/app.js").text


@then(
    "스크립트는 RSS 피드, 카테고리, 주제 목록 각각의 스크롤을 기억했다가 되돌리고 선택한 줄이 안 보이면 보이게 한다"
)
def _list_scroll(world):
    js = world.client.get("/static/app.js").text
    assert (
        'var LISTS = ["sec-rss", "sec-categories", "sec-topics"];' in js
        and "lists: listScrolls()" in js
    )
    assert "body.scrollTop = saved.lists[id]" in js and "if (body) showCurrent(body);" in js
