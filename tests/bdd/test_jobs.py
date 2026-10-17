"""잡 연결 시나리오: SCH-12, 13(겹침, 재시작)과 SET-03, 04, 21(설정 반영, 주기, 설정 전 대기)."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, then, when

from rss_hub.storage.llm_usage import LlmUsageRepository
from tests.bdd.binding import bind
from tests.fakes.runtime_env import KST, RuntimeEnv

bind(globals(), "01_scheduling.feature", ["SCH-12", "SCH-13"])
bind(globals(), "09_settings.feature", ["SET-03", "SET-04", "SET-21"])

SETTING_KEYS = {
    "서비스 주소": "service_base_url",
    "LLM 하루 상한": "llm_daily_cap",
    "모델 체인": "model_chain",
    "서비스 시간대": "service_timezone",
}


@pytest.fixture
def ctx():
    return SimpleNamespace(env=None, pending=[], started=[], first_start=None, runner=None)


def env_of(ctx, tmp_path, **options):
    if ctx.env is None:
        ctx.env = RuntimeEnv(tmp_path, **options)
    return ctx.env


# ---------- SCH-12: 겹쳐 실행하지 않는다 ----------


@given("수집 작업이 아직 실행 중이다")
def _collect_is_running(ctx, tmp_path):
    env = env_of(ctx, tmp_path, spawn=ctx.pending.append)  # 시작한 작업이 끝나지 않은 채로 남는다
    env.serve_new_article()
    env.runner.tick()
    assert "collect" in env.runner.running
    ctx.first_start = env.records.get("collect").last_started_at


@when("다음 슬롯 시각이 된다")
def _next_slot(ctx):
    ctx.env.clock.advance(minutes=5)
    ctx.started = ctx.env.runner.tick()


@then("수집 작업은 겹쳐 실행되지 않는다")
def _no_overlap(ctx):
    assert "collect" not in ctx.started
    assert ctx.env.records.get("collect").last_started_at == ctx.first_start


@then("건너뛴 사실이 기록된다")
def _skip_recorded(ctx):
    run = ctx.env.records.get("collect")
    assert run.skipped_count == 1 and run.last_skipped_at == ctx.env.clock.now()


# ---------- SCH-13: 놓친 슬롯은 따라잡지 않는다 ----------


@given("서비스가 14시 00분부터 14시 20분까지 꺼져 있었다")
def _service_was_down(ctx, tmp_path):
    env = env_of(ctx, tmp_path, start=datetime(2026, 10, 16, 13, 55, tzinfo=KST).astimezone(UTC))
    env.serve_new_article()
    env.runner.tick()  # 13시 55분 슬롯까지 실행하고 멈춘다
    ctx.calls_before = len(env.fetcher.calls)


@when("14시 20분에 서비스가 다시 시작된다")
def _restart_at_1420(ctx):
    ctx.env.clock.advance(minutes=25)
    ctx.env.restart()
    ctx.started = ctx.env.runner.tick()


@then("14시 20분 슬롯만 실행된다")
def _only_1420(ctx):
    assert "collect" in ctx.started
    assert ctx.env.records.get("collect").last_slot == datetime(2026, 10, 16, 14, 20, tzinfo=KST)


@then("14시 00분부터 14시 15분까지의 슬롯은 실행되지 않는다")
def _no_catch_up(ctx):
    assert len(ctx.env.fetcher.calls) == ctx.calls_before + 1  # 14시 20분 한 번만 더 점검했다
    assert "collect" not in ctx.env.runner.tick()


# ---------- SET-03: 설정을 저장하면 재시작 없이 다음 실행부터 반영 ----------


@when(parsers.parse('"{setting}"을 "{value}"로 바꿔 저장한다'))
def _change_setting(ctx, tmp_path, setting, value):
    env = env_of(ctx, tmp_path)
    result = env.settings.update({SETTING_KEYS[setting]: value})
    assert not result.errors


@then("새 메시지의 링크가 새 주소로 만들어진다")
def _new_address(ctx):
    ctx.env.serve_new_article()
    ctx.env.runner.tick()
    assert "(https://new.example.com/a/" in ctx.env.sender.to("rss")[0]


@then("오늘 호출 수가 100이 되면 호출이 멈춘다")
def _cap_reached(ctx):
    usage = LlmUsageRepository(ctx.env.db, ctx.env.clock)
    for _ in range(100):
        usage.record(model="model-a", outcome="success", status=200)
    ctx.env.serve_new_article()
    ctx.env.runner.tick()
    assert ctx.env.client.calls == []
    assert [a.status for a in ctx.env.articles.list_by_status("collected")] == ["collected"]


@then("model-c만 호출한다")
def _only_model_c(ctx):
    ctx.env.serve_new_article()
    ctx.env.runner.tick()
    assert [c.model for c in ctx.env.client.calls] == ["model-c"]


@then('"오늘" 판단이 새 시간대 기준으로 바뀐다')
def _today_in_new_zone(ctx):
    # 한국 시각 10시에 발행된 글은 뉴욕으로는 어제 저녁이라 오늘 글이 아니다
    ctx.env.serve_new_article()
    ctx.env.runner.tick()
    assert ctx.env.articles.count_by_status() == {}


# ---------- SET-04: 주기를 바꾸면 진행 중인 작업은 끝까지, 다음부터 새 주기 ----------


@given("요약 작업이 실행 중이다")
def _summarize_is_running(ctx, tmp_path):
    env = env_of(ctx, tmp_path, spawn=ctx.pending.append)
    env.runner.tick()
    assert "summarize" in env.runner.running
    ctx.runner = env.runner
    ctx.first_start = env.records.get("summarize").last_started_at


@when("요약 주기를 60초에서 30초로 바꿔 저장한다")
def _change_interval(ctx):
    assert ctx.env.settings.snapshot().summarize_interval_seconds == 60
    assert not ctx.env.settings.update({"summarize_interval_seconds": "30"}).errors


@then("실행 중인 요약 작업은 끝까지 마친다")
def _running_job_finishes(ctx):
    assert "summarize" in ctx.env.runner.running  # 설정을 바꿔도 끊지 않았다
    while ctx.pending:
        ctx.pending.pop(0)()  # 보류해 둔 작업이 끝까지 실행된다
    assert ctx.env.records.get("summarize").last_status == "ok"
    assert "summarize" not in ctx.env.runner.running


@then("그다음부터 요약 작업은 30초 간격으로 실행된다")
def _new_interval(ctx):
    ctx.env.clock.advance(seconds=29)
    assert "summarize" not in ctx.env.runner.tick()
    ctx.env.clock.advance(seconds=1)
    assert "summarize" in ctx.env.runner.tick()


@then("서비스를 다시 시작할 필요가 없다")
def _no_restart(ctx):
    assert ctx.env.runner is ctx.runner  # 같은 실행기가 새 주기로 계속 돈다


# ---------- SET-21: 필요한 설정이 없으면 기다리고, 채우면 재시작 없이 시작 ----------


@given('서비스가 설정 없이 시작되어 있고 수집된 글 1개가 "collected" 상태이다')
def _unconfigured_with_collected_article(ctx, tmp_path):
    env = env_of(ctx, tmp_path, configured=False)
    env.serve_new_article()
    env.runner.tick()
    assert [a.status for a in env.articles.list_by_status("collected")] == ["collected"]


@then("요약 작업은 LLM을 호출하지 않고 글은 그대로 남는다")
def _waits(ctx):
    ctx.env.tick(seconds=60)
    assert ctx.env.client.calls == []
    assert [a.status for a in ctx.env.articles.list_by_status("collected")] == ["collected"]


@when("OpenRouter 키, 기본 웹훅, 서비스 주소를 저장한다")
def _fill_settings(ctx):
    ctx.env.configure()


@then("다음 요약 작업부터 LLM을 호출한다")
def _calls_llm(ctx):
    ctx.env.tick(seconds=60)
    assert len(ctx.env.client.calls) == 1


@then("요약이 끝난 글은 다음 발송 작업에서 보낸다")
def _sent_by_the_next_delivery(ctx):
    assert [a.status for a in ctx.env.articles.list_by_status("delivered")] == ["delivered"]
    assert len(ctx.env.sender.to("rss")) == 1
