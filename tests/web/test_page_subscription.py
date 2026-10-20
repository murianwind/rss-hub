"""웹페이지 구독 화면: 추가(후보 확인), 등록, 표시, 주소 고치기, 깨졌을 때의 안내."""

import html as html_module

import pytest

from rss_hub.storage.feeds import KIND_FEED, KIND_PAGE, STATUS_ACTIVE, STATUS_BASELINE
from tests.fakes.discovery_fetcher import FakeDiscoveryFetcher
from tests.fakes.page_html import BASE, listing, sample_items
from tests.fakes.viewer_world import World
from tests.fakes.web_parts import start_app

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


def post(world, path, **data):
    return world.client.post(path, data=data, headers=BROWSER)


def serve_list(world, count=4, url=LIST_URL):
    world.fetcher.page(url, listing(sample_items(count)))


def add_page_feed(world, *, status=STATUS_ACTIVE):
    return world.feeds.add(
        LIST_URL, "예제 블로그", kind=KIND_PAGE, status=status, html_url=f"{BASE}/"
    )


# ---------- 추가: 후보 확인 ----------


def test_the_add_panel_offers_a_web_page_subscription_with_a_preview_of_the_found_posts(world):
    serve_list(world)
    response = post(world, "/feeds/discover", url=LIST_URL, next="/feeds")
    html = response.text
    assert (
        response.status_code == 200
        and "웹페이지 구독" in html
        and 'name="kind" value="page"' in html
    )
    assert (
        "글 4개를 찾았습니다" in html
        and "새 소식 1번" in html
        and "새 소식 3번" in html
        and "새 소식 4번" not in html
    )  # 예시는 앞의 3개
    assert "피드 상태 점이 빨갛게 바뀝니다" in html and "RSS 피드를 제공하지 않아" in html


def test_a_found_feed_is_offered_as_a_feed_without_the_web_page_wording(world):
    world.fetcher.feed("https://new.example.com/rss", "새 블로그", "https://new.example.com")
    html = post(world, "/feeds/discover", url="https://new.example.com/rss", next="/feeds").text
    assert 'name="kind" value="feed"' in html and "웹페이지 구독" not in html.split("찾은 피드")[1]


def test_a_page_with_too_few_posts_gives_the_usual_nothing_found_message(world):
    serve_list(world, count=2)
    response = post(world, "/feeds/discover", url=LIST_URL, next="/feeds")
    assert response.status_code == 400 and "이 주소에서 피드를 찾지 못했습니다" in response.text


def test_the_add_panel_tells_how_to_subscribe_to_sites_without_rss(world):
    html = world.client.get("/panel/add/feed", headers={"x-panel": "1"}).text
    assert "RSS가 없는 사이트는 글 목록 페이지 주소를 넣으면 웹페이지로 구독할 수 있습니다" in html


# ---------- 등록 ----------


def test_registering_the_found_web_page_saves_a_page_feed_that_starts_with_a_baseline(world):
    serve_list(world)
    response = post(
        world,
        "/feeds/register",
        url=LIST_URL,
        kind="page",
        name="",
        category_id="",
        webhook_id="",
        next="/feeds",
    )
    assert response.status_code == 303 and response.headers["location"] == "/feeds?toast=added"
    saved = next(f for f in world.feeds.list_all() if f.url == LIST_URL)
    assert (saved.kind, saved.status, saved.html_url, saved.name) == (
        KIND_PAGE,
        STATUS_BASELINE,
        f"{BASE}/",
        "예제 블로그 - 소식",
    )


def test_registering_a_page_without_posts_is_refused_and_nothing_is_saved(world):
    world.fetcher.page(LIST_URL, "<html><body><p>글 없음</p></body></html>")
    before = len(world.feeds.list_all())
    response = post(world, "/feeds/register", url=LIST_URL, kind="page", name="", next="/feeds")
    assert response.status_code == 400 and "글 목록을 찾지 못했습니다" in response.text
    assert len(world.feeds.list_all()) == before


def test_an_unknown_kind_value_is_treated_as_a_regular_feed(world):
    world.fetcher.feed("https://new.example.com/rss", "새 블로그", "https://new.example.com")
    post(
        world,
        "/feeds/register",
        url="https://new.example.com/rss",
        kind="bogus",
        name="",
        next="/feeds",
    )
    assert (
        next(f for f in world.feeds.list_all() if f.url == "https://new.example.com/rss").kind
        == KIND_FEED
    )


# ---------- 표시와 깨졌을 때의 안내 ----------


def row(html, name):
    rows = html.split('<li class="feed-row">')[1:]
    return html_module.unescape(next(r for r in rows if name in r.split("</li>")[0]))


