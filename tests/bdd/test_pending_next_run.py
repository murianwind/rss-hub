"""41_pending_next_run.feature: 대기 글 목록과 다음 실행 시각."""

import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, then, when

from rss_hub.domain.jobs import next_interval_run, next_slot_start
from rss_hub.services.deliver import DeliveryService  # noqa: F401  (발송 기록 시험의 대상)
from rss_hub.storage.deliveries import DeliveryRepository
from tests.bdd.binding import bind
from tests.fakes.viewer_world import open_world

bind(globals(), "41_pending_next_run.feature", [f"PND-{n:02d}" for n in range(1, 8)])

KST = timedelta(hours=9)


class Runner:
    """다음 실행 시각과 실행 중인 작업을 정해 주는 작업 실행기 대역."""

    def __init__(self, moments=None, running=()):
        self.moments = moments or {}
        self.running = set(running)

    def run_now(self, name):
        return "started"

    def progress_of(self, name):
        return None

    def next_run_of(self, name):
        return None if name in self.running else self.moments.get(name)


@pytest.fixture
def world(tmp_path):
    with open_world(tmp_path) as opened:
        yield opened


@pytest.fixture
def ctx():
    return SimpleNamespace(html="", got=None)


def section(html, heading):
    block = html.split(f'<h3 class="acc-sub">{heading}')[1]
    return block.split("</ul>")[0]


def titles(block):
    return re.findall(r'class="pending-title" title="([^"]*)"', block)


@when("상태 화면을 연다")
def _status(world, ctx):
    ctx.html = world.get("/status").text


# ---------- 요약 대기 목록 ----------


@given("요약 배치가 2건이고 요약을 기다리는 글이 오래된 재시도 글 하나와 새 글 세 개다")
def _batch_case(world):
    world.parts.settings.update({"summarize_batch": "2"})
    retry = world.article(title="오래된 재시도 글", minutes=-600)
    world.articles.bump_retry(retry)
    for n, minutes in enumerate((10, 20, 30), start=1):
        world.article(title=f"새 글 {n}", minutes=minutes)


@then("요약 대기 목록은 새 글이 먼저, 재시도 글이 맨 뒤 순서다")
def _order(ctx):
    assert titles(section(ctx.html, "요약 대기")) == [
        "새 글 1",
        "새 글 2",
        "새 글 3",
        "오래된 재시도 글",
    ]


@then('앞의 2건에만 "다음 차례" 표시가 있고 각 줄에 얼마나 기다렸는지 나온다')
def _marks(ctx):
    items = section(ctx.html, "요약 대기").split("<li")[1:]
    assert [("다음 차례" in item) for item in items] == [True, True, False, False]
    assert all("수집" in item for item in items)
    assert "요약을 1번 다시 시도했습니다" in items[3]


# ---------- 발송 대기 ----------


@given("발송을 시도했다가 HTTP 503으로 못 보낸 글과 아직 시도하지 않은 글이 있다")
def _delivery_case(world, ctx):
    failed = world.article(title="못 보낸 글", ko="못 보낸 글", summary="요약", status="ready")
    fresh = world.article(
        title="새로 대기한 글", ko="새로 대기한 글", summary="요약", status="ready"
    )
    assert fresh
    webhook = world.parts.settings.add_webhook("기본", "https://discord.com/api/webhooks/9/TOKEN")
    repo = DeliveryRepository(world.parts.db, world.parts.clock)
    from rss_hub.domain.routing import Target

    (delivery,) = repo.ensure(failed, [Target(webhook, "default")])
    repo.record_attempt_failure(delivery.id, "HTTP 503")
    repo.record_attempt_failure(delivery.id, "HTTP 503")


@then('못 보낸 글에는 "2번 시도했지만 보내지 못함: HTTP 503"이 나오고 새 글에는 나오지 않는다')
def _attempt_notes(ctx):
    items = section(ctx.html, "발송 대기").split("<li")[1:]
    by_title = {titles(item)[0]: item for item in items}
    assert "2번 시도했지만 보내지 못함: HTTP 503" in by_title["못 보낸 글"]
    assert "시도했지만" not in by_title["새로 대기한 글"]


