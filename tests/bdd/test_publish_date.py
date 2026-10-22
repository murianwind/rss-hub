"""29_publish_date.feature: 글 페이지에서 발행일 찾기, 수집, 화면 표시."""

import re
from datetime import timedelta, timezone
from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, then, when

from rss_hub.domain.page_date import extract_published_date
from rss_hub.services.collect import CollectService
from rss_hub.services.page_source import PageFeedSource
from rss_hub.storage.articles import STATUS_ARCHIVED
from rss_hub.storage.feeds import KIND_PAGE, STATUS_ACTIVE, STATUS_BASELINE
from tests.bdd.binding import bind
from tests.fakes.collect_env import CollectEnv
from tests.fakes.discovery_fetcher import FakeDiscoveryFetcher
from tests.fakes.entries import entry, today
from tests.fakes.page_html import (
    BASE,
    PUBLISHED_PAGES,
    article_html,
    dated_article_html,
    listing,
)

bind(globals(), "29_publish_date.feature", [f"PBD-{n:02d}" for n in range(1, 13)])

KST = timezone(timedelta(hours=9))
LIST_URL = f"{BASE}/news"
POST_TITLE = "새 소식 제목입니다 충분히 길게 씁니다"


def meta(content):
    return f'<meta property="article:published_time" content="{content}">'


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

    def page_feed(self, status):
        return self.feeds.add(LIST_URL, "예제 블로그", status=status, kind=KIND_PAGE)

    def archived(self):
        return self.articles.list_by_status(STATUS_ARCHIVED)


@pytest.fixture
def env(tmp_path):
    return PageEnv(tmp_path)


@pytest.fixture
def ctx():
    return SimpleNamespace(html="", found=None, feed=None, rss_feed=None, calls=0, ids=[])


# ---------- 글 페이지에서 발행일 찾기 ----------


@given(parsers.parse("발행일이 {where}에 적힌 글 페이지가 있다"))
def _page_with_date(ctx, where):
    ctx.html = dated_article_html(1, **PUBLISHED_PAGES[where])


@given(parsers.re(r'발행 시각이 "(?P<raw>[^"]+)"인 메타 태그가 있는 글 페이지가 있다'))
@given(parsers.re(r'발행일이 "(?P<raw>[^"]+)"인 메타 태그가 있는 글 페이지가 있다'))
def _page_with_meta(ctx, raw):
    ctx.html = dated_article_html(1, head=meta(raw))


@given("날짜가 어디에도 없는 글 페이지가 있다")
def _page_without_date(ctx):
    ctx.html = article_html(1)


@when("글 페이지에서 발행일을 찾는다")
def _find(ctx):
    ctx.found = extract_published_date(ctx.html, KST)


@then(parsers.parse('발행일은 "{day}"이다'))
def _found(ctx, day):
    assert ctx.found is not None and ctx.found.isoformat() == day


@then("발행일은 알 수 없다")
def _not_found(ctx):
    assert ctx.found is None


# ---------- 수집 ----------


SLUGS = ("p1", "p2", "p3")  # 목록은 글이 여럿이어야 목록으로 알아본다


def undated_post(env, ctx, page_html):
    ctx.feed = env.page_feed(STATUS_ACTIVE)
    env.pages.page(LIST_URL, listing([(slug, f"{POST_TITLE} {slug}", None) for slug in SLUGS]))
    for slug in SLUGS:
        env.pages.page(f"{BASE}/news/{slug}", page_html)


@given("활성 상태의 웹페이지 구독에 날짜 없는 새 글이 나타났고 그 글 페이지의 발행일은 어제이다")
def _old_post(env, ctx):
    undated_post(env, ctx, dated_article_html(1, head=meta("2026-10-15T09:00:00+09:00")))


@given("활성 상태의 웹페이지 구독에 날짜 없는 새 글이 나타났고 그 글 페이지의 발행일은 오늘이다")
def _today_post(env, ctx):
    undated_post(env, ctx, dated_article_html(1, head=meta("2026-10-16T09:00:00+09:00")))


@given("활성 상태의 웹페이지 구독에 날짜 없는 새 글이 나타났고 그 글 페이지에는 날짜가 없다")
def _no_date_post(env, ctx):
    undated_post(env, ctx, article_html(1))


@given("활성 상태의 웹페이지 구독에 오늘 날짜가 적힌 새 글이 있다")
def _listed_date_post(env, ctx):
    ctx.feed = env.page_feed(STATUS_ACTIVE)
    env.pages.page(
        LIST_URL, listing([(slug, f"{POST_TITLE} {slug}", "2026-10-16") for slug in SLUGS])
    )
    for slug in SLUGS:
        env.pages.page(f"{BASE}/news/{slug}", article_html(1))


@given("활성 상태의 RSS 피드에 오늘 발행된 새 글이 있다")
def _rss_post(env, ctx):
    ctx.rss_feed, url = env.add_feed(1)
    env.fetcher.serve(url, today(1))


