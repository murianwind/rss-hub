from datetime import UTC, date, datetime

import pytest

from rss_hub.domain.budget import BudgetBlock
from rss_hub.services.llm_gateway import BudgetBlocked, LlmNotConfigured, LlmOutage
from rss_hub.services.ports import LlmErrorKind, ServerUsage
from tests.fakes.llm_client import failure, good
from tests.fakes.llm_env import LlmEnv

TODAY = date(2026, 10, 16)


@pytest.fixture
def env(tmp_path):
    return LlmEnv(tmp_path)


def ask(env):
    return env.gateway.complete("프롬프트")


# ---------- 기본 동작 ----------


def test_a_good_answer_comes_back_with_the_model_and_is_recorded_with_tokens(env):
    answer = ask(env)
    assert (answer.model, answer.finish_reason) == ("model-a", "stop")
    assert env.usage.breakdown(TODAY) == {"model-a": {"success": 1}}


def test_without_a_key_nothing_is_called(tmp_path):
    env = LlmEnv(tmp_path, configured=False)
    with pytest.raises(LlmNotConfigured):
        ask(env)
    assert env.client.calls == [] and env.usage.count_day(TODAY) == 0


def test_the_chain_is_read_from_settings_on_every_call(env):
    env.settings.update({"model_chain": "model-c"})
    ask(env)
    env.settings.update({"model_chain": "model-d,model-e"})
    ask(env)
    assert env.client.models_called() == ["model-c", "model-d"]


# ---------- 요청 옵션 ----------


@pytest.mark.parametrize(
    ("params", "reasoning_off", "json_object"),
    [
        (None, True, False),  # 알 수 없으면 추론은 끄고(무해), JSON 강제는 쓰지 않는다
        (frozenset({"reasoning", "response_format"}), True, True),
        (frozenset({"reasoning", "structured_outputs"}), True, True),
        (frozenset({"temperature"}), False, False),
        (frozenset({"response_format"}), False, True),
    ],
)
def test_options_follow_what_the_model_supports(env, params, reasoning_off, json_object):
    env.client.parameters["model-a"] = params
    ask(env)
    options = env.client.calls[0].options
    assert (options.reasoning_off, options.json_object) == (reasoning_off, json_object)
    assert options.max_tokens == 500


def test_a_model_that_rejects_json_mode_is_retried_without_it_and_remembered(env):
    env.client.parameters["model-a"] = frozenset({"reasoning", "response_format"})
    env.client.will("model-a", failure(LlmErrorKind.UNSUPPORTED_PARAMETER, 404))
    answer = ask(env)
    assert answer.model == "model-a"
    assert [c.options.json_object for c in env.client.calls] == [True, False]
    assert env.sleeps == []  # 기다리지 않는다
    ask(env)  # 기억해 두었으니 처음부터 JSON 강제 없이 보낸다
    assert env.client.calls[-1].options.json_object is False


def test_json_mode_rejection_without_json_mode_moves_to_the_next_model(env):
    env.client.parameters["model-a"] = frozenset({"reasoning"})
    env.client.will("model-a", failure(LlmErrorKind.UNSUPPORTED_PARAMETER, 404))
    assert ask(env).model == "model-b"


# ---------- 429와 모델 체인 ----------


def test_rate_limit_waits_for_retry_after_then_retries_the_same_model(env):
    env.client.will("model-a", failure(LlmErrorKind.RATE_LIMITED, 429, retry_after=2.5), good())
    assert ask(env).model == "model-a"
    assert env.sleeps == [2.5]
    assert env.client.models_called() == ["model-a", "model-a"]


def test_the_wait_is_capped_at_thirty_seconds_and_has_a_default(env):
    env.client.will("model-a", failure(LlmErrorKind.RATE_LIMITED, 429, retry_after=40), good())
    env.client.will("model-b", failure(LlmErrorKind.RATE_LIMITED, 429, retry_after=None), good())
    ask(env)
    env.settings.update({"model_chain": "model-b"})
    ask(env)
    assert env.sleeps == [30.0, 5.0]


def test_two_rate_limits_in_a_row_move_on_to_the_next_model(env):
    env.client.will(
        "model-a", failure(LlmErrorKind.RATE_LIMITED, 429), failure(LlmErrorKind.RATE_LIMITED, 429)
    )
    assert ask(env).model == "model-b"
    assert env.client.models_called() == ["model-a", "model-a", "model-b"]


