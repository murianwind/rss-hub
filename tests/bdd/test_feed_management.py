"""11_feed_management.feature: 개별 등록, 자동 탐색, 편집, 삭제, OPML 내보내기."""

import html
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from urllib.parse import urljoin

import pytest
from pytest_bdd import given, parsers, then, when

from rss_hub.domain.importing import parse_import_file
from rss_hub.domain.routing import PRIMARY, Target
from rss_hub.storage.articles import ArticleRepository, NewArticle
from rss_hub.storage.deliveries import DeliveryRepository
from rss_hub.storage.feeds import FeedRepository
from tests.bdd.binding import bind
from tests.fakes.discovery_fetcher import FakeDiscoveryFetcher
from tests.fakes.web_parts import start_app

bind(globals(), "11_feed_management.feature", [f"FED-{n:02d}" for n in range(1, 15)])

TOKENS = {"(빈 값)": "", "(201자)": "가" * 201}
SECRET_URL = "https://discord.com/api/webhooks/777/SECRETFEEDTOKEN"


@pytest.fixture
def world(tmp_path):
    fetcher = FakeDiscoveryFetcher()
    parts, client = start_app(tmp_path, feed_fetcher=fetcher)
    with client:
        parts.fetcher = fetcher
        parts.feeds = FeedRepository(parts.db, parts.clock)
        parts.articles = ArticleRepository(parts.db, parts.clock)
        parts.response = None
        parts.before = None
        parts.category_ids, parts.webhook_ids = {}, {}
        parts.page = None
        yield parts


def feed_named(world, name):
    return next(f for f in world.feeds.list_all() if f.name == name)


def text_of(response):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", response.text))


def candidates(world):
    """확인 결과 화면의 등록 후보: (제목, 주소) 목록."""
    forms = re.findall(
        r'<form method="post" action="/feeds/register"[^>]*>(.*?)</form>', world.response.text, re.S
    )
    found = []
    for form in forms:
        title = html.unescape(
            re.search(r'class="cand-title">(.*?) <span class="kind-badge">', form, re.S).group(1)
        )
        url = html.unescape(re.search(r'name="url" value="([^"]*)"', form).group(1))
        found.append((title, url))
    return found


def category_id(world, name):
    return world.feeds.get_or_create_category(name)[0]


# ---------- 배경 ----------


@given(parsers.re(r'구독 목록에 주소 "(?P<url>[^"]+)"의 피드 "(?P<name>[^"]+)"가 있다'))
def _existing_feed(world, url, name):
    world.feeds.add(url, name)


# ---------- 개별 등록 ----------


@given(parsers.re(r'주소 "(?P<url>[^"]+)"는 제목이 "(?P<title>[^"]+)"인 피드다'))
def _feed_with_title(world, url, title):
    world.fetcher.feed(url, title)


@given(
    parsers.re(
        r'주소 "(?P<url>[^"]+)"는 피드 "(?P<a>[^"]+)"과 "(?P<b>[^"]+)"을 알려 주는 웹페이지다'
    )
)
def _page_with_two_feeds(world, url, a, b):
    links = "".join(
        f'<link rel="alternate" type="application/rss+xml" href="{href}">' for href in (a, b)
    )
    world.fetcher.page(url, f"<html><head>{links}</head></html>")
    world.page = (url, a, b)


@given(parsers.re(r'두 피드는 각각 "(?P<a>[^"]+)"과 "(?P<b>[^"]+)"이라는 제목의 올바른 피드다'))
def _two_valid_feeds(world, a, b):
    base, first, second = world.page
    world.fetcher.feed(urljoin(base, first), a)
    world.fetcher.feed(urljoin(base, second), b)


SITUATIONS = "피드 링크가 없는 웹페이지|HTTP 404|연결 실패"


@given(parsers.re(rf'주소 "(?P<url>[^"]+)"의 응답은 (?P<situation>{SITUATIONS})이?다'))
def _response_situation(world, url, situation):
    if situation == "피드 링크가 없는 웹페이지":
        world.fetcher.page(url, "<html><body>피드 링크 없음</body></html>")
    elif situation == "HTTP 404":
        world.fetcher.fail(url, "HTTP 404")
    else:
        world.fetcher.fail(url, "ConnectionError")


