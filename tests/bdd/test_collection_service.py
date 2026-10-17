"""02_collection.feature의 서비스 시나리오와 01_scheduling.feature의 스케줄 재사용 시나리오.

실제 SQLite 임시 파일과 가짜 시계, 가짜 수집기로 수집 서비스를 실행한다.
시간 초과 시나리오(COL-22)만 로컬 HTTP 서버와 실제 어댑터를 쓴다.
"""

import time
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, then, when

from rss_hub.adapters.http_feed_fetcher import RequestsFeedFetcher
from rss_hub.domain.schedule import PRIORITY_EVERY_SLOT
from rss_hub.services.collect import CollectService
from rss_hub.storage.articles import STATUS_COLLECTED, NewArticle
from rss_hub.storage.feeds import STATUS_ACTIVE, STATUS_BASELINE
from tests.bdd.binding import bind
from tests.fakes.collect_env import CollectEnv
from tests.fakes.entries import entry, today, yesterday
from tests.fakes.http_server import LocalServer
from tests.fakes.network import allow_all

bind(
    globals(),
    "02_collection.feature",
    [f"COL-{n:02d}" for n in (1, 2, 7, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24)],
)
bind(globals(), "01_scheduling.feature", ["SCH-10", "SCH-11"])


@pytest.fixture
def env(tmp_path):
    return CollectEnv(tmp_path)


@pytest.fixture
def ctx():
    return SimpleNamespace(feed_id=None, url=None, report=None, feeds={}, items=[], before=None)


def new_feed(env, ctx, name="A", **options):
    feed_id, url = env.add_feed(len(ctx.feeds) + 1, **options)
    ctx.feeds[name] = (feed_id, url)
    ctx.feed_id, ctx.url = feed_id, url
    return feed_id, url


def collected(env):
    return env.articles.list_by_status(STATUS_COLLECTED)


# ---------- 점검 ----------


@when("이 피드를 점검한다")
def _check(env, ctx):
    ctx.report = env.collect(ctx.feed_id)


@when("이 피드를 처음 점검한다")
def _check_first(env, ctx):
    ctx.report = env.collect(ctx.feed_id)


# ---------- COL-01, 02, 07 ----------


@given("피드에 오늘 발행된 글 2개와 어제 발행된 글 1개가 있다")
def _today_and_yesterday(env, ctx):
    new_feed(env, ctx)
    env.fetcher.serve(ctx.url, [*today(2), *yesterday(1)])


@then("오늘 발행된 글 2개가 수집 대기열에 들어간다")
def _two_today(env):
    articles = collected(env)
    assert len(articles) == 2
    assert all(a.published_date == "2026-10-16" for a in articles)


@then("어제 발행된 글은 들어가지 않는다")
def _no_yesterday(env):
    assert all(a.published_date != "2026-10-15" for a in collected(env))


@given("피드에 발행 시각이 없는 글이 있다")
def _undated(env, ctx):
    new_feed(env, ctx)
    env.fetcher.serve(ctx.url, [entry(published=None)])


@then("그 글은 수집 대기열에 들어가지 않는다")
def _not_queued(env):
    assert collected(env) == []


@given("컨테이너 시스템 시간대는 UTC이다")
def _container_utc(monkeypatch):
    # 프로세스(컨테이너)의 시간대를 UTC로 바꿔도 결과가 같아야 한다
    monkeypatch.setenv("TZ", "UTC")
    if hasattr(time, "tzset"):
        time.tzset()


@given("피드에 UTC 2026-10-15 16:30:00에 발행된 글이 있다")
def _utc_late_entry(env, ctx):
    new_feed(env, ctx)
    env.fetcher.serve(ctx.url, [entry(published="2026-10-15T16:30:00Z")])


@then(parsers.parse('그 글의 발행일은 "{date}"이다'))
def _published_date(env, date):
    assert collected(env)[0].published_date == date


@then("그 글은 수집 대기열에 들어간다")
def _is_queued(env):
    assert len(collected(env)) == 1


# ---------- COL-11, 12, 13 ----------


@given(parsers.parse('GUID "{guid}"인 글은 이미 발송되었다'))
def _already_sent(env, guid):
    env.articles.mark_seen([guid], "article")


