"""구독 관리 화면(M2): 개별 등록, 편집, 삭제, 내보내기."""

import re
from datetime import UTC, datetime

import pytest

from rss_hub.storage.articles import ArticleRepository, NewArticle
from rss_hub.storage.feeds import FeedRepository
from tests.fakes.discovery_fetcher import FakeDiscoveryFetcher
from tests.fakes.web_parts import start_app

BROWSER = {"origin": "null", "sec-fetch-site": "same-origin"}


@pytest.fixture
def world(tmp_path):
    fetcher = FakeDiscoveryFetcher()
    parts, client = start_app(tmp_path, feed_fetcher=fetcher)
    with client:
        parts.fetcher = fetcher
        parts.feeds = FeedRepository(parts.db, parts.clock)
        parts.articles = ArticleRepository(parts.db, parts.clock)
        yield parts


# ---------- 등록 ----------


def test_the_page_has_no_add_form_but_links_to_import_export_and_categories(world):
    html = world.client.get("/feeds").text
    assert 'action="/feeds/discover"' not in html and 'action="/feeds/register"' not in html
    assert (
        'href="/feeds/export.opml"' in html
        and 'href="/import"' in html
        and 'href="/categories"' in html
    )
    assert "사이드바의 RSS 피드 <b>+</b>" in html  # 추가는 사이드바의 +에서 한다


def test_a_feed_address_shows_the_title_in_an_editable_registration_form(world):
    world.fetcher.feed("https://new.example.com/rss", "새 블로그", "https://new.example.com")
    html = world.client.post("/feeds/discover", data={"url": "https://new.example.com/rss"}).text
    assert (
        'class="cand-title">새 블로그' in html
        and 'name="url" value="https://new.example.com/rss"' in html
    )
    assert 'name="name" value="새 블로그"' in html and 'action="/feeds/register"' in html


def test_the_typed_address_is_kept_in_the_form_after_an_error(world):
    response = world.client.post("/feeds/discover", data={"url": "http://192.168.0.10/rss"})
    assert response.status_code == 400 and 'value="http://192.168.0.10/rss"' in response.text
    assert "사설망·내부 주소는 허용하지 않음" in response.text


def test_registering_redirects_with_a_notice_that_explains_the_first_check(world):
    world.fetcher.feed("https://new.example.com/rss", "새 블로그")
    response = world.client.post(
        "/feeds/register",
        data={
            "url": "https://new.example.com/rss",
            "name": "",
            "category_id": "",
            "webhook_id": "",
        },
    )
    assert response.status_code == 303 and response.headers["location"] == "/feeds?added=1"
    notice = world.client.get("/feeds?added=1").text
    assert "새 글부터 알림이 갑니다" in notice and "새 블로그" in notice


def test_a_failed_registration_keeps_the_address_and_says_why(world):
    world.fetcher.fail("https://x.example.com/rss", "HTTP 404")
    response = world.client.post("/feeds/register", data={"url": "https://x.example.com/rss"})
    assert response.status_code == 400 and "주소를 열지 못했습니다(HTTP 404)" in response.text
    assert world.feeds.list_all() == []


def test_titles_and_addresses_from_other_sites_are_escaped(world):
    world.fetcher.feed(
        "https://new.example.com/rss", "<script>alert(1)</script>", '"><img src=x onerror=alert(1)>'
    )
    html = world.client.post("/feeds/discover", data={"url": "https://new.example.com/rss"}).text
    assert (
        "<script>alert(1)</script>" not in html
        and "<img src=x" not in html
        and "&lt;script&gt;" in html
    )


def test_a_very_long_address_is_refused_before_any_request(world):
    response = world.client.post(
        "/feeds/discover", data={"url": "https://a.example.com/" + "x" * 6000}
    )
    assert response.status_code == 400 and "주소가 너무 김" in response.text
    assert world.fetcher.fetch_calls == [] and world.fetcher.page_calls == []


# ---------- 편집 ----------


def add_feed(world, name="블로그"):
    return world.feeds.add("https://f.example.com/rss", name)


def test_the_settings_panel_shows_the_current_values_and_the_default_for_max(world):
    feed_id = add_feed(world)
    html = world.client.get(f"/panel/settings/feed/{feed_id}", headers={"x-panel": "1"}).text
    assert f'action="/feeds/{feed_id}/settings"' in html and 'name="emoji" value="📢"' in html
    assert "비워 두면 기본값 50" in html