@when(parsers.re(r'주소 "(?P<url>[^"]+)"를 확인한다'))
def _discover(world, url):
    world.response = world.client.post("/feeds/discover", data={"url": url})


@then(parsers.re(r'등록 후보로 "(?P<title>[^"]+)"가 표시된다'))
def _one_candidate(world, title):
    assert [t for t, _ in candidates(world)] == [title]


@then(parsers.re(r'등록 후보로 "(?P<a>[^"]+)"과 "(?P<b>[^"]+)"이 표시된다'))
def _two_candidates(world, a, b):
    assert [t for t, _ in candidates(world)] == [a, b]


@then(parsers.re(r'후보의 주소는 전체 주소 "(?P<a>[^"]+)"과 "(?P<b>[^"]+)"이다'))
def _candidate_addresses(world, a, b):
    assert [u for _, u in candidates(world)] == [a, b]


@when(parsers.re(r'후보 "(?P<title>[^"]+)"를 등록한다'))
def _register_candidate(world, title):
    url = next(u for t, u in candidates(world) if t == title)
    world.response = world.client.post(
        "/feeds/register", data={"url": url, "name": title, "category_id": "", "webhook_id": ""}
    )


@then(parsers.re(r'피드 "(?P<name>[^"]+)"가 "(?P<status>[^"]+)" 상태로 등록된다'))
def _registered_with_status(world, name, status):
    assert world.response.status_code == 303
    assert feed_named(world, name).status == status


@then(parsers.re(r'오류 "(?P<message>[^"]+)"가 표시된다'))
def _error_shown(world, message):
    assert message in text_of(world.response) and 'class="banner error"' in world.response.text


@then("외부로는 어떤 요청도 나가지 않는다")
def _no_requests(world):
    assert world.fetcher.fetch_calls == [] and world.fetcher.page_calls == []


# ---------- 카테고리와 웹훅 ----------


@given(parsers.re(r'카테고리 "(?P<category>[^"]+)"와 웹훅 "(?P<webhook>[^"]+)"가 있다'))
def _category_and_webhook(world, category, webhook):
    world.category_ids[category] = world.feeds.add_category(category)
    world.webhook_ids[webhook] = world.settings.add_webhook(webhook, SECRET_URL)


REGISTER_BOTH = (
    r'주소 "(?P<url>[^"]+)"를 카테고리 "(?P<category>[^"]+)"와 '
    r'웹훅 "(?P<webhook>[^"]+)"로 등록한다'
)


@when(parsers.re(REGISTER_BOTH))
def _register_with_both(world, url, category, webhook):
    world.response = world.client.post(
        "/feeds/register",
        data={
            "url": url,
            "name": "",
            "category_id": str(world.category_ids[category]),
            "webhook_id": str(world.webhook_ids[webhook]),
        },
    )


@when(parsers.re(r'주소 "(?P<url>[^"]+)"를 카테고리 "(?P<category>[^"]+)"로 등록한다'))
def _register_with_category(world, url, category):
    world.response = world.client.post(
        "/feeds/register",
        data={
            "url": url,
            "name": "",
            "category_id": str(world.category_ids[category]),
            "webhook_id": "",
        },
    )


@then(parsers.re(r'오류 "(?P<message>[^"]+)"이 표시되고 피드는 등록되지 않는다'))
def _error_and_nothing_saved(world, message):
    assert message in text_of(world.response)
    assert [f.name for f in world.feeds.list_all()] == ["이미 있는 피드"]


@then(parsers.re(r'피드 "(?P<name>[^"]+)"가 카테고리 "(?P<category>[^"]+)"에 속한다'))
def _feed_in_category(world, name, category):
    assert feed_named(world, name).category_id == world.category_ids[category]


# ---------- 등록 직전 재확인 ----------


