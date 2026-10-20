"""피드 상태 점, 강제 새로고침, 피드와 카테고리 설정 한 번에 저장, 사이드바 상태 경로."""

import pytest

from rss_hub.domain.feed_url import feed_url_key
from tests.fakes.entries import today
from tests.fakes.feed_fetcher import FakeFeedFetcher
from tests.fakes.viewer_world import World
from tests.fakes.web_parts import start_app

BROWSER = {"origin": "null", "sec-fetch-site": "same-origin"}
WEBHOOK = "https://discord.com/api/webhooks/9/abc"
NEWS_URL, FREE_URL = "https://n.example.com/rss", "https://f.example.com/rss"


@pytest.fixture
def world(tmp_path):
    fetcher = FakeFeedFetcher()
    parts, client = start_app(tmp_path, feed_fetcher=fetcher)
    with client:
        w = World(parts)
        w.fetcher = fetcher
        yield w


def post(world, path, **data):
    return world.client.post(path, data=data, headers=BROWSER)


def settings_form(world, feed, **override):
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


# ---------- 상태 ----------


def test_the_state_json_has_every_count_and_feed_state(world):
    world.article(world.f_news)
    state = world.get("/ui/state").json()
    assert set(state) == {"feeds", "categories", "topics", "all_unread", "bookmarks"}
    assert state["feeds"][str(world.f_news)] == {
        "state": "never",
        "error": "",
        "unread": 1,
        "total": 1,
    }
    assert state["categories"][str(world.news)] == {"unread": 1, "total": 1}
    assert state["all_unread"] == 1 and state["bookmarks"] == 0


# ---------- 강제 새로고침 ----------


def test_a_forced_refresh_reads_the_feed_now_and_turns_the_state_green(world):
    world.fetcher.serve(FREE_URL, today(2))
    response = post(world, f"/feeds/{world.f_free}/refresh")
    body = response.json()
    assert response.status_code == 200 and body["ok"] is True and body["error"] == ""
    assert body["state"]["feeds"][str(world.f_free)]["state"] == "ok"
    assert world.feeds.get(world.f_free).last_checked_at is not None


def test_a_forced_refresh_ignores_the_stored_validators(world):
    world.feeds.record_success(world.f_free, etag="old-etag", last_modified="old", activate=True)
    world.fetcher.serve(FREE_URL, today(1))
    post(world, f"/feeds/{world.f_free}/refresh")
    call = world.fetcher.calls[-1]
    assert (call.etag, call.last_modified) == (None, None)


def test_a_failed_refresh_turns_the_state_red_and_says_why(world):
    world.fetcher.fail(FREE_URL, "ReadTimeout")
    body = post(world, f"/feeds/{world.f_free}/refresh").json()
    assert body["ok"] is False and body["error"]
    assert body["state"]["feeds"][str(world.f_free)]["state"] == "error"
    assert body["state"]["feeds"][str(world.f_free)]["error"] == "ReadTimeout"


def test_a_later_good_refresh_clears_the_error(world):
    world.fetcher.fail(FREE_URL)
    post(world, f"/feeds/{world.f_free}/refresh")
    world.fetcher.serve(FREE_URL, today(1))
    body = post(world, f"/feeds/{world.f_free}/refresh").json()
    assert body["ok"] and body["state"]["feeds"][str(world.f_free)]["state"] == "ok"


def test_an_unexpected_error_is_reported_without_leaking_details(world):
    world.fetcher.crash(FREE_URL, RuntimeError("https://secret.example.com/token"))
    body = post(world, f"/feeds/{world.f_free}/refresh").json()
    assert body["ok"] is False and "secret" not in str(body)


def test_refreshing_a_missing_feed_gives_404(world):
    assert post(world, "/feeds/999/refresh").status_code == 404


@pytest.mark.security
def test_other_sites_cannot_trigger_a_refresh(world):
    response = world.client.post(
        f"/feeds/{world.f_free}/refresh",
        headers={"origin": "https://evil.example.com", "sec-fetch-site": "cross-site"},
    )
    assert response.status_code == 403 and world.fetcher.calls == []
    assert world.client.get(f"/feeds/{world.f_free}/refresh").status_code == 405


# ---------- 피드 설정 한 번에 저장 ----------


def test_saving_the_feed_settings_changes_name_emoji_and_max_entries(world):
    response = settings_form(world, world.f_free, name="새 이름", emoji="📰", max_entries="7")
    assert response.status_code == 303
    feed = world.feeds.get(world.f_free)
    assert (feed.name, feed.emoji, feed.max_entries) == ("새 이름", "📰", 7)


def test_the_feed_priority_is_left_alone_because_the_panel_no_longer_has_it(world):
    world.feeds.set_poll_priority(world.f_free, "every_slot")
    settings_form(world, world.f_free, name="이름만 바꿈")
    assert world.feeds.get(world.f_free).poll_priority == "every_slot"


def test_the_feed_url_can_be_changed_and_the_checks_restart(world):
    world.feeds.record_success(world.f_free, etag="e", last_modified="m", activate=True)
    response = settings_form(world, world.f_free, url="https://new.example.com/feed.xml")
    assert response.status_code == 303
    feed = world.feeds.get(world.f_free)
    assert (
        feed.url == "https://new.example.com/feed.xml"
        and feed.etag is None
        and feed.last_checked_at is None
    )
    assert feed_url_key(feed.url) in world.feeds.existing_url_keys()


