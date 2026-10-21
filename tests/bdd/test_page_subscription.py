"""20_page_subscription.feature: 웹페이지 구독."""

# ruff: noqa: E501  (HTML 정규식과 견본은 한 줄이 읽기 쉽다)

import html as html_module
import re
from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, then, when

from rss_hub.storage.articles import STATUS_COLLECTED
from rss_hub.storage.feeds import KIND_PAGE, STATUS_BASELINE
from tests.bdd.binding import bind
from tests.fakes.discovery_fetcher import FakeDiscoveryFetcher
from tests.fakes.page_html import BASE, COMSCORE_LIKE, article_html, listing, sample_items
from tests.fakes.viewer_world import World
from tests.fakes.web_parts import start_app

bind(globals(), "20_page_subscription.feature", [f"WPS-{n:02d}" for n in range(1, 14)])

BROWSER = {"origin": "null", "sec-fetch-site": "same-origin"}
LIST_URL = f"{BASE}/news"
FAIL_TEXT = "글 목록을 찾지 못했습니다(사이트 구조가 바뀌었을 수 있습니다)"


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
    return SimpleNamespace(response=None, feed=None, new=None, before=None)


def post(world, path, **data):
    return world.client.post(path, data=data, headers=BROWSER)


def row(html, name):
    rows = html.split('<li class="feed-row">')[1:]
    return html_module.unescape(next(r for r in rows if name in r.split("</li>")[0]))


@given('사이트 "자유 블로그"가 있다')
def _background(world):
    assert world.feeds.get(world.f_free)


# ---------- 후보 ----------


@given(parsers.re(r"피드가 없는 사이트의 글 목록 페이지에 글이 (?P<count>\d+)개 있다$"))
def _list_page(world, count):
    world.fetcher.page(LIST_URL, listing(sample_items(int(count))))


@given(
    "피드가 없는 사이트의 글 목록 페이지에 글이 4개 있고 메뉴와 푸터와 쪽 번호와 태그와 다른 사이트 링크도 있다"
)
def _noisy_list(world):
    world.fetcher.page(LIST_URL, listing(sample_items(4)))


@given("날짜와 분류 이름이 앞에 붙은 글 목록 페이지가 있다")
def _comscore(world):
    world.fetcher.page(
        "https://www.comscore.example.com/Insights/Blog",
        COMSCORE_LIKE.replace("/Insights/Blog", "/Insights/Blog"),
    )


@when("그 주소를 피드 추가에서 확인한다")
def _discover(world, ctx):
    url = (
        "https://www.comscore.example.com/Insights/Blog"
        if "https://www.comscore.example.com/Insights/Blog" in world.fetcher.pages
        else LIST_URL
    )
    ctx.response = post(world, "/feeds/discover", url=url, next="/feeds")


@then(
    parsers.re(
        r'후보 "웹페이지 구독"에 글 (?P<count>\d+)개와 최근 글 (?P<shown>\d+)개가 한 줄에 하나씩 목록으로 보인다'
    )
)
def _candidate(ctx, count, shown):
    html = html_module.unescape(ctx.response.text)
    assert (
        ctx.response.status_code == 200
        and "웹페이지 구독" in html
        and f"글 {count}개를 찾았습니다" in html
    )
    items = re.findall(r"<li>(새 소식 \d번[^<]*)</li>", html)
    assert (
        len(items) == int(shown) and '<ol class="sample-list wide">' in html and "(예:" not in html
    )


@then('"이 주소에서 피드를 찾지 못했습니다"가 보인다')
def _nothing_found(ctx):
    assert (
        ctx.response.status_code == 400
        and "이 주소에서 피드를 찾지 못했습니다" in ctx.response.text
    )


@then(parsers.re(r'후보의 최근 글 목록은 "(?P<a>[^"]+)", "(?P<b>[^"]+)", "(?P<c>[^"]+)"이다'))
def _sample_titles(ctx, a, b, c):
    html = html_module.unescape(ctx.response.text)
    items = re.findall(
        r"<li>([^<]+)</li>", html.split('class="sample-list wide"')[1].split("</ol>")[0]
    )
    assert items == [a, b, c]
    assert not any(x.startswith("Blog:") or "29 jul" in x for x in items)


# ---------- 등록과 점검 ----------


@given("글 목록 페이지에 글이 3개 있는 웹페이지 구독을 등록했다")
def _registered(world, ctx):
    world.fetcher.page(LIST_URL, listing(sample_items(3)))
    post(
        world,
        "/feeds/register",
        url=LIST_URL,
        kind="page",
        name="",
        category_id="",
        webhook_id="",
        next="/feeds",
    )
    ctx.feed = next(f.id for f in world.feeds.list_all() if f.url == LIST_URL)
    assert (
        world.feeds.get(ctx.feed).kind == KIND_PAGE
        and world.feeds.get(ctx.feed).status == STATUS_BASELINE
    )


