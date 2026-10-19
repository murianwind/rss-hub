"""가짜 웹훅 전송기와 가짜 LLM 클라이언트를 단 앱(시험용 부품 묶음)."""

from types import SimpleNamespace

from fastapi.testclient import TestClient

from rss_hub.web.app import create_app
from tests.fakes.clock import FakeClock
from tests.fakes.delivery_env import FakeWebhookSender
from tests.fakes.llm_client import FakeLlmClient, reply

BASE = "https://rss.example.com"


def start_app(tmp_path, *, feed_fetcher=None):
    """(부품 묶음, 실행 중인 클라이언트). 클라이언트는 with로 열어서 서버 시작 절차를 돌린다."""
    clock = FakeClock()
    sender = FakeWebhookSender()
    llm = FakeLlmClient(default=reply("넷플릭스 신작", "요약입니다.", topics=[]))
    app = create_app(
        data_dir=tmp_path,
        clock=clock,
        webhook_sender=sender,
        llm_client=llm,
        feed_fetcher=feed_fetcher,
    )
    client = TestClient(app, base_url=BASE, follow_redirects=False)
    parts = SimpleNamespace(
        client=client,
        sender=sender,
        llm=llm,
        clock=clock,
        app=app,
        settings=app.state.settings_service,
        topics=app.state.topics,
        db=app.state.settings_service._db,
    )
    return parts, client
