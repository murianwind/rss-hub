"""피드 관리: 수집 주기와 마지막 게시 필터, 칩 주소, 버튼 모양, 카드 격자."""

# ruff: noqa: E501  (HTML 정규식과 긴 이름 견본은 한 줄이 읽기 쉽다)

import html as html_module
import re
from datetime import datetime, timedelta

import pytest

from rss_hub.domain.activity import FeedMeasurement
from rss_hub.domain.schedule import Activity, FeedCycle
from rss_hub.web.feeds import _cycle_matches, _feeds_url, _last_matches
from tests.fakes.viewer_world import World
from tests.fakes.web_parts import start_app

# 활동량으로 시간당 1, 2, 3회가 배정되는 값(탐색해서 확인한 값)
ACTIVITY = {1: Activity(0, 0), 2: Activity(3, 0), 3: Activity(10, 1)}


@pytest.fixture
def world(tmp_path):
    parts, client = start_app(tmp_path)
    with client:
        yield World(parts)


def add(world, name, cycle, ago):
    """cycle: 시간당 몇 회로 배정될지. ago: 마지막 게시가 얼마 전인지(None이면 기록 없음)."""
    feed = world.feeds.add(f"https://{abs(hash(name))}.example.com/rss", name)
    last = None if ago is None else world.parts.clock.now() - ago
    world.feeds.save_stats(feed, FeedMeasurement(ACTIVITY[cycle], last))
    return feed


@pytest.fixture
def seeded(world):
    add(world, "하루 전 글", 1, timedelta(hours=2))
    add(world, "주 단위 글", 2, timedelta(days=3))
    add(world, "달 단위 글", 3, timedelta(days=20))
    add(world, "해 단위 글", 1, timedelta(days=200))
    add(world, "오래된 글", 1, timedelta(days=400))
    add(world, "기록 없음 글", 1, None)
    return world


def shown(world, query=""):
    html = world.get("/feeds" + query).text
    listing = html_module.unescape(html.split('<ul class="feed-list">')[1].split("</ul>")[0])
    return {
        name
        for name in (
            "하루 전 글",
            "주 단위 글",
            "달 단위 글",
            "해 단위 글",
            "오래된 글",
            "기록 없음 글",
            "뉴스 블로그",
            "자유 블로그",
        )
        if name in listing
    }


EXTRA = {
    "뉴스 블로그",
    "자유 블로그",
}  # 처음부터 있던 피드(활동량 없음: 시간당 1회, 마지막 게시 기록 없음)


# ---------- 수집 주기 ----------


@pytest.mark.parametrize(
    ("cycle", "names"),
    [
        ("1", {"하루 전 글", "해 단위 글", "오래된 글", "기록 없음 글"} | EXTRA),
        ("2", {"주 단위 글"}),
        ("3", {"달 단위 글"}),
    ],
)
def test_the_cycle_filter_keeps_only_feeds_checked_that_many_times_per_hour(seeded, cycle, names):
    assert shown(seeded, f"?cycle={cycle}") == names


# ---------- 마지막 게시 ----------


@pytest.mark.parametrize(
    ("last", "names"),
    [
        ("day", {"하루 전 글"}),
        ("week", {"주 단위 글"}),  # 하루 초과 1주일 이하
        ("month", {"달 단위 글"}),  # 1주일 초과 1달 이하
        ("year", {"해 단위 글"}),  # 1달 초과 1년 이하
        ("older", {"오래된 글", "기록 없음 글"} | EXTRA),
    ],
)
def test_the_last_published_filter_keeps_only_the_feeds_in_that_band(seeded, last, names):
    assert shown(seeded, f"?last={last}") == names


def test_both_filters_and_the_search_work_together(seeded):
    assert shown(seeded, "?cycle=2&last=week") == {"주 단위 글"}
    assert shown(seeded, "?cycle=1&last=week") == set()
    assert shown(seeded, "?cycle=1&last=year&q=해 단위") == {"해 단위 글"}
    assert shown(seeded, "?cycle=2&last=day") == set()


def test_unknown_filter_values_are_ignored_not_errors(seeded):
    assert shown(seeded, "?cycle=9&last=bogus") == shown(seeded)
    assert seeded.get("/feeds?cycle=<script>&last=%27").status_code == 200