def test_a_valid_edit_is_saved_and_shown(world):
    feed_id = add_feed(world)
    response = world.client.post(
        f"/feeds/{feed_id}/edit",
        data={"name": "새 이름", "emoji": "🧪", "priority": "every_slot", "max_entries": "120"},
    )
    assert response.status_code == 303
    html = world.client.get("/feeds").text
    assert "새 이름" in html and "🧪" in html and "점검할 최대 항목 수 120" in html


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"name": ""}, "이름이 필요함"),
        ({"emoji": ""}, "머리말 이모지가 필요함"),
        ({"priority": "high"}, "점검 우선순위는 보통 또는 매 슬롯"),
        ({"max_entries": "0"}, "최대 검사 항목 수는 1~500 사이의 숫자"),
    ],
)
def test_an_invalid_edit_is_refused_and_nothing_changes(world, data, message):
    feed_id = add_feed(world)
    form = {"name": "블로그", "emoji": "📢", "priority": "normal", "max_entries": ""} | data
    response = world.client.post(f"/feeds/{feed_id}/edit", data=form)
    assert response.status_code == 400 and message in response.text
    assert world.feeds.get(feed_id).name == "블로그"


def test_editing_an_unknown_feed_gives_404(world):
    data = {"name": "x", "emoji": "📢", "priority": "normal", "max_entries": ""}
    assert world.client.post("/feeds/999/edit", data=data).status_code == 404


# ---------- 삭제 ----------


def test_deleting_removes_the_feed_with_its_articles_and_keeps_the_seen_record(world):
    feed_id = add_feed(world)
    world.articles.add(
        NewArticle(
            feed_id,
            "g1",
            "t",
            "https://x/1",
            "c",
            "",
            datetime(2026, 10, 16, tzinfo=UTC),
            "2026-10-16",
        )
    )
    response = world.client.post(f"/feeds/{feed_id}/delete", data={"confirm": "yes"})
    assert response.status_code == 303 and response.headers["location"] == "/feeds?deleted=1"
    assert world.feeds.list_all() == [] and world.articles.is_seen("g1") is True
    assert "삭제했습니다" in world.client.get("/feeds?deleted=1").text


def test_deleting_without_the_confirmation_changes_nothing(world):
    feed_id = add_feed(world)
    response = world.client.post(f"/feeds/{feed_id}/delete", data={})
    assert response.status_code == 400 and world.feeds.get(feed_id) is not None


def test_deleting_an_unknown_feed_gives_404(world):
    assert world.client.post("/feeds/999/delete", data={"confirm": "yes"}).status_code == 404


def test_a_deleted_feed_can_be_added_again_without_resending_old_articles(world):
    feed_id = add_feed(world)
    world.articles.add(
        NewArticle(
            feed_id,
            "g1",
            "t",
            "https://x/1",
            "c",
            "",
            datetime(2026, 10, 16, tzinfo=UTC),
            "2026-10-16",
        )
    )
    world.client.post(f"/feeds/{feed_id}/delete", data={"confirm": "yes"})
    new_id = world.feeds.add("https://f.example.com/rss", "블로그")
    assert world.feeds.get(new_id).status == "baseline_pending" and world.articles.is_seen("g1")


# ---------- 내보내기 ----------


def test_the_export_is_a_download_with_an_opml_filename(world):
    response = world.client.get("/feeds/export.opml")
    assert response.status_code == 200
    assert (
        response.headers["content-disposition"]
        == 'attachment; filename="rss-hub-subscriptions.opml"'
    )
    assert response.headers["content-type"].startswith("text/x-opml") and response.text.startswith(
        "<?xml"
    )


def test_an_empty_list_exports_a_valid_document(world):
    assert "<opml" in world.client.get("/feeds/export.opml").text


def test_names_that_try_to_inject_markup_stay_text_in_the_export(world):
    world.feeds.add("https://f.example.com/rss", '<script>alert(1)</script>"&')
    body = world.client.get("/feeds/export.opml").text
    assert "<script>" not in body and "&lt;script&gt;" in body


def test_the_export_is_not_cached(world):
    assert world.client.get("/feeds/export.opml").headers["cache-control"] == "no-store"


# ---------- 보안 ----------


@pytest.mark.security
@pytest.mark.parametrize(
    "path", ["/feeds/discover", "/feeds/register", "/feeds/1/edit", "/feeds/1/delete"]
)
def test_the_new_routes_reject_other_sites_and_accept_the_browsers_own_form(world, path):
    other = world.client.post(
        path,
        data={"url": "x"},
        headers={"origin": "https://evil.example.com", "sec-fetch-site": "cross-site"},
    )
    own = world.client.post(path, data={"url": "https://x.example.com/rss"}, headers=BROWSER)
    assert other.status_code == 403 and own.status_code != 403
    assert world.client.get(path).status_code == 405


@pytest.mark.security
def test_a_forged_register_request_for_a_private_address_sends_nothing(world):
    response = world.client.post(
        "/feeds/register", data={"url": "http://169.254.169.254/latest/meta-data"}
    )
    assert response.status_code == 400 and world.fetcher.fetch_calls == []


def test_the_page_mentions_how_many_feeds_there_are(world):
    add_feed(world)
    assert re.search(r"전체 1\s*</a>", world.client.get("/feeds").text)
