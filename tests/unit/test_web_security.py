import pytest

from rss_hub.web.security import request_is_same_origin


def check(**headers):
    return request_is_same_origin({k.replace("_", "-"): v for k, v in headers.items()})


def test_requests_without_browser_headers_are_allowed():
    # curl 같은 도구는 CSRF 경로가 아니다(브라우저만 사용자를 대신해서 요청을 만들 수 있다)
    assert check(host="rss.example.com") is True


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({"host": "rss.example.com", "origin": "https://rss.example.com"}, True),
        ({"host": "rss.example.com:8443", "origin": "https://rss.example.com:8443"}, True),
        ({"host": "rss.example.com", "origin": "https://RSS.Example.com"}, True),
        ({"host": "rss.example.com", "origin": "https://evil.example.com"}, False),
        ({"host": "rss.example.com", "origin": "https://rss.example.com.evil.com"}, False),
        ({"host": "rss.example.com", "origin": "null"}, False),
        ({"host": "rss.example.com", "origin": ""}, False),
    ],
)
def test_origin_must_match_the_host(headers, expected):
    assert request_is_same_origin(headers) is expected


@pytest.mark.parametrize(
    ("site", "expected"),
    [("same-origin", True), ("none", True), ("cross-site", False), ("same-site", False)],
)
def test_sec_fetch_site(site, expected):
    headers = {"host": "rss.example.com", "sec-fetch-site": site}
    assert request_is_same_origin(headers) is expected


def test_proxy_forwarded_host_is_accepted_when_origin_matches_it():
    headers = {
        "host": "192.168.0.5:8000",
        "x-forwarded-host": "rss.example.com",
        "origin": "https://rss.example.com",
    }
    assert request_is_same_origin(headers) is True


def test_forwarded_host_does_not_excuse_a_foreign_origin():
    headers = {
        "host": "192.168.0.5:8000",
        "x-forwarded-host": "rss.example.com",
        "origin": "https://evil.example.com",
    }
    assert request_is_same_origin(headers) is False


def test_first_value_of_a_multi_valued_forwarded_host_is_used():
    headers = {
        "host": "10.0.0.1",
        "x-forwarded-host": "rss.example.com, proxy.internal",
        "origin": "https://rss.example.com",
    }
    assert request_is_same_origin(headers) is True


def test_cross_site_marker_wins_even_if_origin_matches():
    headers = {
        "host": "rss.example.com",
        "origin": "https://rss.example.com",
        "sec-fetch-site": "cross-site",
    }
    assert request_is_same_origin(headers) is False
