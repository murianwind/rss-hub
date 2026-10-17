"""06_llm_budget.feature 전체.

모델 체인, 호출 기록, 예산 가드, 시스템 알림, 서버가 알려 주는 남은 호출 수를 다룬다.
"""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, then, when

from rss_hub.services.llm_gateway import BudgetBlocked, LlmOutage
from rss_hub.services.ports import LlmErrorKind, ServerUsage
from tests.bdd.binding import bind
from tests.fakes.llm_client import failure, good
from tests.fakes.llm_env import LlmEnv

bind(globals(), "06_llm_budget.feature", [f"BUD-{n:02d}" for n in range(1, 18)])


@pytest.fixture
def env(tmp_path):
    return LlmEnv(tmp_path)


@pytest.fixture
def ctx():
    return SimpleNamespace(answer=None, error=None, report=None, article_id=None, runs=0)


def today(env):
    return env.clock.now().astimezone(UTC).date()


def ask(env, ctx):
    """LLM에 한 번 요청한다. 결과와 오류를 모두 담아 둔다."""
    try:
        ctx.answer = env.gateway.complete("프롬프트")
        ctx.error = None
    except (LlmOutage, BudgetBlocked) as error:
        ctx.answer, ctx.error = None, error


def alerts_containing(env, text):
    return [t for t in env.notifier.texts() if text in t]


# ---------- 배경 ----------


@given('모델 체인은 "model-a", "model-b" 순서이다')
def _chain(env):
    assert env.settings.snapshot().model_chain == ("model-a", "model-b")


@given("하루 운영 호출 상한은 700회이고 경고 비율은 80%이다")
def _cap_and_warn(env):
    config = env.settings.snapshot()
    assert (config.llm_daily_cap, config.llm_warn_percent) == (700, 80)


@given("분당 호출 상한은 15회이다")
def _rpm(env):
    assert env.settings.snapshot().llm_rpm_cap == 15


@given('모델 체인에는 "model-a"만 있다')
def _only_a(env):
    env.settings.update({"model_chain": "model-a"})


# ---------- 모델 체인 (BUD-01 ~ 04, 13) ----------


@given('"model-a"가 오류로 실패하고 "model-b"가 성공한다')
def _a_fails_b_works(env):
    env.client.will("model-a", failure(LlmErrorKind.UNAVAILABLE, 503))


@given('"model-a"가 429와 Retry-After 40초로 답하고, 기다린 뒤 다시 시도하면 성공한다')
def _a_rate_limited_once(env):
    env.client.will("model-a", failure(LlmErrorKind.RATE_LIMITED, 429, retry_after=40), good())


@given('"model-a"가 두 번 연속 429로 답한다')
def _a_rate_limited_twice(env):
    rate = failure(LlmErrorKind.RATE_LIMITED, 429)
    env.client.will("model-a", rate, rate)


@given('"model-a"와 "model-b"가 모두 실패한다')
def _both_fail(env):
    env.client.default = failure(LlmErrorKind.UNAVAILABLE, 503)


@given("모든 모델이 402로 답한다")
def _all_402(env):
    env.client.default = failure(LlmErrorKind.PAYMENT_REQUIRED, 402)


@given(parsers.parse('설정의 모델 체인을 "{model}"로 바꾼다'))
def _change_chain(env, model):
    env.settings.update({"model_chain": model})


@when("LLM에 요청한다")
def _request(env, ctx):
    ask(env, ctx)


@then('"model-a"를 먼저 호출한 뒤 "model-b"를 호출한다')
def _a_then_b(env):
    assert env.client.models_called() == ["model-a", "model-b"]


@then(parsers.parse('응답과 함께 "{model}" 사용 기록이 반환된다'))
def _answer_model(ctx, model):
    assert ctx.answer is not None and ctx.answer.model == model


@then("대기 시간은 30초로 제한된다")
def _wait_capped(env):
    assert env.sleeps == [30.0]


@then(parsers.parse('"model-a"로 한 번 더 요청한다'))
def _a_again(env):
    assert env.client.models_called() == ["model-a", "model-a"]


@then('"model-b"는 호출하지 않는다')
def _b_not_called(env):
    assert "model-b" not in env.client.models_called()


@then('"model-b"를 호출한다')
def _b_called(env):
    assert "model-b" in env.client.models_called()


@then('호출자는 "장애"를 받는다')
def _outage_received(ctx):
    assert isinstance(ctx.error, LlmOutage)


@then("잘못된 응답이 아니라 호출 자체의 실패로 구분된다")
def _distinguished(ctx):
    assert isinstance(ctx.error, LlmOutage) and not isinstance(ctx.error, BudgetBlocked)
    assert all(isinstance(kind, LlmErrorKind) for _, kind in ctx.error.failures)


@then('"model-c"를 호출하고 "model-a"는 호출하지 않는다')
def _c_not_a(env):
    assert env.client.models_called() == ["model-c"]


# ---------- 호출 수 기록 (BUD-05, 06, 09) ----------


@when("LLM에 3번 요청해서 2번 성공하고 1번 실패한다")
def _three_requests(env, ctx):
    env.client.will("model-a", good(), good(), failure(LlmErrorKind.UNAVAILABLE, 503))
    for _ in range(3):
        ask(env, ctx)


