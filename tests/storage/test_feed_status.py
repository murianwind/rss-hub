"""피드 상태(정상, 오류, 아직 수집 전)와 피드 주소 변경."""

import pytest

from rss_hub.storage.database import Database
from rss_hub.storage.feeds import STATUS_ACTIVE, STATUS_BASELINE, DuplicateFeedError, FeedRepository
from rss_hub.storage.reader import ReaderRepository, feed_state
from tests.fakes.clock import FakeClock


@pytest.fixture
def env(tmp_path):
    db, clock = Database(tmp_path / "rss_hub.db"), FakeClock()
    feeds = FeedRepository(db, clock)
    return feeds, ReaderRepository(db, clock), feeds.add("https://a.example.com/rss", "A"), clock


def state(reader, feed_id):
    return next(f for f in reader.sidebar().feeds if f.id == feed_id)


@pytest.mark.parametrize(
    ("fails", "checked", "expected"),
    [(0, None, "never"), (0, "t", "ok"), (1, "t", "error"), (3, None, "error"), (5, "t", "error")],
)
def test_the_state_rule(fails, checked, expected):
    assert feed_state(fails, checked) == expected


def test_a_new_feed_is_gray_until_it_is_checked(env):
    _, reader, feed, _ = env
    assert state(reader, feed).state == "never"


def test_a_successful_check_makes_it_ok_and_a_failure_makes_it_error_with_the_reason(env):
    feeds, reader, feed, _ = env
    feeds.record_success(feed, etag=None, last_modified=None, activate=True)
    assert (state(reader, feed).state, state(reader, feed).error) == ("ok", "")
    feeds.record_failure(feed, "ReadTimeout")
    assert (state(reader, feed).state, state(reader, feed).error) == ("error", "ReadTimeout")
    feeds.record_success(feed, etag=None, last_modified=None, activate=False)
    assert (state(reader, feed).state, state(reader, feed).error) == ("ok", "")


def test_a_failure_before_any_success_is_still_an_error_not_gray(env):
    feeds, reader, feed, _ = env
    feeds.record_failure(feed, "HTTP 404")
    assert state(reader, feed).state == "error"


def test_changing_the_url_resets_the_checks_and_goes_back_to_the_baseline_state(env):
    feeds, reader, feed, _ = env
    feeds.record_success(feed, etag="e1", last_modified="m1", activate=True)
    assert feeds.get(feed).status == STATUS_ACTIVE
    assert feeds.change_feed_url(feed, "https://b.example.com/feed.xml") is True
    changed = feeds.get(feed)
    assert changed.url == "https://b.example.com/feed.xml"
    assert (changed.etag, changed.last_modified, changed.fail_count, changed.last_error) == (
        None,
        None,
        0,
        None,
    )
    assert changed.last_checked_at is None and changed.status == STATUS_BASELINE
    assert state(reader, feed).state == "never"


def test_the_new_url_key_is_used_for_duplicate_detection(env):
    feeds, _, feed, _ = env
    feeds.change_feed_url(feed, "https://b.example.com/feed.xml")
    with pytest.raises(DuplicateFeedError):
        feeds.add("https://b.example.com/feed.xml", "중복")


def test_a_url_that_another_feed_already_has_is_refused_and_nothing_changes(env):
    feeds, _, _feed, _ = env
    other = feeds.add("https://c.example.com/rss", "C")
    with pytest.raises(DuplicateFeedError):
        feeds.change_feed_url(other, "https://a.example.com/rss")
    assert feeds.get(other).url == "https://c.example.com/rss"


def test_a_missing_feed_is_reported(env):
    assert env[0].change_feed_url(999, "https://x.example.com/rss") is False
