"""04_topic_judgement.feature: 주제 판정(LLM 확인 + 키워드 보완)."""

from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, then, when

from rss_hub.domain.keywords import DEFAULT_OTT_KEYWORDS
from rss_hub.domain.topics import Topic, match_topic
from tests.bdd.binding import bind

bind(
    globals(), "04_topic_judgement.feature", [f"TPC-{n:02d}" for n in (*range(1, 7), *range(8, 12))]
)

LLM_FLAGS = {"맞음": True, "아님": False, "없음": None}


@pytest.fixture
def ctx():
    return SimpleNamespace(topics={}, title="", content="", llm_ids=None, result=None, found=None)


def make_topic(ctx, name, keywords):
    ctx.topics[name] = Topic(len(ctx.topics) + 1, name, "", tuple(keywords), None)


@given('주제 "OTT"가 있고 기본 OTT 키워드가 등록되어 있다')
def _ott_topic(ctx):
    make_topic(ctx, "OTT", (*DEFAULT_OTT_KEYWORDS.ko, *DEFAULT_OTT_KEYWORDS.en))


@given(parsers.parse('글의 제목은 "{title}"이고 본문은 비어 있다'))
def _title_empty_body(ctx, title):
    ctx.title, ctx.content = title, ""


@given(parsers.parse('글의 제목은 "{title}"이고 LLM의 "OTT" 주제 판정은 맞음이다'))
def _title_llm_yes(ctx, title):
    ctx.title, ctx.llm_ids = title, {ctx.topics["OTT"].id}


@given(parsers.parse('LLM의 "OTT" 주제 판정은 {flag}이다'))
def _llm_flag(ctx, flag):
    value = LLM_FLAGS[flag]
    ctx.llm_ids = None if value is None else ({ctx.topics["OTT"].id} if value else set())


@given(parsers.parse("글의 본문은 '{content}'이다"))
@given(parsers.parse('글의 본문은 "{content}"이다'))
def _content(ctx, content):
    ctx.content = content


@given(parsers.parse('주제 "OTT"의 키워드에 "{keyword}"를 추가했다'))
def _add_keyword(ctx, keyword):
    ott = ctx.topics["OTT"]
    ctx.topics["OTT"] = Topic(ott.id, ott.name, ott.description, (*ott.keywords, keyword), None)


@given('주제 "OTT"의 키워드가 비어 있다')
def _no_keywords(ctx):
    ott = ctx.topics["OTT"]
    ctx.topics["OTT"] = Topic(ott.id, ott.name, ott.description, (), None)


@given(parsers.parse('주제 "게임"이 있고 키워드는 "{keyword}"이다'))
def _game_topic(ctx, keyword):
    make_topic(ctx, "게임", (keyword,))


@given(parsers.parse('글의 제목은 "{title}"이고 LLM이 "OTT"와 "게임" 주제를 골랐다'))
def _llm_both(ctx, title):
    ctx.title, ctx.llm_ids = title, {ctx.topics["OTT"].id, ctx.topics["게임"].id}


@given(parsers.parse('글의 제목은 "{title}"이고 LLM이 "게임" 주제만 골랐다'))
def _llm_game_only(ctx, title):
    ctx.title, ctx.llm_ids = title, {ctx.topics["게임"].id}


@when('주제 "OTT" 해당 여부를 판단한다')
def _judge(ctx):
    ctx.result = match_topic(ctx.topics["OTT"], ctx.llm_ids, ctx.title, ctx.content) is not None


@when("해당하는 주제를 모두 찾는다")
def _find_all(ctx):
    ctx.found = [
        name
        for name, topic in ctx.topics.items()
        if match_topic(topic, ctx.llm_ids, ctx.title, ctx.content) is not None
    ]


@then(parsers.parse("결과는 {answer}이다"))
def _expect(ctx, answer):
    assert ctx.result is {"참": True, "거짓": False}[answer]


@then('해당 주제는 "OTT"와 "게임"이다')
def _both(ctx):
    assert ctx.found == ["OTT", "게임"]


@then('해당 주제는 "게임"뿐이다')
def _game_only(ctx):
    assert ctx.found == ["게임"]
