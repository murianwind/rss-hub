"""30_job_results.feature: 작업 결과 한 줄, 실행 중 표시, 지금 실행."""

import re
from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, then, when

from rss_hub.domain.models import FreeModel
from rss_hub.jobs.progress import JobProgress
from rss_hub.jobs.results import describe_result
from rss_hub.jobs.runner import IntervalJob, JobRunner, SlotJob
from rss_hub.services.collect import CollectReport
from rss_hub.services.deliver import DeliveryReport
from rss_hub.services.model_scan import ScanReport
from rss_hub.services.summarize import SummarizeReport
from rss_hub.storage.job_runs import JobRunRepository
from tests.bdd.binding import bind
from tests.fakes.collect_env import CollectEnv
from tests.fakes.delivery_env import DeliveryEnv
from tests.fakes.entries import today
from tests.fakes.llm_env import LlmEnv
from tests.keywords.browser import post
from tests.keywords.page import text_of

bind(globals(), "30_job_results.feature", [f"JOB-{n:02d}" for n in range(1, 11)])

REPORTS = {
    "대기 글 없음": SummarizeReport(),
    "요약 3건": SummarizeReport(considered=3, ready=3),
    "요약 2건과 원문 발췌 확정 1건": SummarizeReport(considered=3, ready=2, fallback=1),
    "키 없이 원문 제목으로 확정 4건": SummarizeReport(considered=4, plain=4),
    "설정이 비어 기다림": SummarizeReport(waiting_for_setup=True),
    "모델 장애로 멈춤": SummarizeReport(considered=2, outage=True),
    "보낼 글 없음": DeliveryReport(),
    "글 2건 메시지 3개 발송": DeliveryReport(considered=2, delivered=2, sent=3),
    "서비스 주소가 없음": DeliveryReport(considered=2, waiting_for_base_url=True),
    "기본 웹훅이 없음": DeliveryReport(considered=2, no_default_webhook=True),
    "피드 4개 점검 새 글 2개": CollectReport(checked=4, added=2, baseline_recorded=0, failed=()),
    "피드 3개 점검 새 글 0개 실패 1개": CollectReport(
        checked=3, added=0, baseline_recorded=0, failed=((1, "Timeout"),)
    ),
    "글 5개 삭제": 5,
    "삭제할 글 없음": 0,
    "모델 12개 확인": ScanReport(
        ok=True, models=tuple(FreeModel(f"m{n}", "m", 1, True) for n in range(12))
    ),
    "확인 실패": ScanReport(ok=False, error="HTTP 503"),
}


@pytest.fixture
def ctx():
    return SimpleNamespace(html="", response=None, runner=None, line="", pending=[], records=None)


def records_of(world):
    return JobRunRepository(world.parts.db, world.parts.clock)


def row_of(html, job):
    """작업 표에서 그 작업의 줄."""
    return html.split(f'data-job="{job}"')[1].split("</li>")[0]


@given(parsers.parse('요약 작업이 "{result}"라는 결과로 끝났다'))
def _finished_with_result(world, result):
    records = records_of(world)
    records.mark_started("summarize")
    records.mark_finished("summarize", None, result)


@given("발송 작업이 실행 중이다")
def _deliver_running(world):
    records_of(world).mark_started("deliver")


@given("작업 실행기가 있고 발송 작업은 이미 실행 중이다")
def _real_runner_busy(world, ctx):
    ctx.records = records_of(world)
    ctx.pending = []
    ctx.runner = JobRunner(
        jobs=[IntervalJob("deliver", lambda: DeliveryReport(), lambda: 60)],
        clock=world.parts.clock,
        records=ctx.records,
        timezone=lambda: world.parts.settings.snapshot().timezone,
        spawn=ctx.pending.append,
    )
    world.client.app.state.runner = ctx.runner
    assert ctx.runner.run_now("deliver") == "started"  # 작업은 시작했고 끝나지 않았다


@given("발송 작업은 차례를 1번 넘긴 기록이 있다")
def _skipped_once(ctx):
    ctx.records.mark_skipped("deliver")


