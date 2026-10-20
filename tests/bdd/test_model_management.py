"""14_model_management.feature: 스캔, 벤치마크, 추천, 교체."""

import re
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, then, when

from rss_hub.adapters.openrouter_client import OpenRouterClient
from rss_hub.domain.benchmark import SAMPLES, ModelScore, recommend
from rss_hub.services.model_benchmark import BenchmarkRunner
from rss_hub.services.model_scan import ModelScanService
from rss_hub.services.ports import LlmErrorKind
from rss_hub.storage.models import ModelRepository
from rss_hub.web.app import create_app
from tests.bdd.binding import bind
from tests.fakes.clock import FakeClock
from tests.fakes.delivery_env import FakeWebhookSender, webhook_url
from tests.fakes.llm_client import FakeLlmClient, failure, reply
from tests.fakes.llm_env import KEY
from tests.fakes.models_env import Env, free
from tests.tools.fake_apis import FakeServer, json_reply

bind(globals(), "14_model_management.feature", [f"MDL-{n:02d}" for n in range(1, 13)])

BROWSER = {"origin": "null", "sec-fetch-site": "same-origin"}
CATALOG = {
    "data": [
        {
            "id": f"free/text-{n}:free",
            "context_length": 32768,
            "pricing": {"prompt": "0", "completion": "0"},
            "architecture": {"output_modalities": ["text"]},
        }
        for n in (1, 2)
    ]
    + [
        {
            "id": "paid/model",
            "context_length": 32768,
            "pricing": {"prompt": "0.000002", "completion": "0.000004"},
            "architecture": {"output_modalities": ["text"]},
        },
        {
            "id": "free/image:free",
            "context_length": 32768,
            "pricing": {"prompt": "0", "completion": "0"},
            "architecture": {"output_modalities": ["image"]},
        },
    ]
}


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


@pytest.fixture
def ctx():
    return SimpleNamespace(
        report=None, outcome=None, spawned=[], rec=None, response=None, scores=[]
    )


@pytest.fixture
def server():
    local = FakeServer(lambda *_: json_reply(200, CATALOG))
    local.start()
    yield local
    local.stop()


@pytest.fixture
def web(tmp_path):
    clock, sender = FakeClock(), FakeWebhookSender()
    llm = FakeLlmClient(default=reply("한국어 제목", "요약입니다.", topics=[]))
    folder = tmp_path / "web"  # 배경 단계의 서비스 시험 환경과 같은 데이터베이스를 쓰지 않는다
    folder.mkdir()
    app = create_app(
        data_dir=folder,
        clock=clock,
        webhook_sender=sender,
        llm_client=llm,
        benchmark_sleep=lambda s: None,
    )
    with TestClient(app, base_url="https://rss.example.com", follow_redirects=False) as client:
        settings = app.state.settings_service
        settings.set_openrouter_key(KEY)
        settings.update({"model_chain": "model-a,model-b"})
        system = settings.add_webhook("시스템", webhook_url("시스템"))
        settings.set_webhook_roles(default_id=None, system_id=system)
        yield SimpleNamespace(
            client=client, llm=llm, sender=sender, settings=settings, clock=clock, app=app
        )


def scan_web(web, *names):
    web.llm.free_models = [free(n) for n in names]
    return web.client.post("/models/scan", data={}, headers=BROWSER)


def quoted(text):
    return re.findall(r'"([^"]+)"', text)


@given('모델 체인은 "model-a", "model-b"이고 OpenRouter 키가 저장되어 있다')
def _background(env):
    assert (
        env.settings.snapshot().model_chain == ("model-a", "model-b")
        and env.settings.has_openrouter_key()
    )


# ---------- 스캔 ----------


@given("OpenRouter의 모델 목록에 무료 텍스트 모델 2개, 유료 모델 1개, 무료 이미지 모델 1개가 있다")
def _catalog_on_server(server):
    assert len(CATALOG["data"]) == 4


