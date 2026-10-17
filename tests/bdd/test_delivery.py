"""05_delivery.feature 전체: 라우팅, 메시지 형식, 발송 기록과 재시도, 안전, 서비스 주소."""

import logging
import re
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, then, when

from rss_hub.adapters.openrouter_client import OpenRouterClient
from rss_hub.domain.message import article_url, build_message
from rss_hub.services.llm_gateway import LlmGateway, LlmOutage
from rss_hub.services.ports import SendResult
from rss_hub.storage.llm_usage import LlmUsageRepository
from rss_hub.web.app import create_app
from tests.bdd.binding import bind
from tests.fakes.delivery_env import DeliveryEnv, webhook_url
from tests.tools.fake_apis import FakeServer, json_reply

bind(
    globals(),
    "05_delivery.feature",
    [f"DLV-{n:02d}" for n in (*range(1, 18), 19, 20, 21, 22, 23, 24)],
)

SEOUL = ZoneInfo("Asia/Seoul")
KEY = "sk-or-v1-FULL-SECRET-KEY-VALUE"
OTT_TITLE = "Netflix announces a new movie"


@pytest.fixture
def env(tmp_path):
    return DeliveryEnv(tmp_path)


@pytest.fixture
def ctx():
    return SimpleNamespace(
        topics=(),
        feed_webhook=None,
        category_webhook=None,
        article_id=None,
        report=None,
        extra={},
    )


def http(status, retry_after=None):
    return SendResult(status, retry_after=retry_after)


def names_of(env, article_id):
    return {key.split(":")[0] for key in env.statuses(article_id)}


# ---------- 배경 ----------


@given('설정의 서비스 주소는 "https://rss.example.com"이다')
def _base_url(env):
    assert env.settings.snapshot().base_url == "https://rss.example.com"


@given('설정에 기본 웹훅 "rss", 웹훅 "ott", "gizmodo", "dev"가 등록되어 있다')
def _webhooks_registered(env):
    assert env.settings.snapshot().webhook_default_id == env.webhooks["rss"]
    assert {"ott", "gizmodo", "dev"} <= set(env.webhooks)


@given('주제 "OTT"가 있고 웹훅은 "ott"이다')
def _ott_topic_exists(env):
    assert env.topics.get(env.topic_id("OTT")).webhook_id == env.webhooks["ott"]


# ---------- 라우팅 (DLV-01 ~ 04) ----------


@given(parsers.re(r"카테고리의 웹훅 지정은 (?P<category>[^ ]+)이다"))
def _category_webhook(ctx, category):
    ctx.category_webhook = None if category == "없음" else category


@given(
    parsers.re(
        r"피드의 웹훅 지정은 (?P<feed>[^ ]+)이고 카테고리의 웹훅 지정은 (?P<category>[^ ]+)이다"
    )
)
def _feed_and_category_webhooks(ctx, feed, category):
    ctx.feed_webhook = None if feed == "없음" else feed
    ctx.category_webhook = None if category == "없음" else category


@given("글은 어떤 주제에도 해당하지 않는다")
def _no_topic(ctx):
    ctx.topics = ()


@given('글은 주제 "OTT"에 해당한다')
def _on_ott(ctx):
    ctx.topics = ("OTT",)


@given(parsers.parse('주제 "게임"과 주제 "만화"의 웹훅은 모두 gizmodo이다'))
def _two_topics_one_webhook(env):
    env.add_topic("게임", (), webhook="gizmodo")
    env.add_topic("만화", (), webhook="gizmodo")


@given('글은 주제 "게임"과 "만화"에 해당한다')
def _on_two_topics(ctx):
    ctx.topics = ("게임", "만화")


@when("발송 대상을 정한다")
def _choose_targets(env, ctx):
    category_id = None
    if ctx.category_webhook:
        category_id = env.feeds.add_category(
            "카테고리", webhook_id=env.webhooks[ctx.category_webhook]
        )
    # 피드 웹훅은 카테고리에 속하지 않은 피드에만 지정할 수 있다
    feed_id = env.add_feed(
        "Blog2", category=category_id, webhook=None if category_id else ctx.feed_webhook
    )
    ctx.article_id = env.add_ready_article(
        feed_id=feed_id,
        title=OTT_TITLE if "OTT" in ctx.topics else "Gardening tips",
        topics=ctx.topics,
    )
    ctx.report = env.service.run()


