"""웹페이지 구독 화면: 추가(후보 확인), 등록, 표시, 주소 고치기, 깨졌을 때의 안내."""

import html as html_module
import re

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
        and "새 주소를 확인하지 못했습니다: 글 목록을 찾지 못했습니다" in response.text
    )
    assert (world.feeds.get(feed).name, world.feeds.get(feed).url) == ("예제 블로그", LIST_URL)


def test_a_new_address_that_cannot_be_opened_gives_the_reason(world):
    feed = add_page_feed(world)
    world.fetcher.fail(f"{BASE}/down", "ReadTimeout")
    assert "시간 초과" in settings_post(world, feed, url=f"{BASE}/down").text


def test_a_bad_new_address_of_a_regular_feed_gives_the_same_message(world):
    world.fetcher.fail("https://new.example.com/rss", "NotAFeed")
    response = settings_post(world, world.f_free, url="https://new.example.com/rss")
    assert "새 주소를 확인하지 못했습니다" in response.text and "피드가 아닙니다" in response.text


def test_the_settings_panel_names_the_address_for_the_kind_of_subscription(world):
    feed = add_page_feed(world)
    page_html = world.client.get(f"/panel/settings/feed/{feed}", headers={"x-panel": "1"}).text
    rss_html = world.client.get(
        f"/panel/settings/feed/{world.f_free}", headers={"x-panel": "1"}
    ).text
    assert 'for="p_furl">목록 페이지 주소' in page_html
    assert "글 목록 페이지(웹페이지 구독)로 확인합니다" in page_html
    assert 'for="p_furl">피드 주소' in rss_html and 'for="p_furl">목록 페이지 주소' not in rss_html


# ---------- 내보내기 ----------


def test_opml_export_leaves_out_web_page_subscriptions_because_they_are_not_feeds(world):
    add_page_feed(world)
    opml = world.client.get("/feeds/export.opml").text
    assert LIST_URL not in opml and "자유 블로그" in opml


# ---------- 주소로 종류를 판정해 고친다(RSS가 있으면 피드, 없으면 웹페이지 구독) ----------


def test_a_regular_feed_edited_to_a_post_list_without_rss_becomes_a_web_page_subscription(world):
    serve_list(world)
    assert settings_post(world, world.f_free, name="자유 블로그", url=LIST_URL).status_code == 303
    saved = world.feeds.get(world.f_free)
    assert (saved.kind, saved.url, saved.status, saved.html_url) == (
        KIND_PAGE,
        LIST_URL,
        STATUS_BASELINE,
        f"{BASE}/",
    )


def test_a_web_page_subscription_edited_to_a_feed_address_becomes_a_regular_feed(world):
    feed = add_page_feed(world)
    world.fetcher.feed("https://blog.example.com/feed.xml", "공식 피드", "https://blog.example.com")
    assert settings_post(world, feed, url="https://blog.example.com/feed.xml").status_code == 303
    saved = world.feeds.get(feed)
    assert (saved.kind, saved.url, saved.status) == (
        KIND_FEED,
        "https://blog.example.com/feed.xml",
        STATUS_BASELINE,
    )


def test_a_page_that_advertises_feeds_is_refused_so_the_user_picks_the_feed(world):
    serve_list(world)
    advertised = '<head><link rel="alternate" type="application/rss+xml" href="https://blog.example.com/feed.xml">'
    world.fetcher.page(LIST_URL, world.fetcher.pages[LIST_URL].replace("<head>", advertised))
    response = settings_post(world, world.f_free, url=LIST_URL)
    assert response.status_code == 400 and "버튼으로 찾아서 고르세요" in response.text
    assert (
        world.feeds.get(world.f_free).kind == KIND_FEED
        and world.feeds.get(world.f_free).url != LIST_URL
    )


