"""43_activity_log.feature: 작업 이력."""

import re
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, then, when

from rss_hub.domain.activity_log import OUTCOME_FAIL, OUTCOME_OK
from rss_hub.domain.error_log import (
    KIND_COLLECT,
    KIND_DELIVER,
    KIND_FULLTEXT,
    KIND_LLM,
    KIND_SUMMARIZE,
)
from rss_hub.services.activity_log import ActivityRecorder
from rss_hub.services.collect import CollectService
from rss_hub.services.fulltext import FullTextService
from rss_hub.services.ports import LlmErrorKind, PageResult, SendResult
from rss_hub.services.retention import RetentionService
from rss_hub.storage.activity_log import ActivityLogRepository
from rss_hub.storage.articles import ArticleRepository, NewArticle
from rss_hub.storage.database import Database
from rss_hub.storage.feeds import FeedRepository
from tests.bdd.binding import bind
from tests.fakes.clock import FakeClock
from tests.fakes.collect_env import CollectEnv
from tests.fakes.delivery_env import DeliveryEnv, webhook_url
from tests.fakes.entries import entry
from tests.fakes.llm_client import failure, good
from tests.fakes.llm_env import LlmEnv
from tests.fakes.viewer_world import open_world

bind(globals(), "43_activity_log.feature", [f"ACT-{n:02d}" for n in range(1, 19)])

KIND_NAMES = {"수집": KIND_COLLECT, "발송": KIND_DELIVER, "요약": KIND_SUMMARIZE}


@pytest.fixture
def ctx():
    return SimpleNamespace(env=None, feed=None, report=None, html="", fulltext=None, articles=())


def rows(log, kind="", outcome=""):
    return log.list(kind=kind, outcome=outcome)


# ---------- 기록: 수집 ----------


@given("새 글이 있는 피드와 새 글이 없는 피드가 있다")
def _one_changed(ctx, tmp_path):
    ctx.env = CollectEnv(tmp_path)
    changed, changed_url = ctx.env.add_feed(1)
    quiet, quiet_url = ctx.env.add_feed(2)
    ctx.feeds = (changed, quiet)
    ctx.env.fetcher.serve(changed_url, [entry()])
    ctx.env.fetcher.serve(quiet_url, [])


@when("두 피드를 수집한다")
def _collect_two(ctx):
    ctx.report = ctx.env.collect(*ctx.feeds)


@then(parsers.parse('작업 이력에 "{label}" 유형으로 "{summary}" 요약이 성공으로 남는다'))
def _collect_summary(ctx, label, summary):
    found = [e for e in rows(ctx.env.activity, KIND_COLLECT) if e.message == summary]
    assert len(found) == 1 and found[0].outcome == OUTCOME_OK and label == "피드 수집"


@then("새 글이 있는 피드 줄만 성공으로 남고 변화 없는 피드 줄은 없다")
def _only_changed(ctx):
    feed_rows = [e for e in rows(ctx.env.activity, KIND_COLLECT) if e.source != "수집 실행"]
    assert [(e.source, e.outcome) for e in feed_rows] == [("피드1", OUTCOME_OK)]
    assert feed_rows[0].message == "새 글 1개"


@given("시간 초과로 실패하는 피드가 있다")
def _failing_feed(ctx, tmp_path):
    ctx.env = CollectEnv(tmp_path)
    ctx.feeds = (ctx.env.add_feed()[0],)
    ctx.env.fetcher.fail(ctx.env.feeds.get(ctx.feeds[0]).url, "Timeout")


@when("수집한다")
def _collect_one(ctx):
    ctx.env.collect(*ctx.feeds)


@then(parsers.parse('작업 이력에 실패한 피드 줄과 "{summary}" 요약이 남는다'))
def _collect_failed(ctx, summary):
    collected = rows(ctx.env.activity, KIND_COLLECT)
    fails = [e for e in collected if e.outcome == OUTCOME_FAIL]
    assert {e.source for e in fails} == {"피드1", "수집 실행"}
    assert any(e.source == "수집 실행" and e.message == summary for e in collected)