def test_an_unchanged_url_does_not_reset_the_checks(world):
    world.feeds.record_success(world.f_free, etag="e", last_modified="m", activate=True)
    settings_form(world, world.f_free, name="이름만")
    assert world.feeds.get(world.f_free).etag == "e"


@pytest.mark.parametrize(
    "url",
    [
        "",
        "ftp://x.example.com/rss",
        "http://127.0.0.1/rss",
        "http://192.168.0.5/rss",
        "javascript:alert(1)",
        "x" * 3000,
    ],
)
def test_a_bad_feed_url_is_refused_and_nothing_changes(world, url):
    before = world.feeds.get(world.f_free)
    response = settings_form(world, world.f_free, name="바뀌면 안 됨", url=url)
    assert response.status_code == 400
    after = world.feeds.get(world.f_free)
    assert (after.name, after.url) == (before.name, before.url)


def test_a_url_another_feed_already_has_is_refused(world):
    response = settings_form(world, world.f_free, name="바뀌면 안 됨", url=NEWS_URL)
    assert response.status_code == 400 and "이미 구독" in response.text
    assert world.feeds.get(world.f_free).name == "자유 블로그"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("name", "", "이름"),
        ("emoji", "", "이모지"),
        ("max_entries", "0", "최대 검사"),
        ("max_entries", "abc", "최대 검사"),
    ],
)
def test_bad_values_are_refused(world, field, value, message):
    response = settings_form(world, world.f_free, **{field: value})
    assert response.status_code == 400 and message in response.text


def test_a_feed_can_have_a_category_or_a_webhook_but_not_both(world):
    webhook = world.parts.settings.add_webhook("개별", WEBHOOK)
    response = settings_form(
        world,
        world.f_free,
        name="바뀌면 안 됨",
        category_id=str(world.tech),
        webhook_id=str(webhook),
    )
    assert response.status_code == 400 and "웹훅" in response.text
    feed = world.feeds.get(world.f_free)
    assert (feed.name, feed.category_id, feed.webhook_id) == ("자유 블로그", None, None)


def test_choosing_a_webhook_for_a_feed_in_a_category_moves_it_out_of_the_category(world):
    webhook = world.parts.settings.add_webhook("개별", WEBHOOK)
    settings_form(world, world.f_news, category_id="", webhook_id=str(webhook))
    feed = world.feeds.get(world.f_news)
    assert (feed.category_id, feed.webhook_id) == (None, webhook)


def test_choosing_a_category_for_a_feed_with_a_webhook_clears_the_webhook(world):
    webhook = world.parts.settings.add_webhook("개별", WEBHOOK)
    world.feeds.set_feed_webhook(world.f_free, webhook)
    settings_form(world, world.f_free, category_id=str(world.tech), webhook_id="")
    feed = world.feeds.get(world.f_free)
    assert (feed.category_id, feed.webhook_id) == (world.tech, None)


def test_a_missing_category_or_webhook_is_refused(world):
    assert settings_form(world, world.f_free, category_id="999").status_code == 400
    assert settings_form(world, world.f_free, webhook_id="999").status_code == 400


def test_a_missing_feed_gives_404_and_the_return_address_is_followed(world):
    assert post(world, "/feeds/999/settings", name="x", url=FREE_URL, emoji="x").status_code == 404
    response = settings_form(world, world.f_free, name="돌아가기", next="/reader")
    assert response.headers["location"] == "/reader?toast=saved"


@pytest.mark.security
def test_other_sites_cannot_change_feed_settings(world):
    response = world.client.post(
        f"/feeds/{world.f_free}/settings",
        data={"name": "해킹", "url": FREE_URL, "emoji": "x"},
        headers={"origin": "https://evil.example.com", "sec-fetch-site": "cross-site"},
    )
    assert response.status_code == 403 and world.feeds.get(world.f_free).name == "자유 블로그"


# ---------- 카테고리 설정 한 번에 저장 ----------


def test_the_category_name_and_webhook_are_saved_together(world):
    webhook = world.parts.settings.add_webhook("카테고리용", WEBHOOK)
    response = post(
        world,
        f"/categories/{world.tech}/settings",
        name="새 기술",
        webhook_id=str(webhook),
        next="/reader",
    )
    assert response.headers["location"] == "/reader?toast=saved"
    category = next(c for c in world.feeds.list_categories() if c.id == world.tech)
    assert (category.name, category.webhook_id) == ("새 기술", webhook)
    post(world, f"/categories/{world.tech}/settings", name="새 기술", webhook_id="")
    assert next(c for c in world.feeds.list_categories() if c.id == world.tech).webhook_id is None


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"name": ""}, "이름"),
        ({"name": "뉴스"}, "같은 이름"),
        ({"name": "정상", "webhook_id": "999"}, "웹훅"),
    ],
)
def test_bad_category_settings_are_refused_and_change_nothing(world, data, message):
    response = post(world, f"/categories/{world.tech}/settings", **data)
    assert response.status_code == 400 and message in response.text
    assert next(c for c in world.feeds.list_categories() if c.id == world.tech).name == "기술"


def test_a_missing_category_gives_404(world):
    assert post(world, "/categories/999/settings", name="x").status_code == 404
