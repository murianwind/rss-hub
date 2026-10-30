"""03_summarization.feature 전체: 실제 SQLite와 가짜 LLM으로 요약 서비스를 실행한다."""

from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, then, when

from rss_hub.domain.korean import is_korean
from rss_hub.domain.text import strip_html
from rss_hub.domain.topics import TopicFields
from rss_hub.services.ports import LlmErrorKind
from rss_hub.storage.articles import MODEL_FALLBACK, STATUS_COLLECTED
from tests.bdd.binding import bind
from tests.fakes.llm_client import failure as llm_failure
from tests.fakes.llm_client import good, reply
from tests.fakes.llm_env import LlmEnv

bind(globals(), "03_summarization.feature", [f"SUM-{n:02d}" for n in range(1, 23)])


@pytest.fixture
def env(tmp_path):
    return LlmEnv(tmp_path)


@pytest.fixture
def ctx():
    return SimpleNamespace(article_id=None, report=None, text="", korean=None, targets=None, ids={})


def article(env, ctx):
    return env.articles.get(ctx.article_id)


BAD_RESPONSES = {
    "JSON이 아닌 문장 형태의": good("그냥 문장입니다"),
    "필수 항목이 빠진 JSON": good('{"title_ko": "제목"}'),
    "요약이 빈 문자열인": reply("제목", ""),
    "제목이 빈 문자열인": reply("", "요약"),
    "요약에 한자가 섞인": reply("제목", "漢字가 섞인 요약"),
    "제목에 한자가 섞인": reply("漢字 제목", "요약"),
    '"We need to translate"로 시작하는 사고 과정이 담긴': reply(
        "제목", "We need to translate this"
    ),
    '"Korean summary"라는 문구가 담긴': reply("제목", "Korean summary: 요약"),
    '"TITLE:" 같은 형식 표지가 본문에 남아 있는': reply("제목", "TITLE: 제목"),
    "길이 제한으로 잘린(finish_reason이 length인)": good(
        '{"title_ko": "제목", "summary_ko": "요약", "topics": []}', finish="length"
    ),
    "불량": good("그냥 문장입니다"),
    "정상": reply("애플, 새 폰 공개", "애플이 새 폰을 공개했다."),
}


# ---------- 배경 ----------


@given("한 번 실행에서 처리하는 최대 글 수는 5이다 (설정값, 기본 5)")
def _batch_default(env):
    assert env.settings.snapshot().summarize_batch == 5


CONTRACT = (
    'LLM은 JSON으로 "title_ko", "summary_ko"를 답하고, 주제가 있으면 "topics"도 답하도록 요청받는다'
)


@given(CONTRACT)
def _json_contract():
    """요청 프롬프트(domain/prompts.py)가 이 항목들을 요구한다(SUM-15, 17에서 확인)."""


# ---------- 글 준비 ----------


@given(parsers.parse('영문 글 "{title}"이 수집되어 있다'))
def _english_article(env, ctx, title):
    ctx.article_id = env.add_article(title=title)


@given("영문 글이 수집되어 있다")
def _english_article_plain(env, ctx):
    ctx.article_id = env.add_article()


@given(parsers.re(r'제목이 "(?P<title>[^"]+)"인 영문 글이 수집되어 있다'))
def _english_article_titled(env, ctx, title):
    ctx.article_id = env.add_article(title=title)


@given(parsers.parse('한국어 글 "{title}"가 수집되어 있다'))
def _korean_article(env, ctx, title):
    ctx.article_id = env.add_article(
        title=title, content="<p>마이그레이션 과정을 정리했습니다.</p>"
    )


@given(parsers.parse("영문 글이 수집되어 있고 재시도 횟수는 {count:d}이다"))
@given(parsers.parse("영문 글의 재시도 횟수는 {count:d}이다"))
def _article_with_retries(env, ctx, count):
    ctx.article_id = env.add_article(retry_count=count)


@given(parsers.parse("글의 본문은 HTML을 제거하면 {size:d}자이다"))
def _content_size(env, ctx, size):
    env.set_content(ctx.article_id, "<p>" + "가" * size + "</p>")


@given("글의 본문이 HTML 태그를 포함한 3000자이다")
def _long_content(env, ctx):
    ctx.article_id = env.add_article(content="<p>" + "가" * 3000 + "</p>")


@given(parsers.parse("요약 대상 글이 {count:d}개 있다"))
def _many_articles(env, ctx, count):
    ctx.ids = [env.add_article() for _ in range(count)]


@given("요약 대상 글 3개가 있고 두 번째 글에서 예상하지 못한 예외가 난다")
def _three_with_exception(env, ctx):
    ctx.ids = [env.add_article() for _ in range(3)]
    env.client.will("model-a", good(), ValueError("예상하지 못한 오류"), good())


@given(parsers.parse('사용 모델이 "{model}"인 글이 있다'))
def _fallback_article(env, ctx, model):
    assert model == MODEL_FALLBACK
    ctx.article_id = env.add_article()
    env.articles.finalize_fallback(ctx.article_id, title_ko="원문 제목", summary_ko="원문 발췌")


