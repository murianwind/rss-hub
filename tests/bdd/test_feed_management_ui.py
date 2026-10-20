"""17_feed_management.feature: 피드 상태, 새로고침, 자동 가변 수집 주기, 주소 변경, 추가 패널."""

# ruff: noqa: E501  (시나리오 문장과 같은 긴 단계 문구)

import html as html_module
import re
from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, then, when

from rss_hub.domain.activity import FeedMeasurement
from rss_hub.domain.schedule import Activity
from tests.bdd.binding import bind
from tests.fakes.discovery_fetcher import FakeDiscoveryFetcher
from tests.fakes.entries import today as entries_today
from tests.fakes.feed_fetcher import FakeFeedFetcher
from tests.fakes.viewer_world import World
from tests.fakes.web_parts import start_app

bind(globals(), "17_feed_management.feature", [f"FMG-{n:02d}" for n in range(1, 13)])

BROWSER = {"origin": "null", "sec-fetch-site": "same-origin"}
FRAGMENT = {"x-panel": "1"}
FREE_URL, NEWS_URL = "https://f.example.com/rss", "https://n.example.com/rss"


class Fetchers(FakeFeedFetcher, FakeDiscoveryFetcher):
    """점검(수집)과 자동 탐색을 모두 흉내 내는 가짜 수집기."""

    def __init__(self):
        FakeFeedFetcher.__init__(self)
        FakeDiscoveryFetcher.__init__(self)

    def fetch(self, url, *, etag, last_modified):
        if url in self.outcomes:
            return FakeFeedFetcher.fetch(self, url, etag=etag, last_modified=last_modified)
        return FakeDiscoveryFetcher.fetch(self, url, etag=etag, last_modified=last_modified)


@pytest.fixture
def world(tmp_path):
    fetcher = Fetchers()
    parts, client = start_app(tmp_path, feed_fetcher=fetcher)
    with client:
        w = World(parts)
        w.fetcher = fetcher
        yield w


@pytest.fixture
def ctx():
    return SimpleNamespace(response=None, page=None)


def post(world, path, **data):
    return world.client.post(path, data=data, headers=BROWSER)


def feed_id(world, name):
    return world.f_news if name == "뉴스 블로그" else world.f_free


def row(html, name):
    rows = html.split('<li class="feed-row">')[1:]
    return html_module.unescape(next(r for r in rows if name in r.split("</li>")[0]))


@given('사이트 "뉴스 블로그"(카테고리 "뉴스")와 사이트 "자유 블로그"가 있다')
def _background(world):
    assert world.feeds.get(world.f_news).category_id == world.news and world.f_free


# ---------- 상태 ----------


@given('사이트 "뉴스 블로그"는 점검에 실패했고 사이트 "자유 블로그"는 아직 점검한 적이 없다')
def _states(world):
    world.feeds.record_failure(world.f_news, "ReadTimeout")


@when("피드 관리 화면을 연다")
def _open_feeds(world, ctx):
    ctx.response = world.get("/feeds")


@then('"뉴스 블로그"는 오류(빨강)이고 이유가 보이며 "자유 블로그"는 수집 전(회색)이다')
def _state_dots(ctx):
    html = ctx.response.text
    assert 'class="state-dot error"' in row(html, "뉴스 블로그") and "ReadTimeout" in row(
        html, "뉴스 블로그"
    )
    assert 'class="state-dot never"' in row(html, "자유 블로그")


@then("사이드바에도 같은 상태 점이 있다")
def _sidebar_dots(world, ctx):
    html = ctx.response.text
    assert f'class="state-dot error" data-state="{world.f_news}"' in html
    assert f'class="state-dot never" data-state="{world.f_free}"' in html


@when('사이트 "자유 블로그"를 정상으로 점검했다')
@given('사이트 "자유 블로그"를 정상으로 점검했다')
def _checked(world, ctx):
    world.feeds.record_success(world.f_free, etag=None, last_modified=None, activate=True)
    ctx.response = world.get("/feeds")


@then('"자유 블로그"는 정상(초록)이다')
def _green(ctx):
    assert 'class="state-dot ok"' in row(ctx.response.text, "자유 블로그")


# ---------- 새로고침 ----------


