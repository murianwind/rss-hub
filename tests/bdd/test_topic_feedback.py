"""13_topic_feedback.feature: 싫어요, 주제로, 키워드 개선 제안, 요청의 예시."""

import html as html_module
import re
from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, then, when

from rss_hub.domain.topics import TopicFields
from rss_hub.runtime import build_llm_services
from rss_hub.services.deliver import DeliveryService
from rss_hub.services.summarize import SummarizeService
from rss_hub.storage.deliveries import DeliveryRepository
from tests.bdd.binding import bind
from tests.fakes.delivery_env import webhook_url
from tests.fakes.llm_client import reply
from tests.fakes.llm_env import KEY
from tests.fakes.viewer_world import World
from tests.fakes.web_parts import start_app

bind(globals(), "13_topic_feedback.feature", [f"FBK-{n:02d}" for n in range(1, 13)])

BROWSER = {"origin": "null", "sec-fetch-site": "same-origin"}
ACTIONS = {"싫어요": "reject", "되돌리기": "restore", "주제로": "add"}


@pytest.fixture
def world(tmp_path):
    parts, client = start_app(tmp_path)
    with client:
        yield World(parts)


@pytest.fixture
def ctx():
    return SimpleNamespace(ids={}, last=None, response=None)


def topic_id(world, name):
    return next(t.id for t in world.topics.list_all() if t.name == name)


def press(world, article, topic, action, **extra):
    path = f"/a/{article}/topics/{topic_id(world, topic)}/{ACTIONS[action]}"
    return world.client.post(path, data=extra, headers=BROWSER)


def listed(world, topic):
    return [
        a
        for a in re.findall(
            r'<a class="title" href="/a/(\d+)"',
            world.get(f"/reader/topic/{topic_id(world, topic)}").text,
        )
    ]


# ---------- 배경 ----------


@given('사이트 "자유 블로그"와 주제 "OTT"(키워드 "netflix"), 주제 "게임"(키워드 "steam")이 있다')
def _background(world):
    ott = world.topics.list_all()[0]
    world.topics.update(
        ott.id, TopicFields("OTT", "스트리밍", ("netflix",)), webhook_id=None, enabled=True
    )
    world.topics.add(TopicFields("게임", "게임 소식", ("steam",)))


# ---------- 글 만들기 ----------


@given(parsers.re(r'주제 "(?P<topic>[^"]+)"로 분류된 글 "(?P<title>[^"]+)"가 있다'))
def _classified(world, ctx, topic, title):
    ctx.last = world.article(title=title)
    world.topics.record_matches(ctx.last, {topic_id(world, topic): ("netflix",)})


@given(parsers.re(r'어느 주제에도 속하지 않은 글 "(?P<title>[^"]+)"가 있다'))
def _unclassified(world, ctx, title):
    ctx.last = world.article(title=title)
    ctx.ids[title] = ctx.last


# ---------- 버튼 ----------


@given(parsers.re(r'그 글에 주제 "(?P<topic>[^"]+)"의 (?P<action>싫어요|되돌리기|주제로)를 눌렀다'))
def _pressed(world, ctx, topic, action):
    press(world, ctx.last, topic, action)


@when(parsers.re(r'그 글에 주제 "(?P<topic>[^"]+)"의 (?P<action>싫어요|되돌리기|주제로)를 누른다'))
def _press(world, ctx, topic, action):
    ctx.response = press(world, ctx.last, topic, action)


@given(parsers.re(r'두 글에 주제 "(?P<topic>[^"]+)"의 주제로를 눌렀다'))
def _press_both(world, ctx, topic):
    for article in ctx.ids.values():
        press(world, article, topic, "주제로")


@then(parsers.re(r'주제 "(?P<topic>[^"]+)" 목록에는 그 글이 없다'))
def _not_in_topic(world, ctx, topic):
    assert str(ctx.last) not in listed(world, topic)


@then(parsers.re(r'주제 "(?P<topic>[^"]+)" 목록에 그 글이 (?:다시 )?있다'))
def _in_topic(world, ctx, topic):
    assert str(ctx.last) in listed(world, topic)


@then(parsers.re(r'주제 "(?P<topic>[^"]+)" 목록에는 그 글이 있다'))
def _in_topic_alt(world, ctx, topic):
    assert str(ctx.last) in listed(world, topic)


@then('전체 목록과 사이트 "자유 블로그" 목록에는 그 글이 그대로 있다')
def _still_elsewhere(world, ctx):
    assert f'href="/a/{ctx.last}"' in world.get("/reader").text
    assert f'href="/a/{ctx.last}"' in world.get(f"/reader/feed/{world.f_free}").text


@then(parsers.re(r'글 페이지에는 주제 "(?P<topic>[^"]+)"의 싫어요 버튼이 보인다'))
def _dislike_button(world, ctx, topic):
    assert (
        f"/a/{ctx.last}/topics/{topic_id(world, topic)}/reject" in world.get(f"/a/{ctx.last}").text
    )


# ---------- 발송 ----------


