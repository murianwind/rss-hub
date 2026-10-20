import pytest

from rss_hub.services.feed_registration import (
    ALL_SUBSCRIBED,
    ALREADY_SUBSCRIBED,
    MAX_CANDIDATES,
    NOTHING_FOUND,
    PAGE_HAS_FEEDS,
    FeedRegistrationService,
)
from rss_hub.services.settings import SettingsService
from rss_hub.storage.database import Database
from rss_hub.storage.feeds import STATUS_BASELINE, FeedRepository
from tests.fakes.clock import FakeClock
from tests.fakes.discovery_fetcher import FakeDiscoveryFetcher

PAGE_URL = "https://blog.example.com/"


def link(href, title=""):
    return f'<link rel="alternate" type="application/rss+xml" title="{title}" href="{href}">'


class Env:
    def __init__(self, tmp_path):
        self.db = Database(tmp_path / "rss_hub.db")
        self.clock = FakeClock()
        self.feeds = FeedRepository(self.db, self.clock)
        self.settings = SettingsService(self.db, self.clock)
        self.fetcher = FakeDiscoveryFetcher()
        self.service = FeedRegistrationService(fetcher=self.fetcher, feeds=self.feeds)
        self.feeds.add("https://a.example.com/feed", "이미 있는 피드")


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


# ---------- 주소 확인: 피드 주소 ----------


def test_a_feed_address_gives_one_candidate_with_the_feed_title_and_site(env):
    env.fetcher.feed("https://new.example.com/rss", "새 블로그", "https://new.example.com")
    result = env.service.discover("https://new.example.com/rss")
    assert result.error == ""
    assert [(c.url, c.title, c.site_url) for c in result.candidates] == [
        ("https://new.example.com/rss", "새 블로그", "https://new.example.com")
    ]
    assert env.fetcher.page_calls == []  # 피드이면 웹페이지를 따로 가져오지 않는다


def test_a_feed_without_a_title_is_named_after_its_site(env):
    env.fetcher.feed("https://untitled.example.com/rss")
    assert (
        env.service.discover("https://untitled.example.com/rss").candidates[0].title
        == "untitled.example.com"
    )


def test_surrounding_spaces_in_the_address_are_ignored(env):
    env.fetcher.feed("https://new.example.com/rss", "새 블로그")
    assert (
        env.service.discover("  https://new.example.com/rss \n").candidates[0].title == "새 블로그"
    )


def test_an_address_that_is_already_subscribed_is_reported_without_any_request(env):
    for same in (
        "https://a.example.com/feed",
        "https://A.Example.com/feed/",
        "  https://a.example.com/feed  ",
    ):
        assert env.service.discover(same).error == ALREADY_SUBSCRIBED
    assert env.fetcher.fetch_calls == []


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("", "주소 없음"),
        ("ftp://x.example.com/feed", "http, https만 가능"),
        ("javascript:alert(1)", "http, https만 가능"),
        ("http://192.168.0.10/rss", "사설망·내부 주소는 허용하지 않음"),
        ("http://localhost/rss", "사설망·내부 주소는 허용하지 않음"),
        ("http://169.254.169.254/latest/meta-data", "사설망·내부 주소는 허용하지 않음"),
        ("https://a.example.com:99999/rss", "주소 형식이 올바르지 않음"),
    ],
)
def test_bad_addresses_are_refused_before_any_request(env, raw, message):
    assert env.service.discover(raw).error == message
    assert env.fetcher.fetch_calls == [] and env.fetcher.page_calls == []


@pytest.mark.parametrize(
    ("reason", "message"),
    [
        ("HTTP 404", "주소를 열지 못했습니다(HTTP 404)"),
        ("ConnectionError", "주소에 연결하지 못했습니다"),
        ("ReadTimeout", "응답이 없습니다(시간 초과)"),
        ("ForbiddenAddress", "사설망·내부 주소는 허용하지 않음"),
        ("TooLarge", "응답이 너무 큽니다"),
    ],
)
def test_a_failed_fetch_is_explained(env, reason, message):
    env.fetcher.fail("https://x.example.com/rss", reason)
    assert env.service.discover("https://x.example.com/rss").error == message


# ---------- 주소 확인: 웹페이지 ----------


