from datetime import timedelta

import pytest

from rss_hub.storage.database import Database
from rss_hub.storage.import_staging import ImportStagingRepository
from tests.fakes.clock import FakeClock

HOUR = timedelta(minutes=60)


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def staging(tmp_path, clock):
    return ImportStagingRepository(Database(tmp_path / "rss_hub.db"), clock)


def test_a_saved_payload_can_be_loaded_with_its_token(staging):
    token = staging.save('{"a": 1}', ttl=HOUR)
    assert staging.load(token) == '{"a": 1}'


def test_tokens_are_long_unique_and_hard_to_guess(staging):
    tokens = {staging.save("x", ttl=HOUR) for _ in range(50)}
    assert len(tokens) == 50
    assert all(len(token) >= 30 for token in tokens)


def test_an_unknown_token_loads_nothing(staging):
    assert staging.load("nope") is None


def test_a_payload_is_available_until_the_ttl_and_expired_exactly_at_it(staging, clock):
    token = staging.save("x", ttl=HOUR)
    clock.advance(minutes=59, seconds=59)
    assert staging.load(token) == "x"
    clock.advance(seconds=1)
    assert staging.load(token) is None


def test_loading_an_expired_payload_removes_it(staging, clock):
    token = staging.save("x", ttl=HOUR)
    clock.advance(minutes=61)
    staging.load(token)
    assert staging.count() == 0


def test_delete_removes_the_payload_and_ignores_unknown_tokens(staging):
    token = staging.save("x", ttl=HOUR)
    staging.delete(token)
    staging.delete("unknown")
    assert staging.load(token) is None


def test_purging_removes_only_expired_payloads(staging, clock):
    old = staging.save("old", ttl=HOUR)
    clock.advance(minutes=30)
    fresh = staging.save("fresh", ttl=HOUR)
    clock.advance(minutes=31)  # old는 61분, fresh는 31분
    assert staging.purge_expired() == 1
    assert staging.load(old) is None and staging.load(fresh) == "fresh"
