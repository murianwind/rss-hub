"""16_ui_management.feature: 슬라이드 패널, 순서와 이동, 설정 탭, 디스플레이 설정."""

import re
from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, then, when

from rss_hub.domain.topics import TopicFields
from tests.bdd.binding import bind
from tests.fakes.viewer_world import World
from tests.fakes.web_parts import start_app

bind(globals(), "16_ui_management.feature", [f"PNL-{n:02d}" for n in range(1, 13)])

BROWSER = {"origin": "null", "sec-fetch-site": "same-origin"}
FRAGMENT = {"x-panel": "1"}
WEBHOOK = "https://discord.com/api/webhooks/9/abc"
KINDS = {"피드": "feed", "카테고리": "category", "주제": "topic"}


@pytest.fixture
def world(tmp_path):
    parts, client = start_app(tmp_path)
    with client:
        yield World(parts)


@pytest.fixture
def ctx():
    return SimpleNamespace(response=None, fragment=None, ids={}, before=None)


def post(world, path, **data):
    return world.client.post(path, data=data, headers=BROWSER)


def feed_id(world, name):
    return world.f_news if name == "뉴스 블로그" else world.f_free


def target_of(world, kind):
    return {"feed": world.f_free, "category": world.news, "topic": world.game}[kind]


def feed_order(world):
    html = world.get("/reader").text
    nav = html.split('<details class="sec" id="sec-rss"')[1].split("</details>")[0]
    return [int(i) for i in re.findall(r'href="/reader/feed/(\d+)"', nav)]


@given(
    '사이트 "뉴스 블로그"(카테고리 "뉴스")와 사이트 "자유 '
    '블로그", 카테고리 "기술", 주제 "게임"이 있다'
)
def _background(world):
    world.game = world.topics.add(TopicFields("게임", "게임 소식", ("steam",)))
    assert world.feeds.get(world.f_news).category_id == world.news and world.tech


# ---------- 패널 ----------


@when(parsers.re(r"스크립트가 (?P<kind>피드|카테고리|주제) 추가 패널을 받는다"))
def _fragment(world, ctx, kind):
    ctx.path = f"/panel/add/{KINDS[kind]}"
    ctx.fragment = world.client.get(ctx.path, headers=FRAGMENT)


@then("조각에는 패널 본문만 있고 화면 틀은 없다")
def _only_fragment(ctx):
    assert ctx.fragment.status_code == 200 and "<html" not in ctx.fragment.text
    assert 'class="slide"' in ctx.fragment.text


@when("스크립트 없이 같은 주소를 연다")
def _full(world, ctx):
    ctx.response = world.get(ctx.path)


@then("사이드바가 있는 전체 화면에 같은 패널이 열려 있다")
def _full_page(ctx):
    assert "<html" in ctx.response.text and '<nav aria-label="구독 목록">' in ctx.response.text
    assert 'class="slide static"' in ctx.response.text


@given(parsers.re(r'읽기 화면에서 사이트 "(?P<feed>[^"]+)"의 설정 패널을 열었다'))
def _open_feed_panel(world, ctx, feed):
    ctx.feed = feed_id(world, feed)
    ctx.fragment = world.client.get(
        f"/panel/settings/feed/{ctx.feed}?next=/reader", headers=FRAGMENT
    )
    assert f'action="/feeds/{ctx.feed}/settings"' in ctx.fragment.text


@when(parsers.re(r'이름을 "(?P<name>[^"]+)"으로, 피드 주소를 "(?P<url>[^"]+)"로 저장한다'))
def _save_feed(world, ctx, name, url):
    ctx.response = post(
        world,
        f"/feeds/{ctx.feed}/settings",
        name=name,
        url=url,
        emoji="📰",
        max_entries="",
        category_id="",
        webhook_id="",
        next="/reader",
    )


@then(
    parsers.re(
        r'읽기 화면으로 돌아와 "(?P<message>[^"]+)" 알림이 '
        r'보이고 사이드바에 "(?P<name>[^"]+)"이 있다'
    )
)
def _back_with_toast(world, ctx, message, name):
    assert ctx.response.headers["location"] == "/reader?toast=saved"
    html = world.get(ctx.response.headers["location"]).text
    assert message in html and "data-toast" in html and name in html


