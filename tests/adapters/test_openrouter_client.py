import json

import pytest

from rss_hub.adapters.openrouter_client import OpenRouterClient, build_payload
from rss_hub.services.ports import CallOptions, LlmCallError, LlmErrorKind, ServerUsage
from tests.tools.fake_apis import FakeServer, json_reply

KEY = "sk-or-v1-THIS-IS-A-SECRET-KEY"
OPTIONS = CallOptions(max_tokens=500, reasoning_off=True, json_object=False)
GOOD = {
    "choices": [{"finish_reason": "stop", "message": {"content": '{"title_ko": "t"}'}}],
    "usage": {
        "prompt_tokens": 250,
        "completion_tokens": 100,
        "completion_tokens_details": {"reasoning_tokens": 0},
    },
}


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def start(handler):
    server = FakeServer(handler)
    server.start()
    return server


@pytest.fixture
def make_client():
    servers = []

    def make(handler, key=KEY, **kwargs):
        server = start(handler)
        servers.append(server)
        client = OpenRouterClient(lambda: key, base_url=server.url(), timeout=(1.0, 1.0), **kwargs)
        return client, server

    yield make
    for server in servers:
        server.stop()


# ---------- 요청 모양 ----------


def test_payload_with_everything_off_is_a_plain_chat_request():
    payload = build_payload(
        "a/b:free", "안녕", CallOptions(500, reasoning_off=False, json_object=False)
    )
    assert payload == {
        "model": "a/b:free",
        "messages": [{"role": "user", "content": "안녕"}],
        "max_tokens": 500,
    }


def test_reasoning_is_switched_off_with_effort_none():
    payload = build_payload("m", "p", CallOptions(500, reasoning_off=True, json_object=False))
    assert payload["reasoning"] == {"effort": "none"}
    assert "response_format" not in payload and "provider" not in payload


def test_json_mode_requires_providers_that_support_it():
    payload = build_payload("m", "p", CallOptions(500, reasoning_off=True, json_object=True))
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["provider"] == {"require_parameters": True}


def test_the_request_carries_the_key_only_in_the_authorization_header(make_client):
    client, server = make_client(lambda *_: json_reply(200, GOOD))
    client.complete("a/b:free", "프롬프트", OPTIONS)
    method, path, headers, body = server.requests[0]
    assert (method, path) == ("POST", "/chat/completions")
    assert headers["authorization"] == f"Bearer {KEY}"
    assert KEY not in json.dumps(body) and KEY not in path
    assert body["max_tokens"] == 500 and body["reasoning"] == {"effort": "none"}


# ---------- 응답 해석 ----------


def test_a_good_answer_is_parsed_with_tokens(make_client):
    client, _ = make_client(lambda *_: json_reply(200, GOOD))
    result = client.complete("m", "p", OPTIONS)
    assert result.content == '{"title_ko": "t"}'
    assert result.finish_reason == "stop"
    assert (result.prompt_tokens, result.completion_tokens, result.reasoning_tokens) == (
        250,
        100,
        0,
    )


def test_missing_content_becomes_an_empty_string(make_client):
    body = {"choices": [{"finish_reason": "length", "message": {"content": None}}]}
    client, _ = make_client(lambda *_: json_reply(200, body))
    result = client.complete("m", "p", OPTIONS)
    assert (result.content, result.finish_reason, result.prompt_tokens) == ("", "length", None)


def test_an_answer_without_choices_is_a_provider_failure(make_client):
    client, _ = make_client(lambda *_: json_reply(200, {"id": "x"}))
    with pytest.raises(LlmCallError) as error:
        client.complete("m", "p", OPTIONS)
    assert error.value.kind is LlmErrorKind.UNAVAILABLE


# ---------- 오류 분류 ----------


def fail_with(make_client, status, message="", headers=None, body=None):
    payload = body if body is not None else {"error": {"code": status, "message": message}}
    client, _ = make_client(lambda *_: json_reply(status, payload, headers))
    with pytest.raises(LlmCallError) as error:
        client.complete("m", "p", OPTIONS)
    return error.value