@given(parsers.re(r"오늘 호출 수는 (?P<count>\d+)이다"))
@given(parsers.re(r"우리 서비스가 센 오늘 호출 수는 (?P<count>\d+)이다"))
@given(parsers.re(r"오늘 호출 수는 (?P<count>\d+)이고 상한에 도달해 있다"))
def _already_called(env, count):
    env.record_calls(int(count))


@then(parsers.parse("오늘 호출 수는 {count:d}이다"))
def _count_today(env, count):
    assert env.usage.count_day(today(env)) == count


@then("모델별 성공과 실패가 따로 기록된다")
def _breakdown(env):
    assert env.usage.breakdown(today(env)) == {"model-a": {"success": 2, "unavailable": 1}}


@when("호출이 429로 실패하고 기다린 뒤 다시 시도한 호출은 성공한다")
def _fail_then_retry(env, ctx):
    env.client.will("model-a", failure(LlmErrorKind.RATE_LIMITED, 429, retry_after=1), good())
    ask(env, ctx)


@when("UTC 날짜가 바뀐다")
def _next_day(env):
    env.clock.set(datetime(2026, 10, 17, 0, 0, 5, tzinfo=UTC))


@then("요약 작업은 다시 호출할 수 있다")
def _can_call_again(env, ctx):
    ask(env, ctx)
    assert ctx.answer is not None


# ---------- 경고와 알림 (BUD-07, 08, 11, 12) ----------


@when(parsers.parse("호출이 {count:d}번 더 일어난다"))
def _more_calls(env, ctx, count):
    for _ in range(count):
        ask(env, ctx)


@then(parsers.parse('시스템 웹훅으로 "{text}" 알림이 1번 간다'))
def _alert_once(env, text):
    assert len(alerts_containing(env, text)) == 1


@then("같은 알림은 다시 가지 않는다")
def _alert_not_repeated(env):
    assert len(alerts_containing(env, "호출 80% 도달")) == 1


@given('"호출 상한 도달" 알림을 방금 보냈다')
def _cap_alert_sent(env):
    assert env.alerts.notify("llm_cap", "호출 상한 도달: 시험") is True


@when("같은 상황이 계속 감지된다")
def _same_situation(env):
    env.clock.advance(minutes=30)
    env.alerts.notify("llm_cap", "호출 상한 도달: 시험")


@then("쿨다운이 끝나기 전에는 같은 알림을 다시 보내지 않는다")
def _cooldown_holds(env):
    assert len(alerts_containing(env, "호출 상한 도달")) == 1


# ---------- 요약 작업과의 연결 (BUD-08, 10, 14 ~ 17) ----------


@given("요약 대상 글이 있다")
def _one_article(env, ctx):
    ctx.article_id = env.add_article()


@given(parsers.parse("요약 대상 글이 {count:d}개 있고 모두 즉시 응답한다"))
def _many_articles(env, count):
    for _ in range(count):
        env.add_article()


@when("요약 작업을 실행한다")
def _run_summarize(env, ctx):
    ctx.report = env.summarizer.run()


@when("1분 동안 요약 작업을 반복 실행한다")
def _run_for_a_minute(env, ctx):
    for _ in range(10):
        env.summarizer.run()
        env.clock.advance(seconds=5)


@then("LLM 호출은 일어나지 않는다")
def _no_calls(env):
    assert env.client.calls == []


@then("LLM 호출은 정상적으로 일어난다")
def _calls_happen(env):
    assert env.client.calls != []


@then("글의 재시도 횟수는 늘지 않는다")
def _retry_unchanged(env, ctx):
    assert env.articles.get(ctx.article_id).retry_count == 0


@then("그 1분 동안의 LLM 호출은 15번 이하이다")
def _at_most_fifteen(env):
    assert 0 < len(env.client.calls) <= 15


@when(parsers.parse("하루 운영 호출 상한을 {cap:d}으로 바꾼다"))
def _raise_cap(env, cap):
    assert env.settings.update({"llm_daily_cap": str(cap)}).errors == {}


# ---------- 서버가 알려 주는 남은 호출 수 (BUD-15 ~ 17) ----------


@given(parsers.parse("서버가 알려 준 오늘 사용량은 {used:d}, 한도는 {limit:d}이다"))
def _server_usage(env, used, limit):
    env.client.usage = ServerUsage(used=used, limit=limit)


@given(parsers.parse("예비 호출 수는 {reserve:d}이다"))
def _reserve(env, reserve):
    assert env.settings.update({"llm_reserve_calls": str(reserve)}).errors == {}


@given("서버의 키 정보 조회가 실패한다")
def _lookup_fails(env):
    env.client.usage = None


@when("요약 작업을 실행하고 4분 뒤에 다시 실행한다")
def _run_then_again(env):
    env.summarizer.run()
    env.clock.advance(minutes=4)
    env.add_article()  # 새 글이 하나 수집되었다
    env.summarizer.run()


@when("6분이 더 지난 뒤 요약 작업을 실행한다")
def _run_after_six_minutes(env):
    env.clock.advance(minutes=6)
    env.add_article()
    env.summarizer.run()


@then(parsers.parse("서버 키 정보 조회는 {count:d}번이다"))
def _server_queries(env, count):
    assert env.client.usage_queries == count


@then("키 정보 조회는 우리 서비스의 호출 수에 포함되지 않는다")
def _lookups_not_counted(env):
    assert env.usage.count_day(today(env)) == len(env.client.calls)