@then(parsers.parse('발송 대상은 "{target}" 웹훅 하나이다'))
def _one_target(env, ctx, target):
    assert names_of(env, ctx.article_id) == {target}
    assert len(env.statuses(ctx.article_id)) == 1


@then(parsers.parse('발송 대상은 "{first}"와 "ott" 두 곳이다'))
def _two_targets(env, ctx, first):
    assert env.statuses(ctx.article_id) == {f"{first}:primary": "sent", "ott:topic:OTT": "sent"}


@then(parsers.parse('발송 대상은 "{first}"와 "ott" 두 곳이고 "rss"는 없다'))
def _two_targets_without_default(env, ctx, first):
    assert env.statuses(ctx.article_id) == {f"{first}:primary": "sent", "ott:topic:OTT": "sent"}
    assert env.sender.to("rss") == []


@then('발송 대상은 "rss"와 "gizmodo" 두 곳이다')
def _rss_and_gizmodo(env, ctx):
    assert env.statuses(ctx.article_id) == {"rss:primary": "sent", "gizmodo:topic:게임": "sent"}


@then('발송 대상은 "ott" 한 곳뿐이다')
def _only_ott(env, ctx):
    assert list(env.statuses(ctx.article_id)) == ["ott:primary"]
    assert len(env.sender.to("ott")) == 1


@then('발송 대상에 "ott"는 없다')
def _no_ott(env, ctx):
    assert "ott" not in names_of(env, ctx.article_id)


# ---------- 요약이 끝난 글만 (DLV-05) ----------


@given('상태가 "collected"인 글과 "ready"인 글이 각각 1개 있다')
def _collected_and_ready(env, ctx):
    ctx.extra["collected"] = env.add_ready_article(status="collected")
    ctx.extra["ready"] = env.add_ready_article()


@when("발송 작업을 실행한다")
def _run(env, ctx):
    ctx.report = env.service.run()


@then('"ready"인 글만 발송된다')
def _only_ready_sent(env, ctx):
    assert env.article(ctx.extra["ready"]).status == "delivered"
    assert len(env.sender.calls) == 1


@then('"collected"인 글은 그대로 남는다')
def _collected_stays(env, ctx):
    assert env.article(ctx.extra["collected"]).status == "collected"


# ---------- 메시지 형식 (DLV-06 ~ 10): 순수 규칙으로 검증 ----------


def message_defaults(ctx):
    return ctx.extra.setdefault(
        "m",
        {
            "site": "Blog",
            "emoji": "📢",
            "title": "제목",
            "summary": "요약",
            "published": "2026-10-16T14:32:00+09:00",
            "article_id": 123,
        },
    )


def make_message(ctx):
    m = message_defaults(ctx)
    ctx.extra["message"] = build_message(
        site=m["site"],
        emoji=m["emoji"],
        title=m["title"],
        summary=m["summary"],
        published=m["published"],
        link_url=article_url("https://rss.example.com", m["article_id"]),
        tz=SEOUL,
    )


@given(
    parsers.parse(
        '글 {article_id:d}의 사이트는 "{site}", 번역 제목은 "{title}", 요약은 "{summary}"이다'
    )
)
def _article_fields(ctx, article_id, site, title, summary):
    message_defaults(ctx).update(article_id=article_id, site=site, title=title, summary=summary)


@given("글의 발행 시각은 서비스 시간대 14시 32분이다")
def _published_1432(ctx):
    message_defaults(ctx)["published"] = "2026-10-16T14:32:00+09:00"


@given(parsers.parse('글의 원문 주소는 "{url}"이다'))
def _original_url(ctx, url):
    ctx.extra["original"] = url