def test_an_unavailable_model_moves_on_without_waiting(env):
    env.client.will("model-a", failure(LlmErrorKind.UNAVAILABLE, 503))
    assert ask(env).model == "model-b"
    assert env.sleeps == []


def test_when_every_model_fails_the_caller_gets_an_outage(env):
    env.client.will("model-a", failure(LlmErrorKind.UNAVAILABLE, 503))
    env.client.will(
        "model-b", failure(LlmErrorKind.RATE_LIMITED, 429), failure(LlmErrorKind.RATE_LIMITED, 429)
    )
    with pytest.raises(LlmOutage) as outage:
        ask(env)
    assert outage.value.failures == (
        ("model-a", LlmErrorKind.UNAVAILABLE),
        ("model-b", LlmErrorKind.RATE_LIMITED),
    )


# ---------- 계정 수준의 문제 ----------


@pytest.mark.parametrize(
    ("kind", "status", "expected"),
    [
        (LlmErrorKind.PAYMENT_REQUIRED, 402, "잔액 확인 필요"),
        (LlmErrorKind.UNAUTHORIZED, 401, "키 확인 필요"),
        (LlmErrorKind.POLICY, 404, "개인정보 설정 확인 필요"),
    ],
)
def test_account_level_errors_stop_the_chain_and_alert(env, kind, status, expected):
    env.client.will("model-a", failure(kind, status))
    with pytest.raises(LlmOutage) as outage:
        ask(env)
    assert env.client.models_called() == [
        "model-a"
    ]  # 다른 모델도 같은 이유로 실패하므로 시도하지 않는다
    assert outage.value.failures == (("model-a", kind),)
    assert any(expected in text for text in env.notifier.texts())


def test_an_account_alert_is_sent_once_during_the_cooldown(env):
    env.client.default = failure(LlmErrorKind.PAYMENT_REQUIRED, 402)
    for _ in range(3):
        with pytest.raises(LlmOutage):
            ask(env)
    assert len([t for t in env.notifier.texts() if "잔액 확인 필요" in t]) == 1


# ---------- 호출 기록 ----------


def test_every_attempt_is_recorded_including_failures_and_retries(env):
    env.client.will(
        "model-a", failure(LlmErrorKind.RATE_LIMITED, 429), failure(LlmErrorKind.UNAVAILABLE, 503)
    )
    ask(env)  # a(429) → a(503) → b(성공)
    assert env.usage.count_day(TODAY) == 3
    assert env.usage.breakdown(TODAY) == {
        "model-a": {"rate_limited": 1, "unavailable": 1},
        "model-b": {"success": 1},
    }


# ---------- 하루 상한과 분당 상한 ----------


def test_at_the_daily_cap_no_call_is_made_and_an_alert_goes_out(env):
    env.record_calls(700)
    with pytest.raises(BudgetBlocked) as blocked:
        ask(env)
    assert blocked.value.reason is BudgetBlock.DAILY_CAP
    assert env.client.calls == []
    assert any("호출 상한 도달" in t for t in env.notifier.texts())


def test_a_repeated_block_does_not_repeat_the_alert_during_the_cooldown(env):
    env.record_calls(700)
    for _ in range(3):
        with pytest.raises(BudgetBlocked):
            ask(env)
    assert len(env.notifier.texts()) == 1


def test_the_cap_is_read_from_settings_on_every_call(env):
    env.record_calls(700)
    with pytest.raises(BudgetBlocked):
        ask(env)
    env.settings.update({"llm_daily_cap": "800"})
    assert ask(env).model == "model-a"


def test_a_new_utc_day_starts_counting_from_zero(env):
    env.record_calls(700)
    with pytest.raises(BudgetBlocked):
        ask(env)
    env.clock.set(datetime(2026, 10, 17, 0, 0, 5, tzinfo=UTC))
    assert env.usage.count_day(date(2026, 10, 17)) == 0
    assert ask(env).model == "model-a"


def test_the_per_minute_cap_blocks_without_an_alert(env):
    for _ in range(15):
        ask(env)
    with pytest.raises(BudgetBlocked) as blocked:
        ask(env)
    assert blocked.value.reason is BudgetBlock.RATE
    assert env.notifier.sent == []
    env.clock.advance(seconds=61)
    assert ask(env).model == "model-a"


