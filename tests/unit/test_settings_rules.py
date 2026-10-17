import pytest

from rss_hub.domain.settings_rules import (
    SettingError,
    normalize_base_url,
    normalize_model_chain,
    normalize_webhook_url,
    parse_collect_interval,
    parse_job_interval_seconds,
    parse_percent,
    parse_positive_int,
    validate_timezone,
    validate_webhook_name,
)

SCHEME_MESSAGE = "http:// 또는 https://로 시작해야 함"
WEBHOOK_MESSAGE = "Discord 웹훅 주소가 아님"
DIVISOR_MESSAGE = "60의 약수만 가능(1,2,3,4,5,6,10,12,15,20,30,60)"


def error_of(func, *args):
    with pytest.raises(SettingError) as info:
        func(*args)
    return info.value.message


# ---------- 서비스 주소 ----------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://rss.example.com/", "https://rss.example.com"),
        ("https://RSS.Example.com", "https://rss.example.com"),
        ("http://192.168.0.5:8000", "http://192.168.0.5:8000"),
        ("https://example.com/rss/", "https://example.com/rss"),
        ("  https://rss.example.com  ", "https://rss.example.com"),
        ("https://rss.example.com/?x=1#y", "https://rss.example.com"),
    ],
)
def test_normalize_base_url(raw, expected):
    assert normalize_base_url(raw) == expected


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("rss.example.com", SCHEME_MESSAGE),
        ("ftp://rss.example.com", SCHEME_MESSAGE),
        ("javascript:alert(1)", SCHEME_MESSAGE),
        ("", SCHEME_MESSAGE),
        ("https://", "주소에 호스트가 필요함"),
    ],
)
def test_base_url_errors(raw, message):
    assert error_of(normalize_base_url, raw) == message


# ---------- 웹훅 주소 ----------


@pytest.mark.parametrize(
    "url",
    [
        "https://discord.com/api/webhooks/123/abcDEF",
        "https://discordapp.com/api/webhooks/123/abcDEF",
        "https://ptb.discord.com/api/webhooks/123/abcDEF",
        "https://canary.discord.com/api/webhooks/123/abc-DEF_1.2",
        "https://discord.com/api/v10/webhooks/123/abcDEF",
    ],
)
def test_valid_webhook_urls(url):
    assert normalize_webhook_url(url) == url


def test_webhook_url_drops_query_and_fragment():
    assert (
        normalize_webhook_url("https://discord.com/api/webhooks/123/abc?wait=true#x")
        == "https://discord.com/api/webhooks/123/abc"
    )


@pytest.mark.parametrize(
    ("url", "message"),
    [
        ("http://discord.com/api/webhooks/123/abcDEF", "https만 가능"),
        ("https://evil.example.com/api/webhooks/123/abcDEF", WEBHOOK_MESSAGE),
        ("https://discord.com.evil.example.com/api/webhooks/1/a", WEBHOOK_MESSAGE),
        ("https://notdiscord.com/api/webhooks/123/abc", WEBHOOK_MESSAGE),
        ("https://192.168.0.10/api/webhooks/123/abcDEF", WEBHOOK_MESSAGE),
        ("https://discord.com/api/other/123/abc", WEBHOOK_MESSAGE),
        ("https://discord.com/api/webhooks/abc/def", WEBHOOK_MESSAGE),
        ("https://discord.com:8443/api/webhooks/123/abc", WEBHOOK_MESSAGE),
        ("https://user:pw@discord.com/api/webhooks/123/abc", WEBHOOK_MESSAGE),
        ("https://evil.com@discord.com/api/webhooks/123/abc", WEBHOOK_MESSAGE),
        ("", WEBHOOK_MESSAGE),
        ("not a url", WEBHOOK_MESSAGE),
    ],
)
def test_invalid_webhook_urls(url, message):
    assert error_of(normalize_webhook_url, url) == message


def test_webhook_error_message_does_not_echo_the_value():
    secret = "https://evil.example.com/api/webhooks/123/SECRETTOKEN"
    assert "SECRETTOKEN" not in error_of(normalize_webhook_url, secret)


# ---------- 주기 ----------


@pytest.mark.parametrize("raw", ["1", "5", "10", "30", "60", " 15 "])
def test_collect_interval_accepts_divisors_of_sixty(raw):
    assert parse_collect_interval(raw) == int(raw)