@given(parsers.re(r'사이트 "(?P<feed>[^"]+)"에 개별 웹훅이 지정되어 있다'))
def _own_webhook(world, feed):
    existing = [w.id for w in world.parts.settings.list_webhooks()]
    webhook = existing[0] if existing else world.parts.settings.add_webhook("개별", WEBHOOK)
    world.feeds.set_feed_webhook(feed_id(world, feed), webhook)


@given("개별 웹훅이 하나 등록되어 있다")
def _one_webhook(world, ctx):
    ctx.webhook = world.parts.settings.add_webhook("개별", WEBHOOK)


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
    return post(world, f"/feeds/{feed}/settings", **{**data, **override})


@when(
    parsers.re(
        r'사이트 "(?P<feed>[^"]+)"의 설정 패널에서 카테고리 "기술"과 개별 웹훅을 함께 골라 저장한다'
    )
)
def _both(world, ctx, feed):
    ctx.feed = feed_id(world, feed)
    ctx.response = settings_post(
        world, ctx.feed, category_id=str(world.tech), webhook_id=str(ctx.webhook)
    )


@then(parsers.re(r'이유를 알리며 거부되고 사이트 "(?P<feed>[^"]+)"는 아무것도 바뀌지 않는다'))
def _refused_nothing(world, ctx, feed):
    item = world.feeds.get(feed_id(world, feed))
    assert ctx.response.status_code == 400 and "웹훅" in ctx.response.text
    assert (item.category_id, item.webhook_id) == (None, None)


@when(parsers.re(r'사이트 "(?P<feed>[^"]+)"의 설정 패널에서 개별 웹훅만 골라 저장한다'))
def _webhook_only(world, ctx, feed):
    ctx.response = settings_post(world, feed_id(world, feed), webhook_id=str(ctx.webhook))


@then(parsers.re(r'사이트 "(?P<feed>[^"]+)"에는 개별 웹훅이 지정되고 카테고리는 없다'))
def _webhook_set(world, ctx, feed):
    item = world.feeds.get(feed_id(world, feed))
    assert (item.category_id, item.webhook_id) == (None, ctx.webhook)


@then(
    parsers.re(r'사이트 "(?P<feed>[^"]+)"의 피드 주소가 바뀌고 처음부터 다시 점검하는 상태가 된다')
)
def _url_changed(world, feed):
    item = world.feeds.get(feed_id(world, feed))
    assert item.url == "https://new.example.com/feed.xml" and item.last_checked_at is None
    assert item.status == "baseline_pending"


# ---------- 삭제 ----------


DELETE = {
    "feed": "/feeds/{id}/delete",
    "category": "/categories/{id}/delete",
    "topic": "/topics/{id}/delete",
}


@when(parsers.re(r"(?P<kind>피드|카테고리|주제) 삭제 패널의 폼을 확인 없이 보낸다"))
def _delete_unconfirmed(world, ctx, kind):
    ctx.kind = KINDS[kind]
    ctx.item = target_of(world, ctx.kind)
    html = world.client.get(
        f"/panel/delete/{ctx.kind}/{ctx.item}?next=/reader", headers=FRAGMENT
    ).text
    assert f'action="{DELETE[ctx.kind].format(id=ctx.item)}"' in html and 'name="confirm"' in html
    ctx.response = post(world, DELETE[ctx.kind].format(id=ctx.item), next="/reader")


def exists(world, kind, item):
    if kind == "feed":
        return world.feeds.get(item) is not None
    if kind == "category":
        return any(c.id == item for c in world.feeds.list_categories())
    return world.topics.get(item) is not None


@then("아무것도 지워지지 않는다")
def _nothing_deleted(world, ctx):
    assert ctx.response.status_code == 400 and exists(world, ctx.kind, ctx.item)


@when("확인란을 선택해서 보낸다")
def _delete_confirmed(world, ctx):
    ctx.response = post(world, DELETE[ctx.kind].format(id=ctx.item), confirm="yes", next="/reader")


@then(
    parsers.re(
        r'읽기 화면으로 돌아와 "(?P<message>[^"]+)" 알림이 '
        r"보이고 그 (?P<kind>피드|카테고리|주제)은 사라진다"
    )
)
def _deleted(world, ctx, message, kind):
    assert ctx.response.headers["location"] == "/reader?toast=deleted"
    assert message in world.get(ctx.response.headers["location"]).text and not exists(
        world, ctx.kind, ctx.item
    )


