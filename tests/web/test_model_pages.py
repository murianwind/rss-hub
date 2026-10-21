"""모델 화면(M3): 스캔, 벤치마크, 추천, 교체."""

import re
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from rss_hub.domain.benchmark import SAMPLES
from rss_hub.storage.models import ModelRepository
from rss_hub.web.app import create_app
from tests.fakes.clock import FakeClock
from tests.fakes.delivery_env import FakeWebhookSender
from tests.fakes.llm_client import FakeLlmClient, reply
from tests.fakes.llm_env import KEY
from tests.fakes.models_env import free
from tests.keywords.browser import BROWSER

BASE = "https://rss.example.com"


@pytest.fixture
def world(tmp_path):
    clock, sender = FakeClock(), FakeWebhookSender()
    llm = FakeLlmClient(default=reply("한국어 제목", "요약입니다.", topics=[]))
    llm.free_models = [free("model-a"), free("model-b"), free("model-c"), free("model-d")]
    pending = []
    app = create_app(
        data_dir=tmp_path,
        clock=clock,
        webhook_sender=sender,
        llm_client=llm,
        benchmark_spawn=pending.append,
        benchmark_sleep=lambda seconds: None,
    )
    with TestClient(app, base_url=BASE, follow_redirects=False) as client:
        settings = app.state.settings_service
        settings.set_openrouter_key(KEY)
        settings.update({"model_chain": "model-a,model-b"})
        yield SimpleNamespace(
            client=client,
            llm=llm,
            clock=clock,
            settings=settings,
            pending=pending,
            models=ModelRepository(settings._db, clock),
        )


def post(world, path, data=None):
    return world.client.post(path, data=data or {}, headers=BROWSER)


def scan(world):
    return post(world, "/models/scan")


def run_benchmark(world, *models):
    for model in models:
        world.llm.will(
            model,
            *[
                reply("한국어 제목", "요약입니다.", topics=[1] if s.expects_topic else [])
                for s in SAMPLES
            ],
        )
    response = post(world, "/models/benchmark", {"models": list(models)})
    while world.pending:
        world.pending.pop()()
    return response


def test_the_page_shows_the_current_chain_in_order_and_asks_for_a_first_scan(world):
    html = world.client.get("/models").text
    assert html.index("model-a") < html.index("model-b") and "아직 스캔하지 않았습니다" in html


def test_the_llm_section_of_the_settings_links_to_the_models_page(world):
    assert 'href="/models"' in world.client.get("/settings").text


def test_a_scan_lists_the_free_models_without_any_llm_call(world):
    response = scan(world)
    assert (
        response.status_code == 200
        and "무료 텍스트 모델 4개" in response.text
        and "처음 스캔했습니다" in response.text
    )
    html = world.client.get("/models").text
    assert (
        all(f'value="{m}"' in html for m in ("model-a", "model-b", "model-c", "model-d"))
        and world.llm.calls == []
    )


def test_the_chain_models_are_marked_with_their_position(world):
    scan(world)
    html = world.client.get("/models").text
    assert re.search(r"model-a</code> <span class=\"badge\">체인 1", html) and "체인 2" in html


def test_a_second_scan_reports_what_changed(world):
    scan(world)
    world.llm.free_models = [free("model-a"), free("model-b"), free("model-e")]
    text = scan(world).text
    assert "새로 보인 모델 1개, 사라진 모델 2개" in text


def test_a_failed_scan_is_an_error_banner_and_keeps_the_old_list(world):
    scan(world)
    world.llm.free_models = None
    response = scan(world)
    assert (
        response.status_code == 502
        and "가져오지 못했습니다" in response.text
        and 'class="banner error"' in response.text
    )
    assert 'value="model-a"' in world.client.get("/models").text


def test_a_chain_model_missing_from_the_free_list_is_pointed_out(world):
    world.llm.free_models = [free("model-b"), free("model-c")]
    assert "지금 체인의 모델이 무료 목록에 없습니다: model-a" in scan(world).text


# ---------- 벤치마크 ----------


def test_the_benchmark_scores_the_chosen_models_and_shows_them(world):
    scan(world)
    response = run_benchmark(world, "model-c")
    assert response.status_code == 303 and response.headers["location"] == "/models?started=1"
    html = world.client.get("/models").text
    assert "100.0점(성공 6/6" in html and "완료" in html and "1개 모델 완료" in html


def test_while_a_run_is_going_the_page_refreshes_and_blocks_a_second_start(world):
    scan(world)
    post(world, "/models/benchmark", {"models": ["model-c"]})
    html = world.client.get("/models").text
    assert (
        '<meta http-equiv="refresh" content="5">' in html
        and "실행 중 0/6" in html
        and "disabled" in html
    )
    second = post(world, "/models/benchmark", {"models": ["model-d"]})
    assert second.status_code == 409 and "이미 벤치마크가 실행 중입니다" in second.text


def test_the_page_does_not_refresh_when_nothing_is_running(world):
    scan(world)
    assert "http-equiv" not in world.client.get("/models").text


def test_the_page_states_the_cost_of_a_benchmark(world):
    scan(world)
    assert "모델 하나당 LLM 호출 6회" in world.client.get("/models").text


@pytest.mark.parametrize(
    ("models", "status", "message"),
    [
        ([], 400, "고르세요"),
        (["nope"], 400, "스캔"),
        (["model-a", "model-b", "model-c", "model-d", "e", "f"], 400, "5개까지"),
    ],
)
def test_invalid_benchmark_requests_are_refused(world, models, status, message):
    scan(world)
    response = post(world, "/models/benchmark", {"models": models})
    assert response.status_code == status and message in response.text and world.pending == []