def test_a_web_page_gives_the_feeds_it_announces_with_full_addresses(env):
    env.fetcher.page(PAGE_URL, link("/feed.xml", "글") + link("/comments.xml", "댓글"))
    env.fetcher.feed("https://blog.example.com/feed.xml", "블로그 글", "https://blog.example.com")
    env.fetcher.feed("https://blog.example.com/comments.xml", "")
    result = env.service.discover(PAGE_URL)
    assert [(c.url, c.title) for c in result.candidates] == [
        ("https://blog.example.com/feed.xml", "블로그 글"),
        ("https://blog.example.com/comments.xml", "댓글"),  # 피드 제목이 없으면 링크의 제목
    ]


def test_relative_links_are_resolved_against_the_final_address_after_redirects(env):
    env.fetcher.page("https://short.example.com/x", link("feed.xml"))
    env.fetcher.final_urls["https://short.example.com/x"] = "https://real.example.com/blog/post/"
    env.fetcher.feed("https://real.example.com/blog/post/feed.xml", "진짜 블로그")
    assert env.service.discover("https://short.example.com/x").candidates[0].url == (
        "https://real.example.com/blog/post/feed.xml"
    )


def test_a_link_that_turns_out_not_to_be_a_feed_is_dropped_and_the_rest_are_kept(env):
    env.fetcher.page(PAGE_URL, link("/broken.xml") + link("/good.xml"))
    env.fetcher.fail("https://blog.example.com/broken.xml", "HTTP 500")
    env.fetcher.feed("https://blog.example.com/good.xml", "좋은 피드")
    assert [c.title for c in env.service.discover(PAGE_URL).candidates] == ["좋은 피드"]


def test_links_to_private_addresses_are_never_requested(env):
    env.fetcher.page(
        PAGE_URL, link("http://192.168.0.10/rss") + link("http://localhost/rss") + link("/ok.xml")
    )
    env.fetcher.feed("https://blog.example.com/ok.xml", "공개 피드")
    result = env.service.discover(PAGE_URL)
    assert [c.title for c in result.candidates] == ["공개 피드"]
    assert all("192.168" not in url and "localhost" not in url for url in env.fetcher.fetch_calls)


def test_subscribed_feeds_are_left_out_of_the_candidates(env):
    env.fetcher.page(PAGE_URL, link("https://a.example.com/feed") + link("/new.xml"))
    env.fetcher.feed("https://blog.example.com/new.xml", "새 피드")
    result = env.service.discover(PAGE_URL)
    assert [c.title for c in result.candidates] == ["새 피드"]
    assert "https://a.example.com/feed" not in env.fetcher.fetch_calls


def test_when_every_announced_feed_is_already_subscribed_that_is_said(env):
    env.fetcher.page(PAGE_URL, link("https://a.example.com/feed"))
    assert env.service.discover(PAGE_URL).error == ALL_SUBSCRIBED


def test_a_page_without_feed_links_says_nothing_was_found(env):
    env.fetcher.page(PAGE_URL, "<html><body>링크 없음</body></html>")
    assert env.service.discover(PAGE_URL).error == NOTHING_FOUND


def test_a_page_whose_links_are_all_broken_says_nothing_was_found(env):
    env.fetcher.page(PAGE_URL, link("/a.xml") + link("/b.xml"))
    assert env.service.discover(PAGE_URL).error == NOTHING_FOUND


def test_at_most_five_candidates_are_verified_and_shown(env):
    env.fetcher.page(PAGE_URL, "".join(link(f"/f{i}.xml") for i in range(8)))
    for i in range(8):
        env.fetcher.feed(f"https://blog.example.com/f{i}.xml", f"피드{i}")
    result = env.service.discover(PAGE_URL)
    assert len(result.candidates) == MAX_CANDIDATES
    assert len([u for u in env.fetcher.fetch_calls if u.endswith(".xml")]) == MAX_CANDIDATES


def test_a_page_that_cannot_be_fetched_is_explained(env):
    env.fetcher.page(PAGE_URL, "")  # 피드가 아닌 웹페이지라서 페이지를 가져오는데
    env.fetcher.page_errors[PAGE_URL] = "SSLError"  # 그 단계에서 실패한다
    assert env.service.discover(PAGE_URL).error == "보안 연결(HTTPS)을 확인하지 못했습니다"


# ---------- 등록 ----------


def test_registering_creates_a_baseline_pending_feed_with_the_title_and_site(env):
    env.fetcher.feed("https://new.example.com/rss", "새 블로그", "https://new.example.com")
    result = env.service.register("https://new.example.com/rss")
    feed = env.feeds.get(result.feed_id)
    assert (feed.name, feed.html_url, feed.status) == (
        "새 블로그",
        "https://new.example.com",
        STATUS_BASELINE,
    )
    assert (feed.category_id, feed.webhook_id, feed.poll_priority) == (None, None, "normal")


