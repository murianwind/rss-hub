"""40_error_log.feature: 서버 오류 기록."""

import re
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, then, when

from rss_hub.domain.discovery import describe_fetch_failure
from rss_hub.domain.error_log import (
    KIND_COLLECT,
    KIND_DELIVER,
    KIND_FULLTEXT,
    KIND_JOB,
    KIND_LLM,
    KIND_SUMMARIZE,
)
from rss_hub.jobs.runner import IntervalJob, JobRunner
from rss_hub.services.collect import CollectService
from rss_hub.services.error_log import ErrorRecorder
from rss_hub.services.fulltext import FullTextService
from rss_hub.services.ports import LlmErrorKind, PageResult, SendResult
from rss_hub.services.retention import RetentionService
from rss_hub.storage.articles import NewArticle
from rss_hub.storage.database import Database
from rss_hub.storage.error_log import ErrorLogRepository
from rss_hub.storage.feeds import FeedRepository
from rss_hub.storage.job_runs import JobRunRepository
from tests.bdd.binding import bind
from tests.fakes.clock import FakeClock
from tests.fakes.collect_env import CollectEnv
from tests.fakes.delivery_env import DeliveryEnv, webhook_url
from tests.fakes.llm_client import failure, good
from tests.fakes.llm_env import LlmEnv
from tests.fakes.viewer_world import open_world

bind(globals(), "40_error_log.feature", [f"ERL-{n:02d}" for n in range(1, 18)])


@pytest.fixture
def ctx():
    return SimpleNamespace(
        feed=None, url="", service=None, log=None, article=None, runner=None, html="", env=None
    )


def entries(log, kind=""):
    return log.list(kind=kind)


# ---------- 기록 ----------


@given("시간 초과로 실패하는 피드가 있다")
def _failing_feed(ctx, tmp_path):
    ctx.env = CollectEnv(tmp_path)
    ctx.feed, ctx.url = ctx.env.add_feed()
    ctx.env.fetcher.fail(ctx.url, "Timeout")


@when("수집한다")
def _collect(ctx):
    ctx.env.collect(ctx.feed)


@then(parsers.parse('오류 기록에 "{label}" 유형으로 피드 이름과 이유가 남는다'))
def _collect_logged(ctx, label):
    (entry,) = entries(ctx.env.error_log, KIND_COLLECT)
    assert entry.source == "피드1" and entry.message == describe_fetch_failure("Timeout")
    assert entry.detail == "Timeout" and entry.count == 1 and label == "피드 수집"


@dataclass
class _Pages:
    html: str
    calls: list[str] = field(default_factory=list)

    def fetch_page(self, url):
        self.calls.append(url)
        return PageResult(self.html, url)


@given("원문 페이지에서 본문을 찾지 못하는 글이 있다")
def _no_content(ctx, tmp_path):
    db, clock = Database(tmp_path / "x.db"), FakeClock()
    feed = FeedRepository(db, clock).add("https://a.example.com/rss", "A")
    ctx.log = ErrorLogRepository(db, clock)
    from rss_hub.storage.articles import ArticleRepository

    articles = ArticleRepository(db, clock)
    ctx.link = "https://a.example.com/post/1"
    ctx.article = articles.get(
        articles.add(
            NewArticle(
                feed, "g", "오류 글", ctx.link, "<p>RSS 요약</p>", "", clock.now(), "2026-10-16"
            )
        )
    )
    ctx.service = FullTextService(
        articles=articles,
        pages=_Pages("<html><body><p>로그인이 필요합니다.</p></body></html>"),
        errors=ErrorRecorder(ctx.log),
    )


@when("전문을 가져온다")
def _fulltext(ctx):
    assert ctx.service.ensure(ctx.article).state == "failed"


@then(parsers.parse('오류 기록에 "{label}" 유형으로 글 제목과 이유와 주소가 남는다'))
def _fulltext_logged(ctx, label):
    (entry,) = entries(ctx.log, KIND_FULLTEXT)
    assert entry.source == "오류 글" and "본문을 찾지 못했습니다" in entry.message
    assert ctx.link in entry.detail and label == "전문 가져오기"


