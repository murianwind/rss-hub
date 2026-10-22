"""25_settings_topics_refine.feature: 시간대, 아코디언, 주제 관리, 알림, 모델 화면."""

import re
from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, then, when

from rss_hub.domain.topics import TopicFields, is_candidate
from rss_hub.services.ports import KeyCheck
from tests.bdd.binding import bind
from tests.fakes.llm_env import LlmEnv
from tests.fakes.models_env import free
from tests.keywords.browser import FRAGMENT, post
from tests.keywords.models import scan
from tests.keywords.page import text_of

bind(globals(), "25_settings_topics_refine.feature", [f"STP-{n:02d}" for n in range(1, 18)])

KEY = "sk-or-v1-abcdefghijklmnop"
PAGES = {
    "설정 화면": "/settings",
    "Discord 화면": "/discord",
    "모델 화면": "/models",
    "상태 화면": "/status",
    "주제 관리 화면": "/topics",
}
WEBHOOK_BLANK = "지정 안 함(추가 알림 없음, 읽기 화면에만 모음)"


@pytest.fixture
def ctx():
    return SimpleNamespace(html="", response=None, topic=None, pages={}, results=[], env=None)


@pytest.fixture
def env(tmp_path):
    return LlmEnv(tmp_path)


def topic_card(html, name):
    """주제 목록에서 이름이 든 카드 하나."""
    cards = html.split('<article class="topic-card"')[1:]
    return next(c.split("</article>")[0] for c in cards if f'data-topic-name="{name}"' in c)


def add_topic(world, name, *keywords, description=""):
    return world.topics.add(TopicFields(name, description, tuple(keywords)))


def add_manual_suggestion(world, topic_id, word):
    """ "주제로"를 두 번 눌러 그 단어를 추가 제안으로 만든다."""
    for suffix in ("할인 시작", "겨울 세일"):
        article = world.article(title=f"{word} {suffix}")
        world.topics.add_manual(article, topic_id)


def add_removal_suggestion(world, topic_id, keyword):
    """그 키워드로 들어온 글을 싫어요로 두 번 빼서 제거 제안으로 만든다."""
    for number in (1, 2):
        article = world.article(title=f"{keyword} other news {number}")
        world.topics.record_matches(article, {topic_id: (keyword,)})
        world.topics.reject(article, topic_id)


@given("서비스가 시작되어 있다")
def _started():
    """화면이 필요한 단계에서 앱이 만들어진다."""


@given(parsers.re(r'주제 "(?P<name>[^"]+)"[이가] 있다$'))
def _topic(world, ctx, name):
    ctx.topic = add_topic(world, name, "steam")


@given(parsers.parse('주제 "{name}"이 설명 "{description}"과 함께 있다'))
def _topic_with_description(world, ctx, name, description):
    ctx.topic = add_topic(world, name, "steam", description=description)


@given(parsers.parse('키워드가 없는 기존 주제 "{name}"가 있다'))
def _legacy_topic(world, ctx, name):
    ctx.topic = add_topic(world, name)


@given(parsers.parse('주제 "{first}"과 "{second}"가 있고 "{with_help}"에만 키워드 제안이 있다'))
def _topics_one_with_suggestions(world, first, second, with_help):
    game = add_topic(world, first, "steam")
    add_topic(world, second, "netflix")
    assert with_help == first
    add_manual_suggestion(world, game, "스팀")


@given(parsers.parse('주제 "{name}"에 추가 제안 "{add}"과 제거 제안 "{remove}"이 있다'))
def _topic_with_both_suggestions(world, ctx, name, add, remove):
    ctx.topic = add_topic(world, name, "steam", remove)
    add_manual_suggestion(world, ctx.topic, add)
    add_removal_suggestion(world, ctx.topic, remove)


@given(parsers.parse("무료 모델이 {count:d}개 스캔되어 있다"))
def _scanned(world, count):
    world.parts.llm.free_models = [free(f"google/model-{n}:free") for n in range(count)]
    scan(world)


