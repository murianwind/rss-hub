"""15_reader_ui.feature: 읽음, 북마크, 검색과 필터, 돌아가기, 사이드바, 인라인 금지."""

import re
from types import SimpleNamespace
from urllib.parse import quote

import pytest
from pytest_bdd import given, parsers, then, when

from rss_hub.services.retention import RetentionService
from rss_hub.storage.articles import NewArticle
from tests.bdd.binding import bind
from tests.fakes.viewer_world import BASE, World
from tests.fakes.web_parts import start_app

bind(globals(), "15_reader_ui.feature", [f"RUI-{n:02d}" for n in range(1, 18)])

BROWSER = {"origin": "null", "sec-fetch-site": "same-origin"}
FILTERS = {"전체": "", "읽지 않은 글": "unread", "북마크": "bookmarks"}


@pytest.fixture
def world(tmp_path):
    parts, client = start_app(tmp_path)
    with client:
        yield World(parts)


@pytest.fixture
def ctx():
    return SimpleNamespace(response=None, ids={}, last=None)


def feed_id(world, name):
    return world.f_news if name == "뉴스 블로그" else world.f_free


def post(world, path, **data):
    return world.client.post(path, data=data, headers=BROWSER)


def card(html, title):
    cards = html.split('<article class="card')[1:]
    return next(c for c in cards if title in c.split("</article>")[0])


def sidebar_count(html, label_pattern):
    """사이드바 항목(링크 이름이 label_pattern과 맞는 것)의 (읽지 않은 글 스타일인가, 숫자)."""
    nav = html.split('<nav aria-label="구독 목록">')[1].split("</nav>")[0]
    for link in re.findall(r'<a class="(?:nav-item|sec sec-link)"[^>]*>(.*?)</a>', nav, re.S):
        if re.search(label_pattern, link):
            count = re.search(r'<span class="count( unread)?"[^>]*>(\d+)</span>', link)
            return (bool(count.group(1)), int(count.group(2))) if count else None
    raise AssertionError(f"사이드바에 {label_pattern} 항목이 없다")


def titles(response):
    found = re.findall(
        r'<a class="title" href="[^"]+">(?:<span class="dot"[^>]*></span>)?(.*?)</a>', response.text
    )
    return sorted(found)


@given('사이트 "뉴스 블로그"(카테고리 "뉴스")와 사이트 "자유 블로그", 주제 "OTT"가 있다')
def _background(world):
    assert world.feeds.get(world.f_news).category_id == world.news and world.topics.list_all()


# ---------- 글 만들기 ----------


@given(parsers.re(r'사이트 "(?P<feed>[^"]+)"에 새 글 "(?P<title>[^"]+)"이 있다'))
def _new_article(world, ctx, feed, title):
    ctx.last = ctx.ids[title] = world.article(feed_id(world, feed), len(ctx.ids), title=title)


@given(parsers.re(r'사이트 "(?P<feed>[^"]+)"에 새 글 "(?P<title>[^"]+)"이 있고 이미 읽었다'))
def _read_article(world, ctx, feed, title):
    ctx.last = ctx.ids[title] = world.article(feed_id(world, feed), 0, title=title)
    world.articles.mark_read(ctx.last)


@given(parsers.re(r'사이트 "(?P<feed>[^"]+)"에 새 글 "(?P<a>[^"]+)"과 "(?P<b>[^"]+)"가 있다'))
def _two_articles(world, ctx, feed, a, b):
    for title in (a, b):
        ctx.ids[title] = world.article(feed_id(world, feed), len(ctx.ids), title=title)


@given(parsers.re(r'사이트 "(?P<feed>[^"]+)"에 새 글 31개가 있다'))
def _thirty_one(world, ctx, feed):
    for number in range(31):
        world.article(feed_id(world, feed), number)


@given(
    parsers.re(
        r'사이트 "(?P<feed>[^"]+)"에 새 글 "(?P<a>[^"]+)"과 '
        r'"(?P<b>[^"]+)"이 있고 "(?P=b)"은 북마크했다'
    )
)
def _two_with_bookmark(world, ctx, feed, a, b):
    for number, title in enumerate((a, b)):
        ctx.ids[title] = world.article(feed_id(world, feed), number, title=title)
    world.articles.set_bookmark(ctx.ids[b], True)