@given(parsers.parse('GUID "{guid}"인 글이 이미 수집 대기열에 있다'))
def _already_queued(env, ctx, guid):
    feed_id, _ = new_feed(env, ctx)
    env.articles.add(
        NewArticle(
            feed_id,
            guid,
            "기존 글",
            "https://x/1",
            "<p>c</p>",
            "",
            datetime(2026, 10, 16, 1, 0, tzinfo=UTC),
            "2026-10-16",
        )
    )


@given(parsers.parse('피드에 오늘 발행된 GUID "{guid}" 글이 있다'))
def _entry_with_guid(env, ctx, guid):
    if ctx.feed_id is None:
        new_feed(env, ctx)
    env.fetcher.serve(ctx.url, [entry(guid=guid)])


@then("수집 대기열에 새로 들어가는 글은 없다")
def _nothing_new(env):
    assert collected(env) == []


@then(parsers.parse('대기열의 "{guid}" 글은 1개뿐이다'))
def _exactly_one(env, guid):
    assert [a.guid for a in collected(env)].count(guid) == 1


@given(parsers.parse('피드 A와 피드 B가 같은 GUID "{guid}"의 글을 오늘 발행했다'))
def _two_feeds_same_guid(env, ctx, guid):
    for name in ("A", "B"):
        _, url = new_feed(env, ctx, name)
        env.fetcher.serve(url, [entry(guid=guid)])


@when("두 피드를 같은 슬롯에서 점검한다")
def _check_two(env, ctx):
    ctx.report = env.collect(ctx.feeds["A"][0], ctx.feeds["B"][0])


# ---------- COL-14, 15, 16 ----------


@given(
    parsers.parse("피드에 오늘 발행된 글이 80개 있고 이 피드의 최대 검사 항목 수는 {limit:d}이다")
)
def _eighty_entries(env, ctx, limit):
    new_feed(env, ctx, max_entries=limit)
    env.fetcher.serve(ctx.url, today(80))


@then(parsers.parse("수집 대기열에 들어가는 글은 {count:d}개이다"))
def _count_queued(env, count):
    assert len(collected(env)) == count


@given("피드에 오늘 발행된 글 2개, 3일 전 글 1개, 10일 전 글 1개가 있다")
def _activity_entries(env, ctx):
    new_feed(env, ctx)
    env.fetcher.serve(
        ctx.url,
        [
            *today(2),
            entry(published="2026-10-13T10:00:00+09:00"),
            entry(published="2026-10-06T10:00:00+09:00"),
        ],
    )


@then(parsers.parse("최근 7일 글 수는 {count:d}이다"))
def _recent_count(env, ctx, count):
    assert env.feeds.stats(ctx.feed_id).recent_count_7d == count


@then(parsers.parse("오늘 글 수는 {count:d}이다"))
def _today_count(env, ctx, count):
    assert env.feeds.stats(ctx.feed_id).target_date_count == count


@then("가장 최근 발행 시각이 기록된다")
def _latest_recorded(env, ctx):
    assert env.feeds.stats(ctx.feed_id).last_published is not None


@given("피드의 글에 HTML이 포함된 요약이 있다")
def _html_summary(env, ctx):
    new_feed(env, ctx)
    ctx.html = "<p>안녕 <b>세상</b></p>"
    env.fetcher.serve(ctx.url, [entry(summary=ctx.html)])


@then("대기열의 글에 요약 HTML이 가공 없이 보관된다")
def _html_kept(env, ctx):
    assert collected(env)[0].content_html == ctx.html


@then(parsers.parse('글의 상태는 "{status}"이다'))
def _article_status(env, status):
    assert {a.status for a in collected(env)} == {status}


# ---------- COL-17, 18 ----------


@given(parsers.parse('상태가 "baseline_pending"인 새 피드에 오늘 발행된 글 {count:d}개가 있다'))
def _new_feed_with_entries(env, ctx, count):
    new_feed(env, ctx, status=STATUS_BASELINE)
    ctx.items = today(count)
    env.fetcher.serve(ctx.url, ctx.items)


@then(parsers.parse('{count:d}개 글의 GUID가 "이미 본 글"로 기록된다'))
def _recorded_as_seen(env, ctx, count):
    assert len(ctx.items) == count
    assert all(env.articles.is_seen(e["id"]) for e in ctx.items)


@then("수집 대기열에는 들어가지 않는다")
def _not_queued_baseline(env):
    assert collected(env) == []


@then(parsers.parse('피드 상태는 "{status}"가 된다'))
def _feed_status(env, ctx, status):
    assert env.feeds.get(ctx.feed_id).status == status == STATUS_ACTIVE


