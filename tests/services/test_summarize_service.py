from datetime import UTC, datetime, timedelta

import pytest

from rss_hub.domain.budget import BudgetBlock
from rss_hub.domain.topics import TopicFields
from rss_hub.services.ports import LlmErrorKind
from rss_hub.storage.articles import MODEL_FALLBACK, STATUS_COLLECTED, STATUS_READY
from tests.fakes.llm_client import failure, good, reply
from tests.fakes.llm_env import LlmEnv


@pytest.fixture
def env(tmp_path):
    return LlmEnv(tmp_path)


def article(env, article_id):
    return env.articles.get(article_id)


# ---------- 정상 처리 ----------


def test_a_good_answer_makes_the_article_ready(env):
    article_id = env.add_article()
    env.client.default = reply("애플, 새 폰 공개", "애플이 새 폰을 공개했다.", topics=[])
    report = env.summarizer.run()
    done = article(env, article_id)
    assert done.status == STATUS_READY
    assert (done.title_ko, done.summary_ko, done.llm_topics, done.llm_model) == (
        "애플, 새 폰 공개",
        "애플이 새 폰을 공개했다.",
        (),
        "model-a",
    )
    assert (report.ready, report.fallback, report.outage, report.blocked) == (1, 0, False, None)


def test_the_llm_request_has_the_title_and_the_plain_text_excerpt(env):
    env.add_article(
        title="Apple unveils new phone", content="<p>The <b>phone</b> lasts longer.</p>"
    )
    env.summarizer.run()
    prompt = env.client.calls[0].prompt
    assert "Title: Apple unveils new phone" in prompt
    assert prompt.endswith("Content: The phone lasts longer.")


def test_the_topics_the_llm_chose_are_recorded_and_unknown_numbers_are_dropped(env):
    first = env.topics.add(TopicFields("OTT", "스트리밍", ("netflix",)))
    second = env.topics.add(TopicFields("게임", "", ()))
    article_id = env.add_article(title="Netflix announces a drama")
    env.client.default = reply("t", "s", topics=[second, 999, str(first), True, 1.5, None, second])
    env.summarizer.run()
    assert article(env, article_id).llm_topics == (second, first)


def test_only_topics_whose_keywords_matched_are_listed_in_the_request(env):
    ott = env.topics.add(TopicFields("OTT", "스트리밍 소식", ("netflix",)))
    game = env.topics.add(TopicFields("게임", "게임 소식", ("steam",)))
    off = env.topics.add(TopicFields("꺼진 주제", "", ("netflix",)), enabled=False)
    env.add_article(title="Netflix announces a drama")
    env.client.default = reply("t", "s")
    env.summarizer.run()
    prompt = env.client.calls[0].prompt
    assert f"{ott}. OTT: 스트리밍 소식" in prompt and f"{game}. 게임" not in prompt
    assert f"{off}. 꺼진 주제" not in prompt and '"topics"' in prompt


def test_the_body_text_counts_for_the_keyword_check_but_markup_does_not(env):
    env.topics.add(TopicFields("OTT", "스트리밍", ("trailer",)))
    env.add_article(title="Weekend picks", content="<p>A new <b>trailer</b> today</p>")
    env.add_article(title="Another", content='<img src="https://x.example.com/trailer.jpg">plain')
    env.client.default = reply("t", "s")
    env.summarizer.run()
    prompts = sorted(call.prompt for call in env.client.calls)
    assert sum("Candidate topics" in prompt for prompt in prompts) == 1


def test_without_a_keyword_match_the_request_has_no_topic_part_and_nothing_is_recorded(env):
    env.topics.add(TopicFields("OTT", "스트리밍", ("netflix",)))
    article_id = env.add_article(title="Spring gardening tips")
    env.client.default = reply(
        "t", "s", topics=[1]
    )  # 모델이 멋대로 답해도 후보가 아니라서 무시한다
    env.summarizer.run()
    prompt = env.client.calls[0].prompt
    assert '"topics"' not in prompt and "Candidate topics" not in prompt
    assert article(env, article_id).llm_topics == ()