@pytest.mark.parametrize(
    ("status", "message", "kind"),
    [
        (429, "rate limited", LlmErrorKind.RATE_LIMITED),
        (500, "", LlmErrorKind.UNAVAILABLE),
        (502, "", LlmErrorKind.UNAVAILABLE),
        (503, "", LlmErrorKind.UNAVAILABLE),
        (504, "", LlmErrorKind.UNAVAILABLE),
        (408, "", LlmErrorKind.UNAVAILABLE),
        (402, "Insufficient credits", LlmErrorKind.PAYMENT_REQUIRED),
        (401, "No auth credentials", LlmErrorKind.UNAUTHORIZED),
        (403, "forbidden", LlmErrorKind.UNAUTHORIZED),
        (404, "No endpoints found matching your data policy", LlmErrorKind.POLICY),
        (
            404,
            "No endpoints found that support response_format",
            LlmErrorKind.UNSUPPORTED_PARAMETER,
        ),
        (404, "No endpoints found for model", LlmErrorKind.UNAVAILABLE),
        (400, "response_format is not supported", LlmErrorKind.UNSUPPORTED_PARAMETER),
        (400, "bad request", LlmErrorKind.OTHER),
        (418, "", LlmErrorKind.OTHER),
    ],
)
def test_http_errors_are_classified(make_client, status, message, kind):
    error = fail_with(make_client, status, message)
    assert error.kind is kind and error.status == status


def test_retry_after_is_read_from_the_header(make_client):
    error = fail_with(make_client, 429, headers={"Retry-After": "2.5"})
    assert error.retry_after == 2.5


def test_retry_after_is_unknown_when_the_server_does_not_say(make_client):
    assert fail_with(make_client, 429).retry_after is None


def test_an_error_inside_a_200_response_is_classified_by_its_code(make_client):
    client, _ = make_client(lambda *_: json_reply(200, {"error": {"code": 429, "message": "slow"}}))
    with pytest.raises(LlmCallError) as error:
        client.complete("m", "p", OPTIONS)
    assert error.value.kind is LlmErrorKind.RATE_LIMITED


def test_an_error_body_that_is_not_json_still_gives_a_kind(make_client):
    def handler(*_):
        return 502, {"Content-Type": "text/html"}, b"<html>Bad Gateway</html>"

    client, _ = make_client(handler)
    with pytest.raises(LlmCallError) as error:
        client.complete("m", "p", OPTIONS)
    assert error.value.kind is LlmErrorKind.UNAVAILABLE


def test_error_messages_are_short_and_never_contain_the_key(make_client):
    long_message = f"upstream echoed {KEY} " + "x" * 1000
    error = fail_with(make_client, 500, long_message)
    assert KEY not in str(error) and KEY not in error.message
    assert len(error.message) <= 200


def test_a_slow_server_is_an_unavailable_error(make_client):
    import time

    def handler(*_):
        time.sleep(1.5)
        return json_reply(200, GOOD)

    client, _ = make_client(handler)
    with pytest.raises(LlmCallError) as error:
        client.complete("m", "p", OPTIONS)
    assert error.value.kind is LlmErrorKind.UNAVAILABLE and error.value.status == 0


def test_a_refused_connection_is_an_unavailable_error():
    client = OpenRouterClient(lambda: KEY, base_url="http://127.0.0.1:1", timeout=(1.0, 1.0))
    with pytest.raises(LlmCallError) as error:
        client.complete("m", "p", OPTIONS)
    assert error.value.kind is LlmErrorKind.UNAVAILABLE


def test_a_missing_key_fails_without_sending_anything(make_client):
    client, server = make_client(lambda *_: json_reply(200, GOOD), key=None)
    with pytest.raises(LlmCallError) as error:
        client.complete("m", "p", OPTIONS)
    assert error.value.kind is LlmErrorKind.UNAUTHORIZED
    assert server.requests == []


# ---------- 모델이 지원하는 옵션 ----------

MODELS = {
    "data": [
        {"id": "a/json:free", "supported_parameters": ["reasoning", "response_format"]},
        {"id": "a/plain:free", "supported_parameters": ["temperature"]},
    ]
}


def test_supported_parameters_are_read_from_the_model_list_and_cached(make_client):
    clock = Clock()
    client, server = make_client(lambda *_: json_reply(200, MODELS), clock=clock)
    assert client.model_parameters("a/json:free") == frozenset({"reasoning", "response_format"})
    assert client.model_parameters("a/plain:free") == frozenset({"temperature"})
    assert client.model_parameters("unknown/model") is None
    assert [r[1] for r in server.requests] == ["/models"]  # 한 번만 가져왔다


def test_the_model_list_is_refreshed_after_an_hour(make_client):
    clock = Clock()
    client, server = make_client(lambda *_: json_reply(200, MODELS), clock=clock)
    client.model_parameters("a/json:free")
    clock.now += 3601
    client.model_parameters("a/json:free")
    assert len(server.requests) == 2


def test_a_failed_model_list_is_not_retried_for_a_minute(make_client):
    clock = Clock()
    client, server = make_client(lambda *_: json_reply(500, {}), clock=clock)
    assert client.model_parameters("a/json:free") is None
    assert client.model_parameters("a/json:free") is None
    assert len(server.requests) == 1
    clock.now += 61
    client.model_parameters("a/json:free")
    assert len(server.requests) == 2


