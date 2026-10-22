"""26_models_screen_refine.feature: 잔여 사용량 새로고침, 벤치마크 중단, 결과 영역 통합."""

import re
from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, then, when

from rss_hub.domain.benchmark import SAMPLES
from rss_hub.services.ports import ServerUsage
from tests.bdd.binding import bind
from tests.keywords.models import call_result, open_model_world, post, record_run, scan
from tests.keywords.page import text_of

bind(globals(), "26_models_screen_refine.feature", [f"MDS-{n:02d}" for n in range(1, 10)])


@pytest.fixture
def world(tmp_path):
    with open_model_world(tmp_path) as opened:
        yield opened


@pytest.fixture
def ctx():
    return SimpleNamespace(html="", response=None, refreshed=None)


def usage_text(html):
    found = re.search(r"<b data-model-usage>([^<]+)</b>", html)
    return found.group(1) if found else None


def auto_value(world):
    state = world.client.get("/ui/state").json()["model_usage"]
    return f"{state['remaining']}/{state['cap']}"


@given(parsers.parse("서버는 오늘 {used:d}회 사용했다고 알린다"))
@when(parsers.parse("서버가 알리는 사용량이 {used:d}회로 바뀐다"))
def _server_says(world, used):
    world.llm.usage = ServerUsage(used=used, limit=1000)


@given("모델 화면을 한 번 열어 잔여 사용량을 불러왔다")
def _warm(world):
    assert usage_text(world.client.get("/models").text) == "967/1000"


@when("모델 화면을 연다")
def _open(world, ctx):
    ctx.response = world.client.get("/models")
    ctx.html = ctx.response.text
    assert ctx.response.status_code == 200


@then("모델 잔여 사용량 옆에 새로고침 버튼이 있다")
def _refresh_button(ctx):
    usage = ctx.html.split('class="model-usage"')[1].split("</span>")[0]
    assert 'data-action="refresh-model-usage"' in usage


@then(parsers.parse('화면의 자동 갱신 값은 아직 "{value}"이다'))
@then(parsers.parse('그 뒤의 자동 갱신 값도 "{value}"이다'))
def _auto_value(world, value):
    assert auto_value(world) == value


@when("잔여 사용량을 새로고침한다")
def _refresh(world, ctx):
    ctx.refreshed = post(world, "/ui/model-usage/refresh")
    assert ctx.refreshed.status_code == 200


@then(parsers.parse('새로고침 결과는 "{value}"이다'))
def _refreshed_value(ctx, value):
    body = ctx.refreshed.json()
    assert f"{body['remaining']}/{body['cap']}" == value


@given(parsers.parse('벤치마크를 "{model}" 하나로 시작했다'))
def _start(world, model):
    scan(world)
    response = post(world, "/models/benchmark", {"models": model})
    assert response.status_code == 303 and len(world.pending) == 1


@when("벤치마크를 중단한다")
def _cancel(world, ctx):
    ctx.response = post(world, "/models/benchmark/cancel")
    ctx.html = ctx.response.text


@when("대기 중이던 벤치마크 작업이 실행된다")
def _run_pending(world):
    world.pending.pop(0)()


@then(parsers.parse('벤치마크는 "{note}"로 멈춘 상태이다'))
def _stopped(world, note):
    run = world.models.latest_run()
    assert run.status == "interrupted" and run.note == note
    assert world.client.get("/models/benchmark/progress").json()["running"] is False


@then("모델 호출은 한 번도 없었다")
def _no_calls(world):
    assert world.llm.calls == []


@then("새 벤치마크를 다시 시작할 수 있다")
def _restart(world):
    response = post(world, "/models/benchmark", {"models": "model-b"})
    assert response.status_code == 303 and len(world.pending) == 1


@then(parsers.parse('"{message}" 안내가 보인다'))
def _notice(ctx, message):
    assert message in text_of(ctx.response)


def cancel_form(html):
    return html.split('action="/models/benchmark/cancel"')[1].split("</form>")[0]


@then("중단 버튼이 보인다")
def _cancel_visible(ctx):
    assert "hidden" not in cancel_form(ctx.html).split(">")[0]


@then("중단 버튼은 숨겨져 있다")
def _cancel_hidden(ctx):
    assert "hidden" in ctx.html.split('action="/models/benchmark/cancel"')[1].split(">")[0]


@given(parsers.parse('모델 "{model}"가 시험 글을 모두 통과한 결과가 있다'))
def _perfect(world, model):
    scan(world)
    record_run(world, model, [call_result() for _ in SAMPLES])


@then('"벤치마크 결과" 안에 진행, 추천, 점수 보는 법이 이 순서로 있다')
def _result_section(ctx):
    html = ctx.html
    section = html.split("<h2>벤치마크 결과</h2>")[1]
    order = [section.index(m) for m in ("data-bench-progress", "추천 체인", "점수 보는 법")]
    assert order == sorted(order)


@then('"추천 체인으로 교체" 버튼은 없다')
def _no_apply_button(ctx):
    assert "추천 체인으로 교체" not in ctx.html


@then('"추천"이라는 별도 제목은 없다')
def _no_recommend_heading(ctx):
    assert "<h2>추천</h2>" not in ctx.html


@then('"벤치마크 결과" 제목은 없다')
def _no_result_heading(ctx):
    assert "<h2>벤치마크 결과</h2>" not in ctx.html


@then("호출 한도는 접혀 있다")
def _limits_closed(ctx):
    tag = ctx.html.split("<summary>호출 한도</summary>")[0].rsplit("<details", 1)[1]
    assert " open" not in tag.split(">")[0]


@when(parsers.parse('호출 한도에 잘못된 값 "{value}"를 저장한다'))
def _bad_limit(world, ctx, value):
    ctx.response = post(world, "/models/settings", {"llm_daily_cap": value, "next": "/models"})
    ctx.html = ctx.response.text
    assert ctx.response.status_code == 400


@then("호출 한도는 펼쳐져 있고 오류가 보인다")
def _limits_open(ctx):
    tag = ctx.html.split("<summary>호출 한도</summary>")[0].rsplit("<details", 1)[1]
    assert " open" in tag.split(">")[0] and 'class="error"' in ctx.html


@given(parsers.parse('모델 "{model}"가 두 칸 실패하고 나머지는 건너뛰어 끝난 결과가 있다'))
def _failed_and_skipped(world, model):
    results = [call_result(ok=False, error="rate_limited") for _ in range(2)]
    run_id = record_run(world, model, results)
    for index in range(2, len(SAMPLES)):
        world.models.save_skipped(run_id, model, index, SAMPLES[index].title, "rate_limited")


@then('범례에는 "실패"와 "건너뜀"만 있고 "진행 중"과 "대기"는 없다')
def _legend(ctx):
    legend = ctx.html.split('class="bench-legend"')[1].split("</p>")[0]
    assert "실패" in legend and "건너뜀" in legend
    assert "진행 중" not in legend and "대기" not in legend and "성공" not in legend
