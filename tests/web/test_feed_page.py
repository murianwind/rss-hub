"""피드 관리 화면: 상태, 활동량, 자동 배정된 수집 주기, 거르기, 패널로 이어지는 추가 흐름."""

import html as html_module
import re

import pytest

from rss_hub.domain.activity import FeedMeasurement
from rss_hub.domain.schedule import Activity
from tests.fakes.discovery_fetcher import FakeDiscoveryFetcher
from tests.fakes.viewer_world import World
from tests.fakes.web_parts import start_app

BROWSER = {"origin": "null", "sec-fetch-site": "same-origin"}
FRAGMENT = {"x-panel": "1"}


@pytest.fixture
def world(tmp_path):
    fetcher = FakeDiscoveryFetcher()
    parts, client = start_app(tmp_path, feed_fetcher=fetcher)
    with client:
        w = World(parts)
        w.fetcher = fetcher
        yield w


def row(html, name):
    rows = html.split('<li class="feed-row">')[1:]
    return html_module.unescape(next(r for r in rows if name in r.split("</li>")[0]))


def listing(html):
    """사이드바를 뺀 본문의 피드 목록."""
    return html_module.unescape(html.split('<ul class="feed-list">')[1].split("</ul>")[0])


def measure(world, feed, recent, today):
    world.feeds.save_stats(feed, FeedMeasurement(Activity(recent, today), world.parts.clock.now()))


def test_every_feed_is_listed_with_state_address_category_and_alert_target(world):
    html = world.get("/feeds").text
    news = row(html, "뉴스 블로그")
    assert (
        "https://n.example.com/rss" in news
        and "뉴스 ·" in news
        and "카테고리 '뉴스'의 웹훅을 따름" in news
    )
    assert (
        'class="state-dot never"' in news
        and "아직 점검하지 않았습니다" in news
        and "첫 점검 대기" in news
    )
    assert "기본 웹훅" in row(html, "자유 블로그")


def test_the_state_dot_and_details_follow_the_real_state(world):
    world.feeds.record_success(world.f_free, etag=None, last_modified=None, activate=True)
    world.feeds.record_failure(world.f_news, "ReadTimeout")
    html = world.get("/feeds").text
    assert 'class="state-dot ok"' in row(html, "자유 블로그") and "· 정상" in row(
        html, "자유 블로그"
    )
    bad = row(html, "뉴스 블로그")
    assert (
        'class="state-dot error"' in bad
        and "연속 실패 1회: ReadTimeout" in bad
        and 'title="오류: ReadTimeout"' in bad
    )


def test_a_quiet_feed_gets_one_check_an_hour_and_a_busy_one_gets_three(world):
    measure(world, world.f_free, recent=0, today=0)
    measure(world, world.f_news, recent=10, today=4)
    html = world.get("/feeds").text
    assert "시간당 1회(약 60분마다)" in row(html, "자유 블로그")
    assert "시간당 3회(약 20분마다)" in row(html, "뉴스 블로그")


def test_the_real_minutes_and_the_next_check_are_shown(world):
    html = world.get("/feeds").text
    free = row(html, "자유 블로그")
    minutes = re.search(r"매시 ((?:\d\d분(?:, )?)+)", free).group(1)
    assert all(int(m[:2]) % 5 == 0 for m in minutes.split(", "))
    assert re.search(r"다음 점검 \d\d:\d\d", free)


def test_the_activity_line_shows_today_week_and_the_last_post(world):
    measure(world, world.f_free, recent=7, today=2)
    line = row(world.get("/feeds").text, "자유 블로그")
    assert "오늘 2개 · 최근 7일 7개 · 마지막 게시" in line
    assert "게시 기록 없음" in row(world.get("/feeds").text, "뉴스 블로그")


def test_article_counts_and_the_max_entries_are_shown(world):
    world.article(world.f_free)
    world.article(world.f_free)
    world.articles.mark_read(world.articles.get(1).id)
    line = row(world.get("/feeds").text, "자유 블로그")
    assert "수집한 글 2개(읽지 않은 글 1개)" in line and "최대 항목 수 50(기본값)" in line


def test_the_note_explains_the_automatic_variable_schedule(world):
    html = world.get("/feeds").text
    assert "자동으로 가변 배정" in html and "시간당 최대 3회" in html and "5분마다" in html


