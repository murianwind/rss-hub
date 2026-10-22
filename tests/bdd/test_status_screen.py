"""28_status_screen.feature: 호출 수 풀이, 건너뜀 설명, 대기 글, 지금 실행, 배치."""

import re
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, then, when

from rss_hub.storage.job_runs import JobRunRepository
from rss_hub.storage.llm_usage import LlmUsageRepository
from tests.bdd.binding import bind
from tests.keywords.browser import post
from tests.keywords.page import text_of

bind(globals(), "28_status_screen.feature", [f"STS-{n:02d}" for n in range(1, 8)])


class FakeRunner:
    """작업 실행기 대역: 실행 요청을 기록하고, busy에 든 이름은 이미 실행 중이라고 답한다."""

    def __init__(self):
        self.calls = []
        self.busy = set()

    def run_now(self, name):
        self.calls.append(name)
        return "busy" if name in self.busy else "started"


@pytest.fixture
def ctx():
    return SimpleNamespace(response=None, html="", runner=None)


def open_status(world, ctx):
    ctx.response = world.get("/status")
    ctx.html = ctx.response.text


@given("오늘 모델 호출이 성공 2번, 한도 초과 3번 있었다")
def _usage(world):
    usage = LlmUsageRepository(world.parts.db, world.parts.clock)
    for _ in range(2):
        usage.record(model="m", outcome="success", status=200)
    for _ in range(3):
        usage.record(model="m", outcome="rate_limited", status=429)


@given("시계가 한국 시간 아침 8시(UTC로는 전날 밤 11시)이고 UTC 기준 그날 호출이 2번 있었다")
def _kst_early_morning(world):
    world.parts.clock.set(datetime(2026, 10, 21, 23, 0, tzinfo=UTC))
    usage = LlmUsageRepository(world.parts.db, world.parts.clock)
    for _ in range(2):
        usage.record(model="m", outcome="success", status=200)


@given("요약 작업이 3번 건너뛰었다")
def _skipped(world):
    records = JobRunRepository(world.parts.db, world.parts.clock)
    for _ in range(3):
        records.mark_skipped("summarize")


@given(parsers.parse('서비스 주소가 없고 발송을 기다리는 글 "{title}"이 있다'))
def _waiting_to_send(world, title):
    assert world.parts.settings.snapshot().base_url == ""
    world.article(title=title, ko=title, summary="요약")  # 요약이 끝나 발송을 기다리는 글


@given(parsers.parse('요약을 기다리는 글 "{title}"이 있다'))
def _waiting_to_summarize(world, title):
    world.article(title=title)


@given("작업 실행기가 있다")
def _runner(world, ctx):
    ctx.runner = FakeRunner()
    world.client.app.state.runner = ctx.runner


@when("상태 화면을 연다")
def _open(world, ctx):
    open_status(world, ctx)
    assert ctx.response.status_code == 200


def run_job(world, ctx, name):
    sent = post(world, f"/status/jobs/{name}/run")
    assert sent.status_code in (303, 404)
    ctx.response = sent
    if sent.status_code == 303:
        ctx.response = world.get(sent.headers["location"])
        ctx.html = ctx.response.text


@when("발송 작업을 지금 실행한다")
def _run_deliver(world, ctx):
    run_job(world, ctx, "deliver")


@when("같은 작업이 이미 실행 중일 때 다시 실행한다")
def _run_busy(world, ctx):
    ctx.runner.busy.add("deliver")
    run_job(world, ctx, "deliver")


@when("작업 실행기가 없는 상태에서 발송 작업을 지금 실행한다")
def _run_without_runner(world, ctx):
    world.client.app.state.runner = None
    run_job(world, ctx, "deliver")


@when("알 수 없는 작업을 지금 실행한다")
def _run_unknown(world, ctx):
    run_job(world, ctx, "nonsense")


@then(parsers.parse('오늘 LLM 호출은 "{total}"이고 "{split}"으로 나뉘어 보인다'))
def _usage_split(ctx, total, split):
    text = re.sub(r"\s+", " ", text_of(ctx.response))
    assert f"오늘 LLM 호출 (UTC 기준 하루) {total}" in text and split in text


@then("사이드바의 잔여 사용량은 서버가 세는 값이라 실패한 호출은 빠질 수 있다는 설명이 있다")
def _usage_note(ctx):
    text = re.sub(r"\s+", " ", text_of(ctx.response))
    assert "OpenRouter 서버가 세는" in text and "실패한 호출은 빠질 수" in text


@then(parsers.parse('요약 작업에 "{label}"가 보이고 그 뜻이 설명되어 있다'))
def _skip_label(ctx, label):
    text = re.sub(r"\s+", " ", text_of(ctx.response))
    assert label in text and "이전 실행이 끝나기 전에 다음 차례가 와서" in text


def pending_list(html, kind):
    return html.split(f'data-pending="{kind}"')[1].split("</ul>")[0]


@then(parsers.parse('발송 대기 목록에 "{title}"과 "{hint}" 안내가 있다'))
def _send_list(ctx, title, hint):
    block = pending_list(ctx.html, "ready")
    assert title in block and hint in block


@then(parsers.parse('요약 대기 목록에 "{title}"이 있다'))
def _summarize_list(ctx, title):
    assert title in pending_list(ctx.html, "collected")


@then("발송 작업이 시작되었다는 안내가 보인다")
def _started(ctx):
    assert "발송 작업을 시작했습니다" in text_of(ctx.response) and ctx.runner.calls == ["deliver"]


@then("이미 실행 중이라는 안내가 보인다")
def _busy(ctx):
    assert "이미 실행 중입니다" in text_of(ctx.response)


@then("실행할 수 없다는 안내가 보인다")
def _unavailable(ctx):
    assert "지금 실행할 수 없습니다" in text_of(ctx.response)


@then("알 수 없는 작업이라는 응답을 받는다")
def _unknown(ctx):
    assert ctx.response.status_code == 404


@then("현재 상태, 작업, 설정 점검, 변경 이력이 격자 칸으로 나뉘어 있다")
def _grid(world, ctx):
    assert 'class="status-grid"' in ctx.html
    cards = re.findall(r'<section class="status-card[^"]*"[^>]*>\s*<h2>([^<]+)</h2>', ctx.html)
    assert cards == ["현재 상태", "작업", "설정 점검", "변경 이력"]
    css = world.get("/static/app.css").text
    assert ".status-grid {" in css and "grid-template-columns" in css.split(".status-grid {")[1]
