from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from rss_hub.adapters.http_feed_fetcher import RequestsFeedFetcher
from rss_hub.domain.dates import parse_entry_datetime
from rss_hub.domain.guid import select_guid
from rss_hub.services.ports import FetchError
from tests.fakes.http_server import LocalServer
from tests.fakes.network import allow_all

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "feeds"
SEOUL = ZoneInfo("Asia/Seoul")


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


@pytest.fixture
def server():
    local = LocalServer()
    local.start()
    yield local
    local.stop()


@pytest.fixture
def fetcher():
    return RequestsFeedFetcher(timeout=(1.0, 1.0), forbid_address=allow_all)


def fetch(fetcher, server, path="/feed", **kwargs):
    return fetcher.fetch(
        server.url(path), etag=kwargs.get("etag"), last_modified=kwargs.get("last_modified")
    )


def reason_of(fetcher, server, path="/feed", **kwargs):
    with pytest.raises(FetchError) as info:
        fetch(fetcher, server, path, **kwargs)
    return info.value.reason


# ---------- 정상 응답 ----------


def test_rss_is_fetched_and_parsed_into_entries(fetcher, server):
    server.serve(
        "/feed", body=fixture("rss_basic.xml"), headers={"Content-Type": "application/rss+xml"}
    )
    result = fetch(fetcher, server)
    assert result.status == 200
    assert [e["title"] for e in result.entries] == ["첫 번째 글", "두 번째 글"]
    first = result.entries[0]
    assert first["link"] == "https://blog.example.com/posts/1"
    assert first["summary"] == "<p>안녕하세요</p>"


def test_atom_is_fetched_too(fetcher, server):
    server.serve("/feed", body=fixture("atom_basic.xml"))
    result = fetch(fetcher, server)
    assert len(result.entries) == 1
    assert result.entries[0]["id"] == "urn:uuid:1225c695-cfb8-4ebb-aaaa-80da344efa6a"


def test_entry_dates_can_be_interpreted_by_the_domain_rules(fetcher, server):
    server.serve("/feed", body=fixture("rss_basic.xml"))
    entry = fetch(fetcher, server).entries[0]
    parsed = parse_entry_datetime(entry, SEOUL)
    assert parsed is not None
    assert parsed.isoformat() == "2026-10-16T01:30:00+09:00"


def test_tracking_parameters_are_removed_by_the_guid_rule(fetcher, server):
    server.serve("/feed", body=fixture("naver_tracking.xml"))
    entry = fetch(fetcher, server).entries[0]
    assert select_guid(entry) == "https://blog.naver.com/abc/123"


def test_entries_without_dates_are_still_returned(fetcher, server):
    server.serve("/feed", body=fixture("no_date.xml"))
    entry = fetch(fetcher, server).entries[0]
    assert parse_entry_datetime(entry, SEOUL) is None


def test_an_empty_but_valid_feed_is_a_success_with_no_entries(fetcher, server):
    server.serve("/feed", body=fixture("empty.xml"))
    result = fetch(fetcher, server)
    assert (result.status, result.entries) == (200, ())


def test_validators_from_the_response_are_returned(fetcher, server):
    server.serve(
        "/feed",
        body=fixture("rss_basic.xml"),
        headers={"ETag": '"v1"', "Last-Modified": "Thu, 15 Oct 2026 00:00:00 GMT"},
    )
    result = fetch(fetcher, server)
    assert (result.etag, result.last_modified) == ('"v1"', "Thu, 15 Oct 2026 00:00:00 GMT")


def test_redirects_are_followed(fetcher, server):
    server.serve("/old", status=302, headers={"Location": "/feed"})
    server.serve("/feed", body=fixture("rss_basic.xml"))
    assert len(fetch(fetcher, server, "/old").entries) == 2


# ---------- 조건부 요청 ----------


def test_stored_validators_are_sent_as_conditional_headers(fetcher, server):
    server.serve("/feed", body=fixture("rss_basic.xml"))
    fetch(fetcher, server, etag='"v1"', last_modified="Thu, 15 Oct 2026 00:00:00 GMT")
    headers = server.requests[-1].headers
    assert headers["if-none-match"] == '"v1"'
    assert headers["if-modified-since"] == "Thu, 15 Oct 2026 00:00:00 GMT"


def test_no_conditional_headers_without_stored_validators(fetcher, server):
    server.serve("/feed", body=fixture("rss_basic.xml"))
    fetch(fetcher, server)
    headers = server.requests[-1].headers
    assert "if-none-match" not in headers and "if-modified-since" not in headers


def test_not_modified_returns_status_304_and_keeps_the_validators(fetcher, server):
    server.serve("/feed", status=304)
    result = fetch(fetcher, server, etag='"v1"', last_modified="Thu, 15 Oct 2026 00:00:00 GMT")
    assert (result.status, result.entries) == (304, ())
    assert (result.etag, result.last_modified) == ('"v1"', "Thu, 15 Oct 2026 00:00:00 GMT")


def test_a_user_agent_that_identifies_the_service_is_sent(fetcher, server):
    server.serve("/feed", body=fixture("rss_basic.xml"))
    fetch(fetcher, server)
    assert "RSS Hub" in server.requests[-1].headers["user-agent"]


# ---------- 실패 ----------


@pytest.mark.parametrize("status", [404, 410, 500, 503])
def test_http_errors_are_reported_with_the_status(fetcher, server, status):
    server.serve("/feed", status=status, body=b"error")
    assert reason_of(fetcher, server) == f"HTTP {status}"


def test_unknown_path_is_a_404(fetcher, server):
    assert reason_of(fetcher, server, "/missing") == "HTTP 404"


def test_connection_refused_is_a_connection_error(fetcher):
    with pytest.raises(FetchError) as info:
        fetcher.fetch("http://127.0.0.1:1/feed", etag=None, last_modified=None)
    assert info.value.reason == "ConnectionError"


def test_a_server_that_does_not_answer_times_out(server):
    server.serve("/slow", body=fixture("rss_basic.xml"), delay=2.0)
    quick = RequestsFeedFetcher(timeout=(0.5, 0.3), forbid_address=allow_all)
    assert reason_of(quick, server, "/slow") == "ReadTimeout"


def test_a_page_that_is_not_a_feed_is_a_failure_not_an_empty_success(fetcher, server):
    server.serve("/feed", body=fixture("not_a_feed.html"), headers={"Content-Type": "text/html"})
    assert reason_of(fetcher, server) == "NotAFeed"


def test_a_response_larger_than_the_limit_is_rejected(server):
    server.serve("/feed", body=b"x" * 5000)
    small = RequestsFeedFetcher(timeout=(1.0, 1.0), max_bytes=1000, forbid_address=allow_all)
    assert reason_of(small, server) == "TooLarge"


def test_a_response_exactly_at_the_limit_is_accepted(server):
    body = fixture("empty.xml")
    server.serve("/feed", body=body)
    exact = RequestsFeedFetcher(timeout=(1.0, 1.0), max_bytes=len(body), forbid_address=allow_all)
    assert fetch(exact, server).status == 200


def test_the_default_timeouts_are_a_few_seconds():
    connect, read = RequestsFeedFetcher().timeout
    assert 0 < connect <= 10 and 0 < read <= 30
    assert timedelta(seconds=read) > timedelta(0)