@pytest.fixture
def deliverer(world):
    parts = world.parts
    parts.settings.update({"service_base_url": "https://rss.example.com"})
    rss = parts.settings.add_webhook("rss", webhook_url("rss"))
    ott_hook = parts.settings.add_webhook("ott", webhook_url("ott"))
    parts.settings.set_webhook_roles(default_id=rss, system_id=None)
    ott = topic_id(world, "OTT")
    world.topics.update(
        ott, TopicFields("OTT", "스트리밍", ("netflix",)), webhook_id=ott_hook, enabled=True
    )
    alerts = build_llm_services(
        parts.db, parts.clock, parts.settings, client=parts.llm, sender=parts.sender
    ).alerts
    return DeliveryService(
        articles=world.articles,
        feeds=world.feeds,
        deliveries=DeliveryRepository(parts.db, parts.clock),
        settings=parts.settings,
        topics=world.topics,
        sender=parts.sender,
        alerts=alerts,
        clock=parts.clock,
        sleep=lambda seconds: None,
    )


def ready(world, title, judged):
    article = world.article(title=title)
    topics = [topic_id(world, "OTT")] if judged else []
    world.articles.mark_ready(
        article, title_ko="번역 제목", summary_ko="요약", topics=topics, model="m"
    )
    if judged:  # 요약 서비스는 요약 직후에 주제 소속을 기록한다
        world.topics.record_matches(article, {topic_id(world, "OTT"): ("netflix",)})
    return article


UNSENT = (
    r'아직 보내지 않은 글 "(?P<title>[^"]+)"이 있다'
    r'\(요약 단계에서 주제 "OTT"로 판정됨 (?P<judged>예|아니오)\)'
)


@given(parsers.re(UNSENT))
def _unsent(world, ctx, deliverer, title, judged):
    ctx.last = ready(world, title, judged == "예")


@given(
    parsers.re(
        r'사용자가 그 글에 주제 "(?P<topic>[^"]+)"의 (?P<action>싫어요|주제로|\(안 누름\))를 눌렀다'
    )
)
def _user_chose(world, ctx, topic, action):
    if action != "(안 누름)":
        press(world, ctx.last, topic, action)


@given(parsers.re(r'이미 기본 웹훅으로 보낸 글 "(?P<title>[^"]+)"가 있다'))
def _already_sent(world, ctx, deliverer, title):
    ctx.last = ready(world, title, False)
    deliverer.run()


@when("발송 작업이 실행된다")
def _deliver(deliverer):
    deliverer.run()


@then(parsers.re(r'기본 웹훅으로는 나가고 주제 "OTT" 웹훅으로는 (?P<result>나간다|나가지 않는다)'))
def _routing(world, result):
    assert len(world.parts.sender.to("rss")) == 1
    assert len(world.parts.sender.to("ott")) == (1 if result == "나간다" else 0)


@then(parsers.re(r'주제 "OTT" 웹훅으로는 아무것도 나가지 않는다'))
def _nothing_to_topic(world):
    assert world.parts.sender.to("ott") == []


@when('요약 단계가 같은 글을 주제 "OTT"로 다시 판정해 기록한다')
def _judged_again(world, ctx):
    world.topics.record_matches(ctx.last, {topic_id(world, "OTT"): ("netflix",)})


# ---------- 제안 ----------


@given(
    parsers.re(
        r'키워드 "(?P<keyword>[^"]+)"로 주제 "(?P<topic>[^"]+)"에 들어온 글 2개에 싫어요를 눌렀다'
    )
)
def _two_dislikes(world, keyword, topic):
    for number in range(2):
        article = world.article(title=f"Misled {number}")
        world.topics.record_matches(article, {topic_id(world, topic): (keyword,)})
        press(world, article, topic, "싫어요")


@when(parsers.re(r'주제 "(?P<topic>[^"]+)"의 키워드 개선 제안을 연다'))
def _open_suggestions(world, ctx, topic):
    ctx.response = world.get(f"/topics/{topic_id(world, topic)}/suggestions")


@then(parsers.re(r'"(?P<keyword>[^"]+)"를 키워드에 추가하자는 제안이 근거 글과 함께 보인다'))
def _addition_shown(ctx, keyword):
    text = ctx.response.text
    assert f"<strong>{keyword}</strong>" in text and "/keywords/add" in text
    assert "Squid Game trailer" in text and "Squid Game cast" in text


REMOVAL_SHOWN = (
    r'"(?P<keyword>[^"]+)"를 키워드에서 빼자는 제안이 '
    r'"(?P<evidence>[^"]+)"이라는 근거와 함께 보인다'
)


@then(parsers.re(REMOVAL_SHOWN))
def _removal_shown(ctx, keyword, evidence):
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", ctx.response.text))
    assert f"{keyword} " in text and evidence in text and "/keywords/remove" in ctx.response.text


def keywords_of(world, topic):
    return world.topics.get(topic_id(world, topic)).keywords


@when(parsers.re(r'주제 "(?P<topic>[^"]+)"의 제안에서 "(?P<keyword>[^"]+)"를 키워드에 추가한다'))
def _add_keyword(world, ctx, topic, keyword):
    ctx.response = world.client.post(
        f"/topics/{topic_id(world, topic)}/keywords/add", data={"keyword": keyword}, headers=BROWSER
    )