@given(
    parsers.re(r'사이트 "자유 블로그"의 피드는 (?P<server>정상으로 응답한다|시간 초과로 실패한다)')
)
def _server(world, server):
    if server == "정상으로 응답한다":
        world.fetcher.serve(FREE_URL, entries_today(1))
    else:
        world.fetcher.fail(FREE_URL, "ReadTimeout")
    world.feeds.record_success(world.f_free, etag="old", last_modified="old", activate=True)


@when('사이트 "자유 블로그"의 새로고침 버튼을 누른다')
def _refresh(world, ctx):
    ctx.response = post(world, f"/feeds/{world.f_free}/refresh")


@then(parsers.re(r'응답은 (?P<ok>성공|실패)이고 "자유 블로그"의 상태는 (?P<state>정상|오류)이다'))
def _refresh_result(world, ctx, ok, state):
    data = ctx.response.json()
    assert data["ok"] is (ok == "성공")
    shown = data["state"]["feeds"][str(world.f_free)]["state"]
    assert shown == {"정상": "ok", "오류": "error"}[state]
    assert (shown == "error") == bool(data["error"])


@then("서버에는 저장된 검증값 없이 요청했다")
def _no_validators(world):
    call = world.fetcher.calls[-1]
    assert (call.etag, call.last_modified) == (None, None)


# ---------- 수집 주기 ----------


@given(
    parsers.re(
        r'사이트 "자유 블로그"의 오늘 글이 (?P<today>\d+)개, 최근 7일 글이 (?P<week>\d+)개이다'
    )
)
def _activity(world, today, week):
    world.feeds.save_stats(
        world.f_free, FeedMeasurement(Activity(int(week), int(today)), world.parts.clock.now())
    )


@then(
    parsers.re(r'"자유 블로그"의 수집 주기는 "(?P<cycle>[^"]+)"이고 점검 시각과 다음 점검이 보인다')
)
def _cycle(ctx, cycle):
    line = row(ctx.response.text, "자유 블로그")
    assert (
        cycle in line
        and re.search(r"매시 (\d\d분(, )?)+", line)
        and re.search(r"다음 점검 \d\d:\d\d", line)
    )


@given('사이트 "자유 블로그"는 조용하고 사이트 "뉴스 블로그"는 오늘 글이 4개이다')
def _quiet_and_busy(world):
    now = world.parts.clock.now()
    world.feeds.save_stats(world.f_free, FeedMeasurement(Activity(0, 0), now))
    world.feeds.save_stats(world.f_news, FeedMeasurement(Activity(4, 4), now))


@then('"뉴스 블로그"는 "자유 블로그"보다 시간당 점검 횟수가 많다')
def _busy_more(ctx):
    def count(name):
        return int(re.search(r"시간당 (\d)회", row(ctx.response.text, name)).group(1))

    assert count("뉴스 블로그") > count("자유 블로그")


# ---------- 주소 변경 ----------


def settings_post(world, feed, **override):
    f = world.feeds.get(feed)
    data = {
        "name": f.name,
        "url": f.url,
        "emoji": f.emoji,
        "max_entries": "",
        "category_id": "",
        "webhook_id": "",
    }
    if f.category_id:
        data["category_id"] = str(f.category_id)
    return post(world, f"/feeds/{feed}/settings", **{**data, **override})


@when(parsers.re(r'사이트 "자유 블로그"의 주소를 "(?P<url>[^"]+)"로 바꾼다'))
def _change_url(world, ctx, url):
    world.fetcher.serve(url, [])  # 새 주소는 정상적인 피드다
    ctx.response = settings_post(world, world.f_free, url=url)


@then("주소가 바뀌고 상태는 수집 전(회색)으로 돌아가며 첫 점검 대기 상태가 된다")
def _url_changed(world, ctx):
    feed = world.feeds.get(world.f_free)
    assert ctx.response.status_code == 303 and feed.url == "https://new.example.com/feed.xml"
    assert feed.last_checked_at is None and feed.status == "baseline_pending"
    assert 'class="state-dot never"' in row(world.get("/feeds").text, "자유 블로그")


@when('사이트 "자유 블로그"의 주소를 사이트 "뉴스 블로그"의 주소로 바꾸려고 한다')
def _duplicate_url(world, ctx):
    ctx.response = settings_post(world, world.f_free, url=NEWS_URL)


@then("이미 구독 중이라는 이유로 거부되고 주소는 그대로다")
def _refused_duplicate(world, ctx):
    assert ctx.response.status_code == 400 and "이미 구독" in ctx.response.text
    assert world.feeds.get(world.f_free).url == "https://new.example.com/feed.xml"