@when("상태 화면을 연다")
def _open(world, ctx):
    ctx.response = world.get("/status")
    ctx.html = ctx.response.text
    assert ctx.response.status_code == 200


@when("발송 작업을 지금 실행한다")
def _run_deliver(world, ctx):
    sent = post(world, "/status/jobs/deliver/run")
    ctx.response = world.get(sent.headers["location"])
    ctx.html = ctx.response.text


@then(parsers.parse('요약 작업 기록에 "{text}"가 보인다'))
def _result_shown(ctx, text):
    assert text in re.sub(r"\s+", " ", text_of_html(row_of(ctx.html, "summarize")))


def text_of_html(fragment):
    return re.sub(r"<[^>]+>", " ", fragment)


@then('발송 작업 기록에 "실행 중"이 보이고 현재 상태의 지금 발송 버튼은 막혀 있다')
def _running_row(ctx):
    assert "실행 중" in text_of_html(row_of(ctx.html, "deliver"))
    current = ctx.html.split("data-current")[1].split("</section>")[0]
    button = current.split('action="/status/jobs/deliver/run"')[1].split("</form>")[0]
    assert re.search(r"<button[^>]*disabled[^>]*>\s*지금 발송", button)


@then("상태 화면은 실행 중인 작업이 있다고 표시해서 화면이 스스로 갱신되게 한다")
def _page_marks_running(ctx):
    assert 'data-jobs-running="1"' in ctx.html


@then("상태 화면은 실행 중인 작업이 없다고 표시한다")
def _page_marks_idle(ctx):
    assert 'data-jobs-running="0"' in ctx.html


@then("이미 실행 중이라는 안내가 보이고 발송 작업의 넘긴 차례는 그대로 1회이다")
def _busy_not_counted(ctx):
    assert "이미 실행 중입니다" in text_of(ctx.response)
    assert ctx.records.get("deliver").skipped_count == 1


@when(parsers.re(r"(?P<job>\w+)의 결과가 (?P<report>.+)일 때 결과 한 줄을 만든다"))
def _describe(ctx, job, report):
    ctx.line = describe_result(job, REPORTS[report])


@then(parsers.parse('결과 한 줄은 "{sentence}"이다'))
def _sentence(ctx, sentence):
    assert ctx.line == sentence


@given("결과를 보고서로 돌려주는 요약 작업이 있다")
def _runner_with_reports(world, ctx):
    ctx.records = records_of(world)
    ctx.outcomes = [SummarizeReport(considered=3, ready=3)]

    def summarize():
        outcome = ctx.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    ctx.runner = JobRunner(
        jobs=[IntervalJob("summarize", summarize, lambda: 60)],
        clock=world.parts.clock,
        records=ctx.records,
        timezone=lambda: world.parts.settings.snapshot().timezone,
        spawn=lambda work: work(),
        describe=describe_result,
    )


@when("요약 작업이 지금 실행되어 끝난다")
def _run_summarize(ctx):
    assert ctx.runner.run_now("summarize") == "started"


@then("요약 작업의 마지막 결과가 기록되어 있다")
def _result_recorded(ctx):
    assert ctx.records.get("summarize").last_result == "요약 3건"


@then("작업이 예외로 끝나면 이전 결과를 지우고 오류만 기록한다")
def _error_clears_result(ctx):
    ctx.outcomes.append(RuntimeError("boom"))
    assert ctx.runner.run_now("summarize") == "started"
    record = ctx.records.get("summarize")
    assert record.last_result == "" and record.last_error == "RuntimeError"


@given("발송 작업이 실행 중으로 남은 채 서비스가 멈췄다")
def _stale_running(world, ctx):
    ctx.records = records_of(world)
    ctx.records.mark_started("deliver")
    ctx.runner = JobRunner(
        jobs=[],
        clock=world.parts.clock,
        records=ctx.records,
        timezone=lambda: world.parts.settings.snapshot().timezone,
        spawn=lambda work: work(),
    )


@when("작업 실행기가 시작된다")
def _runner_starts(ctx):
    ctx.runner.start()
    ctx.runner.shutdown(1.0)


@then("발송 작업은 실행 중이 아니라 중단된 것으로 기록된다")
def _recovered(ctx):
    record = ctx.records.get("deliver")
    assert record.last_status == "error" and record.last_error == "Interrupted"