@given("모델이 쓸 수 없는 응답만 돌려준다")
def _bad_answers(ctx, tmp_path):
    ctx.env = LlmEnv(tmp_path)
    ctx.env.client.default = good("JSON이 아닌 응답")
    ctx.env.add_article(title="Bad answer")


@when("같은 글을 세 번 요약한다")
def _summarize_three(ctx):
    for _ in range(3):
        ctx.env.summarizer.run()


@then(
    parsers.parse('오류 기록에 "{label}" 유형으로 쓸 수 없는 응답과 원문 발췌로 확정한 것이 남는다')
)
def _summarize_logged(ctx, label):
    messages = {e.message for e in entries(ctx.env.error_log, KIND_SUMMARIZE)}
    assert "모델 응답을 쓸 수 없음(not_json)" in messages
    assert "번역하지 못해 원문 제목과 본문 발췌로 확정" in messages
    assert {e.source for e in entries(ctx.env.error_log, KIND_SUMMARIZE)} == {"Bad answer"}
    assert label == "요약"


@given("모델이 인증 오류로 호출에 실패한다")
def _auth_error(ctx, tmp_path):
    ctx.env = LlmEnv(tmp_path)
    ctx.env.client.default = failure(LlmErrorKind.UNAUTHORIZED, status=401)
    ctx.env.add_article()


@when("글을 요약한다")
def _summarize_once(ctx):
    ctx.env.summarizer.run()


@then(parsers.parse('오류 기록에 "{label}" 유형으로 모델 이름과 오류 분류와 HTTP 상태가 남는다'))
def _llm_logged(ctx, label):
    llm = entries(ctx.env.error_log, KIND_LLM)
    assert {e.source for e in llm} == {"model-a"} and llm[0].message == "unauthorized (HTTP 401)"
    assert label == "LLM 호출"
    assert any(
        "모델이 응답하지 않음" in e.message for e in entries(ctx.env.error_log, KIND_SUMMARIZE)
    )


@given("웹훅이 503으로 응답한다")
def _webhook_503(ctx, tmp_path):
    ctx.env = DeliveryEnv(tmp_path)
    ctx.env.add_ready_article()
    ctx.env.sender.will(webhook_url("rss"), SendResult(503))


@when("발송한다")
def _deliver(ctx):
    ctx.env.service.run()


@then(parsers.parse('오류 기록에 "{label}" 유형으로 웹훅 이름과 이유가 남는다'))
def _deliver_logged(ctx, label):
    (entry,) = entries(ctx.env.error_log, KIND_DELIVER)
    assert entry.source == "rss" and entry.message.startswith("발송하지 못함: ")
    assert "503" in entry.message and label == "발송"


@given("실행하면 예외가 나는 작업이 있다")
def _failing_job(ctx, tmp_path):
    db, clock = Database(tmp_path / "j.db"), FakeClock()
    ctx.log = ErrorLogRepository(db, clock)

    def boom():
        raise ValueError("터졌습니다")

    ctx.runner = JobRunner(
        jobs=[IntervalJob("summarize", boom, lambda: 60)],
        clock=clock,
        records=JobRunRepository(db, clock),
        timezone=lambda: clock.now().tzinfo,
        spawn=lambda fn: fn(),
        errors=ErrorRecorder(ctx.log),
    )


@when("작업이 실행된다")
def _run_job(ctx):
    assert ctx.runner.tick() == ["summarize"]


@then(parsers.parse('오류 기록에 "{label}" 유형으로 작업 이름과 예외 종류가 남는다'))
def _job_logged(ctx, label):
    (entry,) = entries(ctx.log, KIND_JOB)
    assert (entry.source, entry.message, entry.detail) == ("summarize", "ValueError", "터졌습니다")
    assert label == "작업 실행"


# ---------- 묶기 ----------


@given("같은 피드가 같은 이유로 세 번 실패했다")
def _three_times(ctx, tmp_path):
    db, ctx.clock = Database(tmp_path / "d.db"), FakeClock()
    ctx.log = ErrorLogRepository(db, ctx.clock)
    for _ in range(3):
        ctx.log.record(KIND_COLLECT, "피드", "시간 초과", "Timeout")
        ctx.clock.advance(minutes=30)


@then("오류 기록에는 한 줄이 있고 횟수는 3이다")
def _one_row(ctx):
    (entry,) = ctx.log.list()
    assert entry.count == 3 and entry.last_at > entry.first_at