def test_the_cap_is_also_checked_before_trying_the_next_model(env):
    env.record_calls(699)
    env.client.will("model-a", failure(LlmErrorKind.UNAVAILABLE, 503))
    with pytest.raises(BudgetBlocked):
        ask(env)  # 첫 시도가 700번째 호출이고, 그 뒤 두 번째 모델은 시도하지 않는다
    assert env.client.models_called() == ["model-a"]


def test_failed_calls_count_toward_the_cap(env):
    env.record_calls(699)
    env.client.will("model-a", failure(LlmErrorKind.RATE_LIMITED, 429), good())
    with pytest.raises(BudgetBlocked):
        ask(env)  # 429 실패가 700번째로 세어져서, 재시도는 일어나지 않는다
    assert env.usage.count_day(TODAY) == 700


# ---------- 80% 경고 ----------


def test_the_eighty_percent_warning_is_sent_once_per_day(env):
    env.record_calls(559)
    ask(env)  # 560번째
    assert [t for t in env.notifier.texts() if "호출 80% 도달" in t] != []
    for _ in range(5):
        env.clock.advance(minutes=2)
        ask(env)
    assert len([t for t in env.notifier.texts() if "호출 80% 도달" in t]) == 1


def test_the_warning_percent_comes_from_settings(env):
    env.settings.update({"llm_warn_percent": "50"})
    env.record_calls(349)
    ask(env)
    assert any("호출 50% 도달" in t for t in env.notifier.texts())


# ---------- 서버가 알려 주는 남은 호출 수 ----------


def test_a_low_server_remaining_blocks_even_when_our_own_count_is_low(env):
    env.client.usage = ServerUsage(used=985, limit=1000)
    env.record_calls(10)
    with pytest.raises(BudgetBlocked) as blocked:
        ask(env)
    assert blocked.value.reason is BudgetBlock.SERVER_LOW
    assert env.client.calls == []
    assert any("서버 한도 임박" in t for t in env.notifier.texts())


def test_the_reserve_comes_from_settings(env):
    env.client.usage = ServerUsage(used=985, limit=1000)
    env.settings.update({"llm_reserve_calls": "10"})
    assert ask(env).model == "model-a"


def test_an_unknown_server_value_falls_back_to_our_own_records(env):
    env.client.usage = None
    env.record_calls(10)
    assert ask(env).model == "model-a"


def test_the_server_value_is_reused_for_five_minutes(env):
    env.client.usage = ServerUsage(used=100, limit=1000)
    ask(env)
    env.clock.advance(minutes=4)
    ask(env)
    assert env.client.usage_queries == 1
    env.clock.advance(minutes=2)  # 처음 조회한 뒤 6분
    ask(env)
    assert env.client.usage_queries == 2


def test_a_failed_lookup_is_retried_after_a_minute_not_on_every_call(env):
    env.client.usage = None
    ask(env)
    ask(env)
    assert env.client.usage_queries == 1
    env.clock.advance(seconds=61)
    ask(env)
    assert env.client.usage_queries == 2


def test_looking_up_the_server_value_is_not_counted_as_a_call(env):
    env.client.usage = ServerUsage(used=100, limit=1000)
    ask(env)
    assert env.usage.count_day(TODAY) == 1


def test_the_calls_the_server_counted_for_others_reduce_our_room(env):
    """같은 키를 쓰는 기존 크론이 호출한 만큼 서버의 남은 수가 줄어든다."""
    env.client.usage = ServerUsage(used=500, limit=1000)
    assert ask(env).model == "model-a"
    env.client.usage = ServerUsage(used=990, limit=1000)
    env.clock.advance(minutes=6)  # 캐시가 지난 뒤
    with pytest.raises(BudgetBlocked):
        ask(env)


def test_the_warning_stays_quiet_for_the_rest_of_the_utc_day_even_after_the_cooldown(env):
    env.record_calls(559)
    ask(env)  # 560번째: 80% 도달
    env.clock.advance(hours=7)  # 쿨다운(6시간)은 지났지만 같은 UTC 날짜
    ask(env)
    assert len([t for t in env.notifier.texts() if "호출 80% 도달" in t]) == 1