@given("키 확인은 실패하도록 되어 있다")
def _check_fails(world):
    world.parts.llm.key_check = KeyCheck(valid=False, reason="OpenRouter가 키를 거부했습니다")


@given("시스템 알림 웹훅이 있고 반복 보내기는 꺼져 있다")
def _repeat_off(env):
    assert env.settings.snapshot().alert_repeat is False


@given(parsers.parse("시스템 알림 웹훅이 있고 반복 보내기를 켜고 간격은 {hours:d}시간이다"))
def _repeat_on(env, hours):
    env.settings.update({"alert_repeat": "on", "alert_cooldown_hours": str(hours)})


@when(parsers.re(r"(?P<name>.+?)[을를] 연다$"))
def _open(world, ctx, name):
    ctx.response = world.get(PAGES[name])
    ctx.html = ctx.response.text
    assert ctx.response.status_code == 200


@when(parsers.parse('서비스 시간대를 "{zone}"로 저장한다'))
def _save_zone(world, ctx, zone):
    ctx.response = post(world, "/settings", service_timezone=zone, next="/settings")


@when("주제 관리 화면과 주제 추가와 수정 패널을 연다")
def _open_topic_screens(world, ctx):
    ctx.pages = {
        "목록": world.get("/topics").text,
        "추가": world.client.get("/panel/add/topic", headers=FRAGMENT).text,
        "수정": world.client.get(f"/panel/settings/topic/{ctx.topic}", headers=FRAGMENT).text,
    }


@when(parsers.parse('키워드를 비워서 주제 "{name}"를 추가한다'))
def _add_without_keywords(world, ctx, name):
    ctx.results.append(post(world, "/topics/add", name=name, keywords=""))


@when(parsers.parse('키워드를 비워서 주제 "{name}"을 수정한다'))
def _update_without_keywords(world, ctx, name):
    ctx.results.append(post(world, f"/topics/{ctx.topic}/update", name=name, keywords=""))


@when("키가 없을 때 주제 추가 패널과 수정 패널을 연다")
def _panels_without_key(world, ctx):
    assert not world.parts.settings.has_openrouter_key()
    _open_topic_screens(world, ctx)


@when("키를 설정하고 주제 추가 패널과 수정 패널을 연다")
def _panels_with_key(world, ctx):
    world.parts.settings.set_openrouter_key(KEY)
    _open_topic_screens(world, ctx)


@when(parsers.parse('추가 제안 "{word}"을 지운다'))
def _dismiss_addition(world, ctx, word):
    ctx.response = post(
        world, f"/topics/{ctx.topic}/suggestions/dismiss", kind="add", keyword=word, next="/topics"
    )


@when(parsers.parse("같은 종류의 알림을 {hours:d}시간 간격으로 두 번 보낸다"))
def _notify_twice(env):
    env.alerts.notify("same-kind", "문제가 생겼습니다")
    env.clock.advance(hours=3)
    env.alerts.notify("same-kind", "문제가 생겼습니다")


@when(parsers.parse("{hours:d}시간이 지난 뒤 같은 알림을 다시 보낸다"))
def _notify_later(env, hours):
    env.clock.advance(hours=hours)
    env.alerts.notify("same-kind", "문제가 생겼습니다")


@when(parsers.parse("같은 종류의 알림을 {first:d}시간 뒤와 {second:d}시간 뒤에 다시 보낸다"))
def _notify_repeat(env, first, second):
    env.alerts.notify("same-kind", "문제가 생겼습니다")
    env.clock.advance(hours=first)
    env.alerts.notify("same-kind", "문제가 생겼습니다")
    env.clock.advance(hours=second - first)
    env.alerts.notify("same-kind", "문제가 생겼습니다")


@when("모델 화면에서 OpenRouter 키를 저장한다")
def _save_key(world, ctx):
    saved = post(world, "/settings/openrouter-key", openrouter_key=KEY, next="/models")
    assert saved.status_code == 200
    ctx.response = saved
    ctx.html = saved.text


