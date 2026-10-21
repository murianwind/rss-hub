"""피드를 가져올 때 사설망으로 연결되지 않는지: 실제로 연결된 상대 IP를 연결 시점에 검사한다."""

import socket

import pytest

from rss_hub.adapters.http_feed_fetcher import RequestsFeedFetcher
from rss_hub.services.ports import FetchError
from tests.fakes.http_server import FakeServer

RSS = b'<?xml version="1.0"?><rss version="2.0"><channel><title>t</title></channel></rss>'


def serve(host="127.0.0.1", handler=None):
    server = FakeServer(
        handler or (lambda *_: (200, {"Content-Type": "application/rss+xml"}, RSS)), host
    )
    server.start()
    return server


@pytest.fixture
def servers():
    made = []

    def make(host="127.0.0.1", handler=None):
        server = serve(host, handler)
        made.append(server)
        return server

    yield make
    for server in made:
        server.stop()


def reason(fetcher, url):
    with pytest.raises(FetchError) as info:
        fetcher.fetch(url, etag=None, last_modified=None)
    return info.value.reason


def test_by_default_a_loopback_server_is_refused_before_any_request_is_sent(servers):
    server = servers()
    assert (
        reason(RequestsFeedFetcher(timeout=(1.0, 1.0)), server.url("/feed")) == "ForbiddenAddress"
    )
    assert server.requests == []


def test_the_unspecified_address_that_reaches_localhost_is_refused_too(servers):
    server = servers()
    url = server.url("/feed").replace("127.0.0.1", "0.0.0.0")
    assert reason(RequestsFeedFetcher(timeout=(1.0, 1.0)), url) == "ForbiddenAddress"
    assert server.requests == []


def test_an_https_address_is_checked_before_the_tls_handshake(servers):
    server = servers()
    url = server.url("/feed").replace("http://", "https://")
    # 검사가 없었다면 일반 HTTP 서버와 TLS 협상을 시도하다가 SSLError가 났을 것이다
    assert reason(RequestsFeedFetcher(timeout=(1.0, 1.0)), url) == "ForbiddenAddress"
    assert server.requests == []


def test_a_name_that_looks_public_but_resolves_to_a_private_address_is_refused(
    servers, monkeypatch
):
    server = servers()
    real = socket.getaddrinfo

    def fake_getaddrinfo(host, *args, **kwargs):
        return real("127.0.0.1" if host == "feeds.example.com" else host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    port = server.url("").rsplit(":", 1)[1]
    url = f"http://feeds.example.com:{port}/feed"
    assert reason(RequestsFeedFetcher(timeout=(1.0, 1.0)), url) == "ForbiddenAddress"
    assert server.requests == []


def test_a_redirect_to_a_forbidden_address_is_refused_while_the_first_hop_is_fine(servers):
    target = servers("127.0.0.2")
    start = servers(
        handler=lambda *_: (302, {"Location": target.url("/feed")}, b""),
    )
    only_second_is_private = lambda ip: ip == "127.0.0.2"  # noqa: E731
    fetcher = RequestsFeedFetcher(timeout=(1.0, 1.0), forbid_address=only_second_is_private)
    assert reason(fetcher, start.url("/feed")) == "ForbiddenAddress"
    assert len(start.requests) == 1  # 첫 번째 주소에는 갔고
    assert target.requests == []  # 리다이렉트로 닿은 사설망 서버에는 요청이 가지 않았다


def test_a_redirect_between_allowed_addresses_is_followed(servers):
    target = servers("127.0.0.2")
    start = servers(handler=lambda *_: (302, {"Location": target.url("/feed")}, b""))
    fetcher = RequestsFeedFetcher(timeout=(1.0, 1.0), forbid_address=lambda ip: False)
    result = fetcher.fetch(start.url("/feed"), etag=None, last_modified=None)
    assert result.status == 200 and len(target.requests) == 1


def test_proxy_settings_from_the_environment_are_ignored(servers, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")
    server = servers()
    fetcher = RequestsFeedFetcher(timeout=(1.0, 1.0), forbid_address=lambda ip: False)
    assert fetcher.fetch(server.url("/feed"), etag=None, last_modified=None).status == 200


def test_the_refusal_message_never_contains_the_address(servers):
    server = servers()
    url = server.url("/feed")
    result = reason(RequestsFeedFetcher(timeout=(1.0, 1.0)), url)
    assert "127.0.0.1" not in result


def test_an_allowed_https_connection_goes_on_to_the_tls_handshake(servers):
    server = servers()
    url = server.url("/feed").replace("http://", "https://")
    fetcher = RequestsFeedFetcher(timeout=(1.0, 1.0), forbid_address=lambda ip: False)
    # 주소 검사를 통과했으므로 TLS 협상까지 가고, 일반 HTTP 서버라서 거기서 실패한다
    assert reason(fetcher, url) == "SSLError"