def test_the_state_chips_show_counts_and_filter_the_list(world):
    world.feeds.record_failure(world.f_news, "x")
    world.feeds.record_success(world.f_free, etag=None, last_modified=None, activate=True)
    html = world.get("/feeds").text
    assert (
        re.search(r"전체 2\s*</a>", html)
        and "정상 1" in html
        and "오류 1" in html
        and "수집 전 0" in html
    )
    only_bad = world.get("/feeds?state=error").text
    assert "뉴스 블로그" in listing(only_bad) and "자유 블로그" not in listing(only_bad)
    assert 'chip-link on" href="/feeds?state=error"' in only_bad
    assert "이 상태의 피드가 없습니다" in world.get("/feeds?state=never").text


def test_an_unknown_filter_shows_everything(world):
    html = listing(world.get("/feeds?state=nonsense").text)
    assert "뉴스 블로그" in html and "자유 블로그" in html


def test_each_row_has_refresh_settings_and_delete_buttons_that_return_to_this_page(world):
    html = row(world.get("/feeds").text, "자유 블로그")
    assert f'data-refresh="{world.f_free}"' in html
    assert f'href="/panel/settings/feed/{world.f_free}?next=%2Ffeeds" data-panel' in html
    assert f'href="/panel/delete/feed/{world.f_free}?next=%2Ffeeds" data-panel' in html


def test_titles_and_addresses_are_escaped(world):
    world.feeds.add("https://x.example.com/rss", "<img src=x onerror=alert(1)>")
    html = world.get("/feeds").text
    assert "<img src=x" not in html and "&lt;img src=x" in html


def test_an_empty_service_explains_where_to_add_feeds(tmp_path):
    _parts, client = start_app(tmp_path)
    with client:
        html = client.get("/feeds").text
        assert "등록된 피드가 없습니다" in html and "RSS 피드 <b>+</b>" in html


# ---------- 추가는 패널에서 끝까지 ----------


def test_the_add_panel_discovers_feeds_and_registers_one_and_returns_to_the_screen(world):
    world.fetcher.feed("https://new.example.com/rss", "새 피드", "https://new.example.com/")
    found = world.client.post(
        "/feeds/discover",
        data={"url": "https://new.example.com/rss", "next": "/reader"},
        headers=BROWSER | FRAGMENT,
    )
    assert found.status_code == 200 and "<html" not in found.text
    assert (
        "찾은 피드" in found.text
        and "새 피드" in found.text
        and 'action="/feeds/register"' in found.text
    )
    assert 'name="next" value="/reader"' in found.text
    done = world.client.post(
        "/feeds/register",
        data={"url": "https://new.example.com/rss", "name": "새 피드", "next": "/reader"},
        headers=BROWSER,
    )
    assert done.headers["location"] == "/reader?toast=added"
    assert "새 피드" in world.get("/reader").text


def test_without_the_script_the_same_flow_is_a_full_page(world):
    world.fetcher.feed("https://new.example.com/rss", "새 피드")
    page = world.client.post(
        "/feeds/discover", data={"url": "https://new.example.com/rss"}, headers=BROWSER
    ).text
    assert "<html" in page and 'class="slide static"' in page and "새 피드" in page


def test_a_bad_address_shows_the_reason_inside_the_panel(world):
    response = world.client.post(
        "/feeds/discover", data={"url": "http://127.0.0.1/rss"}, headers=BROWSER | FRAGMENT
    )
    assert (
        response.status_code == 400
        and 'class="banner error"' in response.text
        and 'value="http://127.0.0.1/rss"' in response.text
    )


def test_a_failed_registration_keeps_the_address_and_says_why(world):
    world.fetcher.fail("https://down.example.com/rss", "ReadTimeout")
    response = world.client.post(
        "/feeds/register",
        data={"url": "https://down.example.com/rss", "name": "x"},
        headers=BROWSER | FRAGMENT,
    )
    assert (
        response.status_code == 400
        and 'class="banner error"' in response.text
        and "down.example.com" in response.text
    )


@pytest.mark.security
def test_the_return_address_of_the_add_flow_is_checked(world):
    world.fetcher.feed("https://new.example.com/rss", "새 피드")
    found = world.client.post(
        "/feeds/discover",
        data={"url": "https://new.example.com/rss", "next": "https://evil.example.com/"},
        headers=BROWSER | FRAGMENT,
    ).text
    assert "evil.example.com" not in found
    done = world.client.post(
        "/feeds/register",
        data={
            "url": "https://new.example.com/rss",
            "name": "n",
            "next": "https://evil.example.com/",
        },
        headers=BROWSER,
    )
    assert done.headers["location"] == "/feeds?added=1"