# ---------- 기록: 요약과 LLM 호출 ----------


@given("영문 글 하나가 요약을 기다린다")
def _one_article(ctx, tmp_path):
    ctx.env = LlmEnv(tmp_path)
    ctx.env.add_article(title="Apple unveils")


@given("모델이 쓸 수 없는 응답만 돌려준다")
def _bad_answers(ctx, tmp_path):
    ctx.env = LlmEnv(tmp_path)
    ctx.env.client.default = good("JSON이 아닌 응답")
    ctx.env.add_article(title="Bad answer")


@given("첫 모델은 호출에 실패하고 둘째 모델은 성공한다")
def _first_fails(ctx, tmp_path):
    ctx.env = LlmEnv(tmp_path)
    ctx.env.client.will("model-a", failure(LlmErrorKind.UNAVAILABLE, 503))
    ctx.env.client.will("model-b", good())
    ctx.env.add_article()


@when("글을 요약한다")
def _summarize(ctx):
    ctx.env.summarizer.run()


@then(parsers.parse('작업 이력에 "{label}" 유형으로 글 제목과 사용한 모델이 성공으로 남는다'))
def _summarize_ok(ctx, label):
    (found,) = rows(ctx.env.activity, KIND_SUMMARIZE, OUTCOME_OK)
    assert found.source == "Apple unveils" and "model-a" in found.message and label == "요약"


@then(parsers.parse('작업 이력에 "{label}" 유형으로 글 제목과 이유가 실패로 남는다'))
def _summarize_failed(ctx, label):
    (found,) = rows(ctx.env.activity, KIND_SUMMARIZE, OUTCOME_FAIL)
    assert found.source == "Bad answer" and "모델 응답을 쓸 수 없음(not_json)" in found.message
    assert label == "요약"


@then(parsers.parse('작업 이력에 "{label}" 유형으로 첫 모델의 실패와 둘째 모델의 성공이 남는다'))
def _llm_rows(ctx, label):
    calls = rows(ctx.env.activity, KIND_LLM)
    assert {(e.source, e.outcome) for e in calls} == {
        ("model-a", OUTCOME_FAIL),
        ("model-b", OUTCOME_OK),
    }
    assert label == "LLM 호출"


# ---------- 기록: 발송 ----------


@given("웹훅 하나는 성공하고 다른 웹훅은 503으로 응답하는 글이 있다")
def _two_webhooks(ctx, tmp_path):
    ctx.env = DeliveryEnv(tmp_path)
    ctx.env.add_topic("영화", ("영화",), webhook="ott")
    ctx.env.add_ready_article(title="영화 소식", topics=("영화",))
    ctx.env.sender.will(webhook_url("ott"), SendResult(503))


@when("발송한다")
def _deliver(ctx):
    ctx.env.service.run()


@then(parsers.parse('작업 이력에 "{label}" 유형으로 웹훅 이름과 함께 성공 줄과 실패 줄이 남는다'))
def _deliver_rows(ctx, label):
    sent = rows(ctx.env.activity, KIND_DELIVER, OUTCOME_OK)
    failed = rows(ctx.env.activity, KIND_DELIVER, OUTCOME_FAIL)
    assert [e.source for e in sent] == ["rss"] and [e.source for e in failed] == ["ott"]
    assert label == "발송"


# ---------- 기록: 전문 ----------


@dataclass
class _Pages:
    html: dict[str, str]
    calls: list[str] = field(default_factory=list)

    def fetch_page(self, url):
        return PageResult(self.html[url], url)


GOOD_PAGE = (
    "<html><body><article>" + "<p>" + "본문 문장입니다. " * 40 + "</p></article></body></html>"
)
BAD_PAGE = "<html><body><p>로그인이 필요합니다.</p></body></html>"


