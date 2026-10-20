import logging
from datetime import UTC, datetime

import pytest

from rss_hub.domain.topics import TopicFields
from rss_hub.services.ports import SendResult
from tests.fakes.delivery_env import DeliveryEnv, ok, webhook_url


@pytest.fixture
def env(tmp_path):
    return DeliveryEnv(tmp_path)


def http(status, retry_after=None):
    return SendResult(status, retry_after=retry_after)


# ---------- 기본 발송 ----------


def test_a_ready_article_is_sent_to_the_default_webhook_and_becomes_delivered(env):
    article_id = env.add_ready_article()
    report = env.service.run()
    assert env.sender.to("rss") == [
        "📢 **[Blog] 새 글 알림** `14:32`\n**새 아이폰 배터리**\n배터리가 커졌다.\n"
        f"🔗 [글 읽기](https://rss.example.com/a/{article_id})"
    ]
    assert env.article(article_id).status == "delivered"
    assert env.statuses(article_id) == {"rss:primary": "sent"}
    assert (report.sent, report.delivered) == (1, 1)


def test_the_message_id_discord_returned_is_kept(env):
    article_id = env.add_ready_article()
    env.sender.will(webhook_url("rss"), ok("1234567890"))
    env.service.run()
    assert env.deliveries.for_article(article_id)[0].message_id == "1234567890"


def test_the_link_is_the_service_page_and_never_the_original_address(env):
    env.add_ready_article()
    env.service.run()
    assert "https://example.com/original" not in env.sender.to("rss")[0]


def test_only_ready_articles_are_sent(env):
    collected = env.add_ready_article(status="collected")
    ready = env.add_ready_article()
    env.service.run()
    assert env.article(collected).status == "collected"
    assert env.article(ready).status == "delivered"
    assert len(env.sender.calls) == 1


def test_a_delivered_article_is_not_sent_again(env):
    env.add_ready_article()
    env.service.run()
    env.service.run()
    assert len(env.sender.calls) == 1


def test_the_fallback_excerpt_is_sent_like_any_summary(env):
    article_id = env.add_ready_article(title_ko="Original title", summary_ko="x" * 300 + "...")
    env.service.run()
    assert env.article(article_id).status == "delivered"
    assert "x" * 300 + "..." in env.sender.to("rss")[0]


def test_the_header_uses_the_feed_name_and_emoji(env):
    feed = env.add_feed("Gizmodo", emoji="🧪")
    env.add_ready_article(feed_id=feed)
    env.service.run()
    assert env.sender.to("rss")[0].startswith("🧪 **[Gizmodo] 새 글 알림**")


def test_the_time_is_shown_in_the_service_timezone(env):
    env.add_ready_article(published=datetime(2026, 10, 16, 5, 32, tzinfo=UTC))
    env.settings.update({"service_timezone": "UTC"})
    env.service.run()
    assert "`05:32`" in env.sender.to("rss")[0]


# ---------- 라우팅 ----------


def test_a_category_without_a_webhook_falls_back_to_the_default_webhook(env):
    category = env.feeds.add_category("뉴스")
    feed = env.add_feed("N", category=category)
    env.add_ready_article(feed_id=feed)
    env.service.run()
    assert (len(env.sender.to("rss")), len(env.sender.to("dev"))) == (1, 0)


def test_the_category_webhook_wins_over_the_default_webhook(env):
    category = env.feeds.add_category("뉴스", webhook_id=env.webhooks["dev"])
    feed = env.add_feed("G", category=category)
    env.add_ready_article(feed_id=feed)
    env.service.run()
    assert (len(env.sender.to("dev")), len(env.sender.to("rss"))) == (1, 0)


def test_the_category_webhook_is_used_when_the_feed_has_none(env):
    category = env.feeds.add_category("뉴스", webhook_id=env.webhooks["dev"])
    feed = env.add_feed("N", category=category)
    env.add_ready_article(feed_id=feed)
    env.service.run()
    assert len(env.sender.to("dev")) == 1 and env.sender.to("rss") == []


def test_an_article_on_a_topic_also_goes_to_the_topic_webhook(env):
    article_id = env.add_ready_article(
        title="Netflix announces a new movie", content="<p>trailer</p>", topics=("OTT",)
    )
    env.service.run()
    assert (len(env.sender.to("rss")), len(env.sender.to("ott"))) == (1, 1)
    assert env.statuses(article_id) == {"rss:primary": "sent", "ott:topic:OTT": "sent"}


