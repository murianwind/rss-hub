import time

import pytest

from rss_hub.adapters.discord_webhook import (
    DiscordNotifier,
    NotificationFailed,
    RequestsWebhookSender,
    check_webhook_address,
)
from tests.fakes.http_server import FakeServer, json_reply

TOKEN = "SECRETTOKEN123"


def make_server(handler):
    server = FakeServer(handler)
    server.start()
    return server


@pytest.fixture
def servers():
    made = []

    def make(handler):
        server = make_server(handler)
        made.append(server)
        sender = RequestsWebhookSender(
            timeout=(1.0, 1.0), allowed_hosts=("127.0.0.1",), require_https=False
        )
        return server, sender, server.url(f"/api/webhooks/1/{TOKEN}")

    yield make
    for server in made:
        server.stop()


RATE = {"X-RateLimit-Limit": "5", "X-RateLimit-Remaining": "4", "X-RateLimit-Reset-After": "1.5"}


def test_the_message_is_posted_as_json_without_pinging_anyone(servers):
    server, sender, url = servers(lambda *_: json_reply(200, {"id": "999"}, RATE))
    sender.send(url, "안녕 @everyone")
    method, path, _headers, body = server.requests[0]
    assert (method, path) == ("POST", f"/api/webhooks/1/{TOKEN}?wait=true")
    assert body == {"content": "안녕 @everyone", "allowed_mentions": {"parse": []}}


def test_a_successful_send_reports_the_message_id_and_the_rate_limit_state(servers):
    _, sender, url = servers(lambda *_: json_reply(200, {"id": "999"}, RATE))
    result = sender.send(url, "x")
    assert (result.status, result.message_id) == (200, "999")
    assert (result.rate_remaining, result.rate_reset_after) == (4, 1.5)


def test_an_empty_success_has_no_message_id(servers):
    _, sender, url = servers(lambda *_: (204, {}, b""))
    result = sender.send(url, "x")
    assert (result.status, result.message_id, result.rate_remaining) == (204, None, None)


def test_a_success_with_an_unreadable_body_is_still_a_success(servers):
    _, sender, url = servers(lambda *_: (200, {"Content-Type": "text/plain"}, b"not json"))
    result = sender.send(url, "x")
    assert (result.status, result.message_id) == (200, None)


@pytest.mark.parametrize("status", [401, 403, 404, 500, 503])
def test_error_statuses_are_reported_as_they_are(servers, status):
    _, sender, url = servers(lambda *_: json_reply(status, {"message": "x"}))
    assert sender.send(url, "x").status == status


def test_rate_limit_wait_prefers_the_header_then_the_body(servers):
    _, sender, url = servers(lambda *_: json_reply(429, {"retry_after": 9.5}, {"Retry-After": "2"}))
    assert sender.send(url, "x").retry_after == 2.0
    _, sender, url = servers(lambda *_: json_reply(429, {"retry_after": 1.25}))
    assert sender.send(url, "x").retry_after == 1.25
    _, sender, url = servers(lambda *_: json_reply(429, {}))
    assert sender.send(url, "x").retry_after is None


def test_a_garbled_rate_limit_header_is_ignored(servers):
    _, sender, url = servers(
        lambda *_: json_reply(429, {}, {"Retry-After": "soon", "X-RateLimit-Remaining": "many"})
    )
    result = sender.send(url, "x")
    assert (result.retry_after, result.rate_remaining) == (None, None)


def test_a_refused_connection_is_a_network_failure_that_does_not_leak_the_address():
    sender = RequestsWebhookSender(
        timeout=(1.0, 1.0), allowed_hosts=("127.0.0.1",), require_https=False
    )
    url = f"http://127.0.0.1:1/api/webhooks/1/{TOKEN}"
    result = sender.send(url, "x")
    assert (result.status, result.error) == (0, "ConnectionError")
    assert TOKEN not in result.error


def test_a_slow_server_is_a_network_failure(servers):
    def slow(*_):
        time.sleep(1.5)
        return json_reply(200, {"id": "1"})

    _, sender, url = servers(slow)
    result = sender.send(url, "x")
    assert (result.status, result.error) == (0, "ReadTimeout")


# ---------- 주소 검사 ----------


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        ("https://discord.com/api/webhooks/123/abcDEF", True),
        ("https://discordapp.com/api/webhooks/123/abcDEF", True),
        ("https://ptb.discord.com/api/webhooks/123/abc", True),
        ("http://discord.com/api/webhooks/123/abc", False),
        ("https://evil.example.com/api/webhooks/123/abc", False),
        ("https://discord.com.evil.com/api/webhooks/123/abc", False),
        ("https://discord.com/other/path", False),
        ("not a url", False),
    ],
)
def test_only_discord_webhook_addresses_are_accepted_by_default(url, ok):
    assert (check_webhook_address(url) == "") is ok


def test_a_forbidden_address_is_rejected_without_sending_anything(servers):
    server, _, url = servers(lambda *_: json_reply(200, {"id": "1"}))
    strict = RequestsWebhookSender()
    result = strict.send(url, "x")
    assert (result.status, result.error) == (400, "InvalidWebhookAddress")
    assert server.requests == []


# ---------- 시스템 알림 전송기 ----------


def test_the_notifier_sends_the_text(servers):
    server, sender, url = servers(lambda *_: json_reply(200, {"id": "1"}))
    DiscordNotifier(sender).send(url, "호출 상한 도달")
    assert server.requests[0][3]["content"] == "호출 상한 도달"


def test_the_notifier_shortens_text_that_is_too_long(servers):
    server, sender, url = servers(lambda *_: json_reply(200, {"id": "1"}))
    DiscordNotifier(sender).send(url, "가" * 5000)
    sent = server.requests[0][3]["content"]
    assert len(sent) == 1900 and sent.endswith("…")


def test_the_notifier_raises_when_discord_refuses_without_leaking_the_address(servers):
    _, sender, url = servers(lambda *_: json_reply(404, {"message": "Unknown Webhook"}))
    with pytest.raises(NotificationFailed) as failure:
        DiscordNotifier(sender).send(url, "x")
    assert "404" in str(failure.value)
    assert TOKEN not in str(failure.value) and url not in str(failure.value)


def test_the_notifier_raises_on_network_failure():
    sender = RequestsWebhookSender(
        timeout=(1.0, 1.0), allowed_hosts=("127.0.0.1",), require_https=False
    )
    with pytest.raises(NotificationFailed) as failure:
        DiscordNotifier(sender).send(f"http://127.0.0.1:1/api/webhooks/1/{TOKEN}", "x")
    assert TOKEN not in str(failure.value)
