"""슬라이드 패널(추가, 설정, 삭제 확인)과 설정 탭."""

# ruff: noqa: E501  (HTML 정규식과 견본은 한 줄이 읽기 쉽다)

import re

import pytest

from rss_hub.domain.topics import TopicFields
from tests.fakes.viewer_world import World
from tests.fakes.web_parts import start_app

BROWSER = {"origin": "null", "sec-fetch-site": "same-origin"}
FRAGMENT = {"x-panel": "1"}
WEBHOOK = "https://discord.com/api/webhooks/9/abc"


@pytest.fixture
def world(tmp_path):
    parts, client = start_app(tmp_path)
    with client:
        w = World(parts)
        w.topic = w.topics.add(TopicFields("게임", "게임 소식", ("steam",)))
        yield w


def panel(world, path, **headers):
    return world.client.get(path, headers=FRAGMENT | headers)


def post(world, path, **data):
    return world.client.post(path, data=data, headers=BROWSER)


# ---------- 조각과 전체 화면 ----------


@pytest.mark.parametrize("kind", ["feed", "category", "topic"])
def test_a_panel_is_an_html_fragment_for_the_script_and_a_full_page_without_it(world, kind):
    fragment = panel(world, f"/panel/add/{kind}")
    assert fragment.status_code == 200 and "<html" not in fragment.text
    assert 'class="slide"' in fragment.text and 'data-action="close-panel"' in fragment.text
    full = world.get(f"/panel/add/{kind}").text
    assert (
        "<html" in full
        and 'class="slide static"' in full
        and '<nav aria-label="구독 목록">' in full
    )


@pytest.mark.parametrize(
    "path",
    [
        "/panel/add/other",
        "/panel/settings/feed/999",
        "/panel/settings/category/999",
        "/panel/settings/topic/999",
        "/panel/delete/feed/999",
        "/panel/delete/other/1",
        "/panel/settings/other/1",
    ],
)
def test_a_missing_panel_gives_404(world, path):
    assert panel(world, path).status_code == 404


# ---------- 추가 ----------


def test_the_add_panels_post_to_the_existing_endpoints_and_carry_the_return_address(world):
    feed = panel(world, "/panel/add/feed?next=/reader").text
    assert 'action="/feeds/discover"' in feed and 'name="url"' in feed
    category = panel(world, "/panel/add/category?next=/reader/bookmarks").text
    assert (
        'action="/categories/add"' in category
        and 'name="next" value="/reader/bookmarks"' in category
    )
    topic = panel(world, "/panel/add/topic?next=/reader").text
    assert (
        'action="/topics/add"' in topic
        and 'name="keywords"' in topic
        and 'name="webhook_id"' in topic
    )


def test_adding_a_category_from_the_panel_returns_to_the_reading_screen_with_a_toast(world):
    response = post(world, "/categories/add", name="새 카테고리", next="/reader")
    assert response.headers["location"] == "/reader?toast=saved"
    assert "새 카테고리" in world.get("/reader").text


def test_adding_a_topic_from_the_panel_works_the_same_way(world):
    response = post(
        world,
        "/topics/add",
        name="새 주제",
        description="",
        keywords="a, b",
        enabled="yes",
        next="/reader",
    )
    assert response.headers["location"] == "/reader?toast=saved"
    assert "새 주제" in world.get("/reader").text


# ---------- 설정 ----------


def test_the_feed_panel_is_one_form_with_every_field_and_no_delete_or_priority(world):
    html = panel(world, f"/panel/settings/feed/{world.f_free}?next=/reader").text
    assert html.count("<form") == 1 and f'action="/feeds/{world.f_free}/settings"' in html
    for field in ("name", "url", "emoji", "max_entries", "category_id", "webhook_id"):
        assert f'name="{field}"' in html, field
    assert 'value="자유 블로그"' in html and f'value="{world.feeds.get(world.f_free).url}"' in html
    assert "/delete" not in html and "/panel/delete" not in html  # 삭제는 사이드바의 −로만
    assert "priority" not in html and "점검 우선순위" not in html