@when("하루가 지나 같은 이유로 또 실패한다")
def _next_day(ctx):
    ctx.clock.advance(days=1)
    ctx.log.record(KIND_COLLECT, "피드", "시간 초과", "Timeout")


@then("오류 기록에는 두 줄이 있다")
def _two_rows(ctx):
    assert sorted(e.count for e in ctx.log.list()) == [1, 3]


@given("오류 기록을 남기려 하면 저장소가 실패한다")
def _broken_log(ctx, tmp_path):
    class Broken:
        def record(self, *args):
            raise RuntimeError("디스크가 가득 참")

    ctx.env = CollectEnv(tmp_path)
    ctx.env.service = CollectService(
        feeds=ctx.env.feeds,
        articles=ctx.env.articles,
        fetcher=ctx.env.fetcher,
        settings=ctx.env.settings,
        clock=ctx.env.clock,
        errors=ErrorRecorder(Broken()),
    )
    ctx.feed, ctx.url = ctx.env.add_feed()
    ctx.env.fetcher.fail(ctx.url, "Timeout")


@when("피드를 수집한다")
def _collect_broken(ctx):
    ctx.report = ctx.env.collect(ctx.feed)


@then("수집 결과에는 실패한 피드가 그대로 나오고 예외는 퍼지지 않는다")
def _not_broken(ctx):
    assert [reason for _, reason in ctx.report.failed] == ["Timeout"]


# ---------- 보관 ----------


@given("오류 기록 보관 기간은 기본 14일이다")
def _default_retention(ctx, tmp_path):
    ctx.env = CollectEnv(tmp_path)
    assert ctx.env.settings.snapshot().error_log_retention_days == 14


@given("20일 전, 10일 전, 오늘의 오류 기록이 있다")
def _old_records(ctx):
    clock, log = ctx.env.clock, ctx.env.error_log
    clock.advance(days=-20)
    log.record(KIND_COLLECT, "옛날", "오래됨")
    clock.advance(days=10)
    log.record(KIND_COLLECT, "열흘", "최근")
    clock.advance(days=10)
    log.record(KIND_COLLECT, "오늘", "방금")


@when("보관 기간 정리를 한다")
def _retention(ctx):
    RetentionService(
        articles=ctx.env.articles,
        settings=ctx.env.settings,
        clock=ctx.env.clock,
        error_log=ctx.env.error_log,
    ).run()


@then("20일 전 기록만 지워진다")
def _only_old_gone(ctx):
    assert {e.source for e in ctx.env.error_log.list()} == {"열흘", "오늘"}


@when(parsers.parse('오류 기록 보관 기간을 "{value}"으로 바꾼다'))
def _set_retention(ctx, tmp_path, value):
    ctx.env = CollectEnv(tmp_path)
    ctx.result = ctx.env.settings.update({"error_log_retention_days": value})


@then("저장되고 30일이 된다")
def _saved(ctx):
    assert not ctx.result.errors and ctx.env.settings.snapshot().error_log_retention_days == 30


@then("거부되고 14일 그대로다")
def _refused(ctx):
    assert ctx.result.errors and ctx.env.settings.snapshot().error_log_retention_days == 14


# ---------- 상태 화면 ----------


@pytest.fixture
def world(tmp_path):
    with open_world(tmp_path) as opened:
        yield opened


def log_of(world):
    return ErrorLogRepository(world.parts.db, world.parts.clock)


def kinds_in(html):
    return re.findall(r'<li class="error-row" data-kind="(\w+)"', html)


@given("수집, 발송, 요약 오류가 각각 기록되어 있다")
def _three_kinds(world):
    log, clock = log_of(world), world.parts.clock
    log.record(KIND_COLLECT, "피드 A", "시간 초과", "Timeout")
    clock.advance(minutes=1)
    log.record(KIND_DELIVER, "rss", "발송하지 못함: HTTP 503")
    clock.advance(minutes=1)
    log.record(KIND_SUMMARIZE, "글 제목", "모델이 응답하지 않음")


