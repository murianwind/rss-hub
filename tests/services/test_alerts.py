from datetime import UTC, datetime

import pytest

from tests.fakes.llm_env import DEFAULT_WEBHOOK, SYSTEM_WEBHOOK, LlmEnv


@pytest.fixture
def env(tmp_path):
    return LlmEnv(tmp_path)


def test_an_alert_goes_to_the_system_webhook_and_is_recorded(env):
    assert env.alerts.notify("llm_cap", "호출 상한 도달") is True
    assert env.notifier.sent == [(SYSTEM_WEBHOOK, "호출 상한 도달")]
    assert env.alert_log.last_sent("llm_cap") == env.clock.now()


def test_alerts_use_the_system_role_not_the_default_one(env):
    env.alerts.notify("x", "t")
    assert all(url != DEFAULT_WEBHOOK for url, _ in env.notifier.sent)


def test_without_a_system_webhook_nothing_is_sent_or_recorded_so_it_can_be_sent_later(env):
    env.settings.set_webhook_roles(default_id=None, system_id=None)
    assert env.alerts.notify("llm_cap", "t") is False
    assert env.notifier.sent == [] and env.alert_log.last_sent("llm_cap") is None
    env.settings.set_webhook_roles(default_id=None, system_id=env.settings.list_webhooks()[1].id)
    assert env.alerts.notify("llm_cap", "t") is True


def test_the_same_kind_is_sent_once_and_not_again_for_a_day_by_default(env):
    assert env.alerts.notify("llm_cap", "첫 알림") is True
    env.clock.advance(hours=23, minutes=59)
    assert env.alerts.notify("llm_cap", "또") is False
    env.clock.advance(minutes=2)  # 반복 보내기가 꺼져 있으면 24시간 뒤에야 다시 보낸다
    assert env.alerts.notify("llm_cap", "다시") is True
    assert env.notifier.texts() == ["첫 알림", "다시"]


def test_with_repeat_on_the_interval_comes_from_settings(env):
    env.settings.update({"alert_repeat": "on", "alert_cooldown_hours": "1"})
    env.alerts.notify("k", "a")
    env.clock.advance(minutes=61)
    assert env.alerts.notify("k", "b") is True


def test_different_kinds_do_not_block_each_other(env):
    assert env.alerts.notify("a", "1") and env.alerts.notify("b", "2")


def test_once_per_day_alerts_wait_for_the_next_utc_day_even_after_the_cooldown(env):
    env.settings.update({"alert_repeat": "on"})
    assert env.alerts.notify("llm_warn", "80%", once_per_day=True) is True
    env.clock.advance(hours=7)  # 쿨다운은 지났지만 같은 UTC 날짜
    assert env.alerts.notify("llm_warn", "80%", once_per_day=True) is False
    env.clock.set(datetime(2026, 10, 17, 0, 0, 5, tzinfo=UTC))
    assert env.alerts.notify("llm_warn", "80%", once_per_day=True) is True


def test_a_failed_send_is_not_recorded_so_the_next_attempt_retries(env):
    env.notifier.fail = True
    assert env.alerts.notify("llm_cap", "t") is False
    assert env.alert_log.last_sent("llm_cap") is None
    env.notifier.fail = False
    assert env.alerts.notify("llm_cap", "t") is True
