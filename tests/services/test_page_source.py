"""웹페이지 구독의 수집원: 글 목록 페이지를 일반 피드와 같은 모양으로 바꾼다."""

from datetime import UTC, datetime

import pytest

from rss_hub.services.page_source import MAX_ARTICLE_CHARS, NO_ITEMS, PageFeedSource, site_of
from rss_hub.services.ports import FetchError
from tests.fakes.clock import FakeClock
from tests.fakes.discovery_fetcher import FakeDiscoveryFetcher
from tests.fakes.page_html import BASE, article_html, listing, sample_items

LIST_URL = f"{BASE}/news"
NOW = datetime(2026, 10, 16, 5, 0, tzinfo=UTC)


@pytest.fixture
def env():
    pages = FakeDiscoveryFetcher()
    return pages, PageFeedSource(pages=pages, clock=FakeClock(NOW))


def test_the_list_becomes_a_fetch_result_with_one_entry_per_post(env):
    pages, source = env
    pages.page(LIST_URL, listing(sample_items(3), title="예제 블로그 - 소식"))
    result = source.fetch(LIST_URL)
    assert (result.status, result.etag, result.last_modified) == (200, None, None)
    assert result.title == "예제 블로그 - 소식" and result.site_url == f"{BASE}/"
    assert [(e["id"], e["link"]) for e in result.entries] == [
        (f"{BASE}/news/post-{n}", f"{BASE}/news/post-{n}") for n in (1, 2, 3)
    ]
    assert result.entries[0]["title"].startswith("새 소식 1번")


def test_undated_posts_get_the_fetch_time_in_list_order(env):
    pages, source = env
    pages.page(LIST_URL, listing(sample_items(3)))
    stamps = [datetime.fromisoformat(e["published"]) for e in source.fetch(LIST_URL).entries]
    assert stamps[0] == NOW and stamps[0] > stamps[1] > stamps[2]  # 목록 순서를 지킨다
    assert all(s.date() == NOW.date() for s in stamps)


def test_dated_posts_use_their_own_date(env):
    pages, source = env
    pages.page(
        LIST_URL,
        listing(
            [
                ("a", "날짜가 있는 첫째 글의 제목입니다", "2026-10-15"),
                ("b", "날짜가 있는 둘째 글의 제목입니다", "2026-10-16"),
                ("c", "날짜가 없는 셋째 글의 제목입니다", None),
            ]
        ),
    )
    assert [e["published"] for e in source.fetch(LIST_URL).entries][:2] == [
        "2026-10-15T12:00:00",
        "2026-10-16T12:00:00",
    ]


def test_a_page_without_posts_fails_so_the_state_turns_red(env):
    pages, source = env
    pages.page(LIST_URL, "<html><body><p>구조가 바뀌었습니다</p></body></html>")
    with pytest.raises(FetchError) as caught:
        source.fetch(LIST_URL)
    assert caught.value.reason == NO_ITEMS


def test_a_fetch_failure_passes_its_reason_through(env):
    pages, source = env
    pages.fail(LIST_URL, "ReadTimeout")
    with pytest.raises(FetchError) as caught:
        source.fetch(LIST_URL)
    assert caught.value.reason == "ReadTimeout"


def test_a_redirect_makes_relative_links_follow_the_final_address(env):
    pages, source = env
    pages.page(LIST_URL, listing(sample_items(3)))
    pages.final_urls[LIST_URL] = f"{BASE}/news/"
    assert source.fetch(LIST_URL).entries[0]["link"] == f"{BASE}/news/post-1"


def test_the_article_body_is_cleaned_text_from_the_post_page(env):
    pages, source = env
    pages.page(f"{BASE}/news/post-1", article_html(1))
    html = source.read_article(f"{BASE}/news/post-1")
    assert "1번 글의 1번째 본문 문단입니다" in html and "<script" not in html


@pytest.mark.parametrize("mode", ["error", "no_body", "crash"])
def test_a_post_page_that_cannot_be_read_gives_an_empty_body(env, mode):
    pages, source = env
    url = f"{BASE}/news/post-9"
    if mode == "error":
        pages.fail(url, "ReadTimeout")
    elif mode == "no_body":
        pages.page(url, "<html><body><p>짧음</p></body></html>")
    else:
        pages.fetch_page = lambda _url: (_ for _ in ()).throw(RuntimeError("예상 못한 오류"))
    assert source.read_article(url) == ""


def test_a_very_long_body_is_cut_to_the_limit(env):
    pages, source = env
    pages.page(
        f"{BASE}/news/long",
        "<html><body><article>"
        + "<p>"
        + "긴 본문 문장입니다. " * 20
        + "</p>" * 1
        + ("<p>" + "또 긴 문단입니다. " * 30 + "</p>") * 400
        + "</article></body></html>",
    )
    assert len(source.read_article(f"{BASE}/news/long")) <= MAX_ARTICLE_CHARS


@pytest.mark.parametrize(
    ("url", "site"),
    [
        ("https://a.example.com/x/y?z=1", "https://a.example.com/"),
        ("http://a.example.com:8080/p", "http://a.example.com:8080/"),
        ("not a url", ""),
        ("", ""),
    ],
)
def test_the_site_front_address_of_a_page(url, site):
    assert site_of(url) == site