def test_the_state_counts_follow_the_filters(seeded):
    html = seeded.get("/feeds?cycle=2").text
    assert "전체 1" in html and "정상 0" in html
    assert "전체 1" not in seeded.get("/feeds").text


def test_the_empty_result_message_names_the_condition(seeded):
    assert "이 조건에 맞는 피드가 없습니다." in seeded.get("/feeds?cycle=2&last=day").text
    assert '"zzz"에 맞는 피드가 없습니다.' in seeded.get("/feeds?q=zzz").text


# ---------- 화면 ----------


def test_the_selects_show_the_options_and_keep_the_chosen_values(seeded):
    html = seeded.get("/feeds?cycle=2&last=month").text
    form = html.split('role="search">')[1].split("</form>")[0]
    for label in (
        "수집 주기: 전체",
        "시간당 1회",
        "시간당 2회",
        "시간당 3회",
        "마지막 게시: 전체",
        "하루 이내",
        "1주일 이내",
        "1달 이내",
        "1년 이내",
        "1년 넘게 없음",
    ):
        assert label in form
    assert re.search(r'<option value="2" selected>', form) and re.search(
        r'<option value="month" selected>', form
    )
    assert 'aria-label="수집 주기로 거르기"' in form and 'aria-label="마지막 게시로 거르기"' in form


def test_the_state_chips_keep_every_condition_and_encode_the_values(seeded):
    html = seeded.get("/feeds?q=a%2Fb&cycle=1&last=week&state=ok").text
    chips = html.split('aria-label="상태로 거르기">')[1].split("</nav>")[0]
    hrefs = [html_module.unescape(h) for h in re.findall(r'href="([^"]+)"', chips)]
    assert hrefs[0] == "/feeds?q=a%2Fb&cycle=1&last=week"  # 전체: 상태만 뺀다
    assert hrefs[1] == "/feeds?state=ok&q=a%2Fb&cycle=1&last=week"
    assert not re.search(r"[?&]\w+=/", " ".join(hrefs))  # 프록시 차단 규칙에 걸리는 모양이 없다


def test_the_hidden_state_stays_in_the_form_so_the_filters_do_not_drop_it(seeded):
    assert (
        '<input type="hidden" name="state" value="error">' in seeded.get("/feeds?state=error").text
    )
    assert (
        'name="state"'
        not in seeded.get("/feeds").text.split('role="search">')[1].split("</form>")[0]
    )


def test_the_script_applies_the_selects_immediately_on_this_page_only(seeded):
    js = seeded.client.get("/static/app.js").text
    assert 'if (event.target.matches("select")) search();' in js
    assert (
        'if (filterBox) filterBox.addEventListener("change", search);' in js
    )  # 글 목록의 필터는 그대로


# ---------- 버튼 모양과 카드 ----------


def test_the_three_buttons_use_the_back_button_design_with_icons(world):
    html = world.get("/feeds").text
    tools = html.split('<span class="row">')[1].split("</span>\n</div>")[0]
    for href, label in (
        ("/import", "OPML 가져오기"),
        ("/feeds/export.opml", "OPML 내보내기"),
        ("/categories", "카테고리 관리"),
    ):
        assert re.search(
            rf'<a class="back" href="{re.escape(href)}"><svg[^>]*>.*?</svg><span>{label}</span></a>',
            tools,
            re.S,
        )
    assert 'class="button"' not in tools


def test_the_feed_page_uses_the_wide_page_and_other_pages_keep_the_normal_width(world):
    assert 'class="page page-wide"' in world.get("/feeds").text
    for path in ("/settings", "/topics", "/categories", "/import"):
        assert 'class="page page-wide"' not in world.get(path).text, path


def test_the_cards_form_a_responsive_grid_with_a_minimum_width_and_ellipsis_titles(world):
    css = world.client.get("/static/app.css").text
    assert (
        "grid-template-columns: repeat(auto-fill, minmax(min(100%, 440px), 1fr))" in css
        and "align-items: start" in css
    )
    assert ".page.page-wide { max-width: none; }" in css
    assert re.search(r"\.feed-row \{[^}]*min-width: 0;", css)  # 긴 제목이 칸을 넓히지 않는다
    assert re.search(
        r"\.feed-name \{[^}]*overflow: hidden; text-overflow: ellipsis; white-space: nowrap;", css
    )