@given('사이트 "자유 블로그"가 처음 점검되어 오래된 글 "보관 글"이 보관되었다')
def _archived(world, ctx):
    ctx.ids["보관 글"] = world.articles.add_archived(
        NewArticle(
            world.f_free,
            "old",
            "보관 글",
            "https://x.example.com/old",
            "<p>c</p>",
            "",
            BASE,
            "2026-10-16",
        )
    )


@given(
    parsers.re(
        r'글 "(?P<a>[^"]+)"\(읽음\), "(?P<b>[^"]+)"\(읽지 않음\), '
        r'"(?P<c>[^"]+)"\(읽지 않음\)이 있다'
    )
)
def _three(world, ctx, a, b, c):
    for number, title in enumerate((a, b, c)):
        ctx.ids[title] = world.article(title=title, minutes=number)
    world.articles.mark_read(ctx.ids[a])


# ---------- 화면 열기 ----------


@when("읽기 화면을 연다")
def _open_reader(world, ctx):
    ctx.response = world.get("/reader")


@when(parsers.re(r'글 "(?P<title>[^"]+)"의 페이지를 연다'))
def _open_article(world, ctx, title):
    ctx.response = world.get(f"/a/{ctx.ids[title]}")


@when(parsers.re(r'글 "(?P<title>[^"]+)"의 페이지에서 "읽지 않음으로"를 누른다'))
def _press_unread(world, ctx, title):
    ctx.response = post(
        world, f"/a/{ctx.ids[title]}/read", state="unread", next=f"/reader/feed/{world.f_free}"
    )
    ctx.response = world.get(ctx.response.headers["location"])


@when(parsers.re(r'사이트 "(?P<feed>[^"]+)" 목록에서 "모두 읽음"을 누른다'))
def _press_mark_all(world, ctx, feed):
    path = f"/reader/feed/{feed_id(world, feed)}"
    response = post(
        world, "/reader/mark-read", kind="feed", ident=str(feed_id(world, feed)), next=path
    )
    ctx.response = world.get(response.headers["location"])


@when(parsers.re(r'목록에서 글 "(?P<title>[^"]+)"의 북마크를 누른다'))
def _press_bookmark(world, ctx, title):
    response = post(world, f"/a/{ctx.ids[title]}/bookmark", on="1", next="/reader")
    ctx.response = world.get(response.headers["location"])


@when(parsers.re(r'글 "(?P<title>[^"]+)"의 페이지에서 북마크를 해제한다'))
def _remove_bookmark(world, ctx, title):
    post(world, f"/a/{ctx.ids[title]}/bookmark", on="0", next=f"/a/{ctx.ids[title]}")
    ctx.response = world.get("/reader/bookmarks")


@when("보관 기간(90일)이 지난 뒤 정리 작업이 돈다")
def _retention(world):
    parts = world.parts
    parts.clock.advance(days=100)
    RetentionService(articles=world.articles, settings=parts.settings, clock=parts.clock).run()


@when(parsers.re(r'검색어 "(?P<query>[^"]*)"와 필터 "(?P<filter>[^"]+)"로 목록을 연다'))
def _search(world, ctx, query, filter):
    ctx.response = world.client.get("/reader", params={"q": query, "only": FILTERS[filter]})


@when(
    parsers.re(
        r'사이트 "(?P<feed>[^"]+)" 목록의 2쪽을 검색어 "(?P<query>[^"]+)"로 열고 글 하나를 연다'
    )
)
def _page_two_then_article(world, ctx, feed, query):
    ctx.list_path = f"/reader/feed/{feed_id(world, feed)}"
    listing = world.client.get(ctx.list_path, params={"page": "2", "q": query}).text
    href = re.search(r'<a class="title" href="(/a/\d+\?back=[^"]+)"', listing).group(1)
    ctx.response = world.get(href.replace("&amp;", "&"))
    ctx.query = query


