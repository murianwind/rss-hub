from datetime import UTC, datetime

import pytest

from rss_hub.domain.schedule import PRIORITY_EVERY_SLOT
from rss_hub.storage.feeds import STATUS_ACTIVE, STATUS_BASELINE
from tests.fakes.collect_env import KST_14_00, CollectEnv
from tests.fakes.entries import entry, today, yesterday


@pytest.fixture
def env(tmp_path):
    return CollectEnv(tmp_path)


# ---------- 한 피드 점검 ----------


def test_only_todays_new_articles_are_collected(env):
    feed_id, url = env.add_feed()
    env.fetcher.serve(url, [*today(2), *yesterday(1), entry(published=None)])
    report = env.collect(feed_id)
    assert len(env.collected()) == 2
    assert (report.checked, report.added, report.failed) == (1, 2, ())


def test_collected_article_keeps_the_feed_and_the_original_html(env):
    feed_id, url = env.add_feed()
    env.fetcher.serve(
        url,
        [
            entry(
                guid="g-1",
                title="새 글",
                summary="<p>안녕 <b>세상</b></p>",
                published="2026-10-16T09:30:00+09:00",
            )
        ],
    )
    env.collect(feed_id)
    article = env.collected()[0]
    assert (article.feed_id, article.guid, article.content_html) == (
        feed_id,
        "g-1",
        "<p>안녕 <b>세상</b></p>",
    )
    assert article.published_date == "2026-10-16"
    assert article.published_dt == datetime(2026, 10, 16, 0, 30, tzinfo=UTC)
    assert article.discovered_at == KST_14_00


def test_the_first_check_of_a_new_feed_only_records_a_baseline(env):
    feed_id, url = env.add_feed(status=STATUS_BASELINE)
    items = today(30)
    env.fetcher.serve(url, items)
    report = env.collect(feed_id)
    assert env.collected() == []
    assert report.baseline_recorded == 30
    assert all(env.articles.is_seen(e["id"]) for e in items)
    assert env.feeds.get(feed_id).status == STATUS_ACTIVE


def test_baseline_covers_entries_of_any_date_up_to_the_limit(env):
    feed_id, url = env.add_feed(status=STATUS_BASELINE)
    old = yesterday(3)
    env.fetcher.serve(url, [*today(2), *old])
    env.collect(feed_id)
    assert all(env.articles.is_seen(e["id"]) for e in old)


def test_new_entries_after_the_baseline_are_collected(env):
    feed_id, url = env.add_feed(status=STATUS_BASELINE)
    existing = today(3)
    env.fetcher.serve(url, existing)
    env.collect(feed_id)
    fresh = entry(published="2026-10-16T13:00:00+09:00")
    env.fetcher.serve(url, [fresh, *existing])
    env.collect(feed_id)
    assert [a.guid for a in env.collected()] == [fresh["id"]]


def test_already_seen_articles_are_not_collected_again(env):
    feed_id, url = env.add_feed()
    items = today(2)
    env.fetcher.serve(url, items)
    env.collect(feed_id)
    env.collect(feed_id)
    assert len(env.collected()) == 2


def test_guid_tracking_parameters_do_not_create_duplicates(env):
    feed_id, url = env.add_feed()
    env.fetcher.serve(url, [entry(guid="https://blog.naver.com/a/1?fromRss=true&trackingCode=rss")])
    env.collect(feed_id)
    env.fetcher.serve(url, [entry(guid="https://blog.naver.com/a/1")])
    env.collect(feed_id)
    assert [a.guid for a in env.collected()] == ["https://blog.naver.com/a/1"]


def test_stored_validators_are_sent_and_new_ones_are_saved(env):
    feed_id, url = env.add_feed()
    env.fetcher.serve(url, [], etag='"v1"', last_modified="Thu, 15 Oct 2026 00:00:00 GMT")
    env.collect(feed_id)
    env.fetcher.serve(url, [], etag='"v2"')
    env.collect(feed_id)
    assert (env.fetcher.calls[0].etag, env.fetcher.calls[0].last_modified) == (None, None)
    assert (env.fetcher.calls[1].etag, env.fetcher.calls[1].last_modified) == (
        '"v1"',
        "Thu, 15 Oct 2026 00:00:00 GMT",
    )
    assert env.feeds.get(feed_id).etag == '"v2"'


def test_not_modified_keeps_validators_and_skips_parsing(env):
    feed_id, url = env.add_feed()
    env.fetcher.serve(url, [], etag='"v1"')
    env.collect(feed_id)
    env.fetcher.not_modified(url)
    report = env.collect(feed_id)
    feed = env.feeds.get(feed_id)
    assert (report.added, report.failed, feed.etag, feed.fail_count) == (0, (), '"v1"', 0)