@when("실제 어댑터로 무료 모델을 스캔한다")
def _scan_with_real_adapter(env, ctx, server):
    client = OpenRouterClient(lambda: KEY, base_url=server.url(), timeout=(1.0, 1.0))
    ctx.report = ModelScanService(
        client=client, models=env.models, settings=env.settings, alerts=env.alerts
    ).scan()


@then("목록에는 무료 텍스트 모델 2개만 있다")
def _only_two(env):
    assert [e.id for e in env.models.catalog()] == ["free/text-1:free", "free/text-2:free"]


@then("모델 목록 조회 말고는 어떤 요청도 가지 않았다")
def _only_models_endpoint(server):
    assert [(r[0], r[1]) for r in server.requests] == [("GET", "/models")]


NAMES = r'(?P<names>"[^"]+"(?:, "[^"]+")*)'


@given(parsers.re(rf'지난 스캔에는 {NAMES}가 있었고 지금은 (?P<now>"[^"]+"(?:, "[^"]+")*)가 있다'))
def _before_and_now(env, names, now):
    env.client.free_models = [free(n) for n in quoted(names)]
    env.scanner.scan()
    env.client.free_models = [free(n) for n in quoted(now)]


@given(parsers.re(rf'지난 스캔에는 {NAMES}가 있었고 지금은 "(?P<only>[^"]+)"만 있다'))
def _before_and_only(env, names, only):
    env.client.free_models = [free(n) for n in quoted(names)]
    env.scanner.scan()
    env.client.free_models = [free(only)]


@given(parsers.re(rf"지난 스캔에는 {NAMES}가 있었다"))
def _before(env, names):
    env.client.free_models = [free(n) for n in quoted(names)]
    env.scanner.scan()


@given("이번에는 목록 조회가 실패한다")
def _lookup_fails(env):
    env.client.free_models = None


@given("이번에는 목록이 비어 있다")
def _lookup_empty(env):
    env.client.free_models = []


@when("무료 모델을 스캔한다")
def _scan(env, ctx):
    ctx.report = env.scanner.scan()


@when("같은 날 다시 스캔한다")
def _scan_again(env, ctx):
    ctx.report = env.scanner.scan()


@then(parsers.re(r'새로 보인 모델은 "(?P<new>[^"]+)", 사라진 모델은 "(?P<gone>[^"]+)"로 보고된다'))
def _diff(ctx, new, gone):
    assert ctx.report.diff.new == (new,) and ctx.report.diff.gone == (gone,)


@then(parsers.re(r'시스템 웹훅으로 "(?P<model>[^"]+)"가 사라졌다는 알림이 한 번만 나간다'))
def _one_alert(env, model):
    assert len([t for t in env.notifier.texts() if model in t and "사라졌습니다" in t]) == 1


@then(parsers.re(r'오류 "(?P<message>[^"]+)"가 보고되고 저장된 목록은 그대로다'))
def _error_and_unchanged(env, ctx, message):
    assert not ctx.report.ok and message in ctx.report.error
    assert [e.id for e in env.models.catalog()] == ["model-a", "model-b"]


# ---------- 벤치마크 ----------


@given(parsers.re(r'모델 "(?P<model>[^"]+)"는 시험 글 6개에 대해 (?P<behavior>.+)'))
def _behavior(env, model, behavior):
    good_answers = [
        reply("한국어 제목", "요약입니다.", topics=[1] if s.expects_topic else []) for s in SAMPLES
    ]
    if behavior.startswith("모두 성공하고 한국어 제목과"):
        env.client.will(model, *good_answers)
    elif behavior.startswith("절반만 성공"):
        env.client.will(
            model, *good_answers[:3], *[failure(LlmErrorKind.UNAVAILABLE, status=503)] * 3
        )
    elif behavior.startswith("모두 성공하지만 제목을 영어로만"):
        env.client.will(
            model,
            *[
                reply("English title only", "요약입니다.", topics=[1] if s.expects_topic else [])
                for s in SAMPLES
            ],
        )
    elif behavior.startswith("모두 정확하지만 한 번에 40초씩"):
        env.latency = 40.0
        env.client.will(model, *good_answers)
    elif behavior.startswith("주제 판정이 모두 틀린다"):
        env.client.will(
            model,
            *[
                reply("한국어 제목", "요약입니다.", topics=[] if s.expects_topic else [1])
                for s in SAMPLES
            ],
        )
    else:
        raise AssertionError(behavior)