@then(parsers.re(r'서비스 시간대는 지역별로 묶인 선택 목록이고 "(?P<zone>[^"]+)"이 선택되어 있다'))
def _zone_select(ctx, zone):
    select = ctx.html.split('<select id="service_timezone"')[1].split("</select>")[0]
    assert '<optgroup label="Asia">' in select and '<optgroup label="America">' in select
    assert f'<option value="{zone}" selected>' in select
    assert '<option value="America/New_York"' in select


@then(parsers.parse('서비스 시간대는 "{zone}"이다'))
def _zone_is(world, zone):
    assert world.parts.settings.snapshot().timezone.key == zone


@then(parsers.parse('저장은 거부되고 서비스 시간대는 "{zone}"이다'))
def _zone_refused(world, ctx, zone):
    assert ctx.response.status_code == 400
    assert world.parts.settings.snapshot().timezone.key == zone


@then("모든 아코디언은 같은 그룹이라 한 번에 하나만 펼쳐진다")
def _exclusive(ctx):
    found = re.findall(r'<details class="acc" id="acc-\w+" name="settings-acc"', ctx.html)
    assert len(found) == 3 and ctx.html.count('<details class="acc"') == 3


@then('어디에도 "사용" 체크박스가 없다')
def _no_enabled(ctx):
    for page, html in ctx.pages.items():
        assert 'name="enabled"' not in html, page


@then(parsers.parse('웹훅 선택의 비움 항목은 "{label}"이다'))
def _blank_webhook(ctx, label):
    for page in ("추가", "수정"):
        assert f'<option value="">{label}</option>' in ctx.pages[page], page
    assert label == WEBHOOK_BLANK


@then(parsers.parse('제목은 "{first}", "{second}" 순서로 나온다'))
def _headings(ctx, first, second):
    shown = re.findall(r"<h2[^>]*>([^<]+)</h2>", ctx.html)
    assert [h for h in shown if h in (first, second)] == [first, second]


@then("주제 목록 머리말에 주제 추가 버튼이 있고 누르면 상단 패널 주소로 연결된다")
def _add_button(ctx):
    head = ctx.html.split("<h2>주제 목록</h2>")[1][:600]
    assert re.search(r'<a class="button" href="/panel/add/topic\?next=[^"]+" data-panel', head)


@then("이 화면에는 주제를 바로 추가하는 양식이 없다")
def _no_inline_add(ctx):
    assert 'action="/topics/add"' not in ctx.html


@then('두 요청 모두 "키워드가 필요함"으로 거부된다')
def _both_refused(ctx):
    assert [r.status_code for r in ctx.results] == [400, 400]
    assert all("키워드가 필요함" in r.text for r in ctx.results)


@then("설명 입력칸은 없다")
def _no_description(ctx):
    assert 'name="description"' not in ctx.pages["추가"] + ctx.pages["수정"]


@then("설명 입력칸이 있다")
def _description(ctx):
    assert 'name="description"' in ctx.pages["추가"] and 'name="description"' in ctx.pages["수정"]


@then("키가 없는 상태에서 주제를 수정해도 설명은 그대로 남는다")
def _description_kept(world, ctx):
    world.parts.settings.delete_openrouter_key()
    response = post(
        world, f"/topics/{ctx.topic}/update", name="게임", keywords="steam, 스팀", next="/topics"
    )
    assert response.status_code == 303
    assert world.topics.get(ctx.topic).description == "게임 소식"


@then(parsers.parse('"{name}" 카드에 "키워드를 입력하세요"가 보인다'))
def _card_hint(ctx, name):
    assert "키워드를 입력하세요" in topic_card(ctx.html, name)


@then(parsers.parse('제목에 어떤 단어가 있어도 "{name}"는 판정 후보가 되지 않는다'))
def _not_candidate(world, ctx, name):
    topic = world.topics.get(ctx.topic)
    assert topic.name == name
    assert not is_candidate(topic, "Anything steam netflix", "<p>body</p>")