# ---------- 진행 ----------


def runner_for(world, *jobs, progress):
    return JobRunner(
        jobs=list(jobs),
        clock=world.parts.clock,
        records=records_of(world),
        timezone=lambda: world.parts.settings.snapshot().timezone,
        spawn=lambda work: work(),
        progress=progress,
    )


@given("요약 작업이 5건 중 2건을 처리하며 실행 중이다")
def _summarize_in_progress(world):
    progress = JobProgress()
    progress.report("summarize", 2, 5)
    world.client.app.state.runner = runner_for(world, progress=progress)
    records_of(world).mark_started("summarize")


@then('현재 상태의 요약 줄과 작업 기록에 "2/5건"이 보인다')
def _progress_shown(ctx):
    current = ctx.html.split("data-current")[1].split("</section>")[0]
    row = current.split('data-run-row="summarize"')[1].split("</li>")[0]
    assert "2/5건" in text_of_html(row)
    assert "2/5건" in text_of_html(row_of(ctx.html, "summarize"))


@given("요약을 기다리는 글 3개와 발송을 기다리는 글 2개가 있다")
def _services_with_progress(tmp_path, ctx):
    ctx.events = {"summarize": [], "deliver": []}
    (tmp_path / "llm").mkdir()
    (tmp_path / "delivery").mkdir()
    ctx.llm_env = LlmEnv(
        tmp_path / "llm", progress=lambda d, t: ctx.events["summarize"].append((d, t))
    )
    ctx.delivery_env = DeliveryEnv(
        tmp_path / "delivery", progress=lambda d, t: ctx.events["deliver"].append((d, t))
    )
    for _ in range(3):
        ctx.llm_env.add_article()
    for _ in range(2):
        ctx.delivery_env.add_ready_article()


@when("요약 작업과 발송 작업이 한 번씩 실행된다")
def _run_services(ctx):
    ctx.llm_env.summarizer.run()
    ctx.delivery_env.service.run()


@then("요약은 0/3부터 3/3까지, 발송은 0/2부터 2/2까지 알렸다")
def _events(ctx):
    assert ctx.events["summarize"] == [(0, 3), (1, 3), (2, 3), (3, 3)]
    assert ctx.events["deliver"] == [(0, 2), (1, 2), (2, 2)]


@then("작업이 끝난 뒤에는 어느 작업도 진행 중으로 남지 않는다")
def _progress_cleared(world):
    progress = JobProgress()

    def work():
        progress.report("summarize", 1, 1)
        return SummarizeReport()

    runner = runner_for(world, IntervalJob("summarize", work, lambda: 60), progress=progress)
    assert runner.run_now("summarize") == "started"
    assert runner.progress_of("summarize") is None


@given("구독한 피드가 셋이고 이번 슬롯에는 하나만 배정되어 있다")
def _three_feeds(tmp_path, ctx):
    ctx.events = {"collect": []}
    (tmp_path / "collect").mkdir()
    env = CollectEnv(tmp_path / "collect")
    ctx.collect_env = env
    for n in (1, 2, 3):
        _, url = env.add_feed(n)
        env.fetcher.serve(url, today(1))
    from rss_hub.services.collect import CollectService

    ctx.collector = CollectService(
        feeds=env.feeds,
        articles=env.articles,
        fetcher=env.fetcher,
        settings=env.settings,
        clock=env.clock,
        progress=lambda d, t: ctx.events["collect"].append((d, t)),
    )


@when("수집을 지금 실행한다")
def _collect_now(world, ctx):
    runner = runner_for(
        world,
        SlotJob("collect", ctx.collector.run_slot, lambda: 5, run_now=ctx.collector.run_all),
        progress=JobProgress(),
    )
    assert runner.run_now("collect") == "started"


@then("피드 셋을 모두 점검하고 점검한 개수를 진행으로 알린다")
def _all_checked(ctx):
    assert len(ctx.collect_env.fetcher.urls_fetched()) == 3
    assert ctx.events["collect"] == [(0, 3), (1, 3), (2, 3), (3, 3)]