@given("점검했다")
@when("점검한다")
def _collect(world, ctx):
    assert post(world, f"/feeds/{ctx.feed}/refresh").status_code == 200


@then("저장된 글은 없고 글 3개가 이미 본 글로 기록된다")
def _baseline(world):
    assert world.articles.list_by_status(STATUS_COLLECTED) == []
    assert all(world.articles.is_seen(f"{BASE}/news/post-{n}") for n in (1, 2, 3))


@when(parsers.re(r'새 글 "post-4"가 올라오고 점검한다'))
def _new_post(world, ctx):
    world.fetcher.page(LIST_URL, listing(sample_items(4)))
    world.fetcher.page(f"{BASE}/news/post-4", article_html(4))
    post(world, f"/feeds/{ctx.feed}/refresh")


@then("새 글 1개만 저장되고 그 글의 본문이 글 페이지에서 채워져 있다")
def _stored(world):
    (article,) = world.articles.list_by_status(STATUS_COLLECTED)
    assert (
        article.guid == f"{BASE}/news/post-4"
        and "4번 글의 1번째 본문 문단입니다" in article.content_html
    )


# ---------- 깨졌을 때 ----------


@when("사이트 구조가 바뀌어 글 목록에서 글이 보이지 않는 상태로 점검한다")
def _broken(world, ctx):
    world.fetcher.page(LIST_URL, "<html><body><p>구조가 바뀌었습니다</p></body></html>")
    post(world, f"/feeds/{ctx.feed}/refresh")


@then(parsers.re(r'피드 상태는 오류이고 피드 관리에는 "(?P<note>[^"]+)"가 보인다'))
def _red(world, ctx, note):
    assert world.get("/ui/state").json()["feeds"][str(ctx.feed)]["state"] == "error"
    assert note in row(world.get("/feeds").text, "예제 블로그")


# ---------- 주소 고치기 ----------


@given(parsers.re(r'새 주소 "(?P<url>[^"]+)"는 "(?P<state>[^"]+)" 상태다'))
def _new_address(world, ctx, url, state):
    ctx.new = url
    path = "/" + url.rsplit("/", 1)[1]
    if state == "RSS 피드":
        world.fetcher.feed(url, "공식 피드", "https://blog.example.com")
    elif state == "RSS를 알려 주는 웹페이지":
        advertised = '<head><link rel="alternate" type="application/rss+xml" href="https://blog.example.com/feed.xml">'
        world.fetcher.page(
            url, listing(sample_items(3), section=path).replace("<head>", advertised)
        )
    elif state in ("글 목록 있음", "RSS 없는 글 목록"):
        world.fetcher.page(url, listing(sample_items(3), section=path))
    else:
        world.fetcher.page(url, "<html><body><p>글 없음</p></body></html>")


@when(parsers.re(r'주소를 "(?P<url>[^"]+)"로 고쳐 저장한다'))
def _fix_address(world, ctx, url):
    ctx.before = world.feeds.get(ctx.feed)
    ctx.response = post(
        world,
        f"/feeds/{ctx.feed}/settings",
        name=ctx.before.name,
        emoji="📢",
        max_entries="",
        category_id="",
        webhook_id="",
        url=url,
        next="/feeds",
    )


@then("주소가 바뀌고 처음부터 다시 점검하는 상태가 된다")
def _fixed(world, ctx):
    saved = world.feeds.get(ctx.feed)
    assert (
        ctx.response.status_code == 303
        and saved.url == ctx.new
        and saved.status == STATUS_BASELINE
        and saved.kind == KIND_PAGE
    )


@then(parsers.re(r'"(?P<message>[^"]+)"로 거부되고 주소는 그대로다'))
def _refused(world, ctx, message):
    assert ctx.response.status_code == 400 and message in ctx.response.text
    assert world.feeds.get(ctx.feed).url == ctx.before.url


# ---------- 표시와 내보내기 ----------


@then(parsers.re(r'피드 관리에서 그 구독에 "(?P<mark>[^"]+)" 표시가 있고 "자유 블로그"에는 없다'))
def _badge(world, ctx, mark):
    html = world.get("/feeds").text
    assert f"{mark}</span>" in row(html, "예제 블로그") and f"{mark}</span>" not in row(
        html, "자유 블로그"
    )


@then('OPML 내보내기에는 그 구독이 없고 "자유 블로그"는 있다')
def _opml(world):
    opml = world.client.get("/feeds/export.opml").text
    assert LIST_URL not in opml and "자유 블로그" in opml


# ---------- 주소를 고칠 때 종류 판정, 주소 찾기 ----------


@given('일반 피드 "자유 블로그"의 주소를 고치려고 한다')
def _regular_feed(world, ctx):
    ctx.feed = world.f_free
    assert world.feeds.get(world.f_free).kind == "feed"


