import pytest

from rss_hub.domain.topics import TopicFields
from rss_hub.services.ports import LlmErrorKind
from rss_hub.services.topic_probe import MAX_BODY_LENGTH, MAX_TITLE_LENGTH, MIN_INTERVAL, TopicProbe
from tests.fakes.llm_client import failure, good, reply
from tests.fakes.llm_env import LlmEnv

MATCHING_TITLE = "Netflix announces a new drama"  # 주제 OTT의 키워드(netflix)가 맞는 제목


@pytest.fixture
def env(tmp_path):
    return LlmEnv(tmp_path)


@pytest.fixture
def probe(env):
    return TopicProbe(gateway=env.gateway, topics=env.topics, clock=env.clock)


def add_topics(env):
    ott = env.topics.add(TopicFields("OTT", "스트리밍 소식", ("netflix", "드라마")))
    game = env.topics.add(TopicFields("게임", "게임 소식", ("steam",)))
    return ott, game


def calls_today(env):
    return env.usage.count_day(env.clock.now().date())


# ---------- 키워드가 먼저 거르고, LLM은 후보만 확인한다 ----------


def test_only_the_topic_whose_keywords_matched_is_asked_about(env, probe):
    ott, _ = add_topics(env)
    env.client.default = reply("넷플릭스 신작", "요약입니다.", topics=[ott])
    result = probe.run(MATCHING_TITLE)
    assert (result.title_ko, result.summary_ko, result.model) == (
        "넷플릭스 신작",
        "요약입니다.",
        "model-a",
    )
    assert result.llm_called is True
    ott_row, game_row = result.rows
    assert (ott_row.name, ott_row.asked, ott_row.chosen, ott_row.keyword_hits, ott_row.matched) == (
        "OTT",
        True,
        True,
        ("netflix",),
        True,
    )
    assert (game_row.asked, game_row.chosen, game_row.keyword_hits, game_row.matched) == (
        False,
        False,
        (),
        False,
    )


def test_a_candidate_the_llm_does_not_confirm_is_shown_as_not_matching(env, probe):
    add_topics(env)
    env.client.default = reply("t", "s", topics=[])
    row = probe.run(MATCHING_TITLE).rows[0]
    assert (row.asked, row.chosen, row.keyword_hits, row.matched) == (
        True,
        False,
        ("netflix",),
        False,
    )


def test_the_llm_cannot_choose_a_topic_that_was_not_a_candidate(env, probe):
    ott, game = add_topics(env)
    env.client.default = reply("t", "s", topics=[ott, game, 999])
    assert [(r.asked, r.matched) for r in probe.run(MATCHING_TITLE).rows] == [
        (True, True),
        (False, False),
    ]


def test_the_body_is_searched_for_keywords_too(env, probe):
    ott, _ = add_topics(env)
    env.client.default = reply("t", "s", topics=[ott])
    row = probe.run("Weekend picks", "<p>A new <b>드라마</b> starts tonight</p>").rows[0]
    assert row.keyword_hits == ("드라마",) and row.matched is True


def test_a_topic_without_keywords_is_always_asked_about(env, probe):
    topic_id = env.topics.add(TopicFields("보안", "", ()))
    env.client.default = reply("t", "s", topics=[topic_id])
    row = probe.run("Anything at all").rows[0]
    assert (row.asked, row.matched) == (True, True)


def test_when_no_topic_is_a_candidate_the_llm_is_not_called_at_all(env, probe):
    add_topics(env)
    before = calls_today(env)
    result = probe.run("Spring gardening tips")
    assert result.llm_called is False and result.error == "" and env.client.calls == []
    assert [(r.asked, r.matched) for r in result.rows] == [(False, False), (False, False)]
    assert calls_today(env) == before


def test_the_request_lists_only_the_candidate_topics(env, probe):
    add_topics(env)
    probe.run(MATCHING_TITLE)
    prompt = env.client.calls[0].prompt
    assert "Candidate topics:\n1. OTT: 스트리밍 소식" in prompt and "게임" not in prompt
    assert "Title: Netflix announces a new drama" in prompt


def test_the_probe_costs_exactly_one_llm_call_and_creates_nothing(env, probe):
    ott, _ = add_topics(env)
    env.client.default = reply("t", "s", topics=[ott])
    before = calls_today(env)
    probe.run(MATCHING_TITLE)
    assert len(env.client.calls) == 1 and calls_today(env) == before + 1
    assert env.articles.count_by_status() == {} and env.topics.matches_for(1) == {}