@given("많이 발생한 수집 오류와 최근에 한 번 난 발송 오류와 오래전에 한 번 난 요약 오류가 있다")
def _count_case(world):
    log, clock = log_of(world), world.parts.clock
    log.record(KIND_SUMMARIZE, "글", "오래된 요약 오류")
    clock.advance(minutes=1)
    for _ in range(5):
        log.record(KIND_COLLECT, "피드", "자주 나는 오류")
    clock.advance(minutes=1)
    log.record(KIND_DELIVER, "rss", "방금 난 발송 오류")


@when("상태 화면을 연다")
def _status(world, ctx):
    ctx.html = world.get("/status").text


@when(parsers.parse('상태 화면에서 "{label}" 유형만 연다'))
def _status_kind(world, ctx, label):
    ctx.html = world.get(f"/status?kind={KIND_DELIVER}").text


@when(parsers.parse('상태 화면을 "{sort}"으로 연다'))
def _status_sort(world, ctx, sort):
    ctx.html = world.get(f"/status?sort={sort}").text


@when("상태 화면을 이상한 유형과 정렬 값으로 연다")
def _status_weird(world, ctx):
    ctx.html = world.get("/status?kind=%27%3Bdrop&sort=1%3B--").text


@then("유형 칩에 전체와 유형별 개수가 나오고 오류 줄은 최근 것부터 나온다")
def _chips(ctx):
    assert re.search(r'href="/status\?sort=recent#error-log">전체 <b>3</b>', ctx.html)
    assert re.search(r'kind=collect&amp;sort=recent#error-log">피드 수집 <b>1</b>', ctx.html)
    assert "발송 <b>1</b>" in ctx.html and "요약 <b>1</b>" in ctx.html
    assert "LLM 호출 <b>0</b>" in ctx.html
    assert kinds_in(ctx.html) == [KIND_SUMMARIZE, KIND_DELIVER, KIND_COLLECT]


@then("발송 오류 줄만 나오고 고른 유형 칩이 표시된다")
def _only_deliver(ctx):
    assert kinds_in(ctx.html) == [KIND_DELIVER]
    assert re.search(r'chip-link on" href="/status\?kind=deliver', ctx.html)


@then(parsers.re(r"오류 줄은 (?P<order>.+) 순서로 나온다"))
def _order(ctx, order):
    names = {"수집": KIND_COLLECT, "발송": KIND_DELIVER, "요약": KIND_SUMMARIZE}
    assert kinds_in(ctx.html) == [names[n.strip()] for n in order.split(",")]


@then("전체 오류가 최근순으로 나온다")
def _all_recent(ctx):
    assert kinds_in(ctx.html) == [KIND_SUMMARIZE, KIND_DELIVER, KIND_COLLECT]
    assert re.search(r'chip-link on" href="/status\?sort=recent#error-log">전체', ctx.html)


@then('"기록된 오류가 없습니다"가 보이고 목록 복사 버튼은 비활성이다')
def _empty(ctx):
    assert "기록된 오류가 없습니다" in ctx.html
    assert re.search(r"data-copy-all=\"\[data-error-list\]\" disabled", ctx.html)


@then("오류 줄마다 유형, 대상, 메시지, 시각, 횟수가 든 복사용 글자가 있다")
def _copy_text(ctx):
    copies = re.findall(r'<li class="error-row"[^>]*data-copy="([^"]*)"', ctx.html)
    assert len(copies) == 3
    deliver = next(c for c in copies if "[발송]" in c)
    assert "[발송] rss" in deliver and "발송하지 못함: HTTP 503" in deliver and "1회" in deliver
    assert re.search(r"\d\d-\d\d \d\d:\d\d:\d\d", deliver)


@then("화면 스크립트는 줄 복사와 목록 복사를 클립보드에 쓰고 쓸 수 없으면 대체 방법을 쓴다")
def _copy_script(world):
    js = world.client.get("/static/app.js").text
    assert "navigator.clipboard.writeText" in js and 'execCommand("copy")' in js
    assert "[data-copy-row]" in js and "[data-copy-all]" in js


@then("오류 기록 구역은 접고 펼 수 있고 보관 기간 안내가 있다")
def _section(ctx):
    section = ctx.html.split('id="error-log"')[1].split("</section>")[0]
    assert '<details class="acc-limit" open>' in section and "보관 기간" in section