@when(parsers.re(r'사이트 "(?P<feed>[^"]+)" 목록에서 그 사이트의 삭제 패널을 연다'))
def _own_list_delete(world, ctx, feed):
    item = feed_id(world, feed)
    ctx.fragment = world.client.get(
        f"/panel/delete/feed/{item}?next=/reader/feed/{item}", headers=FRAGMENT
    )


@then("삭제 후 돌아갈 곳은 전체 글이다")
def _after_is_all(ctx):
    assert 'name="next" value="/reader"' in ctx.fragment.text


@given(parsers.re(r'사이트 "(?P<feed>[^"]+)"에 새 글 "(?P<title>[^"]+)"이 있다'))
def _article(world, ctx, feed, title):
    ctx.ids[title] = world.article(feed_id(world, feed), title=title)


@when(parsers.re(r'카테고리 "(?P<name>[^"]+)"를 확인하고 삭제한다'))
def _delete_category(world, ctx):
    post(world, f"/categories/{world.news}/delete", confirm="yes", next="/reader")


@then(parsers.re(r'사이트 "(?P<feed>[^"]+)"와 글 "(?P<title>[^"]+)"은 남고 카테고리 없이 보인다'))
def _feed_survives(world, ctx, feed, title):
    assert (
        world.feeds.get(world.f_news).category_id is None
        and world.articles.get(ctx.ids[title]) is not None
    )
    assert f"/reader/feed/{world.f_news}" in world.get("/reader").text


# ---------- 순서와 이동 ----------


@when(parsers.re(r'사이트 순서를 "(?P<a>[^"]+)", "(?P<b>[^"]+)"로 저장한다'))
def _save_order(world, a, b):
    assert (
        post(
            world, "/ui/reorder", kind="feed", ids=f"{feed_id(world, a)},{feed_id(world, b)}"
        ).status_code
        == 200
    )


@then(parsers.re(r'사이드바의 RSS 피드는 "(?P<a>[^"]+)", "(?P<b>[^"]+)" 순서다'))
def _order_is(world, a, b):
    assert feed_order(world) == [feed_id(world, a), feed_id(world, b)]


@when("잘못된 순서(없는 번호, 중복, 알 수 없는 종류)를 보낸다")
def _bad_orders(world, ctx):
    ctx.before = feed_order(world)
    ctx.responses = [
        post(world, "/ui/reorder", kind="feed", ids="999"),
        post(world, "/ui/reorder", kind="feed", ids=f"{world.f_news},{world.f_news}"),
        post(world, "/ui/reorder", kind="articles", ids=str(world.f_news)),
    ]


@then("모두 거부되고 순서는 그대로다")
def _all_refused(world, ctx):
    assert all(r.status_code == 400 for r in ctx.responses) and feed_order(world) == ctx.before


@when(parsers.re(r'사이트 "(?P<feed>[^"]+)"를 카테고리 "(?P<category>[^"]+)"로 옮긴다'))
def _move(world, ctx, feed, category):
    target = world.tech if category == "기술" else world.news
    ctx.response = post(
        world, "/ui/move-feed", feed_id=str(feed_id(world, feed)), category_id=str(target)
    )


@when(parsers.re(r'사이트 "(?P<feed>[^"]+)"를 카테고리 없음으로 옮긴다'))
def _move_out(world, ctx, feed):
    ctx.response = post(world, "/ui/move-feed", feed_id=str(feed_id(world, feed)), category_id="")


@then(parsers.re(r'사이트 "(?P<feed>[^"]+)"는 카테고리 "(?P<category>[^"]+)"에 있다'))
def _in_category(world, feed, category):
    assert world.feeds.get(feed_id(world, feed)).category_id == (
        world.tech if category == "기술" else world.news
    )


@then(parsers.re(r'사이트 "(?P<feed>[^"]+)"는 카테고리가 없다'))
def _no_category_now(world, feed):
    assert world.feeds.get(feed_id(world, feed)).category_id is None