@then(parsers.parse('"{name}" 카드에는 개수가 적힌 "키워드 개선 제안" 아코디언이 있다'))
def _has_accordion(ctx, name):
    card = topic_card(ctx.html, name)
    assert re.search(
        r'<details class="suggest-acc"[^>]*>\s*<summary>[^<]*키워드 개선 제안 \(\d+\)', card
    )


@then(parsers.parse('"{name}" 카드에는 개선 제안 아코디언이 없다'))
def _no_accordion(ctx, name):
    assert "suggest-acc" not in topic_card(ctx.html, name)


@then("제안 단어마다 적용 버튼과 지우기 버튼이 있다")
def _suggestion_buttons(ctx):
    card = topic_card(ctx.html, "게임")
    topic = ctx.topic
    for action, word in (("add", "스팀"), ("remove", "sale")):
        assert f'action="/topics/{topic}/keywords/{action}"' in card and f'value="{word}"' in card
    assert card.count(f'action="/topics/{topic}/suggestions/dismiss"') == 2


@then(parsers.parse('추가 제안 "{gone}"은 더 나오지 않고 제거 제안 "{kept}"은 남아 있다'))
def _dismissed(ctx, gone, kept):
    card = topic_card(ctx.html, "게임")
    assert f'name="keyword" value="{gone}"' not in card
    assert f'name="keyword" value="{kept}"' in card


@then("알림은 한 번만 나간다")
def _one_alert(env):
    assert len(env.notifier.sent) == 1


@then("알림은 두 번째로 나간다")
def _second_alert(env):
    assert len(env.notifier.sent) == 2


@then("알림은 처음과 3시간 뒤, 두 번 나간다")
def _two_alerts(env):
    assert len(env.notifier.sent) == 2


@then("같은 알림 반복 보내기는 끔과 켬 중에서 고르고 반복 간격 설명이 있다")
def _repeat_setting(ctx):
    select = ctx.html.split('<select id="alert_repeat"')[1].split("</select>")[0]
    assert ">끔<" in select and ">켬<" in select
    assert "24시간" in text_of(ctx.response) and 'id="alert_cooldown_hours"' in ctx.html


@then("체인 편집이 무료 모델 목록보다 위에 있고 무료 모델 목록은 스크롤 영역 안에 있다")
def _scroll_list(ctx):
    html = ctx.html
    assert html.index("data-chain-editor") < html.index('class="checks model-list')
    wrapper = html.split('<div class="model-scroll"')[1]
    assert wrapper.index("model-list") < wrapper.index("</form>")
    assert html.count('class="check model-row"') == 12


@then("저장했고 키가 유효하다는 결과가 모델 화면에 보인다")
def _saved_and_valid(ctx):
    text = text_of(ctx.response)
    assert "저장했습니다" in text and "키가 유효합니다" in text


@then("키 영역에는 저장과 삭제와 무료 모델 스캔이 한 줄로 있고 확인 버튼은 없다")
def _key_row(ctx):
    html = ctx.html
    assert 'action="/settings/openrouter-key/check"' not in html
    row = html.split('<div class="key-row"')[1].split("</section>")[0]
    assert 'action="/settings/openrouter-key"' in row and 'action="/models/scan"' in row
    assert row.count("<button") >= 2


@then("키는 저장되었고 확인 실패 이유가 화면에 보인다")
def _saved_but_failed(world, ctx):
    assert world.parts.settings.has_openrouter_key()
    text = text_of(ctx.response)
    assert "키 확인에 실패했습니다" in text and "OpenRouter가 키를 거부했습니다" in text


@then("변경 이력은 스크롤 영역 안에 있고 버전 정보는 없다")
def _history(ctx):
    content = ctx.html.split('<div class="page')[1]
    assert '<div class="history-scroll"' in content
    assert "버전" not in content