def test_the_close_button_sits_next_to_save_and_not_in_the_header(world):
    html = panel(world, f"/panel/settings/feed/{world.f_free}").text
    head, form = (
        html.split('<div class="slide-head">')[1].split("</div>", 1)[0],
        html.split("<form")[1],
    )
    assert "닫기" not in head and 'data-action="close-panel"' not in head
    pattern = r'class="primary">저장</button><a class="button" href="[^"]*" '
    assert re.search(pattern + r'data-action="close-panel">닫기', form)


def test_the_feed_panel_explains_that_a_category_and_a_webhook_exclude_each_other(world):
    webhook = world.parts.settings.add_webhook("개별", WEBHOOK)
    world.feeds.set_feed_webhook(world.f_free, webhook)
    html = panel(world, f"/panel/settings/feed/{world.f_free}").text
    assert "함께 지정할 수 없습니다" in html and f'<option value="{webhook}" selected>' in html
    category = panel(world, f"/panel/settings/feed/{world.f_news}").text
    assert f'<option value="{world.news}" selected>' in category


def test_saving_the_feed_panel_returns_to_the_reading_screen(world):
    response = post(
        world,
        f"/feeds/{world.f_free}/edit",
        name="새 이름",
        emoji="📰",
        priority="every_slot",
        max_entries="7",
        next="/reader",
    )
    assert response.headers["location"] == "/reader?toast=saved"
    feed = world.feeds.get(world.f_free)
    assert (feed.name, feed.poll_priority, feed.max_entries) == ("새 이름", "every_slot", 7)


def test_the_category_panel_is_one_form_for_name_and_webhook_without_delete(world):
    html = panel(world, f"/panel/settings/category/{world.news}").text
    assert html.count("<form") == 1 and f'action="/categories/{world.news}/settings"' in html
    assert 'name="name"' in html and 'name="webhook_id"' in html and "피드 1개" in html
    assert "/delete" not in html and re.search(
        r'저장</button><a class="button"[^>]*>닫기</a>', html
    )


def test_the_topic_panel_shows_the_keywords_and_links_to_the_suggestions(world):
    html = panel(world, f"/panel/settings/topic/{world.topic}").text
    assert f'action="/topics/{world.topic}/update"' in html and ">steam</textarea>" in html
    assert f'href="/topics/{world.topic}/suggestions"' in html and "checked" in html
    assert "/delete" not in html and re.search(
        r'저장</button><a class="button"[^>]*>닫기</a>', html
    )


def test_names_in_panels_are_escaped(world):
    feed = world.feeds.add("https://x.example.com/rss", '"><script>alert(1)</script>')
    html = panel(world, f"/panel/settings/feed/{feed}").text
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html


# ---------- 삭제 확인 ----------


@pytest.mark.parametrize(
    ("kind", "target", "action", "note"),
    [
        ("feed", "f_free", "/feeds/{id}/delete", "피드를 삭제합니다"),
        ("category", "news", "/categories/{id}/delete", "카테고리를 삭제합니다"),
        ("topic", "topic", "/topics/{id}/delete", "주제를 삭제합니다"),
    ],
)
def test_the_sidebar_delete_button_is_a_form_that_asks_for_confirmation(
    world, kind, target, action, note
):
    item = getattr(world, target)
    html = world.get("/reader/bookmarks").text
    form = re.search(
        rf'<form method="post" action="{re.escape(action.format(id=item))}" class="inline-del" data-confirm="([^"]+)">(.*?)</form>',
        html,
        re.S,
    )
    assert form is not None
    assert note in form.group(1) and form.group(1).startswith("‘")  # 이름이 들어간 확인 문구
    assert 'name="confirm" value="yes"' in form.group(
        2
    ) and 'name="next" value="/reader/bookmarks"' in form.group(2)
    assert 'type="checkbox"' not in form.group(2)


