"""04_topic_judgement.feature: TPC-12~14(판별 시험)."""

import re

import pytest
from pytest_bdd import given, parsers, then, when

from rss_hub.domain.topics import TopicFields
from rss_hub.storage.deliveries import DeliveryRepository
from rss_hub.storage.llm_usage import LlmUsageRepository
from tests.bdd.binding import bind
from tests.fakes.llm_client import reply
from tests.fakes.llm_env import KEY
from tests.fakes.web_parts import start_app

bind(globals(), "04_topic_judgement.feature", ["TPC-12", "TPC-13", "TPC-14", "TPC-15"])


@pytest.fixture
def parts(tmp_path):
    parts, client = start_app(tmp_path)
    with client:
        parts.response = None
        parts.usage_before = 0
        yield parts


def usage(parts):
    return LlmUsageRepository(parts.db, parts.clock)


def clear_topics(parts):
    for topic in parts.topics.list_all():
        parts.topics.delete(topic.id)


def row(parts, name):
    """판별 결과의 한 줄(주제 이름으로 찾는다)을 글자만 남겨서 돌려준다."""
    blocks = re.findall(r'<li class="check">(.*?)</li>', parts.response.text, re.S)
    for block in blocks:
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", block)).strip()
        if text.startswith(name + " "):
            return text
    raise AssertionError(f"{name} 줄이 없다: {parts.response.text[:200]}")


@given('주제 "OTT"가 있고 기본 OTT 키워드가 등록되어 있다')
def _background_default_topic(parts):
    """파일 공통 배경. 서버 시작 때 만들어진 기본 주제다(시나리오가 필요에 맞게 다시 구성한다)."""
    assert any(t.name == "OTT" for t in parts.topics.list_all())


@given('주제 "OTT"(키워드 "netflix")와 주제 "게임"(키워드 "steam")이 있다')
def _two_topics(parts):
    parts.settings.set_openrouter_key(KEY)
    clear_topics(parts)
    parts.ott_id = parts.topics.add(TopicFields("OTT", "스트리밍 소식", ("netflix",)))
    parts.topics.add(TopicFields("게임", "게임 소식", ("steam",)))


@given('LLM이 "OTT" 주제를 고른다')
def _llm_chooses_ott(parts):
    parts.llm.default = reply("넷플릭스 신작", "요약입니다.", topics=[parts.ott_id])


@given(parsers.re(r'주제 "OTT"가 있다'))
def _ott_topic(parts):
    parts.settings.set_openrouter_key(KEY)
    clear_topics(parts)
    parts.ott_id = parts.topics.add(TopicFields("OTT", "", ("netflix",)))
    parts.llm.default = reply("t", "s", topics=[parts.ott_id])
    parts.usage_before = usage(parts).count_day(parts.clock.now().date())


@given('OpenRouter 키가 없고 주제 "OTT"가 있다')
def _no_key(parts):
    clear_topics(parts)
    parts.topics.add(TopicFields("OTT", "", ("netflix",)))


@given("주제가 하나도 없다")
def _no_topics(parts):
    parts.settings.set_openrouter_key(KEY)
    clear_topics(parts)


@when(parsers.parse('제목 "{title}"로 판별을 시험한다'))
def _probe(parts, title):
    parts.response = parts.client.post("/topics/probe", data={"title": title, "body": ""})


@then('"OTT"는 키워드 "netflix", LLM 선택, 결과 "해당"으로 표시된다')
def _ott_row(parts):
    text = row(parts, "OTT")
    assert "키워드 netflix" in text and "LLM 선택" in text and text.endswith("해당")
    assert "묻지 않음" not in text and not text.endswith("해당 안 함")


@then('"게임"은 키워드 없음, LLM에 묻지 않음, 결과 "해당 안 함"으로 표시된다')
def _game_row(parts):
    text = row(parts, "게임")
    assert "키워드 없음" in text and "LLM에 묻지 않음" in text and text.endswith("해당 안 함")


@then(parsers.re(r'결과에 "(?P<text>[^"]+)"가 표시된다'))
def _note_shown(parts, text):
    assert text in re.sub(r"\s+", " ", parts.response.text)


@then("LLM 호출은 1번이고 오늘 호출 수가 1 늘어난다")
def _one_call(parts):
    assert len(parts.llm.calls) == 1
    assert usage(parts).count_day(parts.clock.now().date()) == parts.usage_before + 1


@then("글과 발송 기록은 만들어지지 않는다")
def _nothing_created(parts):
    db = parts.db
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM articles").fetchone()["n"] == 0
        assert conn.execute("SELECT COUNT(*) AS n FROM deliveries").fetchone()["n"] == 0
    assert DeliveryRepository(db, parts.clock).count_by_status() == {}


@then(parsers.parse('오류 "{message}"가 표시된다'))
def _error_shown(parts, message):
    assert message in parts.response.text and 'class="banner error"' in parts.response.text


@then("LLM 호출은 일어나지 않는다")
def _no_calls(parts):
    assert parts.llm.calls == []
