"""조립한 잡 실행기: 수집, 요약, 발송이 실제 서비스와 저장소로 이어져서 글이 끝까지 흘러간다."""

import pytest

from tests.fakes.delivery_env import webhook_url
from tests.fakes.llm_client import reply
from tests.fakes.runtime_env import BASE_URL, RuntimeEnv


@pytest.fixture
def env(tmp_path):
    return RuntimeEnv(tmp_path)


def test_one_tick_carries_a_new_article_from_the_feed_to_discord(env):
    env.serve_new_article(title="Apple unveils new phone")
    assert env.runner.tick() == ["collect", "summarize", "deliver"]
    article = env.articles.list_by_status("delivered")[0]
    (message,) = env.sender.to("rss")
    assert "**애플, 새 폰 공개**" in message and f"({BASE_URL}/a/{article.id})" in message


def test_every_job_leaves_a_successful_record(env):
    env.serve_new_article()
    env.runner.tick()
    runs = env.records.all()
    assert {name: run.last_status for name, run in runs.items()} == {
        "collect": "ok",
        "summarize": "ok",
        "deliver": "ok",
    }
    assert runs["collect"].last_slot is not None


def test_a_minute_later_only_the_interval_jobs_run_again(env):
    env.serve_new_article()
    env.runner.tick()
    assert env.tick(seconds=60) == ["summarize", "deliver"]
    assert len(env.sender.calls) == 1  # 새 글이 없으니 더 보내지 않는다


def test_the_next_slot_collects_and_delivers_a_newer_article(env):
    env.serve_new_article("first")
    env.runner.tick()
    env.serve_new_article("second", title="Another story")
    assert env.tick(minutes=5) == ["collect", "summarize", "deliver"]
    assert len(env.sender.calls) == 2


def test_without_the_required_settings_the_summary_waits_and_nothing_is_sent(tmp_path):
    env = RuntimeEnv(tmp_path, configured=False)
    env.serve_new_article()
    env.runner.tick()
    assert env.client.calls == []
    assert [a.status for a in env.articles.list_by_status("collected")] == ["collected"]
    assert env.sender.calls == []


def test_filling_in_the_settings_starts_the_work_without_a_restart(tmp_path):
    env = RuntimeEnv(tmp_path, configured=False)
    env.serve_new_article()
    env.runner.tick()
    env.configure()  # 설정 화면에서 키, 기본 웹훅, 서비스 주소를 저장한 것과 같다
    env.tick(seconds=60)
    assert len(env.client.calls) == 1
    assert len(env.sender.to("rss")) == 1


def test_a_changed_summary_interval_applies_from_the_next_run(env):
    env.runner.tick()
    env.settings.update({"summarize_interval_seconds": "30"})
    assert "summarize" in env.tick(seconds=30)


def test_a_changed_service_address_is_used_for_the_next_message(env):
    env.serve_new_article("first")
    env.runner.tick()
    env.settings.update({"service_base_url": "https://new.example.com"})
    env.serve_new_article("second", title="Another story")
    env.tick(minutes=5)
    assert "(https://new.example.com/a/" in env.sender.to("rss")[1]


def test_a_changed_model_chain_is_used_for_the_next_call(env):
    env.serve_new_article("first")
    env.runner.tick()
    env.settings.update({"model_chain": "model-c"})
    env.client.default = reply("t", "s")
    env.serve_new_article("second", title="Another story")
    env.tick(minutes=5)
    assert [c.model for c in env.client.calls] == ["model-a", "model-c"]


def test_a_failing_collection_does_not_stop_summarizing_and_delivering(env):
    env.serve_new_article("first")
    env.runner.tick()
    env.fetcher.crash("https://feed.example.com/rss", RuntimeError(webhook_url("rss")))
    env.tick(minutes=5)
    assert env.records.get("summarize").last_status == "ok"
    assert env.records.get("deliver").last_status == "ok"


def test_the_runner_uses_the_service_timezone_for_slots(env):
    env.settings.update({"service_timezone": "UTC"})
    env.runner.tick()  # 14:00 KST는 UTC로 05:00이라 같은 슬롯이다
    env.clock.advance(minutes=1)
    assert "collect" not in env.runner.tick()


def test_a_normal_feed_is_checked_only_in_its_own_slot_once_an_hour(tmp_path):
    env = RuntimeEnv(tmp_path, priority="normal")
    env.serve_new_article("first")
    env.runner.tick()
    assert len(env.fetcher.calls) == 1
    for _ in range(11):  # 14:05 ~ 14:55
        env.tick(minutes=5)
    assert len(env.fetcher.calls) == 1  # 다른 슬롯에서는 점검하지 않는다
    env.tick(minutes=5)  # 15:00
    assert len(env.fetcher.calls) == 2
