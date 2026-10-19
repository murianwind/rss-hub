"""설정 화면의 웹훅 시험 전송, 키 확인과 주제 화면의 판별 시험."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from rss_hub.domain.topics import TopicFields
from rss_hub.services.ports import KeyCheck, SendResult
from rss_hub.storage.llm_usage import LlmUsageRepository
from rss_hub.web.app import create_app
from tests.fakes.clock import FakeClock
from tests.fakes.delivery_env import FakeWebhookSender
from tests.fakes.llm_client import FakeLlmClient, reply
from tests.fakes.llm_env import KEY

BASE = "https://rss.example.com"
SECRET_URL = "https://discord.com/api/webhooks/123/SECRETWEBHOOKTOKEN"


@pytest.fixture
def parts(tmp_path):
    clock = FakeClock()
    sender = FakeWebhookSender()
    llm = FakeLlmClient(default=reply("넷플릭스 신작", "요약입니다.", topics=[1]))
    app = create_app(data_dir=tmp_path, clock=clock, webhook_sender=sender, llm_client=llm)
    with TestClient(app, base_url=BASE, follow_redirects=False) as client:
        yield SimpleNamespace(
            client=client,
            sender=sender,
            llm=llm,
            clock=clock,
            settings=app.state.settings_service,
            topics=app.state.topics,
            db=app.state.settings_service._db,
        )


def add_webhook(parts, name="dev"):
    webhook_id = parts.settings.add_webhook(
        name, SECRET_URL.replace("123", str(len(parts.settings.list_webhooks()) + 1))
    )
    return webhook_id


# ---------- 웹훅 시험 전송 ----------


def test_the_test_button_sends_exactly_one_message_to_the_chosen_webhook(parts):
    add_webhook(parts, "other")  # 첫 번째가 아닌 웹훅을 고르는 경우도 확인한다
    chosen = add_webhook(parts, "dev")
    response = parts.client.post(f"/settings/webhooks/{chosen}/test")
    assert response.status_code == 200 and "성공" in response.text and "dev" in response.text
    assert len(parts.sender.calls) == 1
    assert parts.sender.calls[0].url == parts.settings.get_webhook_url(chosen)
    assert (
        "시험 메시지" in parts.sender.calls[0].content and "'dev'" in parts.sender.calls[0].content
    )


def test_the_result_page_never_shows_the_webhook_address(parts):
    chosen = add_webhook(parts)
    html = parts.client.post(f"/settings/webhooks/{chosen}/test").text
    assert "SECRETWEBHOOKTOKEN" not in html and "discord.com/api/webhooks" not in html


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (SendResult(404), "웹훅 주소가 틀렸거나 삭제되었습니다(HTTP 404)"),
        (SendResult(401), "HTTP 401"),
        (SendResult(429, retry_after=2.0), "잠시 전송을 제한했습니다(HTTP 429)"),
        (SendResult(503), "Discord 서버 오류입니다(HTTP 503)"),
        (SendResult(0, error="ReadTimeout"), "연결하지 못했습니다(ReadTimeout)"),
    ],
)
def test_a_failure_shows_the_status_and_the_reason_without_the_address(parts, result, expected):
    chosen = add_webhook(parts)
    parts.sender.will(parts.settings.get_webhook_url(chosen), result)
    response = parts.client.post(f"/settings/webhooks/{chosen}/test")
    assert response.status_code == 200 and "실패" in response.text and expected in response.text
    assert 'class="banner error"' in response.text and "SECRETWEBHOOKTOKEN" not in response.text
    assert len(parts.sender.calls) == 1


def test_an_unknown_webhook_sends_nothing(parts):
    response = parts.client.post("/settings/webhooks/999/test")
    assert response.status_code == 404 and "웹훅을 찾을 수 없습니다" in response.text
    assert parts.sender.calls == []


def test_the_test_button_is_shown_next_to_every_webhook(parts):
    first, second = add_webhook(parts, "a"), add_webhook(parts, "b")
    html = parts.client.get("/settings").text
    assert (
        f'action="/settings/webhooks/{first}/test"' in html
        and f'action="/settings/webhooks/{second}/test"' in html
    )


# ---------- 키 확인 ----------


def test_the_key_check_shows_validity_and_usage_without_any_chat_call(parts):
    parts.settings.set_openrouter_key(KEY)
    usage = LlmUsageRepository(parts.db, parts.clock)
    before = usage.count_day(parts.clock.now().date())
    response = parts.client.post("/settings/openrouter-key/check")
    assert "키가 유효합니다" in response.text and "33/1000" in response.text
    assert parts.llm.key_checks == 1 and parts.llm.calls == []
    assert usage.count_day(parts.clock.now().date()) == before


def test_a_valid_key_without_counters_still_says_valid(parts):
    parts.llm.key_check = KeyCheck(valid=True)
    html = parts.client.post("/settings/openrouter-key/check").text
    assert "키가 유효합니다" in html and "오늘 무료 모델 호출" not in html


def test_a_rejected_key_is_an_error_banner(parts):
    parts.llm.key_check = KeyCheck(valid=False, reason="OpenRouter가 키를 거부했습니다(HTTP 401)")
    html = parts.client.post("/settings/openrouter-key/check").text
    assert "거부했습니다(HTTP 401)" in html and 'class="banner error"' in html


def test_an_unknown_result_is_a_neutral_banner_not_an_error(parts):
    parts.llm.key_check = KeyCheck(
        valid=None, reason="OpenRouter에 연결하지 못했습니다(ReadTimeout)"
    )
    html = parts.client.post("/settings/openrouter-key/check").text
    assert "연결하지 못했습니다(ReadTimeout)" in html and 'class="banner error"' not in html


def test_the_key_is_never_shown_and_the_check_button_needs_a_saved_key(parts):
    parts.settings.set_openrouter_key(KEY)
    html = parts.client.get("/settings").text
    assert "openrouter-key/check" in html and KEY not in html
    assert KEY not in parts.client.post("/settings/openrouter-key/check").text


# ---------- 주제 판별 시험 ----------


def probe(parts, title="Netflix announces a new drama", body=""):
    return parts.client.post("/topics/probe", data={"title": title, "body": body})


def test_the_probe_shows_each_topic_with_the_llm_choice_keywords_and_result(parts):
    parts.settings.set_openrouter_key(KEY)
    parts.topics.add(TopicFields("게임", "", ("steam",)))
    html = probe(parts).text
    assert "넷플릭스 신작" in html and "요약입니다." in html
    assert "OTT" in html and "LLM 선택" in html and "netflix" in html and "해당" in html
    assert "게임" in html and "LLM에 묻지 않음" in html and "해당 안 함" in html


def test_the_probe_uses_one_call_and_keeps_the_typed_input(parts):
    parts.settings.set_openrouter_key(KEY)
    html = probe(parts, title="Netflix trailer", body="본문입니다").text
    assert len(parts.llm.calls) == 1
    assert 'value="Netflix trailer"' in html and "본문입니다</textarea>" in html


def test_a_problem_is_shown_as_an_error_banner(parts):
    html = probe(parts).text  # 키가 없다
    assert "OpenRouter 키가 설정되지 않았습니다" in html and 'class="banner error"' in html
    assert parts.llm.calls == []


def test_a_second_probe_right_away_is_refused(parts):
    parts.settings.set_openrouter_key(KEY)
    probe(parts)
    assert "잠시 뒤에 다시 시도하세요" in probe(parts).text and len(parts.llm.calls) == 1


def test_model_output_and_input_are_escaped(parts):
    parts.settings.set_openrouter_key(KEY)
    parts.llm.default = reply(
        "<script>alert(1)</script>", "<img src=x onerror=alert(1)>", topics=[1]
    )
    html = probe(parts, title="<b>Netflix</b>").text
    assert (
        "<script>alert(1)</script>" not in html
        and "<img src=x" not in html
        and "<b>Netflix</b>" not in html
    )
    assert "&lt;script&gt;" in html


def test_an_empty_title_is_refused_without_a_call(parts):
    parts.settings.set_openrouter_key(KEY)
    assert "제목을 입력하세요" in probe(parts, title="").text and parts.llm.calls == []


def test_a_title_without_any_keyword_match_makes_no_call_and_says_so(parts):
    parts.settings.set_openrouter_key(KEY)
    html = probe(parts, title="Spring gardening tips").text
    assert "키워드가 맞은 주제가 없어서 LLM을 호출하지 않았습니다" in html
    assert parts.llm.calls == [] and "LLM에 묻지 않음" in html


# ---------- 보안 ----------


@pytest.mark.security
@pytest.mark.parametrize(
    "path", ["/settings/webhooks/1/test", "/settings/openrouter-key/check", "/topics/probe"]
)
def test_the_new_buttons_reject_other_sites_and_accept_the_browsers_own_form(parts, path):
    other = parts.client.post(
        path,
        data={},
        headers={"origin": "https://evil.example.com", "sec-fetch-site": "cross-site"},
    )
    own = parts.client.post(
        path, data={"title": "x"}, headers={"origin": "null", "sec-fetch-site": "same-origin"}
    )
    assert other.status_code == 403 and own.status_code != 403
    assert parts.client.get(path).status_code == 405