def test_the_llm_choice_alone_is_not_enough_when_the_topic_has_keywords(env):
    env.add_ready_article(title="Gardening tips", content="<p>roses</p>", topics=("OTT",))
    env.service.run()
    assert env.sender.to("ott") == []


def test_a_keyword_alone_is_not_enough_without_the_llm_choice(env):
    env.add_ready_article(title="Netflix movie", topics=())
    env.service.run()
    assert env.sender.to("ott") == []


def test_a_topic_without_keywords_follows_the_llm_alone(env):
    env.add_topic("게임", (), webhook="gizmodo")
    env.add_ready_article(title="Anything at all", topics=("게임",))
    env.service.run()
    assert len(env.sender.to("gizmodo")) == 1


def test_a_disabled_topic_sends_nothing_extra(env):
    env.add_topic("게임", (), webhook="gizmodo", enabled=False)
    env.add_ready_article(title="Anything", topics=("게임",))
    env.service.run()
    assert env.sender.to("gizmodo") == []


def test_topics_are_read_when_delivering_so_a_topic_turned_off_since_the_summary_is_skipped(env):
    env.add_ready_article(title="Netflix movie", topics=("OTT",))
    ott = env.topics.get(env.topic_id("OTT"))
    env.topics.update(
        ott.id,
        TopicFields(ott.name, ott.description, ott.keywords),
        webhook_id=ott.webhook_id,
        enabled=False,
    )
    env.service.run()
    assert env.sender.to("ott") == [] and len(env.sender.to("rss")) == 1


def test_a_topic_without_a_webhook_sends_nothing_extra_but_the_match_is_recorded(env):
    topic_id = env.add_topic("보안", ("cve",))
    article_id = env.add_ready_article(title="New CVE found", topics=("보안",))
    env.service.run()
    assert len(env.sender.calls) == 1
    assert env.topics.matches_for(article_id) == {topic_id: ("cve",)}


def test_the_matched_keywords_are_recorded_for_every_topic_the_article_matched(env):
    game = env.add_topic("게임", ("steam",), webhook="gizmodo")
    article_id = env.add_ready_article(title="Netflix trailer on Steam", topics=("OTT", "게임"))
    env.service.run()
    matches = env.topics.matches_for(article_id)
    assert matches[game] == ("steam",)
    assert set(matches[env.topic_id("OTT")]) == {"netflix", "trailer"}


def test_matches_are_not_recorded_while_delivery_is_on_hold(tmp_path):
    env = DeliveryEnv(tmp_path)
    env.settings.set_webhook_roles(default_id=None, system_id=None)
    article_id = env.add_ready_article(title="Netflix movie", topics=("OTT",))
    env.service.run()
    assert env.topics.matches_for(article_id) == {}


def test_a_topic_webhook_equal_to_the_default_webhook_receives_one_message(env):
    env.add_topic("게임", (), webhook="rss")
    env.add_ready_article(topics=("게임",))
    env.service.run()
    assert len(env.sender.to("rss")) == 1


def test_a_topic_webhook_equal_to_the_category_webhook_receives_one_message(env):
    category = env.feeds.add_category("뉴스", webhook_id=env.webhooks["dev"])
    env.add_topic("게임", (), webhook="dev")
    env.add_ready_article(feed_id=env.add_feed("N", category=category), topics=("게임",))
    env.service.run()
    assert (len(env.sender.to("dev")), len(env.sender.to("rss"))) == (1, 0)


def test_two_topics_sharing_a_webhook_send_one_extra_message(env):
    env.add_topic("게임", (), webhook="gizmodo")
    env.add_topic("만화", (), webhook="gizmodo")
    env.add_ready_article(topics=("게임", "만화"))
    env.service.run()
    assert len(env.sender.to("gizmodo")) == 1


def test_topics_with_different_webhooks_each_send_one_extra_message(env):
    env.add_topic("게임", (), webhook="gizmodo")
    env.add_topic("보안", (), webhook="dev")
    env.add_ready_article(topics=("게임", "보안"))
    env.service.run()
    assert (
        len(env.sender.to("gizmodo")),
        len(env.sender.to("dev")),
        len(env.sender.to("rss")),
    ) == (1, 1, 1)


def test_an_article_without_any_topic_goes_only_to_the_primary_webhook(env):
    env.add_ready_article(title="Netflix movie", topics=())
    env.service.run()
    assert env.sender.to("ott") == [] and len(env.sender.to("rss")) == 1


