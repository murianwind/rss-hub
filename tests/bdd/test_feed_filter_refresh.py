"""27_feed_filter_refresh.feature: 새로고침 뒤 필터 조건 반영."""

import html as html_module
import re
from types import SimpleNamespace

import pytest
from pytest_bdd import given, then, when

from tests.bdd.binding import bind
from tests.fakes.entries import today
from tests.fakes.feed_fetcher import FakeFeedFetcher
from tests.fakes.viewer_world import World
from tests.fakes.web_parts import start_app
from tests.keywords.browser import post

bind(globals(), "27_feed_filter_refresh.feature", ["FFR-01"])

FREE_URL = "https://f.example.com/rss"
FILTER = "/feeds?last=older"


@pytest.fixture
def world(tmp_path):
    fetcher = FakeFeedFetcher()
    parts, client = start_app(tmp_path, feed_fetcher=fetcher)
    with client:
        w = World(parts)
        w.fetcher = fetcher
        yield w


@pytest.fixture
def ctx():
    return SimpleNamespace(html="", before=0)


def listing(html):
    return html_module.unescape(html.split('<ul class="feed-list">')[1].split("</ul>")[0])


def all_count(html):
    """상태 칩의 "전체 N"."""
    chips = html.split('aria-label="상태로 거르기"')[1].split("</nav>")[0]
    return int(re.search(r"전체 (\d+)", chips).group(1))


@given('마지막 게시가 없어서 "1년 넘게 없음" 필터에 나오는 피드가 있다')
def _stale_feed(world, ctx):
    html = world.get(FILTER).text
    assert world.feeds.get(world.f_free).name in listing(html)
    ctx.before = all_count(html)


@when("그 피드를 새로고침해서 새 글을 받는다")
def _refresh(world):
    world.fetcher.serve(FREE_URL, today(2))
    assert post(world, f"/feeds/{world.f_free}/refresh").json()["ok"] is True


@then("같은 필터를 다시 열면 그 피드는 목록에 없다")
def _gone(world):
    assert world.feeds.get(world.f_free).name not in listing(world.get(FILTER).text)


@then("상태별 개수는 새로고침 결과를 반영한다")
def _counts(world, ctx):
    assert all_count(world.get(FILTER).text) == ctx.before - 1
