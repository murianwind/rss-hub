import hashlib

import pytest

from rss_hub.domain.guid import normalize_guid, select_guid


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "https://blog.naver.com/abc/123?fromRss=true&trackingCode=rss",
            "https://blog.naver.com/abc/123",
        ),
        (
            "https://blog.naver.com/abc/123?fromRss=true&trackingCode=rss&x=1",
            "https://blog.naver.com/abc/123?x=1",
        ),
        ("https://example.com/p?a=1&a=2", "https://example.com/p?a=1"),
        (
            "https://example.com/p?q=hello world&z=%EA%B0%80",
            "https://example.com/p?q=hello+world&z=%EA%B0%80",
        ),
        ("tag:example.com,2026:post-1", "tag:example.com,2026:post-1"),
        ("https://example.com/post#frag", "https://example.com/post#frag"),
        ("https://example.com/p?empty=&k=v", "https://example.com/p?empty=&k=v"),
        ("", ""),
        (None, None),
    ],
)
def test_normalize_guid(raw, expected):
    assert normalize_guid(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "https://blog.naver.com/abc/123?fromRss=true&trackingCode=rss&x=1",
        "https://example.com/p?q=hello world",
        "urn:uuid:1225c695-cfb8-4ebb-aaaa-80da344efa6a",
    ],
)
def test_normalize_guid_is_idempotent(raw):
    once = normalize_guid(raw)
    assert normalize_guid(once) == once


def test_select_guid_prefers_id_then_guid_then_link():
    assert select_guid({"id": "i", "guid": "g", "link": "l"}) == "i"
    assert select_guid({"guid": "g", "link": "l"}) == "g"
    assert select_guid({"link": "l"}) == "l"


def test_select_guid_skips_empty_values():
    assert select_guid({"id": "", "guid": "g"}) == "g"


def test_select_guid_normalizes_the_chosen_value():
    assert select_guid({"link": "https://x.com/l?fromRss=true"}) == "https://x.com/l"


def test_select_guid_falls_back_to_hash_of_title_and_summary():
    expected = hashlib.sha1(b"ts").hexdigest()
    assert select_guid({"title": "t", "summary": "s"}) == expected


def test_select_guid_hash_ignores_unencodable_characters():
    entry = {"title": "제목\ud800", "summary": "요약"}
    assert len(select_guid(entry)) == 40


def test_normalize_guid_returns_the_original_when_the_value_cannot_be_parsed():
    broken = "http://[::1/feed?fromRss=true"  # 닫히지 않은 IPv6 주소
    assert normalize_guid(broken) == broken
