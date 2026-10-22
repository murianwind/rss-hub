"""24_benchmark_insight.feature: 점수 풀이, 실패 원인, 진행 상태, 체인 편집."""

import re
from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, then, when

from rss_hub.domain.benchmark import SAMPLES
from rss_hub.domain.models import FreeModel
from rss_hub.services.model_benchmark import CANCEL_POLL_SECONDS
from rss_hub.services.ports import LlmErrorKind
from tests.bdd.binding import bind
from tests.fakes.llm_client import failure, reply
from tests.fakes.models_env import Env
from tests.keywords.models import (
    call_result,
    open_model_world,
    post,
    progress,
    record_run,
    scan,
)
from tests.keywords.page import text_of

bind(globals(), "24_benchmark_insight.feature", [f"BMK-{n:02d}" for n in range(1, 12)])

REASON_TEXT = {"요청 한도 초과": "rate_limited", "응답이 잘림": "truncated"}


@pytest.fixture
def world(tmp_path):
    with open_model_world(tmp_path) as opened:
        yield opened


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


@pytest.fixture
def ctx():
    return SimpleNamespace(html="", response=None, data=None, outcome=None, run_id=None)


def line_of(html, model):
    """무료 모델 목록에서 모델 하나의 줄."""
    rows = html.split('<li class="check model-row"')[1:]
    return next(
        r.split("data-chain-add")[0] for r in rows if f'data-model="{model}"' in r.split(">")[0]
    )


CATALOG_STEP = r'모델 "(?P<first>[^"]+)"와 "(?P<second>[^"]+)"가 무료 목록에 있고 '
CATALOG_STEP += r'체인은 "(?P<chain>[^"]+)"이다'


@given(parsers.re(CATALOG_STEP))
def _catalog(world, first, second, chain):
    world.llm.free_models = [FreeModel(m, m, 32768, True) for m in (first, second)]
    scan(world)
    world.settings.update({"model_chain": chain})


@given(parsers.parse('모델 "{model}"의 문맥 길이는 262144이고 JSON을 지원한다'))
def _big_model(world, model):
    world.llm.free_models = [FreeModel(model, model, 262144, True)]
    scan(world)


@given(
    parsers.parse(
        '"{model}"가 시험 글 6개 중 5개를 통과했고 한국어 제목은 5개 모두, 주제 판정은 4개가 맞았다'
    )
)
def _five_of_six(world, model):
    results = [call_result(topic=index != 0) for index in range(5)]
    results.append(call_result(ok=False, error="truncated"))
    record_run(world, model, results)


@given(
    parsers.parse('"{model}"의 시험 호출 6번 중 2번은 응답 형식이 잘렸고 4번은 요청 한도 초과였다')
)
def _mixed_failures(world, model):
    results = [call_result(ok=False, error="truncated")] * 2
    results += [call_result(ok=False, error="rate_limited")] * 4
    record_run(world, model, results)


@given(parsers.parse('"{model}"의 시험 호출 6번이 모두 요청 한도 초과였다'))
def _all_limited(world, model):
    record_run(world, model, [call_result(ok=False, error="rate_limited")] * 6)


@given(parsers.parse('벤치마크가 "{model}"를 시험하는 중에 2번째 호출까지 끝났다'))
def _two_done(world, model):
    record_run(world, model, [call_result(), call_result()], finish=False)


@given(parsers.parse('벤치마크가 "{model}"를 시험하는 중에 첫 호출이 응답 형식 오류로 끝났다'))
def _first_failed(world, model):
    record_run(world, model, [call_result(ok=False, error="not_json")], finish=False)


@given("벤치마크가 실행 중이다")
def _running(world):
    record_run(world, "model-a", [call_result()], finish=False)


@when("모델 화면을 연다")
def _open(world, ctx):
    ctx.response = world.client.get("/models")
    ctx.html = ctx.response.text
    assert ctx.response.status_code == 200


@when("진행 상태를 요청한다")
def _progress(world, ctx):
    ctx.data = progress(world)


@then(parsers.parse('"{model}" 줄에 "{a}"와 "{b}"와 "{c}"와 "{d}"이 보인다'))
@then(parsers.parse('"{model}" 줄에 "{a}"와 "{b}"와 "{c}"와 "{d}"가 보인다'))
def _score_line(ctx, model, a, b, c, d):
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", line_of(ctx.html, model)))
    for part in (a, b, c, d):
        assert part in text, (part, text)