def test_a_very_long_title_keeps_its_full_text_in_the_tooltip_and_the_actions_stay_in_the_card(
    world,
):
    long_name = ("아주 긴 제목 " * 30).strip()
    feed = world.feeds.add("https://long.example.com/rss", long_name)
    cards = world.get("/feeds").text.split('<li class="feed-row">')[
        1:
    ]  # 첫 조각은 카드 앞(사이드바 포함)
    card = next(c for c in cards if "아주 긴 제목" in c).split("</li>")[0]
    assert f'title="{html_module.escape(long_name)}"' in card and f'data-refresh="{feed}"' in card
    assert f"/panel/settings/feed/{feed}" in card and f"/feeds/{feed}/delete" in card


# ---------- 판정 함수 ----------

NOW = datetime(2026, 10, 21, 12, 0).astimezone()


@pytest.mark.parametrize(
    ("per_hour", "wanted", "expected"),
    [
        (1, "1", True),
        (1, "2", False),
        (2, "2", True),
        (3, "3", True),
        (4, "3", True),
        (2, "3", False),
        (3, "2", False),
        (1, "", True),
    ],
)
def test_the_cycle_match_rule(per_hour, wanted, expected):
    assert _cycle_matches(FeedCycle(per_hour, (0,) * per_hour, 3), wanted) is expected


def test_a_feed_without_an_assigned_cycle_matches_only_when_no_cycle_is_chosen():
    assert _cycle_matches(None, "") is True and _cycle_matches(None, "1") is False


@pytest.mark.parametrize(
    ("ago", "wanted", "expected"),
    [
        (timedelta(days=1), "day", True),
        (timedelta(days=1, seconds=1), "day", False),
        (timedelta(hours=-1), "day", True),  # 시계 차이로 조금 미래여도 하루 이내
        (timedelta(days=1), "week", False),
        (timedelta(days=1, seconds=1), "week", True),
        (timedelta(days=7), "week", True),
        (timedelta(days=7, seconds=1), "week", False),
        (timedelta(days=7), "month", False),
        (timedelta(days=7, seconds=1), "month", True),
        (timedelta(days=30), "month", True),
        (timedelta(days=30, seconds=1), "month", False),
        (timedelta(days=30), "year", False),
        (timedelta(days=30, seconds=1), "year", True),
        (timedelta(days=365), "year", True),
        (timedelta(days=365, seconds=1), "year", False),
        (timedelta(days=365), "older", False),
        (timedelta(days=365, seconds=1), "older", True),
        (timedelta(days=2), "", True),
        (timedelta(days=2), "bogus", False),
    ],
)
def test_the_last_published_band_boundaries(ago, wanted, expected):
    assert _last_matches(NOW - ago, NOW, wanted) is expected


def test_no_publication_record_only_matches_the_older_group():
    assert [_last_matches(None, NOW, w) for w in ("", "day", "week", "month", "year", "older")] == [
        True,
        False,
        False,
        False,
        False,
        True,
    ]


def test_the_chip_address_builder_skips_empty_values_and_encodes_the_rest():
    assert _feeds_url(state="", q="", cycle="", last="") == "/feeds"
    assert (
        _feeds_url(state="ok", q="한 글/글", cycle="2", last="")
        == "/feeds?state=ok&q=%ED%95%9C+%EA%B8%80%2F%EA%B8%80&cycle=2"
    )


# ---------- 위쪽은 고정하고 카드만 스크롤 ----------


def test_the_top_part_is_fixed_and_only_the_cards_are_in_the_scroll_area(world):
    html = world.get("/feeds").text
    fixed = html.split('<div class="feed-fixed">')[1].split('<div class="feed-scroll">')[0]
    scroll = html.split('<div class="feed-scroll">')[1]
    for part in (
        "<h1>피드 관리</h1>",
        'role="search"',
        'aria-label="상태로 거르기"',
        "OPML 가져오기",
        "OPML 내보내기",
        "카테고리 관리",
        'class="note"',
    ):
        assert part in fixed, part
    assert '<ul class="feed-list">' in scroll and "feed-row" in scroll
    assert all(
        part not in scroll
        for part in ('role="search"', "OPML 가져오기", 'aria-label="상태로 거르기"')
    )
    assert '<ul class="feed-list">' not in fixed


def test_the_notice_and_the_error_banners_stay_in_the_fixed_part(world):
    html = world.get("/feeds?saved=1").text
    assert "저장했습니다." in html.split('<div class="feed-scroll">')[0]