# ---------- 피드 추가 ----------


@then("이 화면에는 피드 추가 폼이 없고 사이드바의 + 안내가 있다")
def _no_add_form(ctx):
    html = ctx.response.text
    assert 'action="/feeds/discover"' not in html and "사이드바의 RSS 피드 <b>+</b>" in html


@when(parsers.re(r'사이드바의 \+ 패널에서 주소 "(?P<url>[^"]+)"를 확인한다'))
def _discover(world, ctx, url):
    world.fetcher.feed(url, "새 피드", "https://new.example.com/")
    ctx.url = url
    ctx.response = world.client.post(
        "/feeds/discover", data={"url": url, "next": "/reader"}, headers=BROWSER | FRAGMENT
    )


@then(
    parsers.re(
        r"찾은 피드가 패널 안에 보이고 등록하면 읽기 화면으로 돌아와 "
        r'"(?P<message>[^"]+)" 알림이 보인다'
    )
)
def _register(world, ctx, message):
    assert (
        "찾은 피드" in ctx.response.text
        and "새 피드" in ctx.response.text
        and "<html" not in ctx.response.text
    )
    done = post(world, "/feeds/register", url=ctx.url, name="새 피드", next="/reader")
    assert done.headers["location"] == "/reader?toast=added"
    assert message in world.get(done.headers["location"]).text


# ---------- 거르기 ----------


@when(parsers.re(r'피드 관리 화면에서 "오류" 상태만 본다'))
def _only_errors(world, ctx):
    ctx.response = world.get("/feeds?state=error")


@then('"뉴스 블로그"만 보이고 칩에는 전체 2, 오류 1, 수집 전 1이 표시된다')
def _chips(ctx):
    html = ctx.response.text
    listing = html_module.unescape(html.split('<ul class="feed-list">')[1].split("</ul>")[0])
    assert "뉴스 블로그" in listing and "자유 블로그" not in listing
    assert re.search(r"전체 2\s*</a>", html) and "오류 1" in html and "수집 전 1" in html


# ---------- 주소를 바꿀 때의 확인 ----------

OUTCOMES = {"정상 피드": None, "피드 아님": "NotAFeed", "시간 초과": "ReadTimeout"}


@given(
    parsers.re(
        r'사이트 "자유 블로그"의 주소를 "(?P<url>[^"]+)"로 바꾸면 "(?P<outcome>[^"]+)" 상태다'
    )
)
def _outcome(world, url, outcome):
    reason = OUTCOMES[outcome]
    if reason is None:
        world.fetcher.serve(url, [])
    else:
        world.fetcher.fail(url, reason)


@when(
    parsers.re(
        r'사이트 "자유 블로그"의 이름을 "(?P<name>[^"]+)"으로, 주소를 "(?P<url>[^"]+)"로 저장한다'
    )
)
def _save_name_url(world, ctx, name, url):
    ctx.before = world.feeds.get(world.f_free)
    ctx.new_url = url
    ctx.response = settings_post(world, world.f_free, name=name, url=url)


@then(
    parsers.re(r"저장되고 사이트 \"자유 블로그\"의 이름과 주소가 바뀌며 새 주소를 한 번 가져왔다")
)
def _saved(world, ctx):
    feed = world.feeds.get(world.f_free)
    assert ctx.response.status_code == 303 and feed.name == "바뀐 이름" and feed.url == ctx.new_url
    assert world.fetcher.urls_fetched().count(ctx.new_url) == 1


@then(parsers.re(r'"(?P<message>[^"]+)"로 거부되고 이름과 주소는 그대로다'))
def _refused(world, ctx, message):
    feed = world.feeds.get(world.f_free)
    assert ctx.response.status_code == 400 and message in ctx.response.text
    assert (feed.name, feed.url) == (ctx.before.name, ctx.before.url)


# ---------- 필터와 버튼, 카드 ----------

ACTIVITY = {1: (0, 0), 2: (3, 0), 3: (10, 1)}  # 활동량으로 시간당 1, 2, 3회가 배정되는 값


def make_feed(world, name, cycle, ago):
    from rss_hub.domain.activity import FeedMeasurement
    from rss_hub.domain.schedule import Activity

    feed = world.feeds.add(f"https://{abs(hash(name))}.example.com/rss", name)
    last = None if ago is None else world.parts.clock.now() - ago
    world.feeds.save_stats(feed, FeedMeasurement(Activity(*ACTIVITY[cycle]), last))
    return feed