@given("영문 글이 수집된 지 61분이 지났다")
def _stale_article(env, ctx):
    ctx.article_id = env.add_article()
    env.clock.advance(minutes=61)


@given("대기 허용 시간은 60분이다")
def _wait_limit(env):
    assert env.settings.snapshot().llm_wait_limit_minutes == 60


# ---------- LLM 응답 ----------


@given(parsers.parse('LLM이 제목 "{title}", 요약 "{summary}", 해당 주제 없음으로 답한다'))
def _llm_answers_no_topic(env, title, summary):
    env.client.default = reply(title, summary, topics=[])


@given(parsers.parse('LLM이 제목 "{title}"과 요약 "{summary}"로 답한다'))
def _llm_answers(env, title, summary):
    env.client.default = reply(title, summary)


@given(parsers.re(r"LLM이 (?P<kind>.+) 응답을 준다"))
def _llm_gives(env, kind):
    env.client.default = BAD_RESPONSES[kind]


@given('LLM이 제목과 요약만 있고 "topics"가 없는 JSON으로 답한다')
def _llm_without_topics(env):
    env.client.default = reply("제목", "요약", topics=None)


@given("모든 모델이 한도 초과(429) 또는 서버 오류로 응답하지 못한다")
def _all_models_down(env):
    rate = llm_failure(LlmErrorKind.RATE_LIMITED, 429)
    env.client.will("model-a", rate, rate)
    env.client.will("model-b", llm_failure(LlmErrorKind.UNAVAILABLE, 503))


@given("모든 모델이 응답하지 못한다")
def _all_models_unavailable(env):
    env.client.default = llm_failure(LlmErrorKind.UNAVAILABLE, 503)


# ---------- 실행 ----------


@when("요약 작업을 실행한다")
def _run(env, ctx):
    ctx.report = env.summarizer.run()


@when("한국어 글인지 판별한다")
def _judge_korean(ctx):
    ctx.korean = is_korean(ctx.text)


@when("요약 대상 글을 고른다")
def _choose_targets(env, ctx):
    ctx.targets = env.summarizer.pending(5)


@when("처리 대상 순서를 정한다")
def _order(env, ctx):
    ctx.targets = env.summarizer.pending(10)


# ---------- 결과 ----------


@then(parsers.parse('글의 번역 제목은 "{title}"이다'))
def _title_is(env, ctx, title):
    assert article(env, ctx).title_ko == title


@then("글의 번역 제목은 원문 제목이다")
def _title_is_original(env, ctx):
    done = article(env, ctx)
    assert done.title_ko == done.title


@then(parsers.parse('글의 요약은 "{summary}"이다'))
def _summary_is(env, ctx, summary):
    assert article(env, ctx).summary_ko == summary


@then("글의 주제 판정은 없음으로 기록된다")
def _no_topic_recorded(env, ctx):
    assert article(env, ctx).llm_topics == ()


@then(parsers.parse("LLM 호출은 {count:d}번이다"))
def _calls_exactly(env, count):
    assert len(env.client.calls) == count


@then(parsers.parse("LLM 호출은 최대 {count:d}번이다"))
def _calls_at_most(env, count):
    assert 0 < len(env.client.calls) <= count


@then("사용한 모델 이름이 글에 기록된다")
def _model_recorded(env, ctx):
    assert article(env, ctx).llm_model == "model-a"


@then("LLM 요청에 HTML 태그는 없다")
def _no_html_in_prompt(env):
    assert "<p>" not in env.client.calls[0].prompt and "</p>" not in env.client.calls[0].prompt


@then(parsers.parse("LLM 요청의 본문 길이는 {size:d}자이다"))
def _prompt_content_length(env, size):
    content = env.client.calls[0].prompt.split("Content: ", 1)[1]
    assert len(content) == size


@then("응답은 채택되지 않는다")
def _not_adopted(env, ctx):
    done = article(env, ctx)
    assert (done.summary_ko, done.title_ko, done.llm_model) == (None, None, None)


@then(parsers.parse("글의 재시도 횟수는 {count:d}이다"))
def _retry_count(env, ctx, count):
    assert article(env, ctx).retry_count == count


@then(parsers.parse('글의 상태는 "{status}"로 남는다'))
def _stays(env, ctx, status):
    assert article(env, ctx).status == status == STATUS_COLLECTED


@then(parsers.parse('글의 상태는 "{status}"이다'))
def _status_is(env, ctx, status):
    assert article(env, ctx).status == status


@then('글은 원문 발췌로 확정되고 상태는 "ready"가 된다')
def _finalized(env, ctx):
    done = article(env, ctx)
    assert (done.status, done.llm_model) == ("ready", MODEL_FALLBACK)


@then('글의 요약은 본문 앞 300자에 "..."을 붙인 값이다')
def _fallback_summary(env, ctx):
    plain = strip_html(article(env, ctx).content_html)
    assert article(env, ctx).summary_ko == plain[:300] + "..."