@given("새 피드의 기준선이 이미 기록되어 있다")
def _baseline_done(env, ctx):
    new_feed(env, ctx, status=STATUS_BASELINE)
    ctx.items = today(3)
    env.fetcher.serve(ctx.url, ctx.items)
    env.collect(ctx.feed_id)


@given("그 뒤에 오늘 발행된 새 글이 올라왔다")
def _fresh_entry(env, ctx):
    ctx.fresh = entry(published="2026-10-16T13:00:00+09:00")
    env.fetcher.serve(ctx.url, [ctx.fresh, *ctx.items])


@then("새 글은 수집 대기열에 들어간다")
def _fresh_queued(env, ctx):
    assert [a.guid for a in collected(env)] == [ctx.fresh["id"]]


# ---------- COL-19, 20 ----------


@given("슬롯에 피드 A, B, C가 있고 B는 시간 초과로 실패한다")
def _three_feeds(env, ctx):
    for name in ("A", "B", "C"):
        _, url = new_feed(env, ctx, name)
        if name == "B":
            env.fetcher.fail(url, "ReadTimeout")
        else:
            env.fetcher.serve(url, [entry()])


@when("슬롯을 실행한다")
def _run_slot_feeds(env, ctx):
    ctx.report = env.collect(*(feed_id for feed_id, _ in ctx.feeds.values()))


@then("A와 C의 새 글은 수집된다")
def _a_and_c_collected(env, ctx):
    feed_ids = {a.feed_id for a in collected(env)}
    assert feed_ids == {ctx.feeds["A"][0], ctx.feeds["C"][0]}


@then("B는 실패한 피드로 기록되고 오류 종류가 남는다")
def _b_failed(env, ctx):
    b_id = ctx.feeds["B"][0]
    assert ctx.report.failed == ((b_id, "ReadTimeout"),)
    assert env.feeds.get(b_id).last_error == "ReadTimeout"


@given(parsers.parse("피드 B의 연속 실패 횟수가 {count:d}이다"))
def _failures(env, ctx, count):
    new_feed(env, ctx, "B")
    for _ in range(count):
        env.feeds.record_failure(ctx.feed_id, "Timeout")


@when("피드 B 점검이 성공한다")
def _b_succeeds(env, ctx):
    env.fetcher.serve(ctx.url, [])
    env.collect(ctx.feed_id)


@then(parsers.re(r"피드(?: B)?의 연속 실패 횟수는 (?P<count>\d+)이다"))
def _failures_reset(env, ctx, count):
    assert env.feeds.get(ctx.feed_id).fail_count == int(count)


# ---------- COL-21 ----------


@given("피드에 이전 응답의 ETag가 저장되어 있다")
def _etag_stored(env, ctx):
    new_feed(env, ctx)
    env.fetcher.serve(ctx.url, today(2), etag='"v1"')
    env.collect(ctx.feed_id)
    ctx.stats_before = env.feeds.stats(ctx.feed_id)
    ctx.articles_before = len(collected(env))


@given("서버가 304 Not Modified로 응답한다")
def _not_modified(env, ctx):
    env.fetcher.not_modified(ctx.url)


@then("피드 내용은 해석하지 않는다")
def _not_parsed(env, ctx):
    assert env.fetcher.calls[-1].etag == '"v1"'
    assert env.feeds.stats(ctx.feed_id) == ctx.stats_before
    assert len(collected(env)) == ctx.articles_before
    assert ctx.report.added == 0


@then("점검은 성공으로 기록된다")
def _success_recorded(env, ctx):
    feed = env.feeds.get(ctx.feed_id)
    assert (feed.fail_count, feed.last_error) == (0, None)
    assert feed.last_checked_at == env.clock.now()
    assert ctx.report.failed == ()


# ---------- COL-22: 실제 어댑터와 로컬 서버 ----------


def use_real_fetcher(env, ctx, path, fetcher, **route):
    """로컬 HTTP 서버와 실제 수집기로 점검하도록 환경을 바꾼다."""
    server = LocalServer()
    server.start()
    ctx.server = server
    server.serve(path, **route)
    env.service = CollectService(
        feeds=env.feeds,
        articles=env.articles,
        fetcher=fetcher,
        settings=env.settings,
        clock=env.clock,
    )
    ctx.feed_id = env.feeds.add(server.url(path), "실제 수집 피드", status=STATUS_ACTIVE)