@then(parsers.re(r'구독 종류는 "(?P<kind>feed|page)"로 저장되고 처음부터 다시 점검한다'))
def _kind_saved(world, ctx, kind):
    saved = world.feeds.get(ctx.feed)
    assert ctx.response.status_code == 303 and saved.kind == kind and saved.url == ctx.new
    assert saved.status == STATUS_BASELINE


@then(parsers.re(r'"(?P<message>[^"]+)"로 거부되고 종류와 주소는 그대로다'))
def _kind_refused(world, ctx, message):
    saved = world.feeds.get(ctx.feed)
    assert ctx.response.status_code == 400 and message in ctx.response.text
    assert (saved.kind, saved.url) == (ctx.before.kind, ctx.before.url)


@when('피드 설정의 "변경"에서 그 주소를 확인한다')
def _pick(world, ctx):
    ctx.count = len(world.feeds.list_all())
    ctx.response = post(world, "/feeds/discover", url=LIST_URL, pick="1", next="/feeds")


@then('후보에는 "선택" 버튼만 있고 이름, 카테고리, 웹훅, 등록 칸은 없으며 구독은 늘지 않는다')
def _pick_only(world, ctx):
    html = ctx.response.text
    assert (
        ctx.response.status_code == 200
        and f'data-pick-url="{LIST_URL}"' in html
        and ">선택</button>" in html
    )
    assert all(
        x not in html
        for x in ('name="name"', 'name="category_id"', 'name="webhook_id"', "<form", "등록")
    )
    assert len(world.feeds.list_all()) == ctx.count


@then('스크립트는 "선택"을 누르면 주소 칸에 그 주소를 넣고 저장 전에는 아무것도 바꾸지 않는다')
def _pick_script(world):
    js = world.client.get("/static/app.js").text
    assert 'field.querySelector("input[name=url]").value = picked' in js
    after = js.split('field.querySelector("input[name=url]").value = picked')[1].split("}\n  });")[
        0
    ]
    assert "post(" not in after and "submit" not in after  # 값만 넣고 서버로 보내지 않는다


@when('피드 "자유 블로그"의 설정 패널을 연다')
def _open_settings_panel(world, ctx):
    ctx.response = world.client.get(
        f"/panel/settings/feed/{world.f_free}", headers={"x-panel": "1"}
    )


@then('주소 칸은 읽기 전용이고 "변경" 버튼이 있으며 안내에 "변경" 버튼으로 바꾼다고 적혀 있다')
def _readonly(ctx):
    html = ctx.response.text
    field = re.search(r'<input id="p_furl" name="url"[^>]*>', html).group(0)
    assert (
        " readonly" in field
        and 'aria-readonly="true"' in field
        and "data-finder-open>변경</button>" in html
    )
    assert '오른쪽 "변경" 버튼으로 바꿉니다' in html


# ---------- RSS와 웹페이지 구독을 함께 고르게 한다 ----------

FEED_URL = "https://blog.example.com/feed.xml"


def _serve_rss(world):
    advertised = f'<head><link rel="alternate" type="application/rss+xml" href="{FEED_URL}">'
    world.fetcher.page(LIST_URL, listing(sample_items(4)).replace("<head>", advertised))
    world.fetcher.feed(FEED_URL, "공식 피드", BASE)


@given(parsers.re(r"글 목록 페이지에 글이 4개 있고 RSS 피드 ?(?P<rss>가 있다|는 없다)$"))
def _list_with_or_without_rss(world, rss):
    if rss == "가 있다":
        _serve_rss(world)
    else:
        world.fetcher.page(LIST_URL, listing(sample_items(4)))


@given("글 목록 페이지에 글이 4개 있고 RSS 피드가 있다")
def _list_with_rss(world):
    _serve_rss(world)


@then(parsers.re(r"후보는 (?P<options>.+)이다"))
def _options(ctx, options):
    kinds = re.findall(r'<input type="hidden" name="kind" value="(feed|page)">', ctx.response.text)
    assert kinds == (["feed", "page"] if "순서의 두 가지" in options else ["page"])


@when(parsers.re(r'후보에서 "(?P<choice>[^"]+)"를 골라 주소를 고쳐 저장한다'))
def _choose_and_save(world, ctx, choice):
    kind, url = ("page", LIST_URL) if choice == "웹페이지 구독" else ("feed", FEED_URL)
    ctx.new = url
    ctx.before = world.feeds.get(ctx.feed)
    ctx.response = post(
        world,
        f"/feeds/{ctx.feed}/settings",
        name=ctx.before.name,
        emoji="📢",
        max_entries="",
        category_id="",
        webhook_id="",
        url=url,
        kind=kind,
        next="/feeds",
    )


@then("각 후보의 제목과 주소는 서로 다른 줄에 보인다")
def _separate_lines(ctx):
    html = ctx.response.text
    assert (
        len(
            re.findall(
                r'<span class="cand-title">[^<]*<span class="kind-badge">[^<]+</span></span>\s*<span class="cand-url">https://',
                html,
            )
        )
        == 2
    )