def test_the_llm_cannot_pick_a_topic_that_was_not_a_candidate(env):
    ott = env.topics.add(TopicFields("OTT", "스트리밍", ("netflix",)))
    game = env.topics.add(TopicFields("게임", "", ("steam",)))
    article_id = env.add_article(title="Netflix announces a drama")
    env.client.default = reply("t", "s", topics=[ott, game])
    env.summarizer.run()
    assert article(env, article_id).llm_topics == (ott,)


def test_a_topic_without_keywords_is_always_a_candidate(env):
    topic_id = env.topics.add(TopicFields("보안", "보안 소식", ()))
    article_id = env.add_article(title="Anything at all")
    env.client.default = reply("t", "s", topics=[topic_id])
    env.summarizer.run()
    assert f"{topic_id}. 보안: 보안 소식" in env.client.calls[0].prompt
    assert article(env, article_id).llm_topics == (topic_id,)


def test_the_candidate_check_costs_no_extra_call(env):
    env.topics.add(TopicFields("OTT", "스트리밍", ("netflix",)))
    env.topics.add(TopicFields("게임", "", ()))
    env.add_article(title="Netflix announces a drama")
    env.client.default = reply("t", "s")
    env.summarizer.run()
    assert len(env.client.calls) == 1


def test_without_enabled_topics_the_prompt_does_not_ask_for_topics_and_the_answer_has_none(env):
    article_id = env.add_article()
    env.client.default = reply("t", "s", topics=[1])
    env.summarizer.run()
    assert '"topics"' not in env.client.calls[0].prompt
    assert article(env, article_id).llm_topics == ()  # 켜진 주제가 없으니 어떤 번호도 유효하지 않다


def test_a_topic_the_user_turns_off_before_the_summary_is_not_recorded(env):
    topic_id = env.topics.add(TopicFields("OTT", "", ("phone",)))
    article_id = env.add_article()
    env.client.default = reply("t", "s", topics=[topic_id])
    env.topics.update(topic_id, TopicFields("OTT", "", ("phone",)), webhook_id=None, enabled=False)
    env.summarizer.run()
    assert article(env, article_id).llm_topics == ()


def test_a_korean_article_keeps_its_original_title(env):
    article_id = env.add_article(
        title="스프링 부트 4 마이그레이션 후기", content="<p>이전 과정을 정리했다.</p>"
    )
    env.client.default = reply("Spring Boot 4 migration", "마이그레이션 과정을 정리했다.")
    env.summarizer.run()
    done = article(env, article_id)
    assert done.title_ko == "스프링 부트 4 마이그레이션 후기"
    assert done.summary_ko == "마이그레이션 과정을 정리했다."


# ---------- 불량 응답 ----------


@pytest.mark.parametrize(
    "bad",
    [
        good("그냥 문장입니다"),
        good('{"title_ko": "제목"}'),
        reply("제목", ""),
        reply("", "요약"),
        reply("제목", "漢字가 섞인 요약"),
        reply("漢字 제목", "요약"),
        reply("제목", "We need to translate this"),
        reply("제목", "TITLE: 제목"),
        good('{"title_ko": "제목", "summary_ko": "요약"', finish="length"),
    ],
)
def test_a_bad_answer_is_rejected_and_counts_as_one_retry(env, bad):
    article_id = env.add_article()
    env.client.default = bad
    report = env.summarizer.run()
    assert (article(env, article_id).status, article(env, article_id).retry_count) == (
        STATUS_COLLECTED,
        1,
    )
    assert report.ready == 0 and report.rejected == 1


def test_the_third_bad_answer_finalizes_the_original_excerpt(env):
    article_id = env.add_article(
        title="Original title", content="<p>" + "x" * 500 + "</p>", retry_count=2
    )
    env.client.default = good("그냥 문장입니다")
    report = env.summarizer.run()
    done = article(env, article_id)
    assert done.status == STATUS_READY and done.llm_model == MODEL_FALLBACK
    assert done.title_ko == "Original title"
    assert done.summary_ko == "x" * 300 + "..."
    assert done.llm_topics is None  # 원문 발췌로 확정한 글은 주제를 판별하지 않았다
    assert report.fallback == 1