@given(parsers.re(r'글의 발행 시각 값이 "(?P<published>.*)"이다'))
def _published_value(ctx, published):
    message_defaults(ctx)["published"] = published or None


@given(parsers.parse('피드 "{site}"의 머리말 이모지 설정은 "{emoji}"이다'))
def _emoji_setting(ctx, site, emoji):
    message_defaults(ctx).update(site=site, emoji=emoji)


@given("요약이 2500자인 글이 있다")
def _long_summary(ctx):
    message_defaults(ctx)["summary"] = "가" * 2500


@given("번역 제목이 3000자인 글이 있다")
def _long_title(ctx):
    message_defaults(ctx)["title"] = "나" * 3000


@when("메시지를 만든다")
def _build(ctx):
    make_message(ctx)


@then("메시지는 다음과 같다")
def _message_is(ctx, docstring):
    assert ctx.extra["message"] == docstring


@then(parsers.parse('메시지에 "{text}"은 들어 있지 않다'))
def _message_lacks(ctx, text):
    assert text not in ctx.extra["message"]


@then(parsers.parse("머리말 끝에 {time_part}"))
def _header_time(ctx, time_part):
    header = ctx.extra["message"].splitlines()[0]
    if time_part.startswith("`"):
        assert header.endswith(" " + time_part.split("`")[1].join("``"))
    else:
        assert re.search(r"`\d\d:\d\d`$", header) is None


@then(parsers.parse('머리말은 "{expected}"으로 시작한다'))
def _header_starts(ctx, expected):
    assert ctx.extra["message"].startswith(expected)


@then("메시지 길이는 1900자 이하이다")
def _length(ctx):
    assert len(ctx.extra["message"]) <= 1900


@then("머리말, 제목, 서비스 글 링크는 그대로 들어 있다")
def _parts_kept(ctx):
    message = ctx.extra["message"]
    assert message.startswith("📢 **[Blog] 새 글 알림**")
    assert "**제목**" in message
    assert message.endswith("(https://rss.example.com/a/123)")


@then("서비스 글 링크는 그대로 들어 있다")
def _link_kept(ctx):
    assert ctx.extra["message"].endswith("(https://rss.example.com/a/123)")


@then("요약은 말줄임표로 끝난다")
def _summary_ellipsis(ctx):
    lines = ctx.extra["message"].splitlines()
    assert lines[-2].endswith("…")


# ---------- 발송 기록과 재시도 (DLV-11 ~ 16) ----------


@given('주제 "OTT"에 해당하는 글의 발송 대상은 "rss"와 "ott"이다')
def _ott_article(env, ctx):
    ctx.article_id = env.add_ready_article(title=OTT_TITLE, topics=("OTT",))


@given('"rss"는 성공하고 "ott"는 서버 오류로 실패한다')
def _ott_fails(env):
    env.sender.will(webhook_url("ott"), http(503))


@then('"rss" 발송은 "sent"로 기록된다')
def _rss_sent(env, ctx):
    assert env.statuses(ctx.article_id)["rss:primary"] == "sent"


@then('"ott" 발송은 "pending"으로 남고 시도 횟수가 1 오른다')
def _ott_pending(env, ctx):
    ott = next(
        d for d in env.deliveries.for_article(ctx.article_id) if d.purpose.startswith("topic:")
    )
    assert (ott.status, ott.attempts) == ("pending", 1)


@then('글의 상태는 아직 "delivered"가 아니다')
def _not_delivered_yet(env, ctx):
    assert env.article(ctx.article_id).status != "delivered"


@when('"ott"가 복구되고 발송 작업을 다시 실행한다')
def _recovered(env, ctx):
    ctx.report = env.service.run()


@then('"ott"로만 1번 더 보낸다')
def _only_ott_again(env):
    assert len(env.sender.to("ott")) == 2


@then('"rss"로는 다시 보내지 않는다')
def _rss_not_again(env):
    assert len(env.sender.to("rss")) == 1


@then('글의 상태는 "delivered"가 된다')
def _becomes_delivered(env, ctx):
    assert env.article(ctx.article_id).status == "delivered"


