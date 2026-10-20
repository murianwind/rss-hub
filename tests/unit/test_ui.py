from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from rss_hub.web.ui import ICONS, ago, icon, list_url, safe_path, sprite, with_toast

SEOUL = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("delta", "text"),
    [
        (timedelta(seconds=0), "방금"),
        (timedelta(seconds=59), "방금"),
        (timedelta(seconds=-30), "방금"),  # 시계가 조금 어긋나 미래로 보여도 어색하지 않게
        (timedelta(minutes=1), "1분 전"),
        (timedelta(minutes=59, seconds=59), "59분 전"),
        (timedelta(hours=1), "1시간 전"),
        (timedelta(hours=23, minutes=59), "23시간 전"),
        (timedelta(days=1), "1일 전"),
        (timedelta(days=6, hours=23), "6일 전"),
    ],
)
def test_relative_time_is_short_and_korean(delta, text):
    assert ago(NOW - delta, NOW, SEOUL) == text


def test_older_than_a_week_shows_the_date_in_the_service_time_zone():
    moment = datetime(2026, 10, 10, 16, 30, tzinfo=UTC)  # 한국 시각으로는 10월 11일 01:30
    assert ago(moment, NOW, SEOUL) == "2026-10-11"


# ---------- 주소 ----------


@pytest.mark.parametrize(
    ("kwargs", "url"),
    [
        ({}, "/reader"),
        ({"page": 1}, "/reader"),
        ({"page": 3}, "/reader?page=3"),
        ({"query": "squid game"}, "/reader?q=squid+game"),
        ({"only": "unread"}, "/reader?only=unread"),
        (
            {"page": 2, "query": "오징어", "only": "bookmarks"},
            "/reader?page=2&q=%EC%98%A4%EC%A7%95%EC%96%B4&only=bookmarks",
        ),
    ],
)
def test_list_urls_leave_out_default_values(kwargs, url):
    assert list_url("/reader", **kwargs) == url


@pytest.mark.parametrize(
    "path",
    [
        "/reader",
        "/reader/feed/3",
        "/reader/category/2",
        "/reader/topic/1",
        "/reader/bookmarks",
        "/a/5",
        "/topics/1/suggestions",
        "/reader?page=2&q=ab&only=unread",
        "/reader/feed/3?q=%EC%98%A4",
    ],
)
def test_reading_pages_are_valid_return_paths(path):
    assert safe_path(path, "/default") == path


@pytest.mark.security
@pytest.mark.parametrize(
    "path",
    [
        "https://evil.example.com/",
        "//evil.example.com/",
        "/\\evil.example.com",
        "javascript:alert(1)",
        "/settings",
        "/a/1/../../x",
        "/reader?x=<script>",
        "/reader?x=1;2",
        "/reader#frag",
        "/reader/feed/abc",
        "",
        None,
        5,
        "/reader?" + "a" * 400,
    ],
)
def test_other_return_paths_fall_back_to_the_default(path):
    assert safe_path(path, "/default") == "/default"


def test_a_toast_key_is_added_to_the_address():
    assert with_toast("/reader", "read_all") == "/reader?toast=read_all"
    assert with_toast("/reader?page=2", "read_all") == "/reader?page=2&toast=read_all"


# ---------- 아이콘 ----------


def test_an_icon_points_at_the_sprite_symbol_and_is_hidden_from_screen_readers():
    html = str(icon("rss"))
    assert 'href="#i-rss"' in html and 'aria-hidden="true"' in html and 'class="icon"' in html


def test_an_icon_can_carry_an_extra_class_and_escapes_its_name():
    assert 'class="icon fill"' in str(icon("bookmark", "fill"))
    assert '"><script>' not in str(icon('"><script>alert(1)</script>'))


def test_the_sprite_defines_every_icon_exactly_once():
    html = str(sprite())
    assert all(html.count(f'id="i-{name}"') == 1 for name in ICONS)
    assert "<script" not in html and "onload" not in html