@when(
    parsers.re(r'돌아갈 곳을 "(?P<back>[^"]+)"으로 지정해서 글 "(?P<title>[^"]+)"의 페이지를 연다')
)
def _article_with_back(world, ctx, back, title):
    ctx.response = world.client.get(f"/a/{ctx.ids[title]}", params={"back": back})


OPEN = {
    "전체 글 목록": lambda w: "/reader",
    "사이트 목록": lambda w: f"/reader/feed/{w.f_free}",
    "카테고리 목록": lambda w: f"/reader/category/{w.news}",
    "주제 목록": lambda w: f"/reader/topic/{w.topics.list_all()[0].id}",
    "환경 설정": lambda w: "/settings",
    "주제 관리": lambda w: "/topics",
}


@when(
    parsers.re(
        r"(?P<where>전체 글 목록|사이트 목록|카테고리 목록|주제 목록|환경 설정|주제 관리)을 연다"
    )
)
def _open_where(world, ctx, where):
    ctx.response = world.get(OPEN[where](world))


@given("브라우저에 사이드바를 접어 둔 기억이 있다")
def _remember_collapsed(world):
    world.client.cookies.set("sidebar", "collapsed")


@when('브라우저의 기억이 "펼침"으로 바뀐다')
def _remember_expanded(world):
    world.client.cookies.set("sidebar", "expanded")


@given("본문에 스크립트와 이벤트 속성이 든 글이 있다")
def _hostile(world, ctx):
    ctx.last = world.article(content='<p onclick="x()">본문</p><script>alert(1)</script>')


@when("읽기 화면과 글 페이지와 관리 화면들을 연다")
def _open_many(world, ctx):
    paths = ("/reader", f"/a/{ctx.last}", "/settings", "/feeds", "/topics", "/models", "/status")
    ctx.pages = [world.get(path) for path in paths]


# ---------- 확인 ----------


@then(
    parsers.re(
        r'글 "(?P<title>[^"]+)"은 읽지 않음으로 표시되고 사이드바의 '
        r'"(?P<feed>[^"]+)" 옆에 읽지 않은 글 (?P<n>\d+)이 보인다'
    )
)
def _unread_shown(ctx, title, feed, n):
    assert card(ctx.response.text, title).startswith(" unread")
    assert sidebar_count(ctx.response.text, re.escape(feed)) == (True, int(n))


@then(
    parsers.re(
        r'글 "(?P<title>[^"]+)"은 읽음으로 표시되고 사이드바의 '
        r'"(?P<feed>[^"]+)" 옆에는 숫자가 보이지 않는다'
    )
)
def _read_shown(ctx, title, feed):
    assert not card(ctx.response.text, title).startswith(" unread")
    assert sidebar_count(ctx.response.text, re.escape(feed)) is None


@then(parsers.re(r'목록으로 돌아가서 "(?P<message>[^"]+)" 알림이 보인다'))
def _back_with_toast(ctx, message):
    assert "data-toast" in ctx.response.text and message in ctx.response.text


@then(parsers.re(r'"(?P<message>[^"]+)" 알림이 보인다'))
def _toast(ctx, message):
    assert "data-toast" in ctx.response.text and message in ctx.response.text


@then(parsers.re(r'글 "(?P<title>[^"]+)"은 읽지 않음으로 표시된다'))
def _is_unread(ctx, title):
    assert card(ctx.response.text, title).startswith(" unread")


@then(
    parsers.re(
        r'"(?P<feed>[^"]+)"의 글은 모두 읽음이고 "(?P<other>[^"]+)"의 글은 그대로 읽지 않음이다'
    )
)
def _all_read_scope(world, feed, other):
    mine = [
        a for a in range(1, world.n + 1) if world.articles.get(a).feed_id == feed_id(world, feed)
    ]
    theirs = [
        a for a in range(1, world.n + 1) if world.articles.get(a).feed_id == feed_id(world, other)
    ]
    assert mine and theirs
    assert all(world.articles.get(a).read_at for a in mine) and not any(
        world.articles.get(a).read_at for a in theirs
    )