def test_deleting_the_list_you_are_looking_at_goes_back_to_all_articles(world):
    own = f"/reader/feed/{world.f_free}"
    done = world.client.post(
        f"/feeds/{world.f_free}/delete", data={"confirm": "yes", "next": own}, headers=BROWSER
    )
    assert done.status_code == 303 and done.headers["location"] == "/reader?toast=deleted"
    other_feed = world.feeds.add("https://other.example.com/rss", "다른 피드")
    stay = f"/reader/feed/{world.f_news}"
    kept = world.client.post(
        f"/feeds/{other_feed}/delete", data={"confirm": "yes", "next": stay}, headers=BROWSER
    )
    assert (
        kept.headers["location"] == f"{stay}?toast=deleted"
    )  # 다른 목록을 보고 있었으면 그대로 돌아간다


@pytest.mark.security
@pytest.mark.parametrize(
    "target", ["https://evil.example.com/", "//evil.example.com", "/healthz", "javascript:alert(1)"]
)
def test_a_dangerous_return_address_is_replaced_in_every_panel(world, target):
    for path in (
        "/panel/add/category",
        f"/panel/settings/feed/{world.f_free}",
        f"/panel/delete/topic/{world.topic}",
    ):
        html = world.client.get(path, params={"next": target}, headers=FRAGMENT).text
        assert "evil.example.com" not in html and "javascript:" not in html


def test_deleting_a_feed_from_the_panel_removes_it_with_its_articles(world):
    article = world.article(world.f_free)
    assert (
        post(world, f"/feeds/{world.f_free}/delete", next="/reader").status_code == 400
    )  # 확인 없이는 안 된다
    response = post(world, f"/feeds/{world.f_free}/delete", confirm="yes", next="/reader")
    assert response.headers["location"] == "/reader?toast=deleted"
    assert world.feeds.get(world.f_free) is None and world.articles.get(article) is None


def test_deleting_a_topic_keeps_its_articles(world):
    article = world.article()
    world.topics.add_manual(article, world.topic)
    post(world, f"/topics/{world.topic}/delete", confirm="yes", next="/reader")
    assert world.articles.get(article) is not None and world.topics.get(world.topic) is None


# ---------- 사이드바 ----------


def test_sidebar_rows_have_a_grip_settings_and_delete_buttons_and_drag_attributes(world):
    html = world.get("/reader").text
    assert f'data-drag-kind="feed" data-drag-id="{world.f_free}"' in html
    assert f'href="/panel/settings/feed/{world.f_free}?next=%2Freader" data-panel' in html
    assert f'action="/feeds/{world.f_free}/delete" class="inline-del" data-confirm="' in html
    assert (
        f'data-drag-kind="category" data-drag-id="{world.news}"' in html
        and f'data-drag-kind="topic" data-drag-id="{world.topic}"' in html
    )
    for kind in ("feed", "category", "topic"):
        assert (
            f'data-reorder="{kind}"' in html
            and f'href="/panel/add/{kind}?next=%2Freader" data-panel' in html
        )


def test_categories_and_the_rss_header_are_drop_targets_for_feeds(world):
    html = world.get("/reader").text
    assert (
        f'<summary data-drop-category="{world.news}">' in html
        and '<summary title="RSS 피드" data-drop-category="">' in html
    )


def test_the_panel_return_address_follows_the_current_list_and_drops_unknown_parameters(world):
    html = world.get(f"/reader/feed/{world.f_free}?page=2&q=abc&toast=read_all&x=1").text
    assert f"?next=%2Freader%2Ffeed%2F{world.f_free}%3Fpage%3D2%26q%3Dabc" in html
    assert "toast%3D" not in html and "x%3D1" not in html


# ---------- 설정: 아코디언 한 페이지 ----------