def test_a_short_article_gets_its_whole_text_as_the_fallback_without_dots(env):
    article_id = env.add_article(content="<p>짧은 본문</p>", retry_count=2)
    env.client.default = good("나쁜 응답")
    env.summarizer.run()
    assert article(env, article_id).summary_ko == "짧은 본문"


def test_success_clears_the_retry_count(env):
    article_id = env.add_article(retry_count=2)
    env.summarizer.run()
    assert (article(env, article_id).status, article(env, article_id).retry_count) == (
        STATUS_READY,
        0,
    )


def test_an_article_finalized_as_fallback_is_never_summarized_again(env):
    article_id = env.add_article(retry_count=2)
    env.client.default = good("나쁜 응답")
    env.summarizer.run()
    env.client.calls.clear()
    env.summarizer.run()
    assert env.client.calls == [] and article(env, article_id).llm_model == MODEL_FALLBACK


# ---------- 장애 ----------


def test_an_outage_leaves_the_article_untouched(env):
    article_id = env.add_article()
    env.client.default = failure(LlmErrorKind.UNAVAILABLE, 503)
    report = env.summarizer.run()
    assert (article(env, article_id).status, article(env, article_id).retry_count) == (
        STATUS_COLLECTED,
        0,
    )
    assert report.outage is True and report.rejected == 0


def test_after_an_outage_no_more_calls_are_wasted_on_the_other_articles(env):
    for _ in range(4):
        env.add_article()
    env.client.default = failure(LlmErrorKind.UNAVAILABLE, 503)
    env.summarizer.run()
    assert env.client.models_called() == ["model-a", "model-b"]  # 첫 글에서 체인을 다 돌고 멈춘다


def test_an_outage_that_lasts_past_the_wait_limit_finalizes_the_original_excerpt(env):
    article_id = env.add_article(content="<p>" + "y" * 400 + "</p>")
    env.clock.advance(minutes=61)
    env.client.default = failure(LlmErrorKind.UNAVAILABLE, 503)
    report = env.summarizer.run()
    done = article(env, article_id)
    assert (done.status, done.llm_model) == (STATUS_READY, MODEL_FALLBACK)
    assert done.summary_ko == "y" * 300 + "..."
    assert report.fallback == 1 and report.outage is True


def test_only_the_overdue_articles_are_finalized_during_an_outage(env):
    old = env.add_article()
    env.clock.advance(minutes=61)
    fresh = env.add_article()
    env.client.default = failure(LlmErrorKind.UNAVAILABLE, 503)
    env.summarizer.run()
    assert article(env, old).status == STATUS_READY
    assert article(env, fresh).status == STATUS_COLLECTED


def test_the_wait_limit_comes_from_settings(env):
    article_id = env.add_article()
    env.settings.update({"llm_wait_limit_minutes": "10"})
    env.clock.advance(minutes=11)
    env.client.default = failure(LlmErrorKind.UNAVAILABLE, 503)
    env.summarizer.run()
    assert article(env, article_id).status == STATUS_READY


# ---------- 예산 ----------


def test_a_budget_block_stops_the_run_without_touching_retry_counts(env):
    ids = [env.add_article() for _ in range(3)]
    env.record_calls(700)
    report = env.summarizer.run()
    assert report.blocked is BudgetBlock.DAILY_CAP
    assert env.client.calls == []
    assert [article(env, i).retry_count for i in ids] == [0, 0, 0]


def test_the_per_minute_cap_stops_the_run_midway(env):
    for _ in range(30):
        env.add_article()
    env.settings.update({"summarize_batch": "20"})
    report = env.summarizer.run()
    assert len(env.client.calls) == 15
    assert report.ready == 15 and report.blocked is BudgetBlock.RATE


# ---------- 순서와 양 ----------