@when(parsers.re(r'주소 "(?P<url>[^"]+)"를 확인 없이 바로 등록한다'))
def _register_directly(world, url):
    world.response = world.client.post(
        "/feeds/register", data={"url": url, "name": "", "category_id": "", "webhook_id": ""}
    )


@then(parsers.re(r'오류 "(?P<message>[^"]+)"가 표시되고 피드는 등록되지 않는다'))
def _error_and_not_registered(world, message):
    assert message in text_of(world.response)
    assert [f.name for f in world.feeds.list_all()] == ["이미 있는 피드"]


# ---------- 편집 ----------


EDIT = (
    r'피드 "(?P<feed>[^"]+)"를 이름 "(?P<name>[^"]*)", 이모지 "(?P<emoji>[^"]*)", '
    r'우선순위 "(?P<priority>[^"]*)", 최대 "(?P<maximum>[^"]*)"으로 저장한다'
)


@when(parsers.re(EDIT))
def _edit(world, feed, name, emoji, priority, maximum):
    target = feed_named(world, feed)
    world.before = target
    world.response = world.client.post(
        f"/feeds/{target.id}/edit",
        data={
            "name": TOKENS.get(name, name),
            "emoji": TOKENS.get(emoji, emoji),
            "priority": priority,
            "max_entries": maximum,
        },
    )


EDITED_VALUES = (
    r'피드 "(?P<name>[^"]+)"의 값은 이모지 "(?P<emoji>[^"]+)", '
    r'우선순위 "(?P<priority>[^"]+)", 최대 (?P<maximum>\d+)이다'
)


@then(parsers.re(EDITED_VALUES))
def _edited_values(world, name, emoji, priority, maximum):
    feed = feed_named(world, name)
    assert (feed.emoji, feed.poll_priority, feed.max_entries) == (emoji, priority, int(maximum))


@when(parsers.re(r'피드 "(?P<name>[^"]+)"의 최대 검사 항목 수를 비워서 저장한다'))
def _clear_max(world, name):
    feed = feed_named(world, name)
    world.client.post(
        f"/feeds/{feed.id}/edit",
        data={
            "name": feed.name,
            "emoji": feed.emoji,
            "priority": feed.poll_priority,
            "max_entries": "",
        },
    )


@then(parsers.re(r'피드 "(?P<name>[^"]+)"의 최대 검사 항목 수는 기본값을 쓴다'))
def _default_max(world, name):
    assert feed_named(world, name).max_entries is None


@then(parsers.re(r'피드 "(?P<name>[^"]+)"는 바뀌지 않았다'))
def _unchanged(world, name):
    assert feed_named(world, name) == world.before


# ---------- 삭제 ----------


@given(parsers.re(r'피드 "(?P<name>[^"]+)"에 글 2개와 발송 기록이 있다'))
def _feed_with_articles(world, name):
    feed = feed_named(world, name)
    webhook_id = world.settings.add_webhook("기록용", SECRET_URL)
    world.guids = []
    for number in (1, 2):
        guid = f"guid-{number}"
        article_id = world.articles.add(
            NewArticle(
                feed.id,
                guid,
                f"제목 {number}",
                f"https://x.example.com/{number}",
                "본문",
                "",
                datetime(2026, 10, 16, 5, 0, tzinfo=UTC),
                "2026-10-16",
            )
        )
        world.guids.append(guid)
        if number == 1:
            DeliveryRepository(world.db, world.clock).ensure(
                article_id, [Target(webhook_id, PRIMARY)]
            )


@when(parsers.re(r'피드 "(?P<name>[^"]+)"를 삭제를 확인하고 지운다'))
def _delete_confirmed(world, name):
    world.response = world.client.post(
        f"/feeds/{feed_named(world, name).id}/delete", data={"confirm": "yes"}
    )


@when(parsers.re(r'피드 "(?P<name>[^"]+)"를 확인 없이 삭제 요청한다'))
def _delete_unconfirmed(world, name):
    world.response = world.client.post(f"/feeds/{feed_named(world, name).id}/delete", data={})


def count(world, table):
    with world.db.connect() as conn:
        return conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]