@given("글의 발송 대상이 모두 성공한다")
def _all_succeed(env, ctx):
    ctx.article_id = env.add_ready_article()


@then('글의 상태는 "delivered"이다')
def _is_delivered(env, ctx):
    assert env.article(ctx.article_id).status == "delivered"


@then('글의 GUID는 "이미 본 글"로 기록된다')
def _guid_seen(env, ctx):
    assert env.articles.is_seen(env.article(ctx.article_id).guid) is True


@given("웹훅이 429와 Retry-After 2초로 답한다")
def _webhook_429(env, ctx):
    ctx.article_id = env.add_ready_article()
    env.sender.will(webhook_url("rss"), http(429, 2.0), http(429, 2.0))


@then("2초 뒤에 같은 웹훅으로 한 번 더 보낸다")
def _retry_after_two(env):
    assert env.sleeps == [2.0]
    assert len(env.sender.to("rss")) == 2


@then("그래도 실패하면 이번 실행에서는 더 시도하지 않고 다음 실행으로 넘긴다")
def _then_stop(env, ctx):
    assert ctx.report.stopped_early is True
    assert len(env.sender.to("rss")) == 2  # 더 시도하지 않았다
    assert env.article(ctx.article_id).status == "ready"
    env.service.run()  # 다음 실행에서 다시 시도해서 보낸다
    assert env.article(ctx.article_id).status == "delivered"


@given(parsers.parse('웹훅 "dev"가 {status:d} 상태 코드로 답한다'))
def _dev_refuses(env, ctx, status):
    env.settings.set_webhook_roles(default_id=env.webhooks["dev"], system_id=env.webhooks["시스템"])
    ctx.article_id = env.add_ready_article()
    env.sender.will(webhook_url("dev"), http(status), http(status))


@then('"dev" 대상 발송은 "failed_permanent"로 기록된다')
def _dev_permanent(env, ctx):
    assert env.statuses(ctx.article_id) == {"dev:primary": "failed_permanent"}


@then("시스템 웹훅으로 알림이 1번 간다")
def _one_alert(env):
    assert len(env.notifier.sent) == 1
    assert env.notifier.sent[0][0] == webhook_url("시스템")


@then("같은 웹훅의 같은 실패는 쿨다운 동안 다시 알리지 않는다")
def _no_repeat_alert(env):
    env.add_ready_article()
    env.service.run()
    assert len(env.notifier.sent) == 1


@given("기본 웹훅이 등록되어 있지 않다")
def _no_default_webhook(env):
    env.settings.set_webhook_roles(default_id=None, system_id=env.webhooks["시스템"])


@given("피드는 카테고리에 속하지 않는다")
def _no_category(env):
    assert env.feeds.get(env.feed_id).category_id is None


@given('"ready"인 글이 있다')
def _ready_article(env, ctx):
    ctx.article_id = env.add_ready_article()


@then('글은 발송되지 않고 "ready"로 남는다')
def _unsent(env, ctx):
    assert env.sender.calls == [] and env.article(ctx.article_id).status == "ready"


@then("시스템 웹훅이 있으면 알림이 1번 간다")
def _one_alert_if_configured(env):
    assert len(env.notifier.sent) == 1


@given("발송 대기 글이 10:00, 10:20, 10:10에 발행되었다")
def _three_waiting(env):
    for hour_minute in ("10:00", "10:20", "10:10"):
        hour, minute = (int(part) for part in hour_minute.split(":"))
        env.add_ready_article(published=datetime(2026, 10, 16, hour, minute, tzinfo=SEOUL))


@then("발송 순서는 10:00, 10:10, 10:20이다")
def _order(env):
    times = [re.search(r"`(\d\d:\d\d)`", c.content).group(1) for c in env.sender.calls]
    assert times == ["10:00", "10:10", "10:20"]


# ---------- 안전 (DLV-17) ----------


@given("웹훅 주소와 OpenRouter 키가 설정되어 있다")
def _secrets_configured(env):
    env.settings.set_openrouter_key(KEY)
    env.settings.update({"model_chain": "m1:free"})


