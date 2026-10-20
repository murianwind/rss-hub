"""서비스 엔드포인트: /healthz의 정체 판정, /status의 현재 상태, /a/{id}, 시작과 종료."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from rss_hub.jobs.runner import JobRunner
from rss_hub.main import create_service_app
from rss_hub.storage.llm_usage import LlmUsageRepository
from rss_hub.web.app import SHUTDOWN_WAIT_SECONDS, STALE_MINUTES, create_app
from tests.fakes.clock import FakeClock
from tests.fakes.service_env import BASE, KEY, WEBHOOK, Env, FakeRunner


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


# ---------- /healthz ----------


def test_healthz_is_ok_when_the_collection_ran_a_few_minutes_ago(env):
    env.ran("collect", 3)
    env.ran("summarize", 1)
    env.ran("deliver", 1)
    response = env.client.get("/healthz")
    body = response.json()
    assert response.status_code == 200 and body["status"] == "ok"
    assert all(body[f"last_{name}"] for name in ("collect", "summarize", "deliver"))


def test_healthz_turns_503_stale_when_the_collection_stopped_for_too_long(env):
    env.ran("collect", STALE_MINUTES + 1)
    response = env.client.get("/healthz")
    assert response.status_code == 503 and response.json()["status"] == "stale"


def test_the_boundary_is_fifteen_minutes(env):
    env.ran("collect", STALE_MINUTES)
    assert env.client.get("/healthz").status_code == 200


def test_a_service_that_just_started_is_not_stale_before_its_first_collection(env):
    response = env.client.get("/healthz")
    assert response.status_code == 200 and response.json()["last_collect"] is None


def test_a_service_that_never_collected_becomes_stale_after_the_limit(env):
    env.clock.advance(minutes=STALE_MINUTES + 1)
    assert env.client.get("/healthz").status_code == 503


def test_a_slower_collection_interval_allows_a_longer_silence(env):
    env.settings.update({"collect_interval_minutes": "30"})
    env.ran("collect", 80)
    assert env.client.get("/healthz").status_code == 200
    env.ran("collect", 91)
    assert env.client.get("/healthz").status_code == 503


def test_a_failed_collection_does_not_count_as_a_success(env):
    env.runs.mark_started("collect")
    env.runs.mark_finished("collect", "ConnectionError")
    env.clock.advance(minutes=STALE_MINUTES + 1)
    assert env.client.get("/healthz").status_code == 503


def test_healthz_reports_a_missing_data_directory_before_anything_else(tmp_path):
    app = create_app(
        data_dir=tmp_path / "nope", clock=FakeClock(), runner_factory=lambda *_: FakeRunner()
    )
    response = TestClient(app, base_url=BASE).get("/healthz")
    assert response.status_code == 503 and response.json()["reason"] == "data_dir_not_writable"


# ---------- /status ----------


def test_the_status_page_shows_waiting_articles_todays_calls_and_failing_feeds(env):
    for number in range(4):
        env.article(f"https://example.com/{number}", ready=True)
    usage = LlmUsageRepository(env.db, env.clock)
    for _ in range(120):
        usage.record(model="m", outcome="success", status=200)
    for name in ("고장난 피드 A", "고장난 피드 B"):
        feed_id = env.feeds.add(f"https://{name.encode().hex()}.example.com/rss", name)
        with env.db.connect() as conn:
            conn.execute(
                "UPDATE feeds SET fail_count = 3, last_error = 'Timeout' WHERE id = ?", (feed_id,)
            )
    html = env.client.get("/status").text
    assert "발송 대기 글" in html and "4개" in html
    assert "오늘 LLM 호출" in html and "120회" in html
    assert "실패 피드" in html and "2개" in html and "고장난 피드 A" in html and "Timeout" in html


def test_the_status_page_lists_the_jobs_with_their_last_success_and_skips(env):
    env.ran("collect", 2)
    env.runs.mark_skipped("collect")
    html = env.client.get("/status").text
    for label in ("수집", "요약", "발송"):
        assert label in html
    assert "마지막 성공" in html and "건너뜀 1회" in html


def test_an_idle_service_shows_zero_everywhere(env):
    html = env.client.get("/status").text
    assert "0개" in html and "0회" in html


# ---------- 비밀 값 ----------


@pytest.mark.security
def test_status_and_health_never_contain_secrets(env):
    env.settings.set_openrouter_key(KEY)
    env.settings.add_webhook("dev", WEBHOOK)
    for path in ("/healthz", "/"):
        text = env.client.get(path).text
        assert "SECRETWEBHOOKTOKEN" not in text and "SECRETAPIKEYVALUE" not in text
        assert "discord.com/api/webhooks" not in text


# ---------- /a/{id} ----------


def test_a_article_link_redirects_to_the_original_address(env):
    article_id = env.article("https://example.com/original")
    response = env.client.get(f"/a/{article_id}/original")
    assert (
        response.status_code == 302
        and response.headers["location"] == "https://example.com/original"
    )


def test_an_unknown_article_gives_404(env):
    assert env.client.get("/a/999999/original").status_code == 404
    assert env.client.get("/a/999999").status_code == 404


@pytest.mark.security
@pytest.mark.parametrize(
    "link",
    [
        "javascript:alert(1)",
        "file:///etc/passwd",
        "data:text/html,hello",
        "",
        "https://",
        "//evil.example.com/x",
        "https://a.example.com/x\r\nSet-Cookie: a=b",
        "ftp://a.example.com/x",
    ],
)
def test_links_that_are_not_http_or_https_are_not_followed(env, link):
    article_id = env.article(link)
    response = env.client.get(f"/a/{article_id}/original")
    assert response.status_code == 404 and "location" not in response.headers


def test_a_non_numeric_article_id_is_rejected(env):
    assert env.client.get("/a/abc").status_code == 422
    assert env.client.get("/a/abc/original").status_code == 422


# ---------- 시작과 종료 ----------


def test_the_runner_starts_with_the_server_and_is_shut_down_with_a_wait(tmp_path):
    runner = FakeRunner()
    app = create_app(data_dir=tmp_path, clock=FakeClock(), runner_factory=lambda *_: runner)
    assert runner.started == 0  # 앱을 만든 것만으로는 시작하지 않는다
    with TestClient(app, base_url=BASE):
        assert runner.started == 1 and runner.shutdowns == []
    assert runner.shutdowns == [SHUTDOWN_WAIT_SECONDS]


def test_an_app_without_a_runner_still_works(tmp_path):
    with TestClient(create_app(data_dir=tmp_path, clock=FakeClock()), base_url=BASE) as client:
        assert client.get("/healthz").status_code == 200


def test_the_service_entry_point_builds_a_real_runner_without_starting_it():
    app = create_service_app()
    assert isinstance(app.state.runner, JobRunner) and app.state.runner.running == frozenset()


def test_the_docker_image_starts_the_service_entry_point():
    dockerfile = (Path(__file__).parents[2] / "Dockerfile").read_text(encoding="utf-8")
    assert '"rss_hub.main:create_service_app"' in dockerfile and '"--factory"' in dockerfile


def test_the_root_address_opens_the_article_list_and_the_status_page_lives_at_status(tmp_path):
    app = create_app(data_dir=tmp_path, clock=FakeClock(), runner_factory=lambda *_: FakeRunner())
    with TestClient(app, base_url=BASE) as client:
        root = client.get("/", follow_redirects=False)
        assert root.status_code == 307 and root.headers["location"] == "/reader"
        assert client.get("/").url.path == "/reader"  # 따라가면 글 목록
        assert client.get("/status").status_code == 200