@then("점수 보는 법 설명에 성공률 50, 한국어 제목 20, 주제 판정 20, 속도 10이 적혀 있다")
def _legend(ctx):
    legend = text_of(ctx.response)
    assert "점수 보는 법" in legend
    assert "성공률 50" in legend and "한국어 제목 20" in legend
    assert "주제 판정 20" in legend and "속도 10" in legend


@then(
    parsers.parse(
        '"{model}"의 실패 원인으로 "요청 한도 초과" 4회와 "응답이 잘림" 2회가 풀이와 함께 보인다'
    )
)
def _failure_lines(ctx, model):
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", line_of(ctx.html, model)))
    assert "요청 한도 초과 4회" in text and "응답이 잘림 2회" in text
    assert "모델 품질과는 무관" in text  # 한도 초과 풀이
    assert "글자 수 한도" in text  # 잘림 풀이


@then(parsers.parse('"{model}"는 "측정 못 함"으로 표시되고 "0.0점"은 보이지 않는다'))
def _unmeasured(ctx, model):
    row = line_of(ctx.html, model)
    assert "측정 못 함" in row and "0.0점" not in row


@then(parsers.parse('추천에서 "{model}"는 빠진다'))
def _not_recommended(ctx, model):
    section = ctx.html.split("<h2>추천</h2>")[1] if "<h2>추천</h2>" in ctx.html else ""
    assert model not in section


@then(parsers.parse('"{model}" 줄에 "입력 한도 262K 토큰"과 "JSON 응답 지원"이 보인다'))
def _context(ctx, model):
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", line_of(ctx.html, model)))
    assert "입력 한도 262K 토큰" in text and "JSON 응답 지원" in text


@then("입력 한도가 무엇인지 설명이 있다")
def _context_legend(ctx):
    assert "한 번에 읽을 수 있는 글의 최대 길이" in text_of(ctx.response)


@then("진행 상태는 실행 중이고 전체 6건 중 2건 완료이다")
def _running_state(ctx):
    assert (ctx.data["running"], ctx.data["done"], ctx.data["total"]) == (True, 2, 6)


def cells_of(ctx, model):
    return next(m for m in ctx.data["models"] if m["model"] == model)["cells"]


@then(parsers.parse('"{model}"의 칸은 성공 2칸, 진행 중 1칸, 대기 3칸이다'))
def _cell_states(ctx, model):
    states = [cell["state"] for cell in cells_of(ctx, model)]
    assert states == ["ok", "ok", "running", "pending", "pending", "pending"]


@then("각 칸에는 시험 글 제목이 있고 끝난 칸에는 응답 시간이 있다")
def _cell_details(ctx):
    cells = cells_of(ctx, "model-a")
    assert [c["title"] for c in cells] == [s.title for s in SAMPLES]
    assert cells[0]["latency_ms"] == 2000 and cells[2]["latency_ms"] is None


@then(parsers.parse('"{model}"의 첫 칸은 실패이고 이유로 "응답이 JSON이 아님"이 보인다'))
def _first_cell_failed(ctx, model):
    first = cells_of(ctx, model)[0]
    assert first["state"] == "failed" and "응답이 JSON이 아님" in first["reason"]


@then("진행 패널에 진행 상태 주소가 있고 새로 고침 메타 태그는 없다")
def _panel(ctx):
    assert "data-bench-progress" in ctx.html and 'data-url="/models/benchmark/progress"' in ctx.html
    assert 'http-equiv="refresh"' not in ctx.html


# ---------- 서비스: 한도 초과 재시도 ----------


def limited():
    return failure(LlmErrorKind.RATE_LIMITED, 429)


def good_answers(title="한국어 제목"):
    return [reply(title, "요약입니다.", topics=[1] if s.expects_topic else []) for s in SAMPLES]


@given(parsers.parse('"{model}"는 처음 두 호출이 요청 한도 초과이고 다시 시험하면 모두 통과한다'))
def _limited_then_good(env, model):
    # 한도 초과는 게이트웨이가 한 번 더 시도하므로 시험 글 하나가 응답 두 번을 쓴다
    env.client.will(model, *[limited() for _ in range(4)], *good_answers())