@when("발송 실패, LLM 실패, 상태 조회가 일어난다")
def _failures_and_status(env, ctx, tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    seen: list[str] = []

    # 발송 실패: 전송기가 주소를 담은 예외를 올린다
    env.sender.will(webhook_url("rss"), RuntimeError(f"failed: {webhook_url('rss')}"))
    env.add_ready_article()
    env.service.run()

    # LLM 실패: 서버가 오류 문구에 키를 되풀이한다
    server = FakeServer(
        lambda *_: json_reply(500, {"error": {"code": 500, "message": f"upstream saw {KEY}"}})
    )
    server.start()
    try:
        gateway = LlmGateway(
            client=OpenRouterClient(env.settings.get_openrouter_key, base_url=server.url()),
            usage=LlmUsageRepository(env.db, env.clock),
            settings=env.settings,
            alerts=env.alerts,
            clock=env.clock,
            sleep=lambda _seconds: None,
        )
        with pytest.raises(LlmOutage) as outage:
            gateway.complete("프롬프트")
        seen.append(str(outage.value))
    finally:
        server.stop()

    # 상태 조회: 상태 화면, 설정 화면, 상태 확인
    client = TestClient(create_app(data_dir=tmp_path, clock=env.clock), follow_redirects=False)
    for path in ("/", "/settings", "/healthz"):
        seen.append(client.get(path).text)
    ctx.extra["seen"] = seen


@then("로그와 응답 어디에도 웹훅 주소의 토큰 부분과 API 키 전체가 없다")
def _no_secrets(env, ctx, caplog):
    everything = "\n".join([caplog.text, *ctx.extra["seen"], *env.notifier.texts()])
    deliveries = " ".join(str(d.last_error) for d in env.deliveries.for_article(1))
    for secret in (KEY, "TOKEN1SECRET", "TOKEN5SECRET"):
        assert secret not in everything + deliveries


# ---------- 서비스 주소 (DLV-19, 20) ----------


@given("설정의 서비스 주소가 비어 있다")
def _empty_base_url(env):
    env.settings.update({"service_base_url": ""})


@then('상태 화면에 "서비스 주소 필요"가 표시된다')
def _status_shows_notice(env, tmp_path):
    client = TestClient(create_app(data_dir=tmp_path, clock=env.clock), follow_redirects=False)
    assert "서비스 주소 필요" in client.get("/").text


@given(parsers.parse('글 123이 "ready"이고 서비스 주소는 "{url}"이다'))
def _old_address(env, ctx, url):
    env.settings.update({"service_base_url": url})
    ctx.extra["earlier"] = env.add_ready_article(summary_ko="이미 나간 글")
    env.service.run()  # 이 글은 옛 주소로 이미 나갔다
    ctx.article_id = env.add_ready_article(summary_ko="새로 나갈 글")


@when(parsers.parse('서비스 주소를 "{url}"으로 바꾸고 발송 작업을 실행한다'))
def _change_address_and_run(env, url):
    env.settings.update({"service_base_url": url})
    env.service.run()


@then(parsers.parse('메시지의 링크는 "{link}"이다'))
def _message_link(env, ctx, link):
    expected = link.replace("/a/123", f"/a/{ctx.article_id}")
    assert env.sender.calls[-1].content.endswith(f"({expected})")


@then("이미 Discord로 나간 메시지는 바꾸지 않는다")
def _earlier_unchanged(env, ctx):
    assert len(env.sender.calls) == 2  # 이미 나간 글을 다시 보내거나 고치지 않았다
    assert env.sender.calls[0].content.endswith(
        f"(https://old.example.com/a/{ctx.extra['earlier']})"
    )


@then('주제 "OTT"에 해당했다는 기록과 일치한 키워드가 남는다')
def _matches_recorded(env, ctx):
    matches = env.topics.matches_for(ctx.article_id)
    assert set(matches) == {env.topic_id("OTT")}
    assert "netflix" in matches[env.topic_id("OTT")]
