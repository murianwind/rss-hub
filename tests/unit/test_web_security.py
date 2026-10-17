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


# ---------- 실제 브라우저의 헤더 조합 ----------
# 이 서비스는 Referrer-Policy를 보내고, 브라우저는 그 정책에 따라 폼 제출의 Origin을 정한다.
# Sec-Fetch-Site는 브라우저가 직접 붙이는 값이라 스크립트가 바꿀 수 없다.


def test_a_same_origin_form_post_is_allowed_even_when_the_browser_sends_origin_null():
    # Referrer-Policy가 no-referrer이면 브라우저는 같은 사이트 폼 제출에도 Origin: null을 보낸다
    assert check(host="rss.example.com", origin="null", sec_fetch_site="same-origin") is True


def test_a_same_origin_post_is_allowed_whatever_host_the_proxy_forwards():
    # 리버스 프록시가 Host를 바꿔도(내부 주소) 브라우저의 판단(Sec-Fetch-Site)은 변하지 않는다
    headers = {
        "host": "172.21.0.2:8000",
        "origin": "https://rss.example.com",
        "sec_fetch_site": "same-origin",
    }
    assert check(**headers) is True


def test_a_user_typing_the_address_or_using_a_bookmark_is_not_a_cross_site_request():
    assert check(host="rss.example.com", sec_fetch_site="none") is True


@pytest.mark.parametrize("site", ["cross-site", "same-site"])
def test_other_sites_are_rejected_even_with_a_matching_or_null_origin(site):
    assert check(host="rss.example.com", origin="null", sec_fetch_site=site) is False
    assert (
        check(host="rss.example.com", origin="https://rss.example.com", sec_fetch_site=site)
        is False
    )


def test_an_older_browser_without_sec_fetch_site_is_judged_by_its_origin():
    assert check(host="rss.example.com", origin="https://rss.example.com") is True
    assert check(host="rss.example.com", origin="https://evil.example.com") is False
    assert check(host="rss.example.com", origin="null") is False  # 어디서 왔는지 알 수 없다
