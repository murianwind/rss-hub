"""08_service_endpoints.feature: /healthz, /status, /a/{id}, 종료 신호."""

import threading
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, then, when

from rss_hub.jobs.runner import start_thread
from rss_hub.storage.articles import NewArticle
from rss_hub.storage.llm_usage import LlmUsageRepository
from tests.bdd.binding import bind
from tests.fakes.runtime_env import FEED_URL, RuntimeEnv
from tests.fakes.service_env import KEY, WEBHOOK, Env

bind(globals(), "08_service_endpoints.feature", [f"SVC-0{n}" for n in range(1, 8)] + ["SVC-10"])


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


@pytest.fixture
def ctx():
    return SimpleNamespace(response=None, responses=[], ids={}, runtime=None)


# ---------- /healthz ----------


@given("마지막 수집이 3분 전에 성공했다")
def _collect_3_minutes_ago(env):
    env.ran("collect", 3)
    env.ran("summarize", 1)  # 요약과 발송도 최근에 돌았다
    env.ran("deliver", 1)


@given("마지막 수집이 16분 전이다")
def _collect_16_minutes_ago(env):
    env.ran("collect", 16)


@when(parsers.re(r'"(?P<path>/[^"]*)"[을를] 요청한다'))
def _request(env, ctx, path):
    for fake_id, real_id in ctx.ids.items():
        path = path.replace(f"/a/{fake_id}", f"/a/{real_id}")
    ctx.response = env.client.get(path)


@then(parsers.parse("상태 코드는 {code:d}이다"))
def _status_code(ctx, code):
    assert ctx.response.status_code == code


@then('본문에 마지막 수집, 요약, 발송 시각과 "ok"가 있다')
def _health_body(ctx):
    body = ctx.response.json()
    assert body["status"] == "ok"
    assert all(body[f"last_{name}"] for name in ("collect", "summarize", "deliver"))


@then('본문의 상태는 "stale"이다')
def _stale(ctx):
    assert ctx.response.json()["status"] == "stale"


# ---------- /status ----------


@given("대기 글 4개, 오늘 LLM 호출 120회, 실패 피드 2개가 있다")
def _numbers(env):
    for number in range(4):
        env.article(f"https://example.com/{number}", ready=True)
    usage = LlmUsageRepository(env.db, env.clock)
    for _ in range(120):
        usage.record(model="m", outcome="success", status=200)
    for name in ("피드A", "피드B"):
        feed_id = env.feeds.add(f"https://{name.encode().hex()}.example.com/rss", name)
        with env.db.connect() as conn:
            conn.execute(
                "UPDATE feeds SET fail_count = 2, last_error = 'Timeout' WHERE id = ?", (feed_id,)
            )


@then("본문에 이 숫자들이 있다")
def _numbers_shown(ctx):
    text = ctx.response.text
    assert "4개" in text and "120회" in text and "2개" in text


@when('"/healthz"와 "/status"를 요청한다')
def _request_both(env, ctx, monkeypatch):
    env.settings.set_openrouter_key(KEY)
    env.settings.add_webhook("dev", WEBHOOK)
    monkeypatch.setenv("RSS_HUB_TEST_SECRET", "ENVSECRETVALUE")
    ctx.responses = [env.client.get("/healthz"), env.client.get("/status")]


@then("웹훅 주소, API 키, 환경 변수 원본 값은 어디에도 없다")
def _no_secrets(ctx):
    for response in ctx.responses:
        for secret in ("SECRETWEBHOOKTOKEN", "SECRETAPIKEYVALUE", "ENVSECRETVALUE"):
            assert secret not in response.text
        assert "discord.com/api/webhooks" not in response.text


# ---------- /a/{id} ----------


@given(parsers.parse('글 {number:d}의 원문 주소는 "{link}"이다'))
def _article_with_link(env, ctx, number, link):
    ctx.ids[str(number)] = env.article(link)


@then(parsers.parse('이동 주소는 "{url}"이다'))
def _redirect_target(ctx, url):
    assert ctx.response.headers["location"] == url


# ---------- SVC-10: 종료 신호 ----------


@given("발송 작업이 한창 진행 중이다")
def _delivery_in_progress(ctx, tmp_path):
    runtime = RuntimeEnv(tmp_path, spawn=start_thread)  # 작업마다 실제 스레드로 실행한다
    ctx.runtime = runtime
    runtime.fetcher.serve(FEED_URL, [])
    for number in (1, 2):
        article_id = runtime.articles.add(
            NewArticle(
                runtime.feed_id,
                f"g{number}",
                f"title {number}",
                f"https://example.com/{number}",
                "<p>본문</p>",
                "",
                datetime(2026, 10, 16, number, 0, tzinfo=UTC),
                "2026-10-16",
            )
        )
        runtime.articles.mark_ready(
            article_id, title_ko=f"제목 {number}", summary_ko="요약", topics=[], model="m"
        )
        ctx.ids[number] = article_id
    entered, release = threading.Event(), threading.Event()
    real_send = runtime.sender.send
    sent = {"n": 0}

    def send_slowly(url, content):
        sent["n"] += 1
        if sent["n"] == 1:
            entered.set()
            release.wait(5)  # 첫 글을 보내는 도중에 멈춰 있다
        return real_send(url, content)

    runtime.sender.send = send_slowly
    ctx.release = release
    runtime.runner.tick()
    assert entered.wait(3), "발송이 시작되지 않았다"


@when("서비스가 종료 신호를 받는다")
def _stop_signal(ctx):
    ctx.runtime.runner.request_stop()
    ctx.release.set()
    assert ctx.runtime.runner.wait_idle(5) is True


@then("이미 Discord로 나간 글은 발송 완료로 기록된다")
def _first_delivered(ctx):
    assert ctx.runtime.articles.get(ctx.ids[1]).status == "delivered"
    assert len(ctx.runtime.sender.to("rss")) == 1


@then('아직 보내지 않은 글은 "ready"로 남는다')
def _second_still_ready(ctx):
    assert ctx.runtime.articles.get(ctx.ids[2]).status == "ready"