def test_a_run_that_hit_the_limit_says_so(world):
    scan(world)
    world.settings.update({"llm_daily_cap": "2"})
    post(world, "/models/benchmark", {"models": ["model-c"]})
    while world.pending:
        world.pending.pop()()
    assert "멈춤" in world.client.get("/models").text and "한도" in world.client.get("/models").text


# ---------- 추천과 교체 ----------


def test_a_recommendation_appears_after_scores_exist_and_names_the_best_model(world):
    scan(world)
    run_benchmark(world, "model-c", "model-d")
    html = world.client.get("/models").text
    assert "추천" in html and "model-c" in html and 'action="/models/apply"' in html


def test_applying_the_recommendation_needs_the_confirmation_checkbox(world):
    scan(world)
    run_benchmark(world, "model-c")
    response = post(world, "/models/apply", {"chain": ["model-c"]})
    assert response.status_code == 400 and "확인란" in response.text
    assert world.settings.snapshot().model_chain == ("model-a", "model-b")


def test_applying_replaces_the_chain_and_redirects_with_a_notice(world):
    scan(world)
    run_benchmark(world, "model-c")
    response = post(world, "/models/apply", {"chain": ["model-c"], "confirm": "yes"})
    assert response.status_code == 303 and response.headers["location"] == "/models?applied=1"
    assert world.settings.snapshot().model_chain == ("model-c",)
    assert "모델 체인을 바꿨습니다" in world.client.get("/models?applied=1").text


def test_a_model_that_is_not_in_the_free_list_cannot_be_applied(world):
    scan(world)
    response = post(world, "/models/apply", {"chain": ["typo"], "confirm": "yes"})
    assert response.status_code == 400 and "스캔" in response.text
    assert world.settings.snapshot().model_chain == ("model-a", "model-b")


def test_when_the_current_chain_is_already_best_there_is_no_apply_form(world):
    scan(world)
    world.settings.update({"model_chain": "model-c"})
    run_benchmark(world, "model-c")
    html = world.client.get("/models").text
    assert "이미 가장 좋습니다" in html and 'action="/models/apply"' not in html


def test_without_a_good_enough_model_the_page_says_no_one_qualifies(world):
    scan(world)
    world.llm.default = reply("제목", "요약", topics=[])
    world.llm.will("model-c", *[Exception("x")] * 0)
    from rss_hub.services.ports import LlmErrorKind
    from tests.fakes.llm_client import failure

    world.llm.will("model-c", *[failure(LlmErrorKind.UNAVAILABLE, status=503)] * 6)
    post(world, "/models/benchmark", {"models": ["model-c"]})
    while world.pending:
        world.pending.pop()()
    assert "성공률 80% 이상인 모델이 없습니다" in world.client.get("/models").text


def test_stale_runs_left_by_a_previous_process_are_cleaned_up_when_the_server_starts(tmp_path):
    clock = FakeClock()
    first = create_app(
        data_dir=tmp_path,
        clock=clock,
        llm_client=FakeLlmClient(),
        webhook_sender=FakeWebhookSender(),
    )
    with TestClient(first, base_url=BASE):
        repo = ModelRepository(first.state.settings_service._db, clock)
        repo.start_run(6)
    second = create_app(
        data_dir=tmp_path,
        clock=clock,
        llm_client=FakeLlmClient(),
        webhook_sender=FakeWebhookSender(),
    )
    with TestClient(second, base_url=BASE) as client:
        assert "중단됨" in client.get("/models").text and repo.running_run() is None


# ---------- 보안 ----------


@pytest.mark.security
@pytest.mark.parametrize("path", ["/models/scan", "/models/benchmark", "/models/apply"])
def test_other_sites_cannot_use_the_model_buttons(world, path):
    scan(world)
    other = world.client.post(
        path,
        data={"chain": ["model-c"], "confirm": "yes", "models": ["model-c"]},
        headers={"origin": "https://evil.example.com", "sec-fetch-site": "cross-site"},
    )
    assert other.status_code == 403 and world.settings.snapshot().model_chain == (
        "model-a",
        "model-b",
    )
    assert world.client.get(path).status_code == 405


def test_model_names_from_the_service_are_escaped(world):
    world.llm.free_models = [free("<script>alert(1)</script>"), free("model-a")]
    scan(world)
    html = world.client.get("/models").text
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html


def test_the_failure_reasons_of_a_scored_model_are_shown_next_to_its_score(world):
    from rss_hub.services.ports import LlmErrorKind
    from tests.fakes.llm_client import failure

    scan(world)
    good = [
        reply("한국어 제목", "요약입니다.", topics=[1] if s.expects_topic else []) for s in SAMPLES
    ]
    world.llm.will("model-c", *good[:4], *[failure(LlmErrorKind.UNAVAILABLE, status=503)] * 2)
    post(world, "/models/benchmark", {"models": ["model-c"]})
    while world.pending:
        world.pending.pop()()
    assert "실패 원인 unavailable" in world.client.get("/models").text


def test_a_rejected_key_stops_the_benchmark_and_tells_the_user_why(world):
    from rss_hub.services.ports import LlmErrorKind
    from tests.fakes.llm_client import failure

    scan(world)
    world.llm.will("model-c", *[failure(LlmErrorKind.UNAUTHORIZED, status=401)] * 6)
    post(world, "/models/benchmark", {"models": ["model-c"]})
    while world.pending:
        world.pending.pop()()
    html = world.client.get("/models").text
    assert "멈춤" in html and "키를 거부했습니다" in html and len(world.llm.calls) == 1