@given("전문을 가져올 수 있는 글과 가져올 수 없는 글이 있다")
def _two_pages(ctx, tmp_path):
    db, clock = Database(tmp_path / "x.db"), FakeClock()
    feed = FeedRepository(db, clock).add("https://a.example.com/rss", "A")
    articles = ArticleRepository(db, clock)
    ctx.activity = ActivityLogRepository(db, clock)
    links = {"좋은 글": "https://a.example.com/good", "나쁜 글": "https://a.example.com/bad"}
    ctx.articles = [
        articles.get(
            articles.add(
                NewArticle(feed, title, title, link, "<p>RSS</p>", "", clock.now(), "2026-10-16")
            )
        )
        for title, link in links.items()
    ]
    ctx.fulltext = FullTextService(
        articles=articles,
        pages=_Pages({links["좋은 글"]: GOOD_PAGE, links["나쁜 글"]: BAD_PAGE}),
        activity=ActivityRecorder(ctx.activity),
    )


@when("두 글의 전문을 가져온다")
def _fetch_both(ctx):
    for article in ctx.articles:
        ctx.fulltext.ensure(article)


@then(parsers.parse('작업 이력에 "{label}" 유형으로 글 제목과 함께 성공 줄과 실패 줄이 남는다'))
def _fulltext_rows(ctx, label):
    sent = rows(ctx.activity, KIND_FULLTEXT, OUTCOME_OK)
    failed = rows(ctx.activity, KIND_FULLTEXT, OUTCOME_FAIL)
    assert [e.source for e in sent] == ["좋은 글"] and [e.source for e in failed] == ["나쁜 글"]
    assert label == "전문 가져오기"


# ---------- 기록: 실패해도 본래 일은 계속 ----------


@given("작업 이력을 남기려 하면 저장소가 실패한다")
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
        activity=ActivityRecorder(Broken()),
    )
    feed, url = ctx.env.add_feed()
    ctx.feeds = (feed,)
    ctx.env.fetcher.serve(url, [entry()])


@when("피드를 수집한다")
def _collect_broken(ctx):
    ctx.report = ctx.env.collect(*ctx.feeds)


@then("수집 결과에는 새 글이 그대로 나오고 예외는 퍼지지 않는다")
def _not_broken(ctx):
    assert ctx.report.added == 1 and ctx.report.failed == ()


# ---------- 보관 ----------


@given("20일 전, 10일 전, 오늘의 작업 이력이 있다")
def _old_records(ctx, tmp_path):
    ctx.env = CollectEnv(tmp_path)
    clock, log = ctx.env.clock, ctx.env.activity
    clock.advance(days=-20)
    log.record(KIND_COLLECT, OUTCOME_OK, "옛날", "오래됨")
    clock.advance(days=10)
    log.record(KIND_COLLECT, OUTCOME_OK, "열흘", "최근")
    clock.advance(days=10)
    log.record(KIND_COLLECT, OUTCOME_OK, "오늘", "방금")


@when("보관 기간 정리를 한다")
def _retention(ctx):
    RetentionService(
        articles=ctx.env.articles,
        settings=ctx.env.settings,
        clock=ctx.env.clock,
        activity=ctx.env.activity,
    ).run()


@then("20일 전 작업 이력만 지워진다")
def _only_old_gone(ctx):
    assert {e.source for e in ctx.env.activity.list()} == {"열흘", "오늘"}


# ---------- 상태 화면 ----------


@pytest.fixture
def world(tmp_path):
    with open_world(tmp_path) as opened:
        yield opened


def log_of(world):
    return ActivityLogRepository(world.parts.db, world.parts.clock)


def kinds_in(html):
    return re.findall(r'<li class="activity-row" data-kind="(\w+)"', html)


@when("상태 화면을 연다")
def _status(world, ctx):
    ctx.html = world.get("/status").text


@then('탭은 "오류 기록", "작업 이력", "변경 이력" 순서이고 작업 이력 구역이 있다')
def _tab_order(ctx):
    tabs = re.findall(r'role="tab" href="#(error-log|activity-log|panel-history)"', ctx.html)
    assert tabs == ["error-log", "activity-log", "panel-history"]
    assert 'id="activity-log"' in ctx.html


