"""09_settings.feature: SET-13(웹훅 시험 전송), SET-14(OpenRouter 키 확인)."""

import re

import pytest
from pytest_bdd import given, parsers, then, when

from rss_hub.services.ports import SendResult
from rss_hub.storage.llm_usage import LlmUsageRepository
from tests.bdd.binding import bind
from tests.fakes.llm_env import KEY
from tests.fakes.web_parts import start_app

bind(globals(), "09_settings.feature", ["SET-13", "SET-14"])

SECRET_URL = "https://discord.com/api/webhooks/321/SECRETWEBHOOKTOKEN"


@pytest.fixture
def parts(tmp_path):
    parts, client = start_app(tmp_path)
    with client:
        parts.responses = []
        parts.webhook_ids = {}
        parts.usage_before = None
        yield parts


def text_of(response):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", response.text))


@given(parsers.parse('웹훅 "{name}"가 저장되어 있다'))
def _webhook_saved(parts, name):
    parts.webhook_ids[name] = parts.settings.add_webhook(name, SECRET_URL)


@when(parsers.parse('웹훅 "{name}"의 시험 전송을 누른다'))
def _press_test(parts, name):
    parts.responses.append(parts.client.post(f"/settings/webhooks/{parts.webhook_ids[name]}/test"))


@then(parsers.parse('"{name}"로 시험 메시지 1건이 나간다'))
def _one_message(parts, name):
    assert len(parts.sender.calls) == 1
    assert parts.sender.calls[0].url == parts.settings.get_webhook_url(parts.webhook_ids[name])


@then('성공하면 "성공"이, 실패하면 상태 코드와 이유가 표시된다')
def _success_and_failure(parts):
    assert "성공" in text_of(parts.responses[0])
    # 같은 웹훅이 404로 답하는 경우도 눌러 본다
    url = parts.settings.get_webhook_url(next(iter(parts.webhook_ids.values())))
    parts.sender.will(url, SendResult(404))
    failed = parts.client.post(f"/settings/webhooks/{next(iter(parts.webhook_ids.values()))}/test")
    parts.responses.append(failed)
    assert "HTTP 404" in text_of(failed) and "웹훅 주소가 틀렸거나 삭제되었습니다" in text_of(
        failed
    )


@then("웹훅 주소는 결과 화면에 나타나지 않는다")
def _no_address(parts):
    for response in parts.responses:
        assert (
            "SECRETWEBHOOKTOKEN" not in response.text
            and "discord.com/api/webhooks" not in response.text
        )


# ---------- SET-14 ----------


@given("OpenRouter 키가 저장되어 있다")
def _key_saved(parts):
    parts.settings.set_openrouter_key(KEY)
    parts.usage_before = LlmUsageRepository(parts.db, parts.clock).count_day(
        parts.clock.now().date()
    )


@when("키 확인을 누른다")
def _press_check(parts):
    parts.responses.append(parts.client.post("/settings/openrouter-key/check"))


@then("키가 유효한지 여부와 사용량 정보가 표시된다")
def _validity_shown(parts):
    shown = text_of(parts.responses[-1])
    assert "키가 유효합니다" in shown and "33/1000" in shown and KEY not in parts.responses[-1].text


@then("요약용 채팅 호출은 일어나지 않는다")
def _no_chat_call(parts):
    assert parts.llm.key_checks == 1 and parts.llm.calls == []


@then("오늘 운영 호출 수는 늘지 않는다")
def _usage_unchanged(parts):
    usage = LlmUsageRepository(parts.db, parts.clock)
    assert usage.count_day(parts.clock.now().date()) == parts.usage_before
