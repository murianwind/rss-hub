import pytest

from rss_hub.domain.delivery import SendOutcome, classify_status, pause_after_send, retry_wait


@pytest.mark.parametrize("status", [200, 204, 299])
def test_success(status):
    assert classify_status(status) is SendOutcome.SENT


def test_rate_limit():
    assert classify_status(429) is SendOutcome.RATE_LIMITED


@pytest.mark.parametrize("status", [400, 401, 403, 404, 410])
def test_the_webhook_or_request_itself_is_wrong(status):
    assert classify_status(status) is SendOutcome.PERMANENT


@pytest.mark.parametrize("status", [0, 408, 500, 502, 503, 504, 599])
def test_server_trouble_and_network_failures_are_retried_later(status):
    assert classify_status(status) is SendOutcome.TRANSIENT


@pytest.mark.parametrize("status", [301, 302, 100])
def test_unexpected_statuses_are_retried_later(status):
    assert classify_status(status) is SendOutcome.TRANSIENT


@pytest.mark.parametrize(
    ("remaining", "reset_after", "expected"),
    [
        (4, 1.0, 0.0),
        (1, 1.0, 0.0),
        (0, 1.0, 1.1),
        (0, 0.4, 0.5),
        (0, 99.0, 10.0),
        (0, None, 0.0),
        (None, 1.0, 0.0),
        (None, None, 0.0),
    ],
)
def test_wait_for_the_bucket_to_refill_only_when_it_is_empty(remaining, reset_after, expected):
    assert pause_after_send(remaining, reset_after) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("retry_after", "expected"), [(2.0, 2.0), (40.0, 30.0), (None, 5.0), (0.0, 5.0)]
)
def test_retry_wait(retry_after, expected):
    assert retry_wait(retry_after) == expected