def test_a_name_typed_by_the_user_wins_over_the_feed_title(env):
    env.fetcher.feed("https://new.example.com/rss", "새 블로그")
    result = env.service.register("https://new.example.com/rss", name="  내가 붙인 이름  ")
    assert env.feeds.get(result.feed_id).name == "내가 붙인 이름" == result.name


def test_a_name_over_two_hundred_characters_is_refused(env):
    env.fetcher.feed("https://new.example.com/rss", "x")
    result = env.service.register("https://new.example.com/rss", name="가" * 201)
    assert result.error == "이름은 200자까지" and result.feed_id is None


def test_the_feed_is_checked_again_at_registration_so_a_forged_address_is_not_saved(env):
    env.fetcher.page("https://evil.example.com/x", "<html></html>")  # 피드가 아닌 웹페이지
    result = env.service.register("https://evil.example.com/x")
    assert result.error == "피드가 아닙니다" and result.feed_id is None
    assert len(env.feeds.list_all()) == 1


def test_a_feed_that_stopped_working_since_the_preview_is_not_saved(env):
    env.fetcher.fail("https://new.example.com/rss", "HTTP 410")
    assert (
        env.service.register("https://new.example.com/rss").error
        == "주소를 열지 못했습니다(HTTP 410)"
    )


@pytest.mark.parametrize("raw", ["", "ftp://x.example.com/f", "http://192.168.0.10/rss"])
def test_registering_a_bad_address_fetches_nothing(env, raw):
    assert env.service.register(raw).error and env.fetcher.fetch_calls == []


def test_an_already_subscribed_feed_is_not_registered_twice(env):
    assert env.service.register("https://a.example.com/feed").error == ALREADY_SUBSCRIBED
    assert len(env.feeds.list_all()) == 1


def test_a_feed_can_join_a_category_when_it_is_registered(env):
    env.fetcher.feed("https://new.example.com/rss", "새 블로그")
    category_id = env.feeds.add_category("뉴스")
    result = env.service.register("https://new.example.com/rss", category_id=category_id)
    assert env.feeds.get(result.feed_id).category_id == category_id


def test_a_feed_outside_any_category_can_get_its_own_webhook(env):
    env.fetcher.feed("https://new.example.com/rss", "새 블로그")
    webhook_id = env.settings.add_webhook("dev", "https://discord.com/api/webhooks/1/abc")
    result = env.service.register("https://new.example.com/rss", webhook_id=webhook_id)
    assert env.feeds.get(result.feed_id).webhook_id == webhook_id


def test_a_category_and_a_feed_webhook_together_are_refused_without_saving(env):
    env.fetcher.feed("https://new.example.com/rss", "새 블로그")
    webhook_id = env.settings.add_webhook("dev", "https://discord.com/api/webhooks/1/abc")
    category_id = env.feeds.add_category("뉴스")
    result = env.service.register(
        "https://new.example.com/rss", category_id=category_id, webhook_id=webhook_id
    )
    assert (
        result.error == "카테고리에 속한 피드는 웹훅을 지정할 수 없음"
        and len(env.feeds.list_all()) == 1
    )


def test_an_unknown_webhook_is_refused_without_saving(env):
    env.fetcher.feed("https://new.example.com/rss", "새 블로그")
    assert (
        env.service.register("https://new.example.com/rss", webhook_id=999).error
        == "웹훅을 찾을 수 없음"
    )
    assert len(env.feeds.list_all()) == 1


def test_a_feed_added_by_someone_else_between_the_check_and_the_save_is_reported_as_a_duplicate(
    env,
):
    env.fetcher.feed("https://a.example.com/feed", "같은 피드")
    env.feeds.existing_url_keys = lambda: set()  # 확인 시점에는 아직 없었던 것처럼
    assert env.service.register("https://a.example.com/feed").error == ALREADY_SUBSCRIBED
    assert len(env.feeds.list_all()) == 1


# ---------- 주소 검사(피드 수정 때 쓴다): 저장하지 않고 정상적인 피드인지만 본다 ----------


