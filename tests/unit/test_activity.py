from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from rss_hub.domain.activity import measure_activity
from rss_hub.domain.schedule import Activity

SEOUL = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 10, 16, 14, 0, tzinfo=SEOUL)
TODAY = date(2026, 10, 16)


def at(**delta):
    return NOW - timedelta(**delta)


def test_counts_recent_and_todays_entries_and_finds_the_latest():
    result = measure_activity([at(hours=1), at(hours=2), at(days=3), at(days=10)], NOW, TODAY)
    assert result.activity == Activity(recent_count_7d=3, target_date_count=2)
    assert result.last_published == at(hours=1)


def test_entries_without_a_date_are_ignored():
    result = measure_activity([None, at(hours=1), None], NOW, TODAY)
    assert result.activity == Activity(recent_count_7d=1, target_date_count=1)


def test_no_entries_means_no_activity_and_no_latest():
    result = measure_activity([], NOW, TODAY)
    assert result.activity == Activity(0, 0)
    assert result.last_published is None


def test_the_seven_day_window_includes_exactly_seven_days_ago():
    assert measure_activity([at(days=7)], NOW, TODAY).activity.recent_count_7d == 1
    assert measure_activity([at(days=7, seconds=1)], NOW, TODAY).activity.recent_count_7d == 0


def test_today_is_judged_by_the_date_of_each_entry_in_its_own_timezone():
    yesterday_late = datetime(2026, 10, 15, 23, 59, tzinfo=SEOUL)
    assert measure_activity([yesterday_late], NOW, TODAY).activity.target_date_count == 0


def test_the_latest_is_the_maximum_even_if_the_feed_is_not_sorted():
    result = measure_activity([at(hours=5), at(hours=1), at(hours=3)], NOW, TODAY)
    assert result.last_published == at(hours=1)