@when(parsers.re(r'주제 "(?P<topic>[^"]+)"의 제안에서 "(?P<keyword>[^"]+)"를 키워드에서 뺀다'))
def _remove_keyword(world, ctx, topic, keyword):
    ctx.response = world.client.post(
        f"/topics/{topic_id(world, topic)}/keywords/remove",
        data={"keyword": keyword},
        headers=BROWSER,
    )


@then(parsers.re(r'주제 "(?P<topic>[^"]+)"의 키워드는 "(?P<a>[^"]+)", "(?P<b>[^"]+)"이다'))
def _keywords_are(world, topic, a, b):
    assert keywords_of(world, topic) == (a, b)


@then(
    parsers.re(
        r'마지막 키워드는 지울 수 없다는 안내가 보이고 키워드는 "(?P<keyword>[^"]+)" 하나로 남는다'
    )
)
def _last_kept(world, ctx, keyword):
    assert (
        ctx.response.status_code == 400 and "마지막 키워드는 지울 수 없습니다" in ctx.response.text
    )
    assert keywords_of(world, "OTT") == (keyword,)


# ---------- 요청의 예시 ----------


@given('주제 "OTT"에 직접 넣은 글 3개와 싫어요로 뺀 글 3개가 있다')
def _samples(world, ctx):
    ott = topic_id(world, "OTT")
    for number in range(3):
        manual = world.article(title=f"Manual sample {number}")
        world.articles.mark_ready(manual, title_ko="t", summary_ko="s", topics=[], model="m")
        world.topics.add_manual(manual, ott)
        rejected = world.article(title=f"Rejected sample {number}")
        world.articles.mark_ready(rejected, title_ko="t", summary_ko="s", topics=[], model="m")
        world.topics.record_matches(rejected, {ott: ("netflix",)})
        world.topics.reject(rejected, ott)
        world.parts.clock.advance(minutes=1)


@given(parsers.re(r"요약 요청에 넣을 예시 수 설정은 (?P<count>\d+)이다"))
def _example_count(world, count):
    world.parts.settings.update({"topic_feedback_examples": count})


@given('제목에 "Netflix"가 있는 영문 글이 수집되어 있다')
def _netflix_article(world, ctx):
    ctx.last = world.article(title="Netflix announces a drama")


@when("요약 작업을 실행한다")
def _summarize(world):
    parts = world.parts
    parts.settings.set_openrouter_key(KEY)
    parts.settings.update({"model_chain": "model-a", "service_base_url": "https://rss.example.com"})
    default = parts.settings.add_webhook("기본", webhook_url("rss"))
    parts.settings.set_webhook_roles(default_id=default, system_id=None)
    parts.llm.default = reply("제목", "요약", topics=[])
    gateway = build_llm_services(
        parts.db, parts.clock, parts.settings, client=parts.llm, sender=parts.sender
    ).gateway
    SummarizeService(
        articles=world.articles,
        gateway=gateway,
        settings=parts.settings,
        topics=world.topics,
        clock=parts.clock,
    ).run()


EXAMPLES_IN_REQUEST = (
    r'요청에는 "직접 넣은 글" 예시 (?P<belongs>\d+)개와 '
    r'"싫어요로 뺀 글" 예시 (?P<rejected>\d+)개가 들어 있다'
)


@then(parsers.re(EXAMPLES_IN_REQUEST))
def _examples_in_request(world, belongs, rejected):
    prompt = next(
        c.prompt for c in world.parts.llm.calls if "Netflix announces a drama" in c.prompt
    )

    def count(label):
        line = next((x for x in prompt.splitlines() if label in x), "")
        return len(re.findall(r'"([^"]+)"', line.split(":", 1)[1])) if line else 0

    assert count("Confirmed by the user, belongs:") == int(belongs)
    assert count("Confirmed by the user, does NOT belong:") == int(rejected)


# ---------- 보안 ----------


@when(
    parsers.re(r'돌아갈 곳을 "(?P<target>[^"]+)"로 지정해서 그 글에 주제 "OTT"의 주제로를 누른다')
)
def _press_with_next(world, ctx, target):
    ctx.response = press(world, ctx.last, "OTT", "주제로", next=target)


@then(parsers.re(r'돌아가는 곳은 "(?P<result>[^"]+)"이다'))
def _redirect_target(ctx, result):
    expected = f"/a/{ctx.last}" if result == "그 글의 페이지" else result
    assert ctx.response.headers["location"] == html_module.unescape(expected)


@when('다른 사이트에서 그 글에 주제 "OTT"의 주제로 요청을 보낸다')
def _cross_site(world, ctx):
    ctx.response = world.client.post(
        f"/a/{ctx.last}/topics/{topic_id(world, 'OTT')}/add",
        data={},
        headers={"origin": "https://evil.example.com", "sec-fetch-site": "cross-site"},
    )


@then("요청은 거부되고 글은 주제에 들어가지 않는다")
def _rejected(world, ctx):
    assert ctx.response.status_code == 403 and world.topics.memberships(ctx.last) == []