@given("수집 성공, 발송 실패, 요약 성공 작업 이력이 차례로 기록되어 있다")
def _three_rows(world):
    log, clock = log_of(world), world.parts.clock
    log.record(KIND_COLLECT, OUTCOME_OK, "피드 A", "새 글 1개")
    clock.advance(minutes=1)
    log.record(KIND_DELIVER, OUTCOME_FAIL, "rss", "발송하지 못함: HTTP 503")
    clock.advance(minutes=1)
    log.record(KIND_SUMMARIZE, OUTCOME_OK, "글 제목", "요약 완료(model-a)")


@then("작업 이력 칩에 전체와 유형별 개수와 결과별 개수가 나오고 줄은 최근 것부터 나온다")
def _chips(ctx):
    assert re.search(r'href="/status\?asort=recent#activity-log">전체 <b>3</b>', ctx.html)
    assert "피드 수집 <b>1</b>" in ctx.html and "발송 <b>1</b>" in ctx.html
    assert "LLM 호출 <b>0</b>" in ctx.html
    assert "성공 <b>2</b>" in ctx.html and "실패 <b>1</b>" in ctx.html
    assert kinds_in(ctx.html) == [KIND_SUMMARIZE, KIND_DELIVER, KIND_COLLECT]


@when(parsers.parse('상태 화면에서 작업 이력의 "{label}" 유형만 연다'))
def _status_kind(world, ctx, label):
    ctx.html = world.get(f"/status?akind={KIND_NAMES[label]}").text


@then("발송 작업 이력 줄만 나오고 고른 유형 칩이 표시된다")
def _only_deliver(ctx):
    assert kinds_in(ctx.html) == [KIND_DELIVER]
    assert re.search(r'chip-link on" href="/status\?akind=deliver', ctx.html)


@when(parsers.parse('상태 화면에서 작업 이력의 "{label}" 결과만 연다'))
def _status_outcome(world, ctx, label):
    ctx.html = world.get(f"/status?aresult={OUTCOME_FAIL}").text


@then("실패한 작업 이력 줄만 나오고 고른 결과 칩이 표시된다")
def _only_failed(ctx):
    assert kinds_in(ctx.html) == [KIND_DELIVER]
    assert re.search(r'chip-link on" href="/status\?aresult=fail', ctx.html)


@when(parsers.parse('상태 화면에서 작업 이력을 "{sort}"으로 연다'))
def _status_sort(world, ctx, sort):
    ctx.html = world.get(f"/status?asort={sort}").text


@when("상태 화면을 이상한 작업 이력 값으로 연다")
def _status_weird(world, ctx):
    ctx.html = world.get("/status?akind=%27%3Bdrop&aresult=x&asort=1%3B--").text


@then(parsers.re(r"작업 이력 줄은 (?P<order>.+) 순서로 나온다"))
def _order(ctx, order):
    names = {**KIND_NAMES}
    assert kinds_in(ctx.html) == [names[n.strip()] for n in order.split(",")]


@then('"기록된 작업이 없습니다"가 보이고 작업 이력 목록 복사 버튼은 비활성이다')
def _empty(ctx):
    assert "기록된 작업이 없습니다" in ctx.html
    assert re.search(r'data-copy-all="\[data-activity-list\]" disabled', ctx.html)


@then("작업 이력 줄마다 유형, 결과, 대상, 메시지, 시각이 든 복사용 글자가 있다")
def _copy_text(ctx):
    copies = re.findall(r'<li class="activity-row"[^>]*data-copy="([^"]*)"', ctx.html)
    assert len(copies) == 3
    deliver = next(c for c in copies if "[발송]" in c)
    assert "[발송] rss" in deliver and "실패" in deliver and "발송하지 못함: HTTP 503" in deliver
    assert re.search(r"\d\d-\d\d \d\d:\d\d:\d\d", deliver)


@when("설정 화면을 연다")
def _open_settings(world, ctx):
    ctx.html = world.get("/settings").text


@then("기록 보관 기간 설정 하나가 있고 오류 기록과 작업 이력에 쓴다고 안내한다")
def _one_retention(ctx):
    assert ctx.html.count('name="error_log_retention_days"') == 1
    assert "기록 보관 기간(일)" in ctx.html and "작업 이력" in ctx.html