def test_saving_a_web_page_subscription_without_a_new_address_does_not_fetch_anything(world):
    feed = add_page_feed(world)
    assert settings_post(world, feed, name="이름만 바꿈", url=LIST_URL).status_code == 303
    assert world.fetcher.page_calls == [] and world.fetcher.fetch_calls == []
    assert world.feeds.get(feed).kind == KIND_PAGE


# ---------- 주소 칸 옆 "변경" 버튼: 후보를 찾아 고른다 ----------


def pick(world, url):
    return post(world, "/feeds/discover", url=url, pick="1", next="/feeds")


def test_the_pick_mode_returns_only_a_fragment_with_a_select_button_per_candidate(world):
    world.fetcher.feed("https://new.example.com/rss", "새 블로그", "https://new.example.com")
    response = pick(world, "https://new.example.com/rss")
    html = response.text
    assert response.status_code == 200 and "<html" not in html and "<form" not in html
    assert (
        'data-pick-url="https://new.example.com/rss"' in html
        and ">선택</button>" in html
        and "새 블로그" in html
    )
    assert (
        'name="category_id"' not in html and 'name="webhook_id"' not in html and "등록" not in html
    )  # 이름, 카테고리, 웹훅, 등록 칸은 없다


def test_the_pick_mode_offers_a_web_page_subscription_when_there_is_no_rss(world):
    serve_list(world)
    html = pick(world, LIST_URL).text
    assert (
        'data-pick-url="' + LIST_URL + '"' in html
        and "웹페이지 구독" in html
        and "글 4개를 찾았습니다" in html
        and "새 소식 1번" in html
    )


def test_the_pick_mode_shows_the_error_in_the_fragment_and_registers_nothing(world):
    serve_list(world, count=2)
    before = len(world.feeds.list_all())
    response = pick(world, LIST_URL)
    assert (
        response.status_code == 200
        and "이 주소에서 피드를 찾지 못했습니다" in response.text
        and "data-pick-url" not in response.text
    )
    assert len(world.feeds.list_all()) == before


def test_the_pick_mode_also_refuses_an_address_that_is_already_subscribed(world):
    response = pick(world, world.feeds.get(world.f_free).url)
    assert response.status_code == 200 and "이미 구독 중" in response.text


def test_the_settings_panel_has_the_change_button_and_the_finder(world):
    html = world.client.get(f"/panel/settings/feed/{world.f_free}", headers={"x-panel": "1"}).text
    button = r"<button type=\"button\" class=\"button\" data-finder-open>변경</button>"
    assert re.search(r'<input id="p_furl" name="url"[^>]*>\s*' + button, html)
    assert "피드 주소 변경" in html and "data-finder-run" in html and "data-finder-close" in html
    assert "data-finder-results" in html and re.search(
        r'<input id="p_find" data-finder-input', html
    )
    assert 'name="p_find"' not in html  # 찾기 칸은 저장 값에 섞이지 않는다(name이 없다)


def test_the_script_runs_the_finder_with_the_add_flow_and_fills_the_address(world):
    js = world.client.get("/static/app.js").text
    assert 'post("/feeds/discover", { url: address, pick: "1"' in js and "[data-pick-url]" in js
    assert 'field.querySelector("input[name=url]").value = picked' in js
    assert (
        'event.key !== "Enter"' in js
        and "event.preventDefault()" in js.split('event.key !== "Enter"')[1]
    )


def test_the_style_puts_the_change_button_next_to_the_address_input(world):
    css = world.client.get("/static/app.css").text
    assert (
        ".input-row { display: flex;" in css and ".finder {" in css and ".candidate.pick {" in css
    )


# ---------- 목록 안 스크롤 기억 ----------


def test_the_script_remembers_the_scroll_inside_each_sidebar_list_and_shows_the_selected_row(world):
    js = world.client.get("/static/app.js").text
    assert (
        'var LISTS = ["sec-rss", "sec-categories", "sec-topics"];' in js
        and "lists: listScrolls()" in js
    )
    assert "body.scrollTop = saved.lists[id]" in js
    assert "if (body) showCurrent(body);" in js and "[aria-current=page]" in js