@when(parsers.re(r'모델 "(?P<model>[^"]+)"를 벤치마크한다'))
def _benchmark_one(env, ctx, model):
    ctx.outcome = env.benchmark().run(env.models.start_run(6), [model])


@then(parsers.re(r'모델 "(?P<model>[^"]+)"의 점수는 (?P<score>[\d.]+)점이다'))
def _score_is(env, model, score):
    assert env.models.latest_scores()[model][0].score == float(score)


@given(parsers.re(r"오늘 LLM 호출 상한이 (?P<cap>\d+)회이다"))
def _cap(env, cap):
    env.settings.update({"llm_daily_cap": cap})


@given('모델 "model-a"와 "model-b"는 모두 완벽하게 답한다')
def _both_perfect(env):
    env.client.free_models = [free("model-a"), free("model-b")]
    env.scanner.scan()
    env.perfect_answers("model-a")
    env.perfect_answers("model-b")


@when('모델 "model-a"와 "model-b"를 벤치마크한다')
def _benchmark_two(env, ctx):
    BenchmarkRunner(service=env.benchmark(), models=env.models, spawn=lambda work: work()).start(
        ["model-a", "model-b"]
    )


@then(parsers.re(r"오늘 호출 수는 (?P<count>\d+)이다"))
def _usage(env, count):
    assert env.usage.count_day(env.clock.now().date()) == int(count)


@then('벤치마크는 한도 때문에 멈췄다고 기록되고 "model-a"의 점수만 남는다')
def _stopped_at_the_limit(env):
    latest = env.models.latest_run()
    assert latest.status == "failed" and "한도" in latest.note
    assert set(env.models.latest_scores()) == {"model-a"}


@given("무료 모델 6개가 스캔되어 있다")
def _six_models(env, ctx):
    env.client.free_models = [free(f"model-{c}") for c in "abcdef"]
    env.scanner.scan()
    ctx.runner = BenchmarkRunner(
        service=env.benchmark(), models=env.models, spawn=ctx.spawned.append
    )


@when("벤치마크를 시작한다")
def _start(ctx):
    ctx.first = ctx.runner.start(["model-a"])


@then("두 번째 벤치마크는 이미 실행 중이라는 이유로 시작되지 않는다")
def _busy(ctx):
    second = ctx.runner.start(["model-b"])
    assert ctx.first.status == "started" and second.status == "busy" and "이미" in second.message
    assert len(ctx.spawned) == 1


@when("모델 6개를 한꺼번에 고른다")
def _choose_six(ctx):
    ctx.response = ctx.runner.start([f"model-{c}" for c in "abcdef"])


@then("5개까지만 고를 수 있다는 안내가 나온다")
def _five_max(ctx):
    assert ctx.response.status == "invalid" and "5개까지" in ctx.response.message


@given("벤치마크가 실행 중인 채로 서비스가 멈췄다")
def _stopped_while_running(tmp_path, ctx):
    clock = FakeClock()
    first = create_app(
        data_dir=tmp_path,
        clock=clock,
        llm_client=FakeLlmClient(),
        webhook_sender=FakeWebhookSender(),
    )
    with TestClient(first, base_url="https://rss.example.com"):
        ModelRepository(first.state.settings_service._db, clock).start_run(6)
    ctx.clock = clock


@when("서비스가 다시 시작된다")
def _restart(tmp_path, ctx):
    llm = FakeLlmClient(default=reply("제목", "요약", topics=[]))
    llm.free_models = [free("model-a")]
    second = create_app(
        data_dir=tmp_path,
        clock=ctx.clock,
        llm_client=llm,
        webhook_sender=FakeWebhookSender(),
        benchmark_sleep=lambda s: None,
    )
    ctx.client = TestClient(second, base_url="https://rss.example.com", follow_redirects=False)
    ctx.client.__enter__()
    ctx.second = second
    ctx.repo = ModelRepository(second.state.settings_service._db, ctx.clock)