def section(html, acc_id):
    """설정 화면의 아코디언 구역 하나."""
    return html.split(f'<details class="acc" id="acc-{acc_id}"')[1].split("</details>")[0]


def test_the_settings_are_one_page_of_accordions_in_a_logical_order(world):
    html = world.get("/settings").text
    ids = re.findall(r'<details class="acc" id="acc-(\w+)"', html)
    assert ids == ["general", "collect", "llm", "alerts", "display", "audit"]
    titles = re.findall(r"<summary><span>(\d)\. ([^<]+)</span>", html)
    assert [n for n, _ in titles] == ["1", "2", "3", "4", "5", "6"]
    assert "서비스 주소" in titles[0][1] and "변경 이력" in titles[-1][1]


def test_only_the_first_section_starts_open(world):
    html = world.get("/settings").text
    assert re.findall(r'<details class="acc" id="acc-(\w+)" open>', html) == ["general"]


def test_each_section_holds_its_own_settings(world):
    html = world.get("/settings").text
    assert "service_timezone" in section(html, "general") and "service_base_url" in section(
        html, "general"
    )
    collect = section(html, "collect")
    assert (
        "collect_interval_minutes" in collect
        and "article_retention_days" in collect
        and "자동으로 정해집니다" in collect
    )
    llm = section(html, "llm")
    assert (
        "OpenRouter 키" in llm
        and "model_chain" in llm
        and "llm_daily_cap" in llm
        and 'href="/models"' in llm
    )
    alerts = section(html, "alerts")
    assert (
        "Discord 웹훅" in alerts
        and "alert_cooldown_hours" in alerts
        and 'action="/settings/webhooks"' in alerts
    )
    display = section(html, "display")
    for key in ("ui_theme", "ui_font_size", "ui_auto_read"):
        assert f'id="{key}"' in display
    assert "service_timezone" not in llm and "ui_theme" not in alerts


def test_every_form_on_the_page_returns_to_the_settings_page(world):
    html = world.get("/settings").text
    forms = re.findall(
        r'<form method="post" action="(/settings[^"]*)"[^>]*>\s*'
        r'<input type="hidden" name="next" value="([^"]*)"',
        html,
    )
    assert forms and all(next_path == "/settings" for _, next_path in forms)
    assert html.count('<form method="post" action="/settings') == len(
        forms
    )  # 사이드바의 삭제 폼은 따로


def test_saving_a_section_returns_with_a_toast(world):
    for data in (
        {"service_timezone": "Asia/Seoul"},
        {"ui_theme": "dark"},
        {"llm_daily_cap": "900"},
        {"alert_cooldown_hours": "3"},
        {"ui_auto_read": "off"},
    ):
        response = post(world, "/settings", next="/settings", **data)
        assert response.headers["location"] == "/settings?toast=saved", data
    assert "저장했습니다." in world.get("/settings?toast=saved").text


def test_webhook_and_key_forms_return_to_the_settings_page(world):
    added = post(world, "/settings/webhooks", name="새 웹훅", url=WEBHOOK, next="/settings")
    assert added.headers["location"] == "/settings?toast=saved"
    saved = post(
        world,
        "/settings/openrouter-key",
        openrouter_key="sk-or-v1-abcdefghijklmnop",
        next="/settings",
    )
    assert saved.headers["location"] == "/settings?toast=saved"


def test_an_error_opens_the_section_it_belongs_to(world):
    response = post(world, "/settings", ui_theme="neon", next="/settings")
    assert response.status_code == 400 and "목록에 있는 값" in response.text
    assert set(re.findall(r'<details class="acc" id="acc-(\w+)" open>', response.text)) == {
        "general",
        "display",
    }
    bad_url = post(
        world,
        "/settings/webhooks",
        name="x",
        url="https://not-discord.example.com/",
        next="/settings",
    )
    assert bad_url.status_code == 400
    assert "alerts" in re.findall(r'<details class="acc" id="acc-(\w+)" open>', bad_url.text)