def test_not_modified_does_not_activate_a_pending_feed_because_no_baseline_was_recorded(env):
    feed_id, url = env.add_feed(status=STATUS_BASELINE)
    env.fetcher.not_modified(url)
    env.collect(feed_id)
    assert env.feeds.get(feed_id).status == STATUS_BASELINE


def test_stats_are_saved_after_each_check(env):
    feed_id, url = env.add_feed()
    env.fetcher.serve(
        url,
        [
            *today(2),
            entry(published="2026-10-13T10:00:00+09:00"),
            entry(published="2026-10-01T10:00:00+09:00"),
        ],
    )
    env.collect(feed_id)
    activity = env.feeds.activity_by_key()[str(feed_id)]
    assert (activity.recent_count_7d, activity.target_date_count) == (3, 2)


def test_only_the_first_n_entries_are_examined(env):
    feed_id, url = env.add_feed(max_entries=5)
    env.fetcher.serve(url, today(20))
    env.collect(feed_id)
    assert len(env.collected()) == 5


def test_the_default_limit_comes_from_settings(env):
    feed_id, url = env.add_feed()
    env.settings.update({"default_max_entries": "7"})
    env.fetcher.serve(url, today(20))
    env.collect(feed_id)
    assert len(env.collected()) == 7


def test_todays_date_is_decided_in_the_service_timezone(env):
    feed_id, url = env.add_feed()
    env.fetcher.serve(url, [entry(published="2026-10-16T01:30:00+09:00")])  # UTC로는 어제 16:30
    env.settings.update({"service_timezone": "UTC"})
    env.collect(feed_id)
    assert env.collected() == []
    env.settings.update({"service_timezone": "Asia/Seoul"})
    env.collect(feed_id)
    assert len(env.collected()) == 1


# ---------- 실패 격리 ----------


def test_a_failing_feed_is_recorded_and_the_others_are_still_checked(env):
    a, url_a = env.add_feed(1)
    b, url_b = env.add_feed(2)
    c, url_c = env.add_feed(3)
    env.fetcher.serve(url_a, today(1))
    env.fetcher.fail(url_b, "ReadTimeout")
    env.fetcher.serve(url_c, today(1))
    report = env.collect(a, b, c)
    assert len(env.collected()) == 2
    assert report.failed == ((b, "ReadTimeout"),)
    assert env.feeds.get(b).fail_count == 1
    assert env.feeds.get(b).last_error == "ReadTimeout"


def test_success_after_failures_resets_the_counter(env):
    feed_id, url = env.add_feed()
    env.fetcher.fail(url)
    env.collect(feed_id)
    env.collect(feed_id)
    assert env.feeds.get(feed_id).fail_count == 2
    env.fetcher.serve(url, [])
    env.collect(feed_id)
    assert env.feeds.get(feed_id).fail_count == 0


def test_an_unexpected_error_in_one_feed_does_not_stop_the_slot(env):
    a, url_a = env.add_feed(1)
    b, url_b = env.add_feed(2)
    env.fetcher.crash(url_a, ValueError("예상하지 못한 오류"))
    env.fetcher.serve(url_b, today(1))
    report = env.collect(a, b)
    assert report.failed == ((a, "ValueError"),)
    assert len(env.collected()) == 1


# ---------- 슬롯 실행 ----------


def feeds_in_slot(env, count):
    ids = []
    for n in range(count):
        feed_id, url = env.add_feed(n)
        env.fetcher.serve(url, [])
        ids.append(feed_id)
    return ids


def test_run_slot_checks_only_the_feeds_scheduled_for_the_current_slot(env):
    ids = feeds_in_slot(env, 24)
    report = env.service.run_slot()  # 14:00 → 0번 슬롯
    assert report.slot == 0
    assert report.checked == 2
    assert sorted(env.fetcher.urls_fetched()) == sorted(
        [env.feeds.get(ids[0]).url, env.feeds.get(ids[12]).url]
    )


def test_run_slot_uses_the_local_minute_of_the_service_timezone(env):
    feeds_in_slot(env, 3)
    env.settings.update({"service_timezone": "Asia/Kolkata"})  # UTC+5:30 → 10:30
    assert env.service.run_slot().slot == 6


def test_every_slot_feed_is_checked_in_every_slot(env):
    _, url = env.add_feed(99, poll_priority=PRIORITY_EVERY_SLOT)
    env.fetcher.serve(url, [])
    feeds_in_slot(env, 20)
    for minute in range(0, 60, 5):
        before = env.fetcher.urls_fetched().count(url)
        env.clock.set(datetime(2026, 10, 16, 5, minute, tzinfo=UTC))
        env.service.run_slot()
        assert env.fetcher.urls_fetched().count(url) == before + 1


def test_run_slot_with_no_feeds_does_nothing(env):
    report = env.service.run_slot()
    assert (report.checked, report.added, report.failed) == (0, 0, ())