def test_disabled_topics_are_not_candidates(env, probe):
    ott, _game = add_topics(env)
    env.topics.update(
        ott, TopicFields("OTT", "스트리밍 소식", ("netflix",)), webhook_id=None, enabled=False
    )
    result = probe.run(MATCHING_TITLE)
    assert [r.name for r in result.rows] == ["게임"] and result.llm_called is False


def test_the_webhook_a_matching_topic_would_use_is_reported(env, probe):
    webhook_id = env.settings.add_webhook("ott방", "https://discord.com/api/webhooks/5/abc")
    topic_id = env.topics.add(TopicFields("OTT", "", ("netflix",)), webhook_id=webhook_id)
    env.client.default = reply("t", "s", topics=[topic_id])
    assert probe.run(MATCHING_TITLE).rows[0].webhook_id == webhook_id


# ---------- 시험하지 못하는 경우 ----------


def test_a_missing_key_is_explained_and_nothing_is_called(tmp_path):
    env = LlmEnv(tmp_path, configured=False)
    env.topics.add(TopicFields("OTT", "", ("netflix",)))
    result = TopicProbe(gateway=env.gateway, topics=env.topics, clock=env.clock).run(MATCHING_TITLE)
    assert "키가 설정되지 않았습니다" in result.error and env.client.calls == []


def test_without_enabled_topics_there_is_nothing_to_test(env, probe):
    assert "켜진 주제가 없습니다" in probe.run("x").error and env.client.calls == []


def test_the_daily_limit_blocks_the_probe_with_a_reason(env, probe):
    add_topics(env)
    env.settings.update({"llm_daily_cap": "1"})
    probe.run(MATCHING_TITLE)
    env.clock.advance(seconds=MIN_INTERVAL.seconds + 1)
    assert "한도에 도달" in probe.run(MATCHING_TITLE).error


@pytest.mark.parametrize(
    ("kind", "status", "expected"),
    [
        (LlmErrorKind.UNAVAILABLE, 503, "모든 모델이 응답하지 않았습니다"),
        (LlmErrorKind.OTHER, 400, "모든 모델이 응답하지 않았습니다"),
        (LlmErrorKind.UNAUTHORIZED, 401, "키를 거부했습니다"),
        (LlmErrorKind.PAYMENT_REQUIRED, 402, "잔액이 부족합니다"),
    ],
)
def test_the_reason_every_model_failed_is_explained_when_the_user_can_fix_it(
    env, probe, kind, status, expected
):
    add_topics(env)
    env.client.default = failure(kind, status=status)
    assert expected in probe.run(MATCHING_TITLE).error


def test_a_rate_limited_chain_asks_the_user_to_wait(env, probe):
    add_topics(env)
    env.client.default = failure(LlmErrorKind.RATE_LIMITED, status=429)
    assert "잠시 뒤에 다시 시도하세요" in probe.run(MATCHING_TITLE).error


def test_an_unusable_answer_is_reported_with_the_model_that_gave_it(env, probe):
    add_topics(env)
    env.client.default = good("이건 JSON이 아닙니다")
    result = probe.run(MATCHING_TITLE)
    assert "모델의 응답을 사용할 수 없습니다" in result.error and result.model == "model-a"


def test_a_second_probe_within_the_interval_is_refused_without_a_call(env, probe):
    add_topics(env)
    probe.run(MATCHING_TITLE)
    assert "잠시 뒤에 다시" in probe.run(MATCHING_TITLE).error and len(env.client.calls) == 1
    env.clock.advance(seconds=MIN_INTERVAL.seconds)
    assert probe.run(MATCHING_TITLE).error == ""


def test_a_probe_that_called_nothing_does_not_start_the_interval(env, probe):
    add_topics(env)
    probe.run("Spring gardening tips")
    assert probe.run(MATCHING_TITLE).error == ""


@pytest.mark.parametrize(
    ("title", "body", "message"),
    [
        ("", "", "제목을 입력하세요"),
        ("   ", "", "제목을 입력하세요"),
        ("가" * (MAX_TITLE_LENGTH + 1), "", "제목은 300자까지"),
        ("t", "가" * (MAX_BODY_LENGTH + 1), "본문은 5000자까지"),
    ],
)
def test_input_limits_are_checked_before_any_call(env, probe, title, body, message):
    add_topics(env)
    assert probe.run(title, body).error == message and env.client.calls == []


def test_the_limits_are_inclusive(env, probe):
    add_topics(env)
    assert probe.run("netflix" + "가" * (MAX_TITLE_LENGTH - 7), "나" * MAX_BODY_LENGTH).error == ""
