import argparse
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from tests.tools.fake_apis import (
    GOOD_JSON,
    LEGACY_TEXT,
    FakeServer,
    json_reply,
    make_discord,
    make_openrouter,
)

SPIKE_PATH = Path(__file__).resolve().parents[2] / "tools" / "spike.py"
spec = importlib.util.spec_from_file_location("spike", SPIKE_PATH)
spike = importlib.util.module_from_spec(spec)
sys.modules["spike"] = spike
spec.loader.exec_module(spike)

KEY = "sk-or-v1-THIS-IS-A-SECRET-KEY"


def openrouter_args(base_url, **overrides):
    values = {
        "base_url": base_url,
        "models": "",
        "max_models": 4,
        "variants": "A,B,C,D",
        "delay": 0.0,
        "timeout": 10.0,
        "preflight_timeout": 10.0,
        "max_preflight": 6,
        "yes": True,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def discord_args(**overrides):
    values = {"delay": 0.0, "burst": 8, "skip_host_check": True}
    values.update(overrides)
    return argparse.Namespace(**values)


@pytest.fixture
def openrouter():
    server = FakeServer(make_openrouter())
    server.start()
    yield server
    server.stop()


@pytest.fixture
def discord():
    handler = make_discord()
    server = FakeServer(handler)
    server.start()
    server.handler = handler
    yield server
    server.stop()


# ---------- 응답 검증 규칙 ----------


@pytest.mark.parametrize(
    ("raw", "finish", "expected"),
    [
        (GOOD_JSON, "stop", "ok"),
        ("```json\n" + GOOD_JSON + "\n```", "stop", "ok"),
        (GOOD_JSON, "length", "잘림(length)"),
        ("그냥 문장", "stop", "JSON 아님"),
        (json.dumps({"title_ko": "제목"}), "stop", "필드 누락"),
        (json.dumps({"title_ko": "", "summary_ko": "요약"}), "stop", "빈 제목/요약"),
        (
            json.dumps({"title_ko": "제목", "summary_ko": "漢字 요약"}, ensure_ascii=False),
            "stop",
            "한자 혼입",
        ),
        (
            json.dumps({"title_ko": "제목", "summary_ko": "We need to translate"}),
            "stop",
            "추론 과정 누출",
        ),
    ],
)
def test_json_validation(raw, finish, expected):
    assert spike.validate_json_summary(raw, finish) == expected


@pytest.mark.parametrize(
    ("raw", "finish", "expected"),
    [
        (LEGACY_TEXT, "stop", "ok"),
        (LEGACY_TEXT, "length", "잘림(length)"),
        ("요약만 있음", "stop", "형식 어긋남"),
        ("TITLE: 제목\nSUMMARY: 漢字", "stop", "한자 혼입"),
    ],
)
def test_legacy_validation(raw, finish, expected):
    assert spike.validate_legacy_summary(raw, finish) == expected


# ---------- 계획과 요청 ----------


def test_only_free_text_models_are_listed_newest_first(openrouter):
    free, error = spike.free_text_models(openrouter.url(), KEY)
    assert error == ""
    assert [m["id"] for m in free] == [
        "vendor/json-model:free",
        "nvidia/nemotron-3-ultra-550b-a55b:free",
        "nvidia/nemotron-3-super-120b-a12b:free",
    ]


def test_plan_prefers_current_models_then_json_capable_ones(openrouter):
    free, _ = spike.free_text_models(openrouter.url(), KEY)
    assert spike.plan_models(free, [], 3) == [
        "nvidia/nemotron-3-ultra-550b-a55b:free",
        "nvidia/nemotron-3-super-120b-a12b:free",
        "vendor/json-model:free",
    ]
    assert spike.plan_models(free, ["a/b:free", "c/d:free"], 1) == ["a/b:free"]


@pytest.mark.parametrize(
    ("variant", "has_reasoning", "has_format", "max_tokens"),
    [
        ("A", False, False, 350),
        ("B", False, False, 700),
        ("C", True, False, 700),
        ("D", True, True, 700),
    ],
)
def test_each_variant_changes_only_what_it_should(variant, has_reasoning, has_format, max_tokens):
    payload = spike.build_payload("m", variant, spike.ARTICLES[0])
    assert ("reasoning" in payload) is has_reasoning
    assert ("response_format" in payload) is has_format
    assert payload["max_tokens"] == max_tokens
    if has_reasoning:
        assert payload["reasoning"] == {"effort": "none"}
    if has_format:
        assert payload["provider"] == {"require_parameters": True}
    prompt = payload["messages"][0]["content"]
    assert spike.ARTICLES[0]["title"] in prompt and "<<" not in prompt


def test_discord_url_check():
    ok = "https://discord.com/api/webhooks/123/abcDEF"
    assert spike.check_discord_url(ok) == ""
    assert spike.check_discord_url("http://discord.com/api/webhooks/123/abc") != ""
    assert spike.check_discord_url("https://evil.example.com/api/webhooks/123/abc") != ""
    assert spike.check_discord_url("https://discord.com/api/other/123/abc") != ""
    assert spike.check_discord_url("https://evil.example.com/x", skip_host_check=True) == ""


# ---------- S1 전체 흐름 ----------


def test_openrouter_report_reveals_the_reasoning_problem_and_hides_secrets(openrouter):
    report = spike.run_openrouter(openrouter_args(openrouter.url()), KEY)

    # 비밀 값
    assert KEY not in report
    assert "LABELSECRET" not in report  # 키 정보의 label은 보고서에 넣지 않는다

    # 키와 모델 목록
    assert "is_free_tier: False" in report
    assert "무료 모델 3개" in report
    assert "vendor/json-model:free" in report and "만료 2026-12-01" in report
    assert "vendor/paid-model" not in report and "image-model" not in report

    # 호출: 추론을 끄지 않으면 잘리고(A, B), 끄면 통과(C), JSON 강제는 거부(D)
    ultra = "nvidia/nemotron-3-ultra-550b-a55b:free"
    assert f"{ultra} A [영문 기술 글] HTTP 200" in report and "잘림(length)" in report
    assert f"{ultra} C [영문 기술 글] HTTP 200" in report
    assert f"{ultra} D [영문 기술 글] HTTP 404" in report
    assert "→ 요청 실패" in report
    assert "response_format" in report
    assert "추론 필드 있음" in report

    # 요약과 자동 관찰
    assert "통과율이 가장 높은 방식은 C" in report
    assert "D 요청은 모두 거부됨" in report
    assert "응답이 잘린 횟수" in report
    assert "429를 받아 한 번 기다린 뒤 다시 시도함" in report
    assert "x-ratelimit-remaining" in report
    # 잘 답하는 모델은 모든 방식을 통과
    assert "vendor/json-model:free B [영문 기술 글] HTTP 200" in report


def test_openrouter_calls_never_send_the_key_anywhere_but_the_auth_header(openrouter):
    spike.run_openrouter(
        openrouter_args(openrouter.url(), models="vendor/json-model:free", variants="B"), KEY
    )
    for _method, path, headers, body in openrouter.requests:
        assert headers["authorization"] == f"Bearer {KEY}"
        assert KEY not in path and KEY not in json.dumps(body or {})


def test_openrouter_run_respects_the_planned_call_count(openrouter):
    spike.run_openrouter(
        openrouter_args(openrouter.url(), models="vendor/json-model:free", variants="B,C"), KEY
    )
    chats = [r for r in openrouter.requests if r[1] == "/chat/completions"]
    assert len(chats) == 1 + 1 * 2 * len(spike.ARTICLES)  # 사전 확인 1번 + 계획한 호출


def test_openrouter_cancel_makes_only_the_preflight_calls(openrouter):
    args = openrouter_args(openrouter.url(), yes=False)
    report = spike.run_openrouter(args, KEY, input_fn=lambda _prompt: "n")
    assert report == ""
    chats = [r for r in openrouter.requests if r[1] == "/chat/completions"]
    assert len(chats) == 3  # 무료 모델 3개에 사전 확인만 보냈다


def test_openrouter_unreachable_server_still_produces_a_report():
    args = openrouter_args("http://127.0.0.1:1", models="a/b:free", variants="B", timeout=1.0)
    report = spike.run_openrouter(args, KEY)
    assert "제외" in report and "인터넷 연결" in report
    assert KEY not in report


# ---------- S2 전체 흐름 ----------


def webhook_url(server):
    return server.url("/api/webhooks/123/TOKENXYZ")


def test_discord_report_covers_limits_and_cleans_up(discord):
    url = webhook_url(discord)
    report = spike.run_discord(discord_args(), url)

    assert "TOKENXYZ" not in report and url not in report
    assert (
        "메시지 보내기(?wait=true): HTTP 200" in report
        and "응답 항목: channel_id, content, id" in report
    )
    assert "메시지 보내기(?wait 없음): HTTP 204" in report
    assert "1900자 메시지: HTTP 200" in report
    assert "2000자 메시지: HTTP 200" in report
    assert "2001자 메시지: HTTP 400" in report and "code=50035" in report
    assert "429 응답 내용: HTTP 429" in report and "retry_after=0.01" in report
    assert "X-RateLimit" in report or "x-ratelimit" in report.lower()
    # 보낸 메시지를 모두 지웠다
    assert discord.handler.state["messages"] == set()
    assert "개 삭제됨" in report


def test_discord_report_mentions_manual_checks(discord):
    report = spike.run_discord(discord_args(burst=1), webhook_url(discord))
    assert "직접 확인할 것" in report


def test_discord_rejects_non_discord_addresses_without_sending():
    args = discord_args(skip_host_check=False)
    assert spike.run_discord(args, "https://evil.example.com/api/webhooks/1/a") == ""


def test_deleted_webhook_response_is_reported_without_the_address(discord):
    discord.handler.state["deleted_webhook"] = True
    url = webhook_url(discord)
    report = spike.run_discord_deleted(discord_args(), url)
    assert "삭제된 웹훅으로 보내기: HTTP 404" in report
    assert "code=10015" in report and "Unknown Webhook" in report
    assert "TOKENXYZ" not in report and url not in report


def test_secret_masking_replaces_every_occurrence():
    assert spike.mask_secrets("a SECRET b SECRET", ["SECRET"]) == f"a {spike.MASK} b {spike.MASK}"
    assert spike.mask_secrets("none", [""]) == "none"


def test_retry_after_is_read_from_header_or_body():
    header = spike.Response(429, {"retry-after": "2.5"}, b"", 0.0)
    body = spike.Response(429, {}, json.dumps({"retry_after": 1.25}).encode(), 0.0)
    nothing = spike.Response(429, {}, b"", 0.0)
    assert spike.retry_after_seconds(header) == 2.5
    assert spike.retry_after_seconds(body) == 1.25
    assert spike.retry_after_seconds(nothing, fallback=7) == 7


# ---------- 명령줄 실행 경로 ----------


def test_main_runs_openrouter_end_to_end_and_saves_a_clean_report(
    openrouter, monkeypatch, tmp_path, capsys
):
    monkeypatch.setattr(spike.getpass, "getpass", lambda _prompt: KEY)
    out = tmp_path / "report.txt"
    code = spike.main(
        [
            "openrouter",
            "--base-url",
            openrouter.url(),
            "--models",
            "vendor/json-model:free",
            "--variants",
            "B",
            "--delay",
            "0",
            "--yes",
            "--out",
            str(out),
        ]
    )
    assert code == 0
    saved = out.read_text(encoding="utf-8")
    printed = capsys.readouterr().out
    assert "S1 OpenRouter 시험 보고서" in saved
    assert KEY not in saved and KEY not in printed
    assert "보고서를 저장했습니다" in printed


def test_main_rejects_an_empty_key(monkeypatch, capsys):
    monkeypatch.setattr(spike.getpass, "getpass", lambda _prompt: "   ")
    assert spike.main(["openrouter"]) == 1
    assert "키가 비어 있습니다" in capsys.readouterr().out


def test_main_runs_discord_end_to_end(discord, monkeypatch, tmp_path, capsys):
    url = webhook_url(discord)
    monkeypatch.setattr(spike.getpass, "getpass", lambda _prompt: url)
    out = tmp_path / "discord.txt"
    code = spike.main(["discord", "--skip-host-check", "--delay", "0", "--out", str(out)])
    assert code == 0
    saved = out.read_text(encoding="utf-8")
    assert "S2 Discord 웹훅 시험 보고서" in saved
    assert "TOKENXYZ" not in saved and "TOKENXYZ" not in capsys.readouterr().out


def test_main_returns_an_error_code_when_the_webhook_address_is_not_discord(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setattr(
        spike.getpass, "getpass", lambda _prompt: "https://evil.example.com/api/webhooks/1/a"
    )
    assert spike.main(["discord", "--out", str(tmp_path / "x.txt")]) == 1
    assert not (tmp_path / "x.txt").exists()
    assert "웹훅 주소 확인 실패" in capsys.readouterr().out


def test_default_variants_and_models_match_the_guide():
    args = spike.parse_args(["openrouter"])
    assert (args.variants, args.max_models, args.delay) == ("A,B,C,D", 4, 4.0)
    assert (args.preflight_timeout, args.max_preflight) == (30.0, 6)
    guide = (SPIKE_PATH.parent / "SPIKE.md").read_text(encoding="utf-8")
    assert "--max-models 2" in guide and "--variants A,C,D" in guide


# ---------- 실패를 빨리 알려 주는 동작 ----------


def server_with(mode):
    server = FakeServer(make_openrouter(mode=mode))
    server.start()
    return server


def chat_calls(server):
    return [r for r in server.requests if r[1] == "/chat/completions"]


@pytest.mark.parametrize(("mode", "status"), [("unauthorized", 401), ("payment", 402)])
def test_preflight_stops_the_run_when_the_key_or_balance_is_the_problem(mode, status, capsys):
    server = server_with(mode)
    try:
        report = spike.run_openrouter(openrouter_args(server.url()), KEY)
    finally:
        server.stop()
    assert len(chat_calls(server)) == 1  # 첫 모델에서 바로 멈춘다
    out = capsys.readouterr().out
    assert f"HTTP {status}" in out and "멈춥니다" in out
    assert f"HTTP {status}" in report and "원인 추정" in report
    assert KEY not in report and KEY not in out


def test_when_no_model_answers_the_run_explains_why_and_makes_no_trial_calls(capsys):
    server = server_with("policy")
    try:
        report = spike.run_openrouter(openrouter_args(server.url()), KEY)
    finally:
        server.stop()
    assert len(chat_calls(server)) == 3  # 후보 3개에 사전 확인만
    out = capsys.readouterr().out
    assert "openrouter.ai/settings/privacy" in out and "응답하는 모델이 없어서" in out
    assert (
        "원인 추정: 개인정보" in report and "## 호출별 결과" not in report.split("## 호출 시험")[0]
    )


def test_a_slow_model_is_excluded_and_the_others_are_still_tested(capsys):
    server = server_with("slow_ultra")
    try:
        args = openrouter_args(server.url(), max_models=2, preflight_timeout=0.3, variants="C")
        report = spike.run_openrouter(args, KEY)
    finally:
        server.stop()
    ultra = "nvidia/nemotron-3-ultra-550b-a55b:free"
    out = capsys.readouterr().out
    assert f"{ultra} … 제외" in out and "너무 느려서" in out
    assert f"- {ultra}: HTTP 0" in report and "→ 제외" in report
    assert "응답함" in report
    # 본 시험은 응답한 모델(다음 두 개)만 사용
    tested = {r[3]["model"] for r in chat_calls(server)[3:]}
    assert ultra not in tested and len(tested) == 2


def test_repeated_failures_skip_the_rest_of_a_model(capsys):
    server = server_with("flaky")
    try:
        args = openrouter_args(server.url(), models="a/one:free,a/two:free", max_models=2)
        report = spike.run_openrouter(args, KEY)
    finally:
        server.stop()
    # 사전 확인 2번(성공) + 모델마다 3번까지만 시도
    assert len(chat_calls(server)) == 2 + 3 + 3
    assert "건너뜁니다" in capsys.readouterr().out
    assert "같은 이유(HTTP 404)로 3번 연속 실패" in report
    assert "원인 추정: 개인정보" in report


def test_progress_lines_show_the_failure_reason_immediately(capsys):
    server = server_with("flaky")
    try:
        spike.run_openrouter(openrouter_args(server.url(), models="a/one:free", variants="B"), KEY)
    finally:
        server.stop()
    out = capsys.readouterr().out
    line = next(line for line in out.splitlines() if line.startswith("    [1/"))
    assert "요청 실패" in line and "HTTP 404" in line and "data policy" in line


def test_a_failure_streak_is_reset_by_a_success(openrouter):
    # 추론을 끄지 않은 호출은 잘리지만 HTTP 200이라 "실패 연속"으로 세지 않는다
    args = openrouter_args(
        openrouter.url(), models="nvidia/nemotron-3-ultra-550b-a55b:free", variants="A,B"
    )
    report = spike.run_openrouter(args, KEY)
    assert "건너뛰었습니다" not in report
    assert len(chat_calls(openrouter)) == 1 + 4


def test_preflight_retries_once_after_a_rate_limit_answer():
    answers = iter([429, 200])

    def handler(method, path, headers, body):
        if next(answers) == 429:
            return json_reply(
                429, {"error": {"code": 429, "message": "slow down"}}, {"Retry-After": "0"}
            )
        return json_reply(
            200, {"choices": [{"finish_reason": "stop", "message": {"content": "ok"}}]}
        )

    server = FakeServer(handler)
    server.start()
    try:
        result = spike.preflight(server.url(), KEY, "a/b:free", 5.0)
    finally:
        server.stop()
    assert (result.status, result.retried_429, result.verdict) == (200, True, "ok")


def test_preflight_gives_up_after_a_second_rate_limit_answer():
    def handler(method, path, headers, body):
        return json_reply(
            429, {"error": {"code": 429, "message": "slow down"}}, {"Retry-After": "0"}
        )

    server = FakeServer(handler)
    server.start()
    try:
        result = spike.preflight(server.url(), KEY, "a/b:free", 5.0)
    finally:
        server.stop()
    assert (result.status, result.retried_429) == (429, True)


def test_ctrl_c_creates_a_partial_report(openrouter, monkeypatch, capsys):
    real = spike.call_model
    calls = {"n": 0}

    def interrupted(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 3:
            raise KeyboardInterrupt
        return real(*args, **kwargs)

    monkeypatch.setattr(spike, "call_model", interrupted)
    args = openrouter_args(openrouter.url(), models="vendor/json-model:free", variants="B,C")
    report = spike.run_openrouter(args, KEY)
    assert "시험을 중간에 멈췄습니다" in report
    assert report.count("] HTTP 200") == 2  # 중단 전까지 끝난 2개 호출은 보고서에 있다
    assert "중단했습니다" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("status", "error", "expected"),
    [
        (0, "URLError: timed out", "너무 느려서"),
        (0, "TimeoutError: The read operation timed out", "너무 느려서"),
        (0, "URLError: getaddrinfo failed", "인터넷 연결"),
        (401, "", "키가 올바르지"),
        (402, "", "잔액"),
        (404, "No endpoints found matching your data policy", "개인정보"),
        (404, "No endpoints found that support response_format", "지원하는 제공자가 없습니다"),
        (429, "", "한도"),
        (503, "", "서버 오류"),
        (418, "", ""),
    ],
)
def test_failure_hints(status, error, expected):
    hint = spike.hint_for(status, error)
    assert expected in hint if expected else hint == ""


def test_default_timeout_is_a_minute():
    assert spike.parse_args(["openrouter"]).timeout == 60.0


# ---------- 키 정보 명령과 모델 필터 ----------


def test_key_command_shows_the_daily_free_request_value_but_no_identifiers(openrouter):
    args = argparse.Namespace(base_url=openrouter.url())
    report = spike.run_key(args, KEY)
    assert "free_model_daily_requests: 1000" in report
    assert "is_free_tier: False" in report
    assert KEY not in report and "LABELSECRET" not in report
    assert "PRIVATE-IDENTIFIER" not in report  # 계정, 작업공간 번호의 값은 넣지 않는다
    assert "workspace_id" in report  # 항목 이름만 남긴다
    assert [r[1] for r in openrouter.requests] == ["/key"]  # 채팅 호출이 없다


def test_main_key_command_saves_a_report(openrouter, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(spike.getpass, "getpass", lambda _prompt: KEY)
    out = tmp_path / "key.txt"
    assert spike.main(["key", "--base-url", openrouter.url(), "--out", str(out)]) == 0
    assert "free_model_daily_requests: 1000" in out.read_text(encoding="utf-8")
    assert KEY not in capsys.readouterr().out


def test_models_that_cannot_summarize_are_not_listed():
    free = {"prompt": "0", "completion": "0"}
    data = {
        "data": [
            {
                "id": "a/good:free",
                "created": 3,
                "pricing": free,
                "architecture": {"output_modalities": ["text"]},
            },
            {
                "id": "google/lyria-3-pro-preview",
                "created": 5,
                "pricing": free,
                "architecture": {"output_modalities": ["text", "audio"]},
            },
            {
                "id": "nvidia/nemotron-3.5-content-safety:free",
                "created": 4,
                "pricing": free,
                "architecture": {"output_modalities": ["text"]},
            },
            {
                "id": "a/paid",
                "created": 6,
                "pricing": {"prompt": "0.1", "completion": "0.1"},
                "architecture": {"output_modalities": ["text"]},
            },
        ]
    }
    server = FakeServer(lambda *_unused: json_reply(200, data))
    server.start()
    try:
        models, error = spike.free_text_models(server.url(), KEY)
    finally:
        server.stop()
    assert error == "" and [m["id"] for m in models] == ["a/good:free"]