def test_at_most_the_batch_size_is_processed_per_run(env):
    for _ in range(12):
        env.add_article()
    report = env.summarizer.run()
    assert len(env.client.calls) == 5 and report.ready == 5
    assert len(env.articles.list_by_status(STATUS_COLLECTED)) == 7


def test_the_batch_size_comes_from_settings(env):
    for _ in range(12):
        env.add_article()
    env.settings.update({"summarize_batch": "2"})
    env.summarizer.run()
    assert len(env.client.calls) == 2


def test_first_time_articles_are_processed_before_retries_and_oldest_first(env):
    a = env.add_article(published=datetime(2026, 10, 16, 10, 0, tzinfo=UTC))
    b = env.add_article(published=datetime(2026, 10, 16, 10, 30, tzinfo=UTC))
    c = env.add_article(published=datetime(2026, 10, 16, 9, 0, tzinfo=UTC), retry_count=1)
    env.settings.update({"summarize_batch": "2"})
    env.summarizer.run()
    assert (article(env, a).status, article(env, b).status, article(env, c).status) == (
        STATUS_READY,
        STATUS_READY,
        STATUS_COLLECTED,
    )


def test_nothing_to_do_makes_no_calls(env):
    report = env.summarizer.run()
    assert (report.considered, env.client.calls) == (0, [])


# ---------- 예외 격리 ----------


def test_an_unexpected_error_in_one_article_counts_as_a_retry_and_the_rest_continue(env):
    first, second, third = (env.add_article() for _ in range(3))
    env.client.will("model-a", good(), ValueError("예상하지 못한 오류"), good())
    report = env.summarizer.run()
    assert article(env, first).status == STATUS_READY
    assert (article(env, second).status, article(env, second).retry_count) == (STATUS_COLLECTED, 1)
    assert article(env, third).status == STATUS_READY
    assert report.ready == 2 and report.rejected == 1


# ---------- 설정이 비어 있을 때 ----------


def test_without_the_required_settings_the_run_waits_and_calls_nothing(tmp_path):
    env = LlmEnv(tmp_path, configured=False)
    article_id = env.add_article()
    report = env.summarizer.run()
    assert report.waiting_for_setup is True
    assert env.client.calls == []
    assert (article(env, article_id).status, article(env, article_id).retry_count) == (
        STATUS_COLLECTED,
        0,
    )


def test_once_the_settings_are_filled_the_next_run_works_without_a_restart(tmp_path):
    env = LlmEnv(tmp_path, configured=False)
    article_id = env.add_article()
    env.summarizer.run()
    env.configure()
    report = env.summarizer.run()
    assert report.waiting_for_setup is False and article(env, article_id).status == STATUS_READY


def test_old_articles_are_not_finalized_while_the_service_is_waiting_for_setup(tmp_path):
    env = LlmEnv(tmp_path, configured=False)
    article_id = env.add_article()
    env.clock.advance(hours=5)
    env.summarizer.run()
    assert article(env, article_id).status == STATUS_COLLECTED


def test_times_are_compared_in_utc(env):
    article_id = env.add_article()
    env.clock.set(datetime(2026, 10, 16, 12, 0, tzinfo=UTC) + timedelta(minutes=59))
    env.client.default = failure(LlmErrorKind.UNAVAILABLE, 503)
    env.summarizer.run()
    assert article(env, article_id).status == STATUS_COLLECTED  # 59분은 아직 허용 시간 안


def test_a_key_removed_during_the_run_makes_the_service_wait_without_changing_articles(
    env, monkeypatch
):
    from rss_hub.services.llm_gateway import LlmNotConfigured

    article_id = env.add_article()

    def key_vanished(_prompt):
        raise LlmNotConfigured

    monkeypatch.setattr(env.gateway, "complete", key_vanished)
    report = env.summarizer.run()
    assert report.waiting_for_setup is True and report.considered == 1
    assert (article(env, article_id).status, article(env, article_id).retry_count) == (
        STATUS_COLLECTED,
        0,
    )