@then(parsers.re(r'이유를 알리며 거부되고 사이트 "(?P<feed>[^"]+)"는 카테고리가 없다'))
def _refused_with_reason(world, ctx, feed):
    assert ctx.response.status_code == 400 and ctx.response.text
    assert world.feeds.get(feed_id(world, feed)).category_id is None


# ---------- 설정 탭 ----------


def acc_section(html, name):
    return html.split(f'<details class="acc" id="acc-{name}"')[1].split("</details>")[0]


@when("설정 화면을 연다")
def _open_settings(world, ctx):
    ctx.response = world.get("/settings")


@then(
    parsers.re(
        r'"(?P<shown>[^"]+)"은 "(?P<section>[^"]+)" 구역에 있고 '
        r'"(?P<hidden>[^"]+)"은 그 구역에 없다'
    )
)
def _section_content(ctx, shown, section, hidden):
    body = acc_section(ctx.response.text, section)
    assert shown in body and hidden not in body


@when(parsers.re(r'설정 "(?P<key>[^"]+)"를 "(?P<value>[^"]+)"로 저장한다'))
def _save_setting(world, ctx, key, value):
    ctx.response = post(world, "/settings", next="/settings", **{key: value})


@then(parsers.re(r'설정 화면으로 돌아와 "(?P<message>[^"]+)" 알림이 보인다'))
def _back_to_settings(world, ctx, message):
    assert ctx.response.headers["location"] == "/settings?toast=saved"
    assert message in world.get(ctx.response.headers["location"]).text


@when(parsers.re(r'화면 테마를 "어둡게", 글자 크기를 "크게"로 저장한다'))
def _save_display(world):
    post(world, "/settings", ui_theme="dark", ui_font_size="large")


@then("읽기 화면과 글 페이지와 설정 화면의 틀에 어두운 테마와 큰 글자가 지정된다")
def _display_applied(world):
    article = world.article()
    for path in ("/reader", f"/a/{article}", "/settings"):
        assert 'data-theme="dark" data-font="large"' in world.get(path).text, path


@when(parsers.re(r'목록에 없는 테마 "(?P<theme>[^"]+)"을 저장하려고 한다'))
def _bad_theme(world, ctx, theme):
    ctx.response = post(world, "/settings", ui_theme=theme)


@then("거부되고 테마는 그대로다")
def _theme_unchanged(world, ctx):
    assert ctx.response.status_code == 400 and 'data-theme="dark"' in world.get("/reader").text


# ---------- 보안 ----------


@when(parsers.re(r'돌아갈 곳을 "(?P<next>[^"]+)"로 지정해서 카테고리 추가 패널을 연다'))
def _panel_with_next(world, ctx, next):
    ctx.next = next
    ctx.fragment = world.client.get("/panel/add/category", params={"next": next}, headers=FRAGMENT)


@then(parsers.re(r"패널에는 (?P<result>그 돌아갈 곳 그대로|전체 글로 바뀐 돌아갈 곳)이다"))
def _panel_next(ctx, result):
    expected = ctx.next if result.startswith("그") else "/reader"
    assert (
        f'name="next" value="{expected}"' in ctx.fragment.text
        and "evil.example.com" not in ctx.fragment.text
    )


@when("다른 사이트에서 순서 저장, 피드 이동, 카테고리 삭제 요청을 보낸다")
def _cross_site(world, ctx):
    ctx.before = (feed_order(world), world.feeds.get(world.f_free).category_id)
    cross = {"origin": "https://evil.example.com", "sec-fetch-site": "cross-site"}
    ctx.responses = [
        world.client.post(
            "/ui/reorder",
            data={"kind": "feed", "ids": f"{world.f_free},{world.f_news}"},
            headers=cross,
        ),
        world.client.post(
            "/ui/move-feed",
            data={"feed_id": str(world.f_free), "category_id": str(world.tech)},
            headers=cross,
        ),
        world.client.post(
            f"/categories/{world.news}/delete", data={"confirm": "yes"}, headers=cross
        ),
    ]


@then("모두 거부되고 아무것도 바뀌지 않는다")
def _cross_refused(world, ctx):
    assert all(r.status_code == 403 for r in ctx.responses)
    assert (feed_order(world), world.feeds.get(world.f_free).category_id) == ctx.before
    assert any(c.id == world.news for c in world.feeds.list_categories())