@given("피드 서버가 연결은 되지만 응답하지 않는다")
def _hanging_server(env, ctx):
    fetcher = RequestsFeedFetcher(timeout=(0.5, 0.3), forbid_address=allow_all)
    use_real_fetcher(env, ctx, "/slow", fetcher, body=b"<rss/>", delay=2.0)


@given("피드 서버가 HTML 페이지를 돌려준다")
def _html_server(env, ctx):
    html = b"<!doctype html><html><body>not a feed</body></html>"
    use_real_fetcher(env, ctx, "/page", RequestsFeedFetcher(forbid_address=allow_all), body=html)


@given("피드 서버가 제한(5MB)을 넘는 크기의 응답을 돌려준다")
def _huge_server(env, ctx):
    # 시나리오의 "5MB"는 기본 제한값이다. 테스트에서는 같은 동작을 작은 제한으로 확인한다
    fetcher = RequestsFeedFetcher(max_bytes=1_000, forbid_address=allow_all)
    use_real_fetcher(env, ctx, "/huge", fetcher, body=b"x" * 5_000)


@then(parsers.parse('점검은 "{reason}"로 실패로 기록된다'))
def _failed_with_reason(env, ctx, reason):
    try:
        assert ctx.report.failed == ((ctx.feed_id, reason),)
        assert env.feeds.get(ctx.feed_id).last_error == reason
    finally:
        ctx.server.stop()


@then("점검은 읽기 제한 시간 안에 실패로 끝난다")
def _timed_out(env, ctx):
    try:
        assert ctx.report.failed == ((ctx.feed_id, "ReadTimeout"),)
        assert env.feeds.get(ctx.feed_id).fail_count == 1
    finally:
        ctx.server.stop()


@then("서비스 전체는 멈추지 않는다")
def _service_continues(env, ctx):
    assert ctx.report.checked == 1  # 점검 호출이 예외 없이 끝났고 보고서를 돌려줬다


# ---------- SCH-10, 11 ----------


@given("이번 시간의 스케줄이 이미 만들어져 있다")
def _schedule_exists(env, ctx):
    for n in range(5):
        feed_id, url = env.add_feed(n + 1)
        env.fetcher.serve(url, [])
        ctx.feeds[f"f{n}"] = (feed_id, url)
    assert env.service.run_slot().schedule_rebuilt is True


def apply_change(env, ctx, change):
    if change == "다음 시간이 되었다":
        env.clock.advance(hours=1)
    elif change == "대상 날짜가 바뀌었다":
        env.clock.advance(days=1)
    elif change == "피드가 추가되었다":
        _, url = env.add_feed(50)
        env.fetcher.serve(url, [])
    elif change == "피드가 삭제되었다":
        env.feeds.delete(ctx.feeds["f0"][0])
    elif change == "피드의 폴링 우선순위가 바뀌었다":
        env.feeds.set_poll_priority(ctx.feeds["f0"][0], PRIORITY_EVERY_SLOT)
    elif change == "피드 개수는 같지만 피드 구성이 바뀌었다":
        env.feeds.delete(ctx.feeds["f0"][0])
        _, url = env.add_feed(51)
        env.fetcher.serve(url, [])
    elif change == "수집 주기 설정이 바뀌었다":
        env.settings.update({"collect_interval_minutes": "10"})
    else:
        pytest.fail(f"알 수 없는 변경: {change}")


@when(
    parsers.re(
        r"(?P<change>다음 시간이 되었다|대상 날짜가 바뀌었다|피드가 추가되었다|피드가 삭제되었다"
        r"|피드의 폴링 우선순위가 바뀌었다|피드 개수는 같지만 피드 구성이 바뀌었다"
        r"|수집 주기 설정이 바뀌었다)"
    )
)
def _change_input(env, ctx, change):
    apply_change(env, ctx, change)


@then("스케줄을 새로 만든다")
def _rebuilt(env):
    assert env.service.run_slot().schedule_rebuilt is True


@when("같은 시간 안에서 다음 슬롯을 실행한다")
def _next_slot_same_hour(env, ctx):
    env.clock.advance(minutes=5)
    ctx.report = env.service.run_slot()


@then("스케줄을 새로 만들지 않는다")
def _not_rebuilt(ctx):
    assert ctx.report.schedule_rebuilt is False