def test_the_feed_management_page_marks_web_page_subscriptions(world):
    add_page_feed(world)
    html = world.get("/feeds").text
    assert "웹페이지</span>" in row(html, "예제 블로그") and "웹페이지</span>" not in row(
        html, "자유 블로그"
    )


def test_a_broken_list_shows_a_red_dot_and_a_plain_language_reason(world):
    feed = add_page_feed(world)
    world.feeds.record_failure(feed, "NoItems")
    html = world.get("/feeds").text
    assert FAIL_TEXT in row(html, "예제 블로그") and "NoItems" not in row(html, "예제 블로그")
    assert (
        world.get("/ui/state").json()["feeds"][str(feed)]["state"] == "error"
    )  # 사이드바의 빨간 점


def test_other_failure_reasons_are_shown_as_they_are(world):
    feed = add_page_feed(world)
    world.feeds.record_failure(feed, "ReadTimeout")
    assert "ReadTimeout" in row(world.get("/feeds").text, "예제 블로그")


def test_the_force_refresh_reads_the_list_like_any_feed(world):
    feed = add_page_feed(world, status=STATUS_BASELINE)
    serve_list(world)
    response = post(world, f"/feeds/{feed}/refresh")
    assert response.status_code == 200 and world.feeds.get(feed).status == STATUS_ACTIVE
    world.fetcher.errors[LIST_URL] = "ReadTimeout"
    post(world, f"/feeds/{feed}/refresh")
    assert world.feeds.get(feed).last_error == "ReadTimeout"


# ---------- 주소 고치기(구조가 바뀌었을 때) ----------


def settings_post(world, feed, **fields):
    data = {
        "name": "예제 블로그",
        "emoji": "📢",
        "max_entries": "",
        "category_id": "",
        "webhook_id": "",
        "next": "/feeds",
    } | fields
    return post(world, f"/feeds/{feed}/settings", **data)


def test_fixing_the_address_checks_that_the_new_page_has_a_post_list(world):
    feed = add_page_feed(world)
    new = f"{BASE}/new-news"
    world.fetcher.page(new, listing(sample_items(4), section="/new-news"))
    assert settings_post(world, feed, url=new).status_code == 303
    saved = world.feeds.get(feed)
    assert (saved.url, saved.status, saved.kind, saved.html_url) == (
        new,
        STATUS_BASELINE,
        KIND_PAGE,
        f"{BASE}/",
    )  # 처음부터 다시 점검


def test_a_new_address_without_a_post_list_is_refused_and_nothing_changes(world):
    feed = add_page_feed(world)
    world.fetcher.page(f"{BASE}/empty", "<html><body><p>글 없음</p></body></html>")
    response = settings_post(world, feed, name="바뀌면 안 됨", url=f"{BASE}/empty")
    assert (
        response.status_code == 400
        and "새 목록 페이지 주소를 확인하지 못했습니다: 글 목록을 찾지 못했습니다" in response.text
    )
    assert (world.feeds.get(feed).name, world.feeds.get(feed).url) == ("예제 블로그", LIST_URL)


def test_a_new_address_that_cannot_be_opened_gives_the_reason(world):
    feed = add_page_feed(world)
    world.fetcher.fail(f"{BASE}/down", "ReadTimeout")
    assert "시간 초과" in settings_post(world, feed, url=f"{BASE}/down").text


def test_a_regular_feed_still_gets_the_feed_wording_when_its_new_address_is_bad(world):
    world.fetcher.fail("https://new.example.com/rss", "NotAFeed")
    response = settings_post(
        world, world.f_free, name="자유 블로그", url="https://new.example.com/rss"
    )
    assert (
        "새 피드 주소를 확인하지 못했습니다" in response.text and "목록 페이지" not in response.text
    )


def test_the_settings_panel_names_the_address_for_the_kind_of_subscription(world):
    feed = add_page_feed(world)
    page_html = world.client.get(f"/panel/settings/feed/{feed}", headers={"x-panel": "1"}).text
    rss_html = world.client.get(
        f"/panel/settings/feed/{world.f_free}", headers={"x-panel": "1"}
    ).text
    assert (
        "목록 페이지 주소" in page_html
        and "글 목록이 보이는지 확인" in page_html
        and "피드 주소" not in page_html
    )
    assert "피드 주소" in rss_html and "목록 페이지 주소" not in rss_html


# ---------- 내보내기 ----------


def test_opml_export_leaves_out_web_page_subscriptions_because_they_are_not_feeds(world):
    add_page_feed(world)
    opml = world.client.get("/feeds/export.opml").text
    assert LIST_URL not in opml and "자유 블로그" in opml