@given(
    "새로 등록한 웹페이지 구독의 목록에 날짜 없는 글이 둘 있고 하나의 글 페이지에만 발행일이 있다"
)
def _baseline_page(env, ctx):
    ctx.feed = env.page_feed(STATUS_BASELINE)
    env.pages.page(
        LIST_URL,
        listing([(slug, f"{POST_TITLE} {slug}", None) for slug in ("dated", "plain", "other")]),
    )
    env.pages.page(f"{BASE}/news/other", article_html(3))
    env.pages.page(f"{BASE}/news/dated", dated_article_html(1, head=meta("2026-09-28")))
    env.pages.page(f"{BASE}/news/plain", article_html(2))


@given("새로 등록한 RSS 피드에 날짜가 없는 항목이 있다")
def _baseline_rss(env, ctx):
    ctx.rss_feed, url = env.add_feed(1, status=STATUS_BASELINE)
    env.fetcher.serve(url, [entry(published=None)])


@when("수집한다")
def _collect(env, ctx):
    ids = [i for i in (ctx.feed, ctx.rss_feed) if i is not None]
    env.collect(*ids)


@then("그 글은 저장되지 않고 이미 본 글로 기록된다")
def _seen_not_stored(env):
    assert env.collected() == []
    assert all(env.articles.is_seen(f"{BASE}/news/{slug}") for slug in SLUGS)


@then("다음 수집에서 글 페이지를 다시 가져오지 않는다")
def _not_refetched(env, ctx):
    urls = [f"{BASE}/news/{slug}" for slug in SLUGS]
    before = [env.pages.page_calls.count(url) for url in urls]
    env.collect(ctx.feed)
    assert before == [1, 1, 1] and [env.pages.page_calls.count(url) for url in urls] == before


@then(parsers.parse('그 글은 발행일 "{day}"이 날짜만 아는 값으로 저장된다'))
def _stored_dated(env, day):
    stored = env.collected()
    assert len(stored) == len(SLUGS)
    for article in stored:
        assert article.published_date == day and article.published_kind == "date"
        assert article.published_dt.date().isoformat() == day


@then("그 글은 저장되고 발행일은 모르는 값이다")
def _stored_unknown(env):
    stored = env.collected()
    assert len(stored) == len(SLUGS) and {a.published_kind for a in stored} == {"unknown"}


@then("웹페이지 구독 글은 날짜만 아는 값이고 RSS 글은 시각까지 아는 값이다")
def _kinds(env):
    kinds = {a.guid.startswith(BASE): a.published_kind for a in env.collected()}
    assert kinds == {True: "date", False: "exact"}


@then("보관된 글 중 발행일이 있는 글은 그 날짜이고 없는 글은 모르는 값이다")
def _archived_kinds(env):
    by_guid = {a.guid.rsplit("/", 1)[1]: a for a in env.archived()}
    assert by_guid["dated"].published_kind == "date"
    assert by_guid["dated"].published_dt.date().isoformat() == "2026-09-28"
    assert by_guid["plain"].published_kind == "unknown"


@then("보관된 글의 발행일은 모르는 값이다")
def _archived_rss_unknown(env):
    (stored,) = env.archived()
    assert stored.published_kind == "unknown"


# ---------- 화면 ----------

TITLES = {"exact": "시각까지 아는 글", "date": "날짜만 아는 글", "unknown": "날짜를 모르는 글"}


@given("시각까지 아는 글, 날짜만 아는 글, 날짜를 모르는 글이 있다")
def _three_articles(world, ctx):
    ctx.ids = {
        kind: world.article(title=title, published_kind=kind) for kind, title in TITLES.items()
    }


@when("세 글의 화면을 연다")
def _open_articles(world, ctx):
    ctx.pages = {kind: world.get(f"/a/{article}").text for kind, article in ctx.ids.items()}


@when("읽기 화면을 연다")
def _open_reader(world, ctx):
    ctx.html = world.get("/reader").text


def meta_line(html):
    return html.split('class="doc-meta"')[1].split("</div>")[0]


ARTICLE_DATES = (
    "시각까지 아는 글은 날짜와 시각을, 날짜만 아는 글은 날짜만 보이고 "
    "모르는 글은 발행일을 보이지 않는다"
)


@then(ARTICLE_DATES)
def _article_dates(ctx):
    assert "2026-10-16 10:00" in meta_line(ctx.pages["exact"])
    date_only = meta_line(ctx.pages["date"])
    assert "2026-10-16" in date_only and "10:00" not in date_only
    assert "<time" not in meta_line(ctx.pages["unknown"])


def card_of(html, title):
    cards = html.split('<article class="card')[1:]
    return next(c for c in cards if title in c.split("</article>")[0]).split("</article>")[0]


@then("카드마다 읽음 표시 옆에 발행일이 보이고 모르는 글에는 보이지 않는다")
def _card_dates(ctx):
    for kind in ("exact", "date"):
        foot = card_of(ctx.html, TITLES[kind]).split('class="card-foot"')[1]
        assert re.search(r'class="pub-date"[^>]*>\s*발행 2026-10-16\s*<', foot)
        assert foot.index("읽음으로 표시") < foot.index('class="pub-date"')
    assert "pub-date" not in card_of(ctx.html, TITLES["unknown"])