def test_a_topic_whose_webhook_is_the_primary_one_does_not_send_twice(env):
    category = env.feeds.add_category("영화", webhook_id=env.webhooks["ott"])
    feed = env.add_feed("O", category=category)
    env.add_ready_article(feed_id=feed, title="Netflix movie", topics=("OTT",))
    env.service.run()
    assert len(env.sender.to("ott")) == 1


# ---------- 순서 ----------


def test_older_articles_are_sent_first(env):
    for hour_minute in ((10, 0), (10, 20), (10, 10)):
        env.add_ready_article(
            summary_ko=f"{hour_minute[0]}:{hour_minute[1]:02d}",
            published=datetime(2026, 10, 16, *hour_minute, tzinfo=UTC),
        )
    env.service.run()
    order = [c.content.splitlines()[2] for c in env.sender.calls]
    assert order == ["10:00", "10:10", "10:20"]


def test_at_most_twenty_five_articles_are_sent_per_run(env):
    for _ in range(30):
        env.add_ready_article()
    report = env.service.run()
    assert len(env.sender.calls) == 25 and report.delivered == 25
    env.service.run()
    assert len(env.sender.calls) == 30


# ---------- 목적지마다 따로 기록 ----------


def test_only_the_failed_destination_is_retried_next_time(env):
    article_id = env.add_ready_article(title="Netflix movie", topics=("OTT",))
    env.sender.will(webhook_url("ott"), http(503))
    env.service.run()
    assert env.statuses(article_id) == {"rss:primary": "sent", "ott:topic:OTT": "pending"}
    assert env.article(article_id).status == "ready"
    failed = next(d for d in env.deliveries.for_article(article_id) if d.status == "pending")
    assert (failed.attempts, failed.last_error) == (1, "HTTP 503")

    env.service.run()
    assert (len(env.sender.to("rss")), len(env.sender.to("ott"))) == (1, 2)
    assert env.article(article_id).status == "delivered"


def test_a_network_failure_is_recorded_by_its_kind(env):
    article_id = env.add_ready_article()
    env.sender.will(webhook_url("rss"), SendResult(0, error="ReadTimeout"))
    env.service.run()
    assert env.deliveries.for_article(article_id)[0].last_error == "ReadTimeout"


def test_three_failures_in_a_row_stop_the_run_early(env):
    for _ in range(6):
        env.add_ready_article()
    env.sender.will(webhook_url("rss"), *[http(503)] * 10)
    report = env.service.run()
    assert len(env.sender.calls) == 3 and report.failed == 3 and report.stopped_early is True


def test_a_success_resets_the_failure_streak(env):
    for _ in range(6):
        env.add_ready_article()
    env.sender.will(webhook_url("rss"), http(503), http(503), ok(), http(503), http(503), ok())
    report = env.service.run()
    assert report.stopped_early is False and len(env.sender.calls) >= 6


# ---------- 429 ----------


def test_a_rate_limit_waits_the_given_time_then_retries_once(env):
    article_id = env.add_ready_article()
    env.sender.will(webhook_url("rss"), http(429, retry_after=2.0))
    env.service.run()
    assert env.sleeps == [2.0]
    assert len(env.sender.to("rss")) == 2 and env.article(article_id).status == "delivered"
    assert env.deliveries.for_article(article_id)[0].attempts == 2


def test_the_wait_is_capped_at_thirty_seconds(env):
    env.add_ready_article()
    env.sender.will(webhook_url("rss"), http(429, retry_after=90.0))
    env.service.run()
    assert env.sleeps == [30.0]


def test_if_the_retry_is_limited_again_the_run_stops_and_the_rest_waits(env):
    first = env.add_ready_article(published=datetime(2026, 10, 16, 1, 0, tzinfo=UTC))
    second = env.add_ready_article(published=datetime(2026, 10, 16, 2, 0, tzinfo=UTC))
    env.sender.will(webhook_url("rss"), http(429, retry_after=1.0), http(429, retry_after=1.0))
    report = env.service.run()
    assert len(env.sender.calls) == 2  # 한 번 더 시도한 뒤 멈춘다
    assert env.article(first).status == env.article(second).status == "ready"
    assert report.stopped_early is True
    env.service.run()  # 다음 실행에서 보낸다
    assert env.article(first).status == env.article(second).status == "delivered"