@then("피드, 글, 발송 기록이 모두 사라진다")
def _everything_gone(world):
    assert (
        world.feeds.list_all() == []
        and count(world, "articles") == 0
        and count(world, "deliveries") == 0
    )


@then('지워진 글의 "이미 본 글" 기록은 남아 있다')
def _seen_stays(world):
    assert all(world.articles.is_seen(guid) for guid in world.guids)


@then(parsers.re(r'오류 "(?P<message>[^"]+)"가 표시된다'))
def _delete_error(world, message):
    assert message in text_of(world.response)


@then("피드와 글은 그대로 남아 있다")
def _still_there(world):
    assert [f.name for f in world.feeds.list_all()] == ["이미 있는 피드"] and count(
        world, "articles"
    ) == 2


# ---------- 내보내기 ----------


CATEGORY_FEED = (
    r'카테고리 "(?P<category>[^"]+)"에 속한 피드 "(?P<name>[^"]+)"'
    r'\(사이트 "(?P<site>[^"]+)"\)가 있다'
)


@given(parsers.re(CATEGORY_FEED))
def _category_feed_with_site(world, category, name, site):
    world.feeds.add(
        f"https://{name.encode().hex()}.example.com/rss",
        name,
        html_url=site,
        category_id=category_id(world, category),
    )


@given(parsers.re(r'피드 "(?P<name>[^"]+)"에 웹훅 "(?P<webhook>[^"]+)"이 지정되어 있다'))
def _feed_with_webhook(world, name, webhook):
    webhook_id = world.settings.add_webhook(webhook, SECRET_URL)
    world.feeds.set_feed_webhook(feed_named(world, name).id, webhook_id)


@when("OPML로 내보낸다")
def _export(world):
    world.response = world.client.get("/feeds/export.opml")


@then("파일로 내려받는 응답이다")
def _is_download(world):
    headers = world.response.headers
    assert (
        "attachment" in headers["content-disposition"] and ".opml" in headers["content-disposition"]
    )
    assert headers["content-type"].startswith("text/x-opml")


def exported(world):
    return {e.name: e for e in parse_import_file("export.opml", world.response.content)}


@then(
    parsers.re(
        r'폴더 "(?P<folder>[^"]+)" 아래에 "(?P<name>[^"]+)"의 이름, 피드 주소, 사이트 주소가 있다'
    )
)
def _folder_entry(world, folder, name):
    entry = exported(world)[name]
    assert (
        entry.category == folder
        and entry.url.startswith("https://")
        and entry.html_url == "https://news.example.com"
    )


@then(parsers.re(r'카테고리가 없는 "(?P<name>[^"]+)"는 폴더 밖에 있다'))
def _outside_folders(world, name):
    assert exported(world)[name].category is None


@then("웹훅 주소나 웹훅 이름은 파일에 없다")
def _no_webhook_in_file(world):
    body = world.response.text
    assert "시험웹훅" not in body and "SECRETFEEDTOKEN" not in body and "discord.com" not in body


@when("OPML로 내보낸 파일을 가져오기 미리보기에 올린다")
def _export_then_import(world):
    exported_file = world.client.get("/feeds/export.opml").content
    world.response = world.client.post(
        "/import/preview", files={"file": ("rss-hub-subscriptions.opml", exported_file)}
    )


@then("미리보기는 신규 0개, 중복 2개, 오류 0개다")
def _round_trip(world):
    assert (
        "신규 <strong>0</strong> · 중복 <strong>2</strong> · 오류 <strong>0</strong>"
        in world.response.text
    )


@given(parsers.re(r'피드 "(?P<name>[^"]+)"가 있다'))
def _feed_with_special_name(world, name):
    world.feeds.add("https://special.example.com/rss", name)
    world.special = name


@then("파일은 올바른 XML이고 스크립트로 해석될 내용은 없다")
def _valid_xml(world):
    ET.fromstring(world.response.content)  # 올바른 XML이어야 예외가 나지 않는다
    assert "<b>" not in world.response.text and "&lt;b&gt;" in world.response.text


@then("그 파일을 다시 가져오면 이름이 그대로다")
def _name_survives(world):
    assert world.special in exported(world)
