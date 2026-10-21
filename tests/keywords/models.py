"""모델 화면 키워드: 무료 모델 목록, 벤치마크 점수와 호출 기록 준비, 진행 상태 읽기."""

from contextlib import contextmanager
from types import SimpleNamespace

from fastapi.testclient import TestClient

from rss_hub.domain.benchmark import SAMPLES, CallResult, score_model
from rss_hub.storage.models import ModelRepository
from rss_hub.web.app import create_app
from tests.fakes.clock import FakeClock
from tests.fakes.delivery_env import FakeWebhookSender
from tests.fakes.llm_client import FakeLlmClient, reply
from tests.fakes.llm_env import KEY
from tests.fakes.models_env import free
from tests.keywords.browser import BROWSER

BASE = "https://rss.example.com"


@contextmanager
def open_model_world(tmp_path, *, free_models=("model-a", "model-b", "model-c", "model-d")):
    """모델 화면 시험 세계. 벤치마크 작업은 pending에 쌓아 두었다가 시험이 직접 실행한다."""
    clock, sender = FakeClock(), FakeWebhookSender()
    llm = FakeLlmClient(default=reply("한국어 제목", "요약입니다.", topics=[]))
    llm.free_models = [free(model_id) for model_id in free_models]
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
            sender=sender,
            models=ModelRepository(settings._db, clock),
        )


def post(world, path, data=None):
    return world.client.post(path, data=data or {}, headers=BROWSER)


def scan(world):
    return post(world, "/models/scan")


def call_result(*, ok=True, korean=True, topic=True, latency=2000, error=""):
    return CallResult(ok, korean and ok, topic and ok, latency if ok else None, error)


def record_run(world, model, results, *, models=None, finish=True):
    """시험 호출 결과를 한 건씩 기록하고 점수를 남긴다(벤치마크를 돌린 것과 같은 상태)."""
    run_id = world.models.start_run(len(SAMPLES), models or [model])
    for index, result in enumerate(results):
        world.models.save_call(run_id, model, index, SAMPLES[index].title, result)
    world.models.advance(run_id, len(results))
    if finish:
        world.models.save_score(run_id, score_model(model, results))
        world.models.finish_run(run_id, "done", "1개 모델 완료")
    return run_id


def progress(world):
    response = world.client.get("/models/benchmark/progress")
    assert response.status_code == 200
    return response.json()