def test_an_empty_rate_limit_bucket_is_waited_out_before_the_next_message(env):
    env.add_ready_article()
    env.add_ready_article()
    env.sender.will(webhook_url("rss"), ok(remaining=0, reset_after=1.5))
    env.service.run()
    assert env.sleeps == [pytest.approx(1.6)]


# ---------- 영구 실패 ----------


@pytest.mark.parametrize("status", [401, 403, 404])
def test_a_refusing_webhook_is_a_permanent_failure_with_one_system_alert(env, status):
    article_id = env.add_ready_article()
    env.sender.will(webhook_url("rss"), http(status))
    env.service.run()
    assert env.statuses(article_id) == {"rss:primary": "failed_permanent"}
    assert env.article(article_id).status == "ready"
    assert len(env.notifier.sent) == 1
    url, text = env.notifier.sent[0]
    assert url == webhook_url("시스템") and "rss" in text and str(status) in text
    assert "TOKEN" not in text


def test_the_same_failure_is_not_announced_again_during_the_cooldown(env):
    env.add_ready_article()
    env.add_ready_article()
    env.sender.will(webhook_url("rss"), http(404), http(404))
    env.service.run()
    env.add_ready_article()
    env.sender.will(webhook_url("rss"), http(404))
    env.service.run()
    assert len(env.notifier.sent) == 1


def test_a_permanently_failed_destination_is_not_retried(env):
    env.add_ready_article()
    env.sender.will(webhook_url("rss"), http(404))
    env.service.run()
    calls = len(env.sender.calls)
    env.service.run()
    assert len(env.sender.calls) == calls


def test_after_the_default_webhook_is_replaced_the_waiting_article_is_sent_to_the_new_one(env):
    article_id = env.add_ready_article()
    env.sender.will(webhook_url("rss"), http(404))
    env.service.run()
    env.settings.set_webhook_roles(default_id=env.webhooks["dev"], system_id=env.webhooks["시스템"])
    env.service.run()
    assert len(env.sender.to("dev")) == 1 and env.article(article_id).status == "delivered"


# ---------- 보류 ----------


def test_without_a_default_webhook_nothing_is_sent_and_one_alert_goes_out(tmp_path):
    env = DeliveryEnv(tmp_path)
    env.settings.set_webhook_roles(default_id=None, system_id=env.webhooks["시스템"])
    article_id = env.add_ready_article()
    report = env.service.run()
    env.service.run()
    assert env.sender.calls == [] and env.article(article_id).status == "ready"
    assert report.no_default_webhook is True
    assert len(env.notifier.sent) == 1


def test_without_any_webhook_the_run_holds_quietly(tmp_path):
    env = DeliveryEnv(tmp_path, register_webhooks=False)
    article_id = env.add_ready_article()
    env.service.run()
    assert env.sender.calls == [] and env.notifier.sent == []
    assert env.article(article_id).status == "ready"


def test_an_empty_service_address_holds_everything_without_an_alert(env):
    article_id = env.add_ready_article()
    env.settings.update({"service_base_url": ""})
    report = env.service.run()
    assert env.sender.calls == [] and env.article(article_id).status == "ready"
    assert report.waiting_for_base_url is True and report.considered == 1
    assert env.notifier.sent == []


def test_a_changed_service_address_is_used_from_the_next_message(env):
    first = env.add_ready_article()
    env.service.run()
    env.settings.update({"service_base_url": "https://new.example.com"})
    second = env.add_ready_article()
    env.service.run()
    messages = env.sender.to("rss")
    assert messages[0].endswith(f"(https://rss.example.com/a/{first})")
    assert messages[1].endswith(f"(https://new.example.com/a/{second})")


# ---------- 안전 ----------


def test_a_misbehaving_sender_cannot_leak_the_address_into_logs_or_records(env, caplog):
    caplog.set_level(logging.DEBUG)
    article_id = env.add_ready_article()
    secret_url = webhook_url("rss")
    env.sender.will(secret_url, RuntimeError(f"connection to {secret_url} failed"))
    env.service.run()
    delivery = env.deliveries.for_article(article_id)[0]
    assert delivery.last_error == "RuntimeError"
    assert "TOKEN" not in caplog.text and "TOKEN" not in (delivery.last_error or "")
    assert env.article(article_id).status == "ready"