# ---------- 서버가 알려 주는 오늘 호출 수 ----------


def test_server_usage_reads_the_daily_free_request_counter(make_client):
    body = {"data": {"free_model_daily_requests": {"used": 33, "limit": 1000, "remaining": 967}}}
    client, server = make_client(lambda *_: json_reply(200, body))
    usage = client.server_usage()
    assert usage == ServerUsage(used=33, limit=1000)
    assert usage.remaining == 967
    assert [r[1] for r in server.requests] == ["/key"]


@pytest.mark.parametrize(
    "body",
    [
        {"data": {}},
        {"data": {"free_model_daily_requests": None}},
        {"data": {"free_model_daily_requests": {"used": "many", "limit": 1000}}},
        {"data": {"free_model_daily_requests": {"limit": 1000}}},
        {"unexpected": True},
    ],
)
def test_unusable_server_usage_is_none(make_client, body):
    client, _ = make_client(lambda *_: json_reply(200, body))
    assert client.server_usage() is None


def test_server_usage_is_none_when_the_lookup_fails(make_client):
    client, _ = make_client(lambda *_: json_reply(500, {}))
    assert client.server_usage() is None


def test_server_usage_is_none_without_a_key_and_sends_nothing(make_client):
    client, server = make_client(lambda *_: json_reply(200, {}), key=None)
    assert client.server_usage() is None
    assert server.requests == []


def test_a_retry_after_given_as_a_date_is_treated_as_unknown(make_client):
    error = fail_with(make_client, 429, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"})
    assert error.retry_after is None


def test_model_parameters_are_unknown_without_a_key_and_nothing_is_sent(make_client):
    client, server = make_client(lambda *_: json_reply(200, MODELS), key=None)
    assert client.model_parameters("a/json:free") is None
    assert server.requests == []


def test_model_parameters_are_unknown_when_the_server_is_unreachable():
    client = OpenRouterClient(lambda: KEY, base_url="http://127.0.0.1:1", timeout=(1.0, 1.0))
    assert client.model_parameters("a/json:free") is None


def test_server_usage_is_none_when_the_server_is_unreachable():
    client = OpenRouterClient(lambda: KEY, base_url="http://127.0.0.1:1", timeout=(1.0, 1.0))
    assert client.server_usage() is None


# ---------- 키 확인(채팅 호출 없이 키 정보만 조회) ----------


def test_a_valid_key_reports_validity_and_the_free_model_counter(make_client):
    body = {"data": {"free_model_daily_requests": {"used": 33, "limit": 1000}}}
    client, server = make_client(lambda *_: json_reply(200, body))
    check = client.check_key()
    assert (check.valid, check.used, check.limit, check.reason) == (True, 33, 1000, "")
    assert [(r[0], r[1]) for r in server.requests] == [("GET", "/key")]  # 채팅 호출은 없다
    assert server.requests[0][2].get("authorization") == f"Bearer {KEY}"


@pytest.mark.parametrize(
    "body", [{}, {"data": {}}, {"data": {"free_model_daily_requests": {"used": "x"}}}]
)
def test_a_valid_key_without_a_usable_counter_is_still_valid(make_client, body):
    client, _ = make_client(lambda *_: json_reply(200, body))
    check = client.check_key()
    assert (check.valid, check.used, check.limit) == (True, None, None)


@pytest.mark.parametrize("status", [401, 403])
def test_a_rejected_key_is_reported_as_invalid_without_showing_the_key(make_client, status):
    client, _ = make_client(lambda *_: json_reply(status, {"error": {"message": f"bad key {KEY}"}}))
    check = client.check_key()
    assert check.valid is False and f"HTTP {status}" in check.reason
    assert KEY not in check.reason


@pytest.mark.parametrize("status", [429, 500, 503])
def test_other_failures_mean_the_key_could_not_be_checked(make_client, status):
    client, _ = make_client(lambda *_: json_reply(status, {}))
    check = client.check_key()
    assert check.valid is None and f"HTTP {status}" in check.reason


def test_a_connection_failure_means_the_key_could_not_be_checked():
    client = OpenRouterClient(lambda: KEY, base_url="http://127.0.0.1:1", timeout=(0.5, 0.5))
    check = client.check_key()
    assert check.valid is None and "ConnectionError" in check.reason and KEY not in check.reason


def test_a_missing_key_is_invalid_and_nothing_is_sent(make_client):
    client, server = make_client(lambda *_: json_reply(200, {}), key=None)
    check = client.check_key()
    assert check.valid is False and "설정되지 않았습니다" in check.reason
    assert server.requests == []