@pytest.mark.parametrize("raw", ["7", "0", "-5", "61", "120"])
def test_collect_interval_rejects_others(raw):
    assert error_of(parse_collect_interval, raw) == DIVISOR_MESSAGE


@pytest.mark.parametrize("raw", ["", "abc", "5.5", "5분"])
def test_collect_interval_rejects_non_integers(raw):
    assert error_of(parse_collect_interval, raw) == "숫자만 입력할 수 있음"


@pytest.mark.parametrize("raw", ["10", "60", "3600"])
def test_job_interval_accepts_range(raw):
    assert parse_job_interval_seconds(raw) == int(raw)


@pytest.mark.parametrize("raw", ["9", "0", "3601", "-1"])
def test_job_interval_rejects_out_of_range(raw):
    assert error_of(parse_job_interval_seconds, raw) == "10~3600초 사이"


def test_job_interval_rejects_non_integers():
    assert error_of(parse_job_interval_seconds, "ten") == "숫자만 입력할 수 있음"


# ---------- 시간대와 모델 체인 ----------


@pytest.mark.parametrize("name", ["Asia/Seoul", "UTC", "America/New_York"])
def test_valid_timezones(name):
    assert validate_timezone(name) == name


@pytest.mark.parametrize("name", ["KST", "Korea Standard", "", "../etc/passwd", "Asia/Nowhere"])
def test_invalid_timezones(name):
    assert error_of(validate_timezone, name) == "IANA 시간대 이름이 아님"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("model-a, model-b", ("model-a", "model-b")),
        ("model-a, model-a", ("model-a",)),
        ("a/b:free , c/d:free", ("a/b:free", "c/d:free")),
        (["x", " y ", "x"], ("x", "y")),
    ],
)
def test_normalize_model_chain(raw, expected):
    assert normalize_model_chain(raw) == expected


@pytest.mark.parametrize("raw", ["", " , ,", []])
def test_model_chain_must_not_be_empty(raw):
    assert error_of(normalize_model_chain, raw) == "모델이 하나 이상 필요"


def test_base_url_with_malformed_host_is_rejected():
    assert error_of(normalize_base_url, "http://[::1/") == SCHEME_MESSAGE


def test_webhook_url_with_malformed_host_is_rejected():
    assert (
        error_of(normalize_webhook_url, "https://[discord.com/api/webhooks/1/a") == WEBHOOK_MESSAGE
    )


# ---------- 숫자, 비율, 웹훅 이름 ----------


@pytest.mark.parametrize(("raw", "expected"), [("1", 1), (" 700 ", 700), ("15", 15)])
def test_parse_positive_int(raw, expected):
    assert parse_positive_int(raw) == expected


@pytest.mark.parametrize(("raw", "message"), [("0", "1 이상이어야 함"), ("-3", "1 이상이어야 함")])
def test_parse_positive_int_rejects_small_values(raw, message):
    assert error_of(parse_positive_int, raw) == message


def test_parse_positive_int_with_maximum():
    assert parse_positive_int("500", maximum=500) == 500
    assert error_of(lambda raw: parse_positive_int(raw, maximum=500), "501") == "1~500 사이"


@pytest.mark.parametrize("raw", ["", "abc", "1.5"])
def test_parse_positive_int_rejects_non_integers(raw):
    assert error_of(parse_positive_int, raw) == "숫자만 입력할 수 있음"


@pytest.mark.parametrize(("raw", "expected"), [("1", 1), ("80", 80), ("100", 100)])
def test_parse_percent(raw, expected):
    assert parse_percent(raw) == expected


@pytest.mark.parametrize("raw", ["0", "101"])
def test_parse_percent_rejects_out_of_range(raw):
    assert error_of(parse_percent, raw) == "1~100 사이"


def test_webhook_name_is_trimmed():
    assert validate_webhook_name("  dev  ") == "dev"


@pytest.mark.parametrize(
    ("raw", "message"),
    [("", "이름이 필요함"), ("   ", "이름이 필요함"), ("가" * 41, "이름은 40자까지")],
)
def test_webhook_name_errors(raw, message):
    assert error_of(validate_webhook_name, raw) == message
