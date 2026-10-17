import pytest

from rss_hub.domain.feed_url import FeedUrlError, feed_url_key, validate_feed_url


@pytest.mark.parametrize(
    "url",
    [
        "https://a.example.com/feed",
        "http://a.example.com/rss.xml",
        "https://a.example.com:8443/x?y=1",
    ],
)
def test_valid_urls_are_returned_stripped(url):
    assert validate_feed_url(f"  {url}  ") == url


@pytest.mark.parametrize(
    ("url", "message"),
    [
        (None, "주소 없음"),
        ("", "주소 없음"),
        ("   ", "주소 없음"),
        ("ftp://x.example.com/feed", "http, https만 가능"),
        ("javascript:alert(1)", "http, https만 가능"),
        ("file:///etc/passwd", "http, https만 가능"),
        ("x.example.com/feed", "http, https만 가능"),
        ("https://", "호스트 없음"),
        ("https:///path", "호스트 없음"),
        ("https://x.example.com/" + "a" * 2100, "주소가 너무 김"),
    ],
)
def test_invalid_urls(url, message):
    with pytest.raises(FeedUrlError) as info:
        validate_feed_url(url)
    assert info.value.message == message


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("https://n.example.com/rss", "https://n.example.com/rss"),
        ("https://n.example.com/rss", "https://N.Example.com/rss"),
        ("https://n.example.com/rss/", "https://n.example.com/rss"),
        ("HTTPS://n.example.com/rss", "https://n.example.com/rss"),
        ("https://n.example.com", "https://n.example.com/"),
        ("https://n.example.com/rss#top", "https://n.example.com/rss"),
    ],
)
def test_same_feed_gets_same_key(first, second):
    assert feed_url_key(first) == feed_url_key(second)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("https://n.example.com/rss", "https://n.example.com/RSS"),  # 경로는 대소문자를 구분한다
        ("https://n.example.com/rss?a=1", "https://n.example.com/rss?a=2"),
        ("https://n.example.com/rss", "http://n.example.com/rss"),
        ("https://n.example.com:8443/rss", "https://n.example.com/rss"),
    ],
)
def test_different_feeds_get_different_keys(first, second):
    assert feed_url_key(first) != feed_url_key(second)


def test_malformed_host_is_rejected_with_a_clear_message():
    with pytest.raises(FeedUrlError) as info:
        validate_feed_url("http://[::1/feed")
    assert info.value.message == "주소 형식이 올바르지 않음"


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/feed",
        "http://localhost/rss",
        "http://192.168.0.10/rss",
        "http://10.0.0.5/rss",
        "http://172.16.0.1/rss",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/rss",
        "http://2130706433/rss",
        "http://nas/rss",
        "http://printer.local/rss",
        "https://user:pass@192.168.0.10/rss",
    ],
)
def test_private_and_internal_addresses_are_rejected(url):
    with pytest.raises(FeedUrlError) as info:
        validate_feed_url(url)
    assert info.value.message == "사설망·내부 주소는 허용하지 않음"


def test_the_message_does_not_repeat_the_address():
    with pytest.raises(FeedUrlError) as info:
        validate_feed_url("http://192.168.0.10/rss")
    assert "192.168" not in info.value.message


@pytest.mark.parametrize(
    "url",
    [
        "https://a.example.com:99999/rss",
        "https://a.example.com:abc/rss",
        "https://a.example.com:-1/rss",
    ],
)
def test_an_invalid_port_is_rejected_instead_of_crashing_later(url):
    with pytest.raises(FeedUrlError) as info:
        validate_feed_url(url)
    assert info.value.message == "주소 형식이 올바르지 않음"