def test_an_overdue_article_behind_the_failing_one_is_finalized_without_another_call(env):
    # 처리 순서는 발행 시각 기준(오래된 글 먼저), 대기 시간은 수집 시각 기준이라 둘이 엇갈릴 수 있다
    overdue = env.add_article(published=datetime(2026, 10, 16, 10, 30, tzinfo=UTC))
    env.clock.advance(minutes=61)
    first_in_line = env.add_article(published=datetime(2026, 10, 16, 10, 0, tzinfo=UTC))
    env.client.default = failure(LlmErrorKind.UNAVAILABLE, 503)
    report = env.summarizer.run()
    assert article(env, first_in_line).status == STATUS_COLLECTED  # 아직 기다릴 수 있다
    assert (article(env, overdue).status, article(env, overdue).llm_model) == (
        STATUS_READY,
        MODEL_FALLBACK,
    )
    assert env.client.models_called() == ["model-a", "model-b"]  # 첫 글에서만 체인을 돌았다
    assert report.fallback == 1


@pytest.mark.parametrize(("minutes", "finalized"), [(59, False), (60, True), (61, True)])
def test_the_wait_limit_boundary_is_inclusive(env, minutes, finalized):
    article_id = env.add_article()
    env.clock.advance(minutes=minutes)
    env.client.default = failure(LlmErrorKind.UNAVAILABLE, 503)
    env.summarizer.run()
    assert (article(env, article_id).status == STATUS_READY) is finalized


@pytest.mark.parametrize("missing", ["openrouter_key", "default_webhook", "service_base_url"])
def test_every_required_setting_is_needed_before_summarizing(tmp_path, missing):
    from tests.fakes.llm_env import DEFAULT_WEBHOOK, KEY

    env = LlmEnv(tmp_path, configured=False)
    article_id = env.add_article()
    if missing != "openrouter_key":
        env.settings.set_openrouter_key(KEY)
    if missing != "default_webhook":
        webhook_id = env.settings.add_webhook("기본", DEFAULT_WEBHOOK)
        env.settings.set_webhook_roles(default_id=webhook_id, system_id=None)
    if missing != "service_base_url":
        env.settings.update({"service_base_url": "https://rss.example.com"})

    report = env.summarizer.run()

    assert report.waiting_for_setup is True
    assert env.client.calls == []
    assert article(env, article_id).status == STATUS_COLLECTED


# ---------- 요약 직후 주제 소속 기록(뷰어의 주제별 목록) ----------


def test_the_topics_a_summary_confirmed_are_recorded_with_their_keywords_right_away(env):
    ott = env.topics.add(TopicFields("OTT", "스트리밍", ("netflix", "drama")))
    env.topics.add(TopicFields("게임", "", ("steam",)))
    article_id = env.add_article(title="Netflix announces a drama")
    env.client.default = reply("t", "s", topics=[ott])
    env.summarizer.run()
    assert env.topics.matches_for(article_id) == {ott: ("netflix", "drama")}


def test_nothing_is_recorded_when_no_topic_is_confirmed(env):
    env.topics.add(TopicFields("OTT", "스트리밍", ("netflix",)))
    article_id = env.add_article(title="Netflix announces a drama")
    env.client.default = reply("t", "s", topics=[])
    env.summarizer.run()
    assert env.topics.matches_for(article_id) == {}


def test_a_topic_without_keywords_is_recorded_with_an_empty_keyword_list(env):
    topic_id = env.topics.add(TopicFields("보안", "", ()))
    article_id = env.add_article(title="Anything")
    env.client.default = reply("t", "s", topics=[topic_id])
    env.summarizer.run()
    assert env.topics.matches_for(article_id) == {topic_id: ()}


def test_a_failed_summary_records_no_topics(env):
    env.topics.add(TopicFields("OTT", "", ("netflix",)))
    article_id = env.add_article(title="Netflix announces a drama")
    env.client.default = good("이건 JSON이 아닙니다")
    env.summarizer.run()
    assert env.topics.matches_for(article_id) == {}
