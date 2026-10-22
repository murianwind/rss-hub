"""관리 동작(순서, 이동, 카테고리 이름 변경과 삭제, 돌아갈 곳, 디스플레이 설정)."""

import re

import pytest

from rss_hub.web.ui import done, safe_return
from tests.keywords.browser import post

WEBHOOK = "https://discord.com/api/webhooks/9/abc"


def feed_order(world):
    html = world.get("/reader").text
    nav = html.split('<details class="sec" id="sec-rss"')[1].split("</details>")[0]
    return re.findall(r'href="/reader/feed/(\d+)"', nav)


# ---------- 순서 ----------


def test_feeds_cannot_be_reordered_by_dragging(world):
    world.feeds.set_feed_category(world.f_news, None)
    before = feed_order(world)
    assert (
        post(world, "/ui/reorder", kind="feed", ids=f"{world.f_free},{world.f_news}").status_code
        == 400
    )
    assert feed_order(world) == before and 'data-reorder="feed"' not in world.get("/reader").text


@pytest.mark.parametrize("ids", ["", "abc", "1,,x", "999", "1,1", "1;2", "-1"])
def test_a_bad_order_is_refused_and_nothing_changes(world, ids):
    before = feed_order(world)
    response = post(world, "/ui/reorder", kind="category", ids=ids)
    assert response.status_code == 400 and feed_order(world) == before


def test_an_unknown_kind_is_refused(world):
    assert post(world, "/ui/reorder", kind="articles", ids=str(world.f_news)).status_code == 400


# ---------- 카테고리로 이동(기존 규칙 그대로) ----------


def test_a_feed_can_be_dropped_on_a_category_and_out_of_it(world):
    assert (
        post(
            world, "/ui/move-feed", feed_id=str(world.f_free), category_id=str(world.tech)
        ).status_code
        == 200
    )
    assert world.feeds.get(world.f_free).category_id == world.tech
    assert (
        post(world, "/ui/move-feed", feed_id=str(world.f_free), category_id="").status_code == 200
    )
    assert world.feeds.get(world.f_free).category_id is None


def test_a_feed_with_its_own_webhook_cannot_enter_a_category(world):
    webhook = world.parts.settings.add_webhook("개별", WEBHOOK)
    world.feeds.set_feed_webhook(world.f_free, webhook)
    response = post(world, "/ui/move-feed", feed_id=str(world.f_free), category_id=str(world.tech))
    assert response.status_code == 400 and response.text
    assert world.feeds.get(world.f_free).category_id is None


def test_moving_to_a_missing_category_or_feed_is_refused(world):
    assert (
        post(world, "/ui/move-feed", feed_id=str(world.f_free), category_id="999").status_code
        == 400
    )
    assert post(world, "/ui/move-feed", feed_id="999", category_id="").status_code == 404
    assert post(world, "/ui/move-feed", feed_id="abc", category_id="").status_code == 400


# ---------- 카테고리 이름 변경과 삭제 ----------


def test_a_category_can_be_renamed_and_the_sidebar_shows_the_new_name(world):
    response = post(world, f"/categories/{world.tech}/rename", name="새 이름")
    assert response.status_code == 303 and "새 이름" in world.get("/reader").text


@pytest.mark.parametrize(
    ("name", "message"), [("", "이름"), ("뉴스", "같은 이름"), ("가" * 41, "40자")]
)
def test_a_bad_category_name_is_refused(world, name, message):
    response = post(world, f"/categories/{world.tech}/rename", name=name)
    assert response.status_code == 400 and message in response.text


def test_deleting_a_category_needs_the_confirmation_and_keeps_its_feeds(world):
    assert post(world, f"/categories/{world.news}/delete").status_code == 400
    assert any(c.id == world.news for c in world.feeds.list_categories())
    response = post(world, f"/categories/{world.news}/delete", confirm="yes")
    assert response.status_code == 303 and world.feeds.get(world.f_news).category_id is None
    assert post(world, f"/categories/{world.news}/delete", confirm="yes").status_code == 404
    assert post(world, "/categories/999/rename", name="x").status_code == 404


# ---------- 돌아갈 곳 ----------


@pytest.mark.parametrize(
    "path",
    [
        "/reader",
        "/reader/feed/3",
        "/settings",
        "/settings/llm",
        "/feeds",
        "/topics",
        "/models",
        "/status",
        "/import",
        "/feeds?x=1",
    ],
)
def test_management_forms_may_return_to_reading_and_management_pages(path):
    assert safe_return(path, "/x") == path


@pytest.mark.security
@pytest.mark.parametrize(
    "path",
    [
        "https://evil.example.com/",
        "//evil.example.com",
        "/settings/other",
        "/healthz",
        "/feeds/export.opml",
        "javascript:alert(1)",
        "/static/app.js",
        None,
    ],
)
def test_other_return_paths_are_refused(path):
    assert safe_return(path, "/x") == "/x"


def test_done_redirects_with_a_toast_or_to_the_default():
    assert (
        done({"next": "/reader"}, "/feeds?saved=1", "saved").headers["location"]
        == "/reader?toast=saved"
    )
    assert (
        done({"next": "https://evil.example.com"}, "/feeds?saved=1", "saved").headers["location"]
        == "/feeds?saved=1"
    )
    assert done({}, "/feeds?saved=1", "saved").headers["location"] == "/feeds?saved=1"


def test_saving_from_the_reading_screen_returns_there_with_a_toast(world):
    response = post(world, f"/categories/{world.tech}/rename", name="새 이름", next="/reader")
    assert response.headers["location"] == "/reader?toast=saved"
    assert "저장했습니다." in world.get(response.headers["location"]).text
    response = post(
        world,
        f"/feeds/{world.f_free}/edit",
        name="바뀐 이름",
        emoji="📰",
        priority="normal",
        max_entries="5",
        next="/reader",
    )
    assert response.headers["location"] == "/reader?toast=saved"
    assert world.feeds.get(world.f_free).name == "바뀐 이름"


def test_without_a_return_address_the_old_pages_still_redirect_as_before(world):
    assert (
        post(world, f"/categories/{world.tech}/rename", name="다른 이름").headers["location"]
        == "/categories?saved=1"
    )
    assert post(world, "/categories/add", name="신규").headers["location"] == "/categories?saved=1"


# ---------- 디스플레이 설정 ----------


def test_the_theme_and_font_size_are_chosen_with_select_boxes_and_applied_to_every_page(world):
    html = world.get("/settings").text
    assert (
        '<select id="ui_theme"' in html
        and '<option value="dark" >어둡게</option>' in html.replace("selected", "")
    )
    post(world, "/settings", ui_theme="dark", ui_font_size="large")
    page = world.get("/reader").text
    assert '<html lang="ko" data-theme="dark" data-font="large">' in page


@pytest.mark.parametrize(
    "values", [{"ui_theme": "neon"}, {"ui_font_size": "huge"}, {"ui_theme": ""}]
)
def test_an_unknown_display_choice_is_refused(world, values):
    response = post(world, "/settings", **values)
    assert response.status_code == 400 and "목록에 있는 값" in response.text
    assert 'data-theme="system"' in world.get("/reader").text


@pytest.mark.security
@pytest.mark.parametrize(
    "path", ["/ui/reorder", "/ui/move-feed", "/categories/1/rename", "/categories/1/delete"]
)
def test_other_sites_cannot_use_these_endpoints(world, path):
    response = world.client.post(
        path,
        data={"kind": "feed", "ids": "1", "name": "x", "confirm": "yes"},
        headers={"origin": "https://evil.example.com", "sec-fetch-site": "cross-site"},
    )
    assert response.status_code == 403