@then(parsers.parse('사용한 모델은 "{model}"로 기록된다'))
def _model_is(env, ctx, model):
    assert article(env, ctx).llm_model == model


@then("이 글은 대상에 포함되지 않는다")
def _not_a_target(ctx):
    assert ctx.targets == []


@then("순서는 A, B, C이다")
def _order_is(env, ctx):
    assert [t.id for t in ctx.targets] == [ctx.ids["A"], ctx.ids["B"], ctx.ids["C"]]


@then(parsers.parse("나머지 {count:d}개는 다음 실행으로 남는다"))
def _rest_wait(env, count):
    assert len(env.articles.list_by_status(STATUS_COLLECTED)) == count


@then("첫 번째와 세 번째 글은 정상 처리된다")
def _first_and_third_done(env, ctx):
    first, _, third = ctx.ids
    assert env.articles.get(first).status == "ready" and env.articles.get(third).status == "ready"


@then(parsers.parse("두 번째 글의 재시도 횟수는 {count:d}이다"))
def _second_retry(env, ctx, count):
    assert env.articles.get(ctx.ids[1]).retry_count == count


# ---------- SUM-02: 한국어 판별 ----------


@given(parsers.parse('글의 제목과 본문을 합친 텍스트가 "{text}"이다'))
def _text_is(ctx, text):
    ctx.text = text


@then(parsers.parse("판별 결과는 {answer}이다"))
def _korean_is(ctx, answer):
    assert ctx.korean is (answer == "참")


# ---------- SUM-12: 글 A, B, C ----------


@given("재시도 횟수 0인 글 A(10:00 발행)와 B(10:30 발행)가 있다")
def _a_and_b(env, ctx):
    from datetime import UTC, datetime

    ctx.ids = {
        "A": env.add_article(published=datetime(2026, 10, 16, 10, 0, tzinfo=UTC)),
        "B": env.add_article(published=datetime(2026, 10, 16, 10, 30, tzinfo=UTC)),
    }


@given("재시도 횟수 1인 글 C(09:00 발행)가 있다")
def _c(env, ctx):
    from datetime import UTC, datetime

    ctx.ids["C"] = env.add_article(
        published=datetime(2026, 10, 16, 9, 0, tzinfo=UTC), retry_count=1
    )


# ---------- 주제 판별 (SUM-15 ~ 17) ----------


@given(parsers.parse('주제 "OTT"(설명 "{description}")와 주제 "게임"이 있다'))
def _topics_on(env, description):
    env.topics.add(TopicFields("OTT", description, ("netflix",)))
    env.topics.add(TopicFields("게임", "", ("steam",)))


@given(parsers.parse('LLM이 주제 번호로 1, 99, "2", true를 답한다'))
def _llm_topic_numbers(env):
    env.client.default = reply("제목", "요약", topics=[1, 99, "2", True])


@given("LLM이 주제 번호로 1, 2를 답한다")
def _llm_topic_one_and_two(env):
    env.client.default = reply("제목", "요약", topics=[1, 2])


@given("LLM이 주제 번호로 1을 답한다")
def _llm_topic_one(env):
    env.client.default = reply("제목", "요약", topics=[1])


@given(parsers.re(r'키워드가 없는 주제 "(?P<name>[^"]+)"\(설명 "(?P<description>[^"]+)"\)이 있다'))
def _keywordless_topic(env, name, description):
    env.topics.add(TopicFields(name, description, ()))


@then(parsers.re(r'글의 주제 판정은 "(?P<name>[^"]+)"뿐이다'))
def _only_topic(env, ctx, name):
    names = {t.id: t.name for t in env.topics.list_all()}
    assert [names[i] for i in article(env, ctx).llm_topics] == [name]


@then(parsers.re(r'요청에 "(?P<text>[^"]+)"이 들어 있다'))
def _prompt_has(env, text):
    assert text in env.client.calls[0].prompt


@then(parsers.re(r'요청에 키워드가 맞지 않은 주제 "(?P<text>[^"]+)"은 들어 있지 않다'))
def _prompt_lacks_unmatched(env, text):
    assert text not in env.client.calls[0].prompt


@then('글의 주제 판정은 "OTT"와 "게임"이다')
def _topics_recorded(env, ctx):
    names = {t.id: t.name for t in env.topics.list_all()}
    assert [names[i] for i in article(env, ctx).llm_topics] == ["OTT", "게임"]


@then(parsers.parse('요청에 "{text}"가 들어 있지 않다'))
def _prompt_lacks(env, text):
    assert text not in env.client.calls[0].prompt


@given("첫 모델은 쓸 수 없는 응답을 주고 둘째 모델은 정상 응답을 준다")
def _first_bad_second_good(env):
    env.client.will("model-a", BAD_RESPONSES["불량"])
    env.client.will("model-b", BAD_RESPONSES["정상"])


@then("글은 둘째 모델의 요약으로 확정된다")
def _second_model_summary(env, ctx):
    saved = article(env, ctx)
    assert saved.status == "ready" and saved.llm_model == "model-b"