@then(
    parsers.re(
        r'글 "(?P<title>[^"]+)"은 읽음으로 표시되고 사이드바 "전체 글" 옆에는 읽지 않은 글이 없다'
    )
)
def _archived_is_read(ctx, title):
    assert not card(ctx.response.text, title).startswith(" unread")
    assert sidebar_count(ctx.response.text, "전체 글") in (None, (False, 0))


@then(
    parsers.re(r'"(?P<message>[^"]+)" 알림이 보이고 글 "(?P<title>[^"]+)"은 북마크됨으로 표시된다')
)
def _bookmarked_shown(ctx, message, title):
    assert message in ctx.response.text and 'aria-pressed="true"' in card(ctx.response.text, title)


@then(
    parsers.re(
        r'북마크 목록에 글 "(?P<title>[^"]+)"이 있고 사이드바 "북마크" 옆에 (?P<n>\d+)이 보인다'
    )
)
def _in_bookmarks(world, title, n):
    html = world.get("/reader/bookmarks").text
    assert title in html and sidebar_count(html, "북마크") == (False, int(n))


@then("북마크 목록은 비어 있다")
def _bookmarks_empty(ctx):
    assert "북마크한 글이 없습니다" in ctx.response.text


@then(parsers.re(r'글 "(?P<gone>[^"]+)"은 지워지고 글 "(?P<kept>[^"]+)"은 남는다'))
def _retention_result(world, ctx, gone, kept):
    assert (
        world.articles.get(ctx.ids[gone]) is None and world.articles.get(ctx.ids[kept]) is not None
    )


@then(parsers.re(r"목록에는 (?P<expected>.+)만 있고 게시물 수는 (?P<count>\d+)개다"))
def _list_result(ctx, expected, count):
    wanted = [] if expected == "없음" else sorted(part.strip() for part in expected.split(","))
    assert titles(ctx.response) == wanted and f"{count}개의 게시물" in ctx.response.text


@then(
    parsers.re(
        r'위쪽의 "목록으로 돌아가기"는 사이트 "(?P<feed>[^"]+)" '
        r'목록의 2쪽과 검색어 "(?P<query>[^"]+)"로 돌아간다'
    )
)
def _back_links(ctx, feed, query):
    expected = f'href="{ctx.list_path}?page=2&amp;q={quote(query)}"'
    links = re.findall(r'<a class="back[^"]*" ([^>]+)>', ctx.response.text)
    assert len(links) == 1 and all(expected in link for link in links)  # 위쪽에만 있다


@then(
    parsers.re(
        r'"목록으로 돌아가기"는 사이트 "(?P<feed>[^"]+)" '
        r"목록으로 가고 페이지에 다른 사이트 주소가 없다"
    )
)
def _safe_back(world, ctx, feed):
    text = ctx.response.text
    assert (
        f'<a class="back" href="/reader/feed/{feed_id(world, feed)}">' in text
        and "evil.example.com" not in text
    )
    assert "javascript:alert" not in text


@then(parsers.re(r"펼쳐진 사이드바 구역은 (?P<open>.+)이다"))
def _opened(ctx, open):
    names = {"rss": "RSS", "categories": "카테고리", "topics": "주제", "settings": "환경 설정"}
    opened = {
        names[k]
        for k in re.findall(r'<details class="sec" id="sec-(\w+)" open>', ctx.response.text)
    }
    assert opened == (set() if open == "없음" else {open})


@then("사이드바는 접힌 상태로 그려진다")
def _collapsed(ctx):
    assert '<body class="app sidebar-collapsed" data-auto-read="on">' in ctx.response.text


@then("사이드바는 펼쳐진 상태로 그려진다")
def _expanded(ctx):
    assert "sidebar-collapsed" not in ctx.response.text


@then("어느 페이지에도 인라인 스크립트, 인라인 스타일, 이벤트 속성이 없다")
def _no_inline(ctx):
    for response in ctx.pages:
        html = response.text
        assert not re.search(r"<script(?![^>]*\ssrc=)", html) and " style=" not in html
        assert not re.search(r"\son[a-z]+=", html)