@pytest.mark.parametrize(
    "bad",
    ["ftp://x.example.com/rss", "javascript:alert(1)", "http://192.168.0.5/rss", "", "not a url"],
)
def test_resolve_refuses_an_address_that_breaks_the_address_rules_without_fetching(env, bad):
    result = env.service.resolve(bad)
    assert result.error and env.fetcher.fetch_calls == [] and env.fetcher.page_calls == []


def test_resolve_takes_a_real_feed_as_a_feed_and_reports_its_site_and_title_without_saving(env):
    env.fetcher.feed("https://new.example.com/rss", "새 블로그", "https://new.example.com")
    before = len(env.feeds.existing_url_keys())
    result = env.service.resolve("https://new.example.com/rss")
    assert (result.error, result.kind, result.site_url, result.title) == (
        "",
        "feed",
        "https://new.example.com",
        "새 블로그",
    )
    assert len(env.feeds.existing_url_keys()) == before and env.fetcher.page_calls == []


@pytest.mark.parametrize(
    ("reason", "message"),
    [("NotAFeed", "피드가 아닙니다"), ("ReadTimeout", "시간 초과"), ("ForbiddenAddress", "사설망")],
)
def test_resolve_turns_a_fetch_failure_into_a_short_reason(env, reason, message):
    env.fetcher.fail("https://new.example.com/rss", reason)
    result = env.service.resolve("https://new.example.com/rss")
    assert message in result.error


# ---------- 웹페이지 구독(RSS가 없는 사이트) ----------

LIST_PAGE = "https://blog.example.com/news"


def with_posts(env, count=4, url=LIST_PAGE):
    from tests.fakes.page_html import listing, sample_items

    env.fetcher.page(url, listing(sample_items(count)))


def test_a_page_without_feed_links_but_with_a_post_list_offers_a_web_page_subscription(env):
    with_posts(env)
    result = env.service.discover(LIST_PAGE)
    assert result.error == ""
    (candidate,) = result.candidates
    assert (candidate.kind, candidate.url, candidate.count) == ("page", LIST_PAGE, 4)
    assert (
        candidate.title == "예제 블로그 - 소식"
        and candidate.site_url == "https://blog.example.com/"
    )
    assert candidate.sample[0].startswith("새 소식 1번") and len(candidate.sample) == 4


def test_a_page_with_too_few_posts_is_still_nothing_found(env):
    with_posts(env, count=2)
    assert env.service.discover(LIST_PAGE).error == NOTHING_FOUND


def test_a_page_with_feed_links_offers_only_the_feeds_not_the_web_page(env):
    with_posts(env)
    env.fetcher.page(
        LIST_PAGE,
        env.fetcher.pages[LIST_PAGE].replace(
            "<head>", f"<head>{link('https://blog.example.com/feed.xml')}"
        ),
    )
    env.fetcher.feed("https://blog.example.com/feed.xml", "공식 피드", "https://blog.example.com")
    kinds = [c.kind for c in env.service.discover(LIST_PAGE).candidates]
    assert kinds == ["feed"]


def test_when_every_found_feed_is_already_subscribed_the_web_page_is_not_offered(env):
    with_posts(env)
    env.fetcher.page(
        LIST_PAGE,
        env.fetcher.pages[LIST_PAGE].replace(
            "<head>", f"<head>{link('https://a.example.com/feed')}"
        ),
    )
    assert env.service.discover(LIST_PAGE).error == ALL_SUBSCRIBED


def test_registering_a_web_page_subscription_checks_the_list_and_saves_it_as_a_page_feed(env):
    with_posts(env)
    result = env.service.register(LIST_PAGE, name="", kind="page")
    assert result.error == "" and result.name == "예제 블로그 - 소식"
    saved = env.feeds.get(result.feed_id)
    assert (saved.kind, saved.url, saved.html_url, saved.status) == (
        "page",
        LIST_PAGE,
        "https://blog.example.com/",
        STATUS_BASELINE,
    )


def test_the_given_name_wins_over_the_page_title_and_long_names_are_cut(env):
    with_posts(env)
    assert (
        env.service.register(LIST_PAGE, name="내가 정한 이름", kind="page").name == "내가 정한 이름"
    )