@then('그 벤치마크는 "중단됨"으로 표시되고 새 벤치마크를 시작할 수 있다')
def _interrupted(ctx):
    try:
        assert "중단됨" in ctx.client.get("/models").text and ctx.repo.running_run() is None
        ctx.second.state.settings_service.set_openrouter_key(KEY)
        ctx.client.post("/models/scan", data={}, headers=BROWSER)
        started = ctx.client.post(
            "/models/benchmark", data={"models": ["model-a"]}, headers=BROWSER
        )
        assert started.status_code == 303
    finally:
        ctx.client.__exit__(None, None, None)


# ---------- 추천 ----------


@given(parsers.re(r"점수가 있다: (?P<rows>.+)"))
def _scores(ctx, rows):
    for name, score, ok, calls in re.findall(r'"([^"]+)" (\d+)점\(성공 (\d+)/(\d+)\)', rows):
        ctx.scores.append(
            ModelScore(name, int(calls), int(ok), int(ok), int(ok), 3000, float(score), ())
        )


@when("추천을 만든다")
def _recommend(ctx):
    ctx.rec = recommend(ctx.scores, ("x",))


@then('추천 체인은 "m1", "m2" 순서이고 "m3"는 성공률이 낮아 빠진다')
def _recommendation(ctx):
    assert ctx.rec.chain == ("m1", "m2") and ctx.rec.changed is True


@when('현재 체인이 이미 "m1", "m2"이다')
def _already_best(ctx):
    ctx.rec = recommend(ctx.scores, ("m1", "m2"))


@then("추천은 현재 체인이 이미 가장 좋다고 알리고 교체를 권하지 않는다")
def _no_change(ctx):
    assert ctx.rec.changed is False and "이미 가장 좋습니다" in ctx.rec.reason


# ---------- 교체 ----------


@given(parsers.re(rf"무료 모델 {NAMES}가 스캔되어 있다"))
def _scanned(web, names):
    scan_web(web, *quoted(names))


@when(parsers.re(r'확인 없이 체인을 "(?P<model>[^"]+)"로 교체하려고 한다'))
def _apply_unconfirmed(web, ctx, model):
    ctx.response = web.client.post("/models/apply", data={"chain": [model]}, headers=BROWSER)


@when(parsers.re(r'확인하고 체인을 "(?P<model>[^"]+)"로 교체한다'))
def _apply_confirmed(web, ctx, model):
    ctx.response = web.client.post(
        "/models/apply", data={"chain": [model], "confirm": "yes"}, headers=BROWSER
    )


@then("교체되지 않고 확인하라는 안내가 나온다")
def _needs_confirmation(web, ctx):
    assert ctx.response.status_code == 400 and "확인란" in ctx.response.text
    assert web.settings.snapshot().model_chain == ("model-a", "model-b")


@then(parsers.re(r'모델 체인은 "(?P<model>[^"]+)"가 되고 시스템 웹훅으로 이전과 새 체인을 알린다'))
def _applied(web, model):
    assert web.settings.snapshot().model_chain == (model,)
    texts = web.sender.to("시스템")
    assert any("이전: model-a, model-b" in t and f"새로: {model}" in t for t in texts)


@then("교체되지 않고 먼저 스캔하라는 안내가 나온다")
def _scan_first(web, ctx):
    assert ctx.response.status_code == 400 and "스캔" in ctx.response.text
    assert web.settings.snapshot().model_chain == ("model-a", "model-b")


@when(parsers.re(r'다른 사이트에서 체인을 "(?P<model>[^"]+)"로 교체하는 요청을 보낸다'))
def _cross_site(web, ctx, model):
    ctx.response = web.client.post(
        "/models/apply",
        data={"chain": [model], "confirm": "yes"},
        headers={"origin": "https://evil.example.com", "sec-fetch-site": "cross-site"},
    )


@then("요청은 거부되고 모델 체인은 그대로다")
def _refused(web, ctx):
    assert ctx.response.status_code == 403 and web.settings.snapshot().model_chain == (
        "model-a",
        "model-b",
    )