def test_run_slot_ignores_the_seconds_and_respects_the_interval_setting(env):
    feeds_in_slot(env, 12)
    env.settings.update({"collect_interval_minutes": "10"})
    env.clock.set(datetime(2026, 10, 16, 5, 25, 59, tzinfo=UTC))
    assert env.service.run_slot().slot == 2


# ---------- 스케줄 재사용 ----------


def test_the_schedule_is_reused_within_the_hour_and_rebuilt_when_inputs_change(env):
    feeds_in_slot(env, 5)
    assert env.service.run_slot().schedule_rebuilt is True
    env.clock.advance(minutes=5)
    assert env.service.run_slot().schedule_rebuilt is False

    env.clock.advance(hours=1)
    assert env.service.run_slot().schedule_rebuilt is True  # 시간이 바뀜
    assert env.service.run_slot().schedule_rebuilt is False

    _, extra_url = env.add_feed(50)
    env.fetcher.serve(extra_url, [])
    assert env.service.run_slot().schedule_rebuilt is True  # 피드 추가

    env.feeds.delete(env.feeds.list_all()[0].id)
    assert env.service.run_slot().schedule_rebuilt is True  # 피드 삭제

    env.feeds.set_poll_priority(env.feeds.list_all()[0].id, PRIORITY_EVERY_SLOT)
    assert env.service.run_slot().schedule_rebuilt is True  # 우선순위 변경

    env.settings.update({"collect_interval_minutes": "10"})
    assert env.service.run_slot().schedule_rebuilt is True  # 수집 주기 변경
    assert env.service.run_slot().schedule_rebuilt is False


def test_replacing_a_feed_keeps_the_count_but_still_rebuilds(env):
    ids = feeds_in_slot(env, 3)
    env.service.run_slot()
    env.feeds.delete(ids[0])
    _, replacement_url = env.add_feed(77)
    env.fetcher.serve(replacement_url, [])
    assert env.service.run_slot().schedule_rebuilt is True


# ---------- 첫 점검 때 최근 글을 뷰어용으로 보관 ----------


def archived(env):
    return env.articles.list_by_status("archived")


def test_the_first_check_archives_the_five_newest_entries_for_the_viewer(env):
    feed_id, url = env.add_feed(status=STATUS_BASELINE)
    items = today(30)
    env.fetcher.serve(url, items)
    report = env.collect(feed_id)
    newest = {e["id"] for e in sorted(items, key=lambda e: e["published"], reverse=True)[:5]}
    assert {a.guid for a in archived(env)} == newest
    assert env.collected() == [] and report.baseline_recorded == 30  # 알림 대상은 없다


def test_the_number_of_archived_entries_is_a_setting(env):
    env.settings.update({"baseline_archive_count": "2"})
    feed_id, url = env.add_feed(status=STATUS_BASELINE)
    env.fetcher.serve(url, today(10))
    env.collect(feed_id)
    assert len(archived(env)) == 2


def test_zero_means_nothing_is_archived(env):
    env.settings.update({"baseline_archive_count": "0"})
    feed_id, url = env.add_feed(status=STATUS_BASELINE)
    env.fetcher.serve(url, today(10))
    env.collect(feed_id)
    assert archived(env) == []


def test_a_feed_with_fewer_entries_than_the_setting_archives_all_of_them(env):
    feed_id, url = env.add_feed(status=STATUS_BASELINE)
    env.fetcher.serve(url, today(3))
    env.collect(feed_id)
    assert len(archived(env)) == 3


def test_entries_of_any_date_are_archived_and_undated_ones_count_as_now(env):
    feed_id, url = env.add_feed(status=STATUS_BASELINE)
    env.fetcher.serve(url, [*yesterday(2), entry(published=None)])
    env.collect(feed_id)
    assert len(archived(env)) == 3
    undated = next(a for a in archived(env) if a.published_raw == "")
    assert undated.published_dt == env.clock.now()


def test_only_entries_within_the_feed_limit_are_considered(env):
    feed_id, url = env.add_feed(status=STATUS_BASELINE, max_entries=3)
    env.fetcher.serve(url, today(30))
    env.collect(feed_id)
    assert len(archived(env)) == 3


def test_archived_entries_are_not_collected_again_and_later_new_ones_are_normal(env):
    feed_id, url = env.add_feed(status=STATUS_BASELINE)
    items = today(10)
    env.fetcher.serve(url, items)
    env.collect(feed_id)
    new_entry = entry(published="2026-10-16T13:00:00+09:00")
    env.fetcher.serve(url, [new_entry, *items])
    report = env.collect(feed_id)
    assert report.added == 1 and [a.guid for a in env.collected()] == [new_entry["id"]]
    assert len(archived(env)) == 5


def test_a_feed_that_is_already_active_archives_nothing(env):
    feed_id, url = env.add_feed()
    env.fetcher.serve(url, today(10))
    env.collect(feed_id)
    assert archived(env) == []