def visible(world, path, names):
    html = world.get(path).text
    listing = html_module.unescape(html.split('<ul class="feed-list">')[1].split("</ul>")[0])
    return {
        n for n in names if f"{n}</a>" in listing or f" {n}\n" in listing or f"> {n}<" in listing
    }


@given('피드 "가"는 시간당 1회, "나"는 시간당 2회, "다"는 시간당 3회로 배정되어 있다')
def _cycles(world):
    from datetime import timedelta

    for name, cycle in (("가", 1), ("나", 2), ("다", 3)):
        make_feed(world, name, cycle, timedelta(hours=1))


@when(parsers.re(r'피드 관리에서 수집 주기 "(?P<cycle>\d)"로 거른다'))
def _filter_cycle(world, ctx, cycle):
    ctx.path = f"/feeds?cycle={cycle}"


@given(
    '피드 "하루"는 2시간 전, "주"는 3일 전, "달"은 20일 전, "해"는 200일 전, "오래"는 400일 전에 마지막으로 게시했고 "없음"은 게시 기록이 없다'
)
def _ages(world):
    from datetime import timedelta

    for name, ago in (
        ("하루", timedelta(hours=2)),
        ("주", timedelta(days=3)),
        ("달", timedelta(days=20)),
        ("해", timedelta(days=200)),
        ("오래", timedelta(days=400)),
        ("없음", None),
    ):
        make_feed(world, name, 1, ago)


@when(parsers.re(r'피드 관리에서 마지막 게시 "(?P<last>[a-z]+)"로 거른다'))
def _filter_last(world, ctx, last):
    ctx.path = f"/feeds?last={last}"


@then(parsers.re(r'"가", "나", "다" 중 (?P<shown>"[^\n]+")만 보인다'))
@then(parsers.re(r'"하루", "주", "달", "해", "오래", "없음" 중 (?P<shown>"[^\n]+")만 보인다'))
def _shown_only(world, ctx, shown):
    expected = set(re.findall(r'"([^"]+)"', shown))
    group = {"가", "나", "다"}
    candidates = group if expected <= group else {"하루", "주", "달", "해", "오래", "없음"}
    assert visible(world, ctx.path, candidates) == expected


@given("제목이 매우 긴 피드가 있다")
def _long_title(world, ctx):
    ctx.long_name = ("매우 긴 제목을 가진 피드 " * 12).strip()
    world.feeds.add("https://long.example.com/rss", ctx.long_name)


@when("피드 관리를 연다")
def _open_feeds(world, ctx):
    ctx.response = world.get("/feeds")


@then('세 버튼은 "목록으로 돌아가기"와 같은 버튼 디자인이다')
def _back_design(world, ctx):
    tools = ctx.response.text.split('<span class="row">')[1].split("</span>\n</div>")[0]
    assert tools.count('class="back"') == 3 and 'class="button"' not in tools
    assert (
        "<span>OPML 가져오기</span>" in tools
        and "<span>OPML 내보내기</span>" in tools
        and "<span>카테고리 관리</span>" in tools
    )


@then(
    "카드는 최소 너비 440px로 화면 너비에 따라 열 수가 바뀌고 긴 제목은 줄임표로 줄여 보이며 전체 제목은 말풍선으로 볼 수 있다"
)
def _cards(world, ctx):
    css = world.client.get("/static/app.css").text
    assert (
        "repeat(auto-fill, minmax(min(100%, 440px), 1fr))" in css
        and "text-overflow: ellipsis" in css
    )
    assert 'class="page page-wide"' in ctx.response.text
    assert f'title="{html_module.escape(ctx.long_name)}"' in ctx.response.text


@then(
    "위쪽 영역에는 제목과 검색, 필터, 상태 칩, 세 버튼이 있고 카드 목록은 따로 스크롤되는 영역에 있다"
)
def _fixed_top(ctx):
    html = ctx.response.text
    fixed = html.split('<div class="feed-fixed">')[1].split('<div class="feed-scroll">')[0]
    scroll = html.split('<div class="feed-scroll">')[1]
    assert all(
        x in fixed
        for x in (
            "<h1>피드 관리</h1>",
            'role="search"',
            'name="cycle"',
            'name="last"',
            "상태로 거르기",
            "OPML 가져오기",
            "카테고리 관리",
        )
    )
    assert '<ul class="feed-list">' in scroll and 'role="search"' not in scroll