@given(parsers.parse('"{model}"는 모두 통과한다'))
def _all_good(env, model):
    env.client.will(model, *good_answers())


@given(parsers.parse('"{model}"는 언제나 요청 한도 초과이다'))
def _always_limited(env, model):
    env.client.will(model, *[limited() for _ in range(24)])


@when(parsers.re(r'"(?P<first>[^"]+)"와 "(?P<second>[^"]+)"를 벤치마크한다'))
def _bench_two(env, ctx, first, second):
    ctx.run_id = env.models.start_run(12, [first, second])
    ctx.outcome = env.benchmark(real_time=True).run(ctx.run_id, [first, second])


@when(parsers.re(r'"(?P<model>[^"]+)"를 벤치마크한다'))
def _bench_one(env, ctx, model):
    ctx.run_id = env.models.start_run(6, [model])
    ctx.outcome = env.benchmark(real_time=True).run(ctx.run_id, [model])


@then(parsers.parse('시험 순서는 "{later}"가 먼저이고 "{first}"는 한 번 기다린 뒤 다시 시험한다'))
def _order(env, later, first):
    called = [c.model for c in env.client.calls]
    # a가 시험 글 두 개에서 한도에 걸린 뒤(글마다 두 번 시도) b가 6번, 그 다음 a가 다시 6번
    assert called[:4] == [first] * 4
    assert called[4:10] == [later] * 6 and called[10:] == [first] * 6
    assert env.sleeps_log.count(CANCEL_POLL_SECONDS) >= 60  # 60초를 1초씩 나누어 기다린다


@then(parsers.parse('"{model}"는 두 번째 시험의 결과로 점수가 매겨진다'))
def _second_result(env, ctx, model):
    score = next(s for s in ctx.outcome.scores if s.model == model)
    assert (score.calls, score.ok) == (6, 6)
    calls = [c for c in env.models.calls(ctx.run_id) if c.model == model]
    assert [c.state for c in calls] == ["ok"] * 6


@then(parsers.parse('"{model}"는 호출 2번만 하고 나머지 칸은 건너뜀으로 남는다'))
def _skipped(env, ctx, model):
    assert len(env.client.calls) == 8  # 첫 시험 글 2개 + 재시험 글 2개, 글마다 두 번 시도
    calls = [c for c in env.models.calls(ctx.run_id) if c.model == model]
    assert [c.state for c in calls] == [
        "failed",
        "failed",
        "skipped",
        "skipped",
        "skipped",
        "skipped",
    ]


@then(parsers.parse('벤치마크는 끝났고 "{model}"는 측정 못 함이다'))
def _finished_unmeasured(env, ctx, model):
    score = next(s for s in ctx.outcome.scores if s.model == model)
    assert score.ok == 0 and set(score.errors) == {"rate_limited"}
    assert env.models.latest_run().done == 6


# ---------- 체인 편집 ----------


@then("체인 목록의 항목과 무료 모델 목록의 항목은 끌 수 있고 모델 이름을 갖고 있다")
def _draggable(ctx):
    chain = re.findall(r'<li class="chain-item" draggable="true" data-model="([^"]+)"', ctx.html)
    catalog = re.findall(
        r'<li class="check model-row" draggable="true" data-model="([^"]+)"', ctx.html
    )
    assert chain == ["model-a"]
    assert catalog == ["model-a", "model-b"]


@then("체인 저장 양식은 체인 순서대로 모델을 보내고 확인 창을 거친다")
def _chain_form(ctx):
    start = ctx.html.index('action="/models/apply"')
    tag = ctx.html[ctx.html.rindex("<form", 0, start) : ctx.html.index(">", start)]
    assert "data-confirm=" in tag
    form = ctx.html[start : ctx.html.index("</form>", start)]
    assert 'name="chain" value="model-a"' in form and 'name="confirm" value="yes"' in form


@when(parsers.parse('체인을 "{first}"와 "{second}" 순서로 저장한다'))
def _save_chain(world, ctx, first, second):
    ctx.response = post(world, "/models/apply", {"chain": [first, second], "confirm": "yes"})


@then(parsers.parse('모델 체인은 "{first}", "{second}" 순서가 된다'))
def _chain_saved(world, ctx, first, second):
    assert ctx.response.status_code == 303
    assert world.settings.snapshot().model_chain == (first, second)