def test_one_failing_article_does_not_stop_the_others_when_the_sender_raises(env):
    first = env.add_ready_article(published=datetime(2026, 10, 16, 1, 0, tzinfo=UTC))
    second = env.add_ready_article(published=datetime(2026, 10, 16, 2, 0, tzinfo=UTC))
    env.sender.will(webhook_url("rss"), RuntimeError("boom"))
    env.service.run()
    assert env.article(first).status == "ready" and env.article(second).status == "delivered"


def test_a_webhook_address_that_cannot_be_found_is_a_permanent_failure_for_that_destination(
    env, monkeypatch
):
    article_id = env.add_ready_article()
    monkeypatch.setattr(env.settings, "get_webhook_url", lambda _id: None)
    env.service.run()
    assert env.sender.calls == []
    delivery = env.deliveries.for_article(article_id)[0]
    assert (delivery.status, delivery.last_error) == (
        "failed_permanent",
        "웹훅 주소를 찾을 수 없음",
    )


def test_an_unexpected_error_in_one_article_is_logged_and_the_next_article_is_still_sent(
    env, monkeypatch
):
    first = env.add_ready_article(published=datetime(2026, 10, 16, 1, 0, tzinfo=UTC))
    second = env.add_ready_article(published=datetime(2026, 10, 16, 2, 0, tzinfo=UTC))
    real = env.feeds.category_webhook_id
    calls = {"n": 0}

    def flaky(category_id):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("예상하지 못한 오류")
        return real(category_id)

    monkeypatch.setattr(env.feeds, "category_webhook_id", flaky)
    env.service.run()
    assert env.article(first).status == "ready"
    assert env.article(second).status == "delivered"


def test_an_article_whose_feed_has_disappeared_is_skipped(env, monkeypatch):
    article_id = env.add_ready_article()
    monkeypatch.setattr(env.feeds, "get", lambda _feed_id: None)
    env.service.run()
    assert env.sender.calls == [] and env.article(article_id).status == "ready"


def test_each_dead_webhook_gets_its_own_alert(env):
    category = env.feeds.add_category("G", webhook_id=env.webhooks["gizmodo"])
    env.add_ready_article(feed_id=env.add_feed("G", category=category))
    env.add_ready_article()
    env.sender.will(webhook_url("gizmodo"), http(404))
    env.sender.will(webhook_url("rss"), http(404))
    env.service.run()
    texts = env.notifier.texts()
    assert len(texts) == 2
    assert any("'gizmodo'" in t for t in texts) and any("'rss'" in t for t in texts)


# ---------- 피드 웹훅(카테고리에 속하지 않은 피드) ----------


def test_a_feed_webhook_wins_and_the_article_does_not_go_to_the_default(env):
    feed = env.add_feed("G", webhook="gizmodo")
    env.add_ready_article(feed_id=feed)
    env.service.run()
    assert (len(env.sender.to("gizmodo")), len(env.sender.to("rss"))) == (1, 0)


def test_a_feed_webhook_lets_the_article_go_out_even_without_a_default_webhook(tmp_path):
    env = DeliveryEnv(tmp_path)
    env.settings.set_webhook_roles(default_id=None, system_id=None)
    env.add_ready_article(feed_id=env.add_feed("G", webhook="gizmodo"))
    report = env.service.run()
    assert len(env.sender.to("gizmodo")) == 1 and report.no_default_webhook is False


def test_a_topic_article_from_a_feed_with_its_own_webhook_goes_to_it_and_the_topic_only(env):
    feed = env.add_feed("G", webhook="gizmodo")
    article_id = env.add_ready_article(feed_id=feed, title="Netflix movie", topics=("OTT",))
    env.service.run()
    assert env.statuses(article_id) == {"gizmodo:primary": "sent", "ott:topic:OTT": "sent"}
    assert env.sender.to("rss") == []


def test_a_topic_article_from_a_category_feed_goes_to_the_category_and_the_topic_only(env):
    category = env.feeds.add_category("뉴스", webhook_id=env.webhooks["dev"])
    article_id = env.add_ready_article(
        feed_id=env.add_feed("N", category=category), title="Netflix movie", topics=("OTT",)
    )
    env.service.run()
    assert env.statuses(article_id) == {"dev:primary": "sent", "ott:topic:OTT": "sent"}
    assert env.sender.to("rss") == []


def test_a_topic_article_from_a_feed_without_overrides_goes_to_the_default_and_the_topic(env):
    article_id = env.add_ready_article(title="Netflix movie", topics=("OTT",))
    env.service.run()
    assert env.statuses(article_id) == {"rss:primary": "sent", "ott:topic:OTT": "sent"}