def test_only_the_feed_page_uses_the_fixed_scroll_layout(world):
    assert 'class="scroll scroll-fixed"' in world.get("/feeds").text
    for path in ("/settings", "/topics", "/categories", "/import", "/reader"):
        assert "scroll-fixed" not in world.get(path).text, path


def test_the_style_fills_the_height_and_scrolls_only_the_card_area(world):
    css = world.client.get("/static/app.css").text
    assert ".scroll.scroll-fixed { display: flex; flex-direction: column; overflow: hidden;" in css
    assert (
        ".scroll-fixed > .page { display: flex; flex: 1; flex-direction: column; min-height: 0;"
        in css
    )
    assert ".feed-fixed { flex: none; max-height: 60%; overflow-y: auto; }" in css
    assert ".feed-scroll { flex: 1; min-height: 0; overflow-y: auto;" in css


def test_the_fixed_part_and_the_scroll_part_are_siblings_not_nested(world):
    """고정 영역이 닫히지 않아 카드가 그 안에 들어가면 고정 영역이 카드와 함께 커진다."""
    from html.parser import HTMLParser

    class Tree(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack, self.parent_of = [], {}
            self.void = {"input", "br", "img", "meta", "link", "hr", "use", "path", "circle"}

        def handle_starttag(self, tag, attrs):
            name = dict(attrs).get("class") or ""
            for mark in ("feed-fixed", "feed-scroll"):
                if mark in name.split():
                    self.parent_of[mark] = list(self.stack)
            if tag not in self.void:
                self.stack.append(f"{tag}.{name}")

        def handle_endtag(self, tag):
            if tag not in self.void and self.stack:
                self.stack.pop()

    tree = Tree()
    tree.feed(world.get("/feeds").text)
    assert tree.parent_of["feed-fixed"] == tree.parent_of["feed-scroll"]  # 같은 부모 아래의 형제


def test_each_last_published_option_names_its_band(world):
    form = world.get("/feeds").text.split('role="search">')[1].split("</form>")[0]
    labels = re.findall(r'<option value="(day|week|month|year|older)"[^>]*>([^<]+)</option>', form)
    assert labels == [
        ("day", "하루 이내"),
        ("week", "1주일 이내(하루 초과)"),
        ("month", "1달 이내(1주일 초과)"),
        ("year", "1년 이내(1달 초과)"),
        ("older", "1년 넘게 없음"),
    ]


# ---------- 작업을 해도 필터가 유지된다 ----------

BROWSER = {"origin": "null", "sec-fetch-site": "same-origin"}


def post(world, path, **data):
    return world.client.post(path, data=data, headers=BROWSER)


def test_the_panel_links_and_delete_forms_carry_the_current_filters(seeded):
    html = html_module.unescape(seeded.get("/feeds?cycle=1&last=day").text)
    here = "/feeds?cycle=1&last=day"
    assert "next=%2Ffeeds%3Fcycle%3D1%26last%3Dday" in html  # 카드의 설정 링크(값의 /도 인코딩)
    assert f'name="next" value="{here}"' in html  # 카드의 삭제 폼
    assert 'name="next" value="/feeds"' not in html  # 사이드바의 폼도 필터를 지킨다


def test_the_sidebar_forms_on_the_feed_page_keep_every_filter_and_nothing_else(seeded):
    html = html_module.unescape(
        seeded.get("/feeds?state=ok&q=%EA%B8%80&cycle=2&last=week&junk=1&page=3").text
    )
    assert 'name="next" value="/feeds?state=ok&q=%EA%B8%80&cycle=2&last=week"' in html
    assert "junk" not in html.split("<main")[0] if "<main" in html else True


def test_without_filters_the_return_address_is_the_plain_page(seeded):
    html = seeded.get("/feeds").text
    assert '?next=%2Ffeeds"' in html and 'name="next" value="/feeds"' in html


@pytest.mark.parametrize(
    "values", ["?cycle=2", "?last=week", "?q=%EA%B8%80&cycle=2&last=week&state=ok", "?state=error"]
)
def test_saving_a_feed_setting_returns_to_the_same_filtered_view(seeded, values):
    feed = seeded.feeds.list_all()[0].id
    response = post(
        seeded,
        f"/feeds/{feed}/settings",
        name="이름",
        emoji="📢",
        max_entries="",
        category_id="",
        webhook_id="",
        url=seeded.feeds.get(feed).url,
        next="/feeds" + values,
    )
    assert (
        response.status_code == 303
        and response.headers["location"] == f"/feeds{values}&toast=saved"
    )


def test_deleting_a_feed_returns_to_the_same_filtered_view(seeded):
    feed = seeded.feeds.list_all()[0].id
    response = post(seeded, f"/feeds/{feed}/delete", confirm="yes", next="/feeds?cycle=2&last=week")
    assert response.headers["location"] == "/feeds?cycle=2&last=week&toast=deleted"


def test_an_error_screen_keeps_the_filters_and_the_list(seeded):
    feed = seeded.feeds.list_all()[0].id
    response = post(
        seeded,
        f"/feeds/{feed}/settings",
        name="",
        emoji="📢",
        max_entries="",
        category_id="",
        webhook_id="",
        url="https://x.example.com/rss",
        next="/feeds?cycle=2&last=week",
    )
    html = response.text
    assert (
        response.status_code == 400
        and re.search(r'<option value="2" selected>', html)
        and re.search(r'<option value="week" selected>', html)
    )
    assert (
        "주 단위 글" in html.split('<ul class="feed-list">')[1]
        and "하루 전 글" not in html.split('<ul class="feed-list">')[1]
    )


def test_an_error_screen_of_a_delete_without_confirmation_keeps_the_filters_too(seeded):
    feed = seeded.feeds.list_all()[0].id
    html = post(seeded, f"/feeds/{feed}/delete", next="/feeds?cycle=3").text
    assert re.search(r'<option value="3" selected>', html)


@pytest.mark.security
@pytest.mark.parametrize(
    "nxt",
    [
        "/feeds?cycle=<script>&last=%27",
        "https://evil.example.com/feeds?cycle=2",
        "//evil.example.com/feeds",
        "/settings?cycle=2",
        "javascript:alert(1)",
    ],
)
def test_a_hostile_return_address_is_never_followed_or_trusted(seeded, nxt):
    feed = seeded.feeds.list_all()[0].id
    ok = post(
        seeded,
        f"/feeds/{feed}/settings",
        name="이름",
        emoji="📢",
        max_entries="",
        category_id="",
        webhook_id="",
        url=seeded.feeds.get(feed).url,
        next=nxt,
    )
    assert ok.status_code == 303 and not ok.headers["location"].startswith(
        ("http", "//", "javascript")
    )
    bad = post(
        seeded,
        f"/feeds/{feed}/settings",
        name="",
        emoji="📢",
        max_entries="",
        category_id="",
        webhook_id="",
        url="https://x.example.com/rss",
        next=nxt,
    )
    assert bad.status_code == 400 and "<script>" not in bad.text.replace("<script src", "").replace(
        "</script>", ""
    )


def test_the_filters_in_the_return_address_are_validated_like_the_query(seeded):
    feed = seeded.feeds.list_all()[0].id
    html = post(
        seeded,
        f"/feeds/{feed}/settings",
        name="",
        emoji="📢",
        max_entries="",
        category_id="",
        webhook_id="",
        url="https://x.example.com/rss",
        next="/feeds?cycle=9&last=bogus&state=zzz",
    ).text
    assert not re.search(r'<option value="9" selected>', html) and 'value="zzz"' not in html


@pytest.mark.parametrize(
    ("next_value", "expected"),
    [
        (
            "/feeds?q=a&state=ok&cycle=2&last=week",
            {"q": "a", "state": "ok", "cycle": "2", "last": "week"},
        ),
        ("/feeds", {"q": "", "state": "", "cycle": "", "last": ""}),
        ("/feeds?cycle=2&junk=1", {"q": "", "state": "", "cycle": "2", "last": ""}),
        (
            "/settings?cycle=2&q=a",
            {"q": "", "state": "", "cycle": "", "last": ""},
        ),  # 다른 화면의 조건은 이어받지 않는다
        ("", {"q": "", "state": "", "cycle": "", "last": ""}),
        ("//evil.example.com/feeds?cycle=2", {"q": "", "state": "", "cycle": "", "last": ""}),
    ],
)
def test_only_the_feed_page_conditions_are_carried_from_the_return_address(next_value, expected):
    from rss_hub.web.feeds import _carried

    assert _carried(next_value) == expected