@pytest.mark.parametrize(
    "mode", ["too_few", "fetch_error", "not_a_page_address", "subscribed", "long_name"]
)
def test_registering_a_web_page_subscription_refuses_bad_input_and_saves_nothing(env, mode):
    before = len(env.feeds.existing_url_keys())
    url, name = LIST_PAGE, ""
    if mode == "too_few":
        with_posts(env, count=2)
        expected = "글 목록을 찾지 못했습니다"
    elif mode == "fetch_error":
        env.fetcher.fail(LIST_PAGE, "ReadTimeout")
        expected = "시간 초과"
    elif mode == "not_a_page_address":
        url, expected = "ftp://x.example.com/news", "http"
    elif mode == "subscribed":
        url, expected = "https://a.example.com/feed", ALREADY_SUBSCRIBED
    else:
        with_posts(env)
        name, expected = "가" * 500, "이름은"
    result = env.service.register(url, name=name, kind="page")
    assert expected in result.error and result.feed_id is None
    assert len(env.feeds.existing_url_keys()) == before


def test_resolve_takes_a_post_list_without_feeds_as_a_web_page_subscription(env):
    with_posts(env)
    ok = env.service.resolve(LIST_PAGE)
    assert (ok.error, ok.kind, ok.site_url, ok.title) == (
        "",
        "page",
        "https://blog.example.com/",
        "예제 블로그 - 소식",
    )
    env.fetcher.page("https://blog.example.com/empty", "<html><body><p>글 없음</p></body></html>")
    assert (
        "글 목록을 찾지 못했습니다" in env.service.resolve("https://blog.example.com/empty").error
    )
    env.fetcher.errors["https://blog.example.com/down"] = "ConnectionError"
    assert "연결하지 못했습니다" in env.service.resolve("https://blog.example.com/down").error


def test_a_page_that_advertises_feeds_is_refused_with_a_hint_to_pick_one(env):
    with_posts(env)
    env.fetcher.page(
        LIST_PAGE,
        env.fetcher.pages[LIST_PAGE].replace(
            "<head>", f"<head>{link('https://blog.example.com/feed.xml')}"
        ),
    )
    assert env.service.resolve(LIST_PAGE).error == PAGE_HAS_FEEDS


def test_feed_links_that_cannot_be_used_do_not_block_a_web_page_subscription(env):
    with_posts(env)
    env.fetcher.page(
        LIST_PAGE,
        env.fetcher.pages[LIST_PAGE].replace(
            "<head>", f"<head>{link('http://192.168.0.9/feed.xml')}"
        ),
    )
    assert env.service.resolve(LIST_PAGE).kind == "page"


def test_a_feed_address_is_a_feed_even_when_it_also_looks_like_a_list_page(env):
    with_posts(env, url="https://blog.example.com/feed.xml")
    env.fetcher.feed("https://blog.example.com/feed.xml", "공식 피드", "https://blog.example.com")
    assert env.service.resolve("https://blog.example.com/feed.xml").kind == "feed"


def test_a_feed_registration_is_unchanged_and_saved_as_a_feed(env):
    env.fetcher.feed("https://new.example.com/rss", "새 블로그", "https://new.example.com")
    result = env.service.register("https://new.example.com/rss", name="")
    assert env.feeds.get(result.feed_id).kind == "feed"


def test_registering_a_web_page_with_both_a_category_and_a_webhook_is_refused(env):
    with_posts(env)
    result = env.service.register(LIST_PAGE, name="", kind="page", category_id=1, webhook_id=1)
    assert "웹훅" in result.error and result.feed_id is None


def test_a_web_page_subscription_that_was_added_in_the_meantime_is_reported_as_subscribed(
    env, monkeypatch
):
    from rss_hub.storage.feeds import DuplicateFeedError

    with_posts(env)

    def duplicate(*args, **kwargs):
        raise DuplicateFeedError

    monkeypatch.setattr(env.feeds, "add", duplicate)
    assert env.service.register(LIST_PAGE, name="", kind="page").error == ALREADY_SUBSCRIBED


def test_three_links_with_only_two_usable_titles_are_not_offered_as_a_web_page_subscription(env):
    html = (
        '<body><a href="/news/a">진짜 제목 하나입니다 길게</a>'
        '<a href="/news/b">진짜 제목 둘입니다 길게</a><a href="/news/c">Read more</a></body>'
    )
    env.fetcher.page(LIST_PAGE, html)
    assert env.service.discover(LIST_PAGE).error == NOTHING_FOUND


def test_a_web_page_candidate_shows_at_most_five_recent_posts(env):
    with_posts(env, count=8)
    (candidate,) = env.service.discover(LIST_PAGE).candidates
    assert (
        candidate.count == 8
        and len(candidate.sample) == 5
        and candidate.sample[4].startswith("새 소식 5번")
    )