# ---------- 서비스 종료 ----------


def test_when_the_service_is_stopping_the_current_article_is_finished_and_the_rest_waits(
    env, monkeypatch
):
    first = env.add_ready_article(
        title="Netflix movie", topics=("OTT",), published=datetime(2026, 10, 16, 1, 0, tzinfo=UTC)
    )
    second = env.add_ready_article(published=datetime(2026, 10, 16, 2, 0, tzinfo=UTC))
    real_send = env.sender.send

    def send_then_stop(url, content):
        result = real_send(url, content)
        env.stop_flag = True  # 첫 글을 보내는 도중에 종료 신호가 온다
        return result

    monkeypatch.setattr(env.sender, "send", send_then_stop)
    report = env.service.run()
    assert (
        env.article(first).status == "delivered"
    )  # 이미 나간 글은 모든 목적지를 마치고 완료로 기록된다
    assert env.statuses(first) == {"rss:primary": "sent", "ott:topic:OTT": "sent"}
    assert env.article(second).status == "ready" and report.stopped_early is True
    env.stop_flag = False
    env.service.run()  # 다음에 시작하면 이어서 보낸다
    assert env.article(second).status == "delivered"


# ---------- 사용자가 정한 주제 소속(싫어요, 주제로) ----------


def ott_article(env, **kwargs):
    return env.add_ready_article(title="Netflix movie", topics=("OTT",), **kwargs)


def test_a_topic_the_user_rejected_does_not_receive_the_article(env):
    article_id = ott_article(env)
    env.topics.record_matches(article_id, {env.topic_id("OTT"): ("netflix",)})
    env.topics.reject(article_id, env.topic_id("OTT"))
    env.service.run()
    assert env.statuses(article_id) == {"rss:primary": "sent"}
    assert env.sender.to("ott") == []


def test_other_topics_still_receive_it_when_only_one_was_rejected(env):
    env.add_topic("게임", ("netflix",), webhook="gizmodo")
    article_id = env.add_ready_article(title="Netflix movie", topics=("OTT", "게임"))
    env.topics.record_matches(article_id, {env.topic_id("OTT"): (), env.topic_id("게임"): ()})
    env.topics.reject(article_id, env.topic_id("OTT"))
    env.service.run()
    assert env.statuses(article_id) == {"rss:primary": "sent", "gizmodo:topic:게임": "sent"}


def test_an_article_the_user_added_by_hand_goes_to_the_topics_webhook_without_keywords(env):
    article_id = env.add_ready_article(title="Totally unrelated words")
    env.topics.add_manual(article_id, env.topic_id("OTT"))
    env.service.run()
    assert env.statuses(article_id) == {"rss:primary": "sent", "ott:topic:OTT": "sent"}


def test_the_manual_choice_is_recorded_again_without_losing_its_source(env):
    article_id = env.add_ready_article(title="Totally unrelated words")
    env.topics.add_manual(article_id, env.topic_id("OTT"))
    env.service.run()
    (membership,) = env.topics.memberships(article_id)
    assert (membership.source, membership.rejected) == ("manual", False)


def test_a_hand_added_topic_that_was_later_rejected_gets_nothing(env):
    article_id = env.add_ready_article(title="Totally unrelated words")
    topic = env.topic_id("OTT")
    env.topics.add_manual(article_id, topic)
    env.topics.reject(article_id, topic)
    env.service.run()
    assert env.statuses(article_id) == {"rss:primary": "sent"}


def test_a_hand_added_topic_that_is_turned_off_is_ignored(env):
    article_id = env.add_ready_article(title="Totally unrelated words")
    topic = env.topic_id("OTT")
    env.topics.add_manual(article_id, topic)
    env.topics.update(topic, TopicFields("OTT", "", ()), webhook_id=None, enabled=False)
    env.service.run()
    assert env.statuses(article_id) == {"rss:primary": "sent"}


def test_an_article_that_was_already_delivered_is_not_sent_again_after_a_manual_add(env):
    article_id = env.add_ready_article(title="Totally unrelated words")
    env.service.run()
    env.topics.add_manual(article_id, env.topic_id("OTT"))
    env.service.run()
    assert env.statuses(article_id) == {"rss:primary": "sent"} and len(env.sender.to("ott")) == 0