@then("보안 정책은 우리 서버의 스크립트와 스타일만 허용하고 인라인과 eval은 허용하지 않는다")
def _policy(ctx):
    policy = ctx.pages[0].headers["content-security-policy"]
    assert "script-src 'self'" in policy and "style-src 'self'" in policy
    assert "unsafe-inline" not in policy and "unsafe-eval" not in policy


# ---------- 자동 읽음, 읽음 버튼, 폭 ----------


@given(parsers.re(r'사이트 "(?P<feed>[^"]+)"에 새 글 "(?P<a>[^"]+)"와 "(?P<b>[^"]+)"가 있다'))
def _two_articles_wa(world, ctx, feed, a, b):
    for title in (a, b):
        ctx.ids[title] = world.article(feed_id(world, feed), len(ctx.ids), title=title)
    ctx.feed = feed


@given(parsers.re(r'글 "(?P<title>[^"]+)"를 읽지 않음으로 바꿨다'))
def _pin(world, ctx, title):
    post(world, "/ui/read-state", id=str(ctx.ids[title]), state="unread")


@when("스크롤로 두 글이 모두 지나가서 화면이 자동 읽음을 요청한다")
def _auto_read(world, ctx):
    ctx.response = post(world, "/ui/auto-read", ids=",".join(str(i) for i in ctx.ids.values()))


@then(parsers.re(r'글 "(?P<read>[^"]+)"만 읽음이 되고 글 "(?P<kept>[^"]+)"는 계속 읽지 않음이다'))
def _only_one_read(world, ctx, read, kept):
    assert world.articles.get(ctx.ids[read]).read_at is not None
    assert world.articles.get(ctx.ids[kept]).read_at is None


@then(parsers.re(r'사이드바의 "(?P<feed>[^"]+)" 옆에 읽지 않은 글 (?P<n>\d+)이 보인다'))
def _sidebar_unread(world, feed, n):
    assert sidebar_count(world.get("/reader").text, re.escape(feed)) == (True, int(n))


@when(parsers.re(r'글 "(?P<title>[^"]+)"의 읽음 버튼을 누른다'))
def _read_button(world, ctx, title):
    ctx.response = post(world, "/ui/read-state", id=str(ctx.ids[title]), state="read")


@then(parsers.re(r'글 "(?P<title>[^"]+)"는 읽음이고 읽지 않음 고정은 풀렸다'))
def _released(world, ctx, title):
    assert world.articles.get(ctx.ids[title]).read_at is not None
    with world.parts.db.connect() as conn:
        pinned = conn.execute(
            "SELECT keep_unread FROM articles WHERE id = ?", (ctx.ids[title],)
        ).fetchone()[0]
    assert pinned == 0
    post(world, "/ui/read-state", id=str(ctx.ids[title]), state="unread")
    post(world, "/ui/read-state", id=str(ctx.ids[title]), state="read")  # 다시 읽음으로 돌려 둔다


@then("응답에는 갱신된 사이드바 개수가 들어 있다")
def _counts_in_response(world, ctx):
    state = ctx.response.json()["state"]
    assert state["feeds"][str(world.f_free)]["unread"] == 1 and state["all_unread"] == 1


@then("읽기 화면은 자동 읽음이 켜져 있다고 알린다")
def _auto_on(world, ctx):
    assert 'data-auto-read="on"' in world.get("/reader").text


@when("설정에서 스크롤 자동 읽음을 끈다")
def _auto_off(world):
    assert post(world, "/settings", ui_auto_read="off", next="/settings").status_code == 303


@then("읽기 화면은 자동 읽음이 꺼져 있다고 알린다")
def _auto_is_off(world):
    assert 'data-auto-read="off"' in world.get("/reader").text


@given(parsers.re(r'브라우저에 사이드바 폭 "(?P<value>[^"]*)"가 기억되어 있다'))
def _remember_width(world, value):
    world.client.cookies.set("sbw", value)


@then(parsers.re(r'사이드바 폭 클래스는 "(?P<expected>[^"]+)"이다'))
def _width_class(ctx, expected):
    body = ctx.response.text.split("<body")[1].split(">")[0]
    classes = re.findall(r"sw-\d+", body)
    assert classes == ([] if expected == "없음" else [expected])