def test_the_old_tab_addresses_are_gone(world):
    for tab in ("general", "notifications", "llm", "display"):
        assert world.get(f"/settings/{tab}").status_code in (404, 405)
    assert world.get("/settings/webhooks").status_code == 405


def test_there_is_no_top_navigation_only_the_sidebar_menu_with_five_items(world):
    for path in ("/settings", "/feeds", "/topics", "/status", "/models"):
        assert 'class="tabs"' not in world.get(path).text
    menu = world.get("/settings").text.split('id="sec-settings"')[1].split("</details>")[0]
    links = [h for h in re.findall(r'href="([^"]+)"', menu) if h.startswith("/")]
    assert links == ["/settings", "/feeds", "/topics", "/models", "/status"]
    assert "피드 관리" in menu


# ---------- 테마와 글자 크기는 스타일시트가 실제로 따른다 ----------


def test_the_stylesheet_follows_the_theme_and_font_attributes(world):
    css = world.client.get("/static/app.css").text
    assert ':root[data-theme="dark"] {' in css
    assert ':root:not([data-theme="light"]):not([data-theme="dark"])' in css  # 기기 설정 따르기
    assert ':root[data-font="large"] body { font-size: 17px; }' in css
    # 어둡게일 때와 기기가 어두울 때의 색이 같아야 한다
    dark = re.findall(r"--surface: (#[0-9a-f]{6});", css)
    assert len(dark) == 3 and dark[1] == dark[2] != dark[0]


def test_no_delete_form_uses_a_checkbox_any_more_and_the_delete_panel_is_gone(world):
    for path in ("/settings", "/topics", "/feeds", "/reader", "/categories"):
        assert 'type="checkbox" name="confirm"' not in world.get(path).text, path
    assert (
        world.client.get(f"/panel/delete/feed/{world.f_free}", headers={"x-panel": "1"}).status_code
        == 404
    )


@pytest.mark.parametrize(
    "path",
    [
        "/feeds/{feed}/delete",
        "/categories/{news}/delete",
        "/topics/{topic}/delete",
        "/settings/openrouter-key/delete",
    ],
)
def test_the_server_still_refuses_a_delete_request_without_the_confirm_value(world, path):
    url = path.format(feed=world.f_free, news=world.news, topic=world.topic)
    response = world.client.post(url, data={}, headers=BROWSER)
    assert response.status_code == 400 and "삭제 확인이 필요합니다" in response.text
    assert world.feeds.get(world.f_free) is not None and world.topics.get(world.topic) is not None


def test_deleting_an_article_page_s_feed_or_a_category_page_s_category_leaves_the_vanished_page(
    world,
):
    article = world.article(world.f_free)
    gone = world.client.post(
        f"/feeds/{world.f_free}/delete",
        data={"confirm": "yes", "next": f"/a/{article}?back=%2Freader"},
        headers=BROWSER,
    )
    assert gone.headers["location"] == "/reader?toast=deleted"
    cat = world.client.post(
        f"/categories/{world.news}/delete",
        data={"confirm": "yes", "next": f"/reader/category/{world.news}"},
        headers=BROWSER,
    )
    assert cat.headers["location"] == "/reader?toast=deleted"
    topic = world.client.post(
        f"/topics/{world.topic}/delete",
        data={"confirm": "yes", "next": f"/reader/topic/{world.topic}"},
        headers=BROWSER,
    )
    assert topic.headers["location"] == "/reader?toast=deleted"


def test_the_confirm_script_stops_the_submit_when_the_user_cancels(world):
    js = world.client.get("/static/app.js").text
    assert 'getAttribute("data-confirm")' in js and "window.confirm(message)" in js
    assert "event.preventDefault()" in js.split("window.confirm(message)")[1].split("}")[0]
    assert "true\n  );" in js.split("window.confirm(message)")[1]  # 캡처 단계에서 가장 먼저