# ---------- 많을 때 ----------


@given("요약을 기다리는 글이 25개 있다")
def _many(world):
    for n in range(25):
        world.article(title=f"대기 {n:02d}", minutes=n)


@then('요약 대기 목록에는 20개만 나오고 "20개만 표시"와 전체 개수 25개가 보인다')
def _many_result(ctx):
    block = section(ctx.html, "요약 대기")
    assert len(titles(block)) == 20
    assert "20개만 표시" in ctx.html.split('<h3 class="acc-sub">요약 대기')[1][:200]
    assert re.search(r"요약 대기 글.*?25개", ctx.html, re.S)


# ---------- 다음 실행 시각 ----------


def _set_runner(world, runner):
    world.client.app.state.runner = runner


@given("작업 실행기가 수집은 5분 뒤, 요약은 30초 뒤, 발송은 지금으로 알려 준다")
def _runner_times(world):
    now = world.parts.clock.now()
    _set_runner(
        world,
        Runner(
            {
                "collect": now + timedelta(minutes=5),
                "summarize": now + timedelta(seconds=30),
                "deliver": now,
            }
        ),
    )
    world.article(title="요약 대기 글")  # 요약 줄에 "한 번에 N건" 안내가 붙는 조건
    world.article(title="발송 대기 글", ko="발송 대기 글", summary="요약", status="ready")


def next_hint(html, name):
    row = html.split(f'data-run-row="{name}"')[1].split("</li>")[0]
    found = re.search(rf'data-next-run="{name}">([^<]*)<', row)
    return found.group(1) if found else None


@then('수집 줄에는 "5분 뒤", 요약 줄에는 "30초 뒤", 발송 줄에는 "곧"이 나온다')
def _times(ctx):
    assert "(5분 뒤)" in next_hint(ctx.html, "collect")
    assert "(30초 뒤)" in next_hint(ctx.html, "summarize") and "한 번에" in next_hint(
        ctx.html, "summarize"
    )
    assert "(곧)" in next_hint(ctx.html, "deliver")
    assert re.search(r"다음 실행 \d\d:\d\d:\d\d", next_hint(ctx.html, "collect"))


@given("작업 실행기가 요약을 실행 중이라고 알려 준다")
def _running(world):
    now = world.parts.clock.now()
    _set_runner(world, Runner({"summarize": now}, running=("summarize",)))


@then("요약 줄에는 다음 실행 시각이 없다")
def _no_summarize_time(ctx):
    assert next_hint(ctx.html, "summarize") is None


@given("작업 실행기가 없다")
def _no_runner(world):
    _set_runner(world, None)


@then("어느 줄에도 다음 실행 시각이 없다")
def _none(ctx):
    assert "data-next-run" not in ctx.html


# ---------- 계산 ----------


@given(parsers.parse("요약 간격이 {interval:d}초이고 마지막 시작이 {before:d}초 전이다"))
def _interval_case(ctx, interval, before):
    now = datetime(2026, 10, 27, 5, 0, 0, tzinfo=UTC)
    ctx.got = (next_interval_run(now, now - timedelta(seconds=before), interval) - now, now)


@then(parsers.parse("다음 실행은 {left:d}초 뒤다"))
def _interval_result(ctx, left):
    assert ctx.got[0] == timedelta(seconds=left)
    now = ctx.got[1]
    assert next_interval_run(now, None, 60) == now  # 한 번도 안 했으면 지금


@given(
    parsers.parse("수집 주기가 5분이고 지금이 한국 시각 {now}이며 마지막 실행한 슬롯은 {last}이다")
)
def _slot_case(ctx, now, last):
    hour, minute, *second = (int(x) for x in re.split(":", now))
    moment = datetime(2026, 10, 27, hour, minute, second[0] if second else 0, tzinfo=UTC)
    last_slot = None if last == "없음" else moment.replace(minute=int(last[-2:]), second=0)
    ctx.got = next_slot_start(moment, last_slot, 5)


@then(parsers.parse("다음 수집 슬롯은 {expected}이다"))
def _slot_result(ctx, expected):
    assert ctx.got.strftime("%H:%M") == expected
