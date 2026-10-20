"""웹페이지 구독 피드의 수집: 일반 피드와 같은 기준선, 오늘 글, 알림 규칙을 따른다."""

import pytest

from rss_hub.services.collect import MAX_ENRICH_PER_RUN, CollectService
from rss_hub.services.page_source import NO_ITEMS, PageFeedSource
from rss_hub.storage.feeds import KIND_PAGE, STATUS_ACTIVE, STATUS_BASELINE
from tests.fakes.collect_env import CollectEnv
from tests.fakes.discovery_fetcher import FakeDiscoveryFetcher
from tests.fakes.entries import today
from tests.fakes.page_html import BASE, article_html, listing, sample_items

LIST_URL = f"{BASE}/news"


class PageEnv(CollectEnv):
    def __init__(self, tmp_path):
        super().__init__(tmp_path)
        self.pages = FakeDiscoveryFetcher()
        self.service = CollectService(
            feeds=self.feeds,
            articles=self.articles,
            fetcher=self.fetcher,
            settings=self.settings,
            clock=self.clock,
            pages=PageFeedSource(pages=self.pages, clock=self.clock),
        )

    def add_page_feed(self, *, status=STATUS_BASELINE):
        return self.feeds.add(LIST_URL, "예제 블로그", status=status, kind=KIND_PAGE)


@pytest.fixture
def env(tmp_path):
    return PageEnv(tmp_path)


def show(env, count, *, dated=False):
    env.pages.page(LIST_URL, listing(sample_items(count, dated=dated)))


def test_the_first_check_only_records_a_baseline_and_makes_the_feed_active(env):
    feed = env.add_page_feed()
    show(env, 5)
    report = env.collect(feed)
    assert env.collected() == [] and report.baseline_recorded == 5 and report.failed == ()
    assert all(env.articles.is_seen(f"{BASE}/news/post-{n}") for n in range(1, 6))
    assert env.feeds.get(feed).status == STATUS_ACTIVE
    assert env.pages.page_calls == [LIST_URL]  # 글 페이지는 아직 가져오지 않는다
    assert env.fetcher.calls == []  # RSS 수집기는 부르지 않는다


def test_a_new_post_after_the_baseline_is_stored_with_its_body_from_the_post_page(env):
    feed = env.add_page_feed()  # 첫 점검 전
    show(env, 3)
    env.collect(feed)  # 기준선: 있던 글 3개는 기록만
    env.pages.page(f"{BASE}/news/post-4", article_html(4))
    show(env, 4)
    report = env.collect(feed)
    stored = env.collected()
    assert report.added == 1 and [a.guid for a in stored] == [f"{BASE}/news/post-4"]
    assert "4번 글의 1번째 본문 문단입니다" in stored[0].content_html
    assert stored[0].link == f"{BASE}/news/post-4" and stored[0].title.startswith("새 소식 4번")
    assert stored[0].feed_id == feed


def test_posts_already_seen_are_not_stored_again_nor_fetched_again(env):
    feed = env.add_page_feed()
    show(env, 3)
    env.collect(feed)  # 기준선
    first = len(env.pages.page_calls)
    env.collect(feed)
    env.collect(feed)
    assert env.collected() == [] and len(env.pages.page_calls) == first + 2  # 목록 두 번만


def test_only_the_first_ten_new_posts_get_their_body_fetched_but_all_are_stored(env):
    feed = env.add_page_feed(status=STATUS_ACTIVE)
    show(env, 12)
    for n in range(1, 13):
        env.pages.page(f"{BASE}/news/post-{n}", article_html(n))
    report = env.collect(feed)
    bodies = [a.content_html for a in env.collected()]
    assert report.added == 12 and len(bodies) == 12
    assert (
        sum(1 for b in bodies if b) == MAX_ENRICH_PER_RUN and sum(1 for b in bodies if not b) == 2
    )


def test_a_post_page_that_cannot_be_read_is_stored_with_the_title_only(env):
    feed = env.add_page_feed(status=STATUS_ACTIVE)
    show(env, 3)
    env.pages.fail(f"{BASE}/news/post-1", "ReadTimeout")
    report = env.collect(feed)
    assert report.added == 3 and all(a.title for a in env.collected())
    assert [a.content_html for a in env.collected() if a.guid.endswith("post-1")] == [""]


def test_listed_dates_follow_the_today_only_rule_like_any_feed(env):
    feed = env.add_page_feed(status=STATUS_ACTIVE)
    env.pages.page(
        LIST_URL,
        listing(
            [
                ("old", "어제 날짜가 적힌 글의 제목입니다", "2026-10-15"),
                ("new", "오늘 날짜가 적힌 글의 제목입니다", "2026-10-16"),
                ("none", "날짜가 없는 글의 제목입니다 길게", None),
            ]
        ),
    )
    env.collect(feed)
    assert sorted(a.guid.rsplit("/", 1)[1] for a in env.collected()) == ["new", "none"]


def test_a_list_without_posts_is_recorded_as_a_failure_with_the_reason(env):
    feed = env.add_page_feed(status=STATUS_ACTIVE)
    env.pages.page(LIST_URL, "<html><body><p>구조가 바뀌었습니다</p></body></html>")
    report = env.collect(feed)
    assert report.failed == ((feed, NO_ITEMS),) and report.added == 0
    saved = env.feeds.get(feed)
    assert saved.last_error == NO_ITEMS and saved.fail_count == 1


def test_a_failed_list_fetch_is_recorded_with_its_own_reason_and_recovers_later(env):
    feed = env.add_page_feed(status=STATUS_ACTIVE)
    env.pages.fail(LIST_URL, "ReadTimeout")
    assert env.collect(feed).failed == ((feed, "ReadTimeout"),)
    env.pages.errors.clear()
    show(env, 3)
    assert env.collect(feed).failed == () and env.feeds.get(feed).fail_count == 0


def test_a_page_feed_without_a_page_source_fails_safely(tmp_path):
    env = CollectEnv(tmp_path)
    feed = env.feeds.add(LIST_URL, "예제", status=STATUS_ACTIVE, kind=KIND_PAGE)
    assert env.collect(feed).failed == ((feed, "PageSourceUnavailable"),)


def test_regular_feeds_never_touch_the_page_source(env):
    feed_id, url = env.add_feed()
    env.fetcher.serve(url, today(2))
    assert env.collect(feed_id).added == 2 and env.pages.page_calls == []


def test_a_regular_feed_article_keeps_its_own_summary_even_next_to_page_feeds(env):
    feed_id, url = env.add_feed()
    env.fetcher.serve(url, today(1))
    env.collect(feed_id)
    assert env.collected()[0].content_html == "<p>요약 1</p>" or env.collected()[0].content_html
