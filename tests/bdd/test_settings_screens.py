"""23_settings_screens.feature: 환경 설정 화면 구성."""

import re
from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, then, when

from rss_hub.domain.topics import TopicFields
from rss_hub.services.settings import SETTING_DEFS
from tests.bdd.binding import bind
from tests.keywords.backup import download_backup, restore_backup
from tests.keywords.browser import post
from tests.keywords.page import text_of

bind(globals(), "23_settings_screens.feature", [f"SCR-{n:02d}" for n in range(1, 12)])

KEY = "sk-or-v1-abcdefghijklmnop"
PAGES = {
    "읽기 화면": "/reader",
    "설정 화면": "/settings",
    "Discord 화면": "/discord",
    "모델 화면": "/models",
    "백업·복원 화면": "/backup",
    "상태 화면": "/status",
    "주제 관리 화면": "/topics",
    "피드 가져오기": "/import",
    "카테고리 관리": "/categories",
}


@pytest.fixture
def ctx():
    return SimpleNamespace(html="", response=None, topic=None, results={})


def accordion_titles(html):
    return [t.strip() for t in re.findall(r"<summary><span>\d+\. ([^<:]+)", html)]


def headings(html):
    return re.findall(r"<h2[^>]*>([^<]+)</h2>", html)


@given("서비스가 시작되어 있다")
def _started(world):
    assert world.get("/healthz").status_code == 200


@given(parsers.re(r'웹훅 "(?P<first>[^"]+)"와 "(?P<second>[^"]+)"가 등록되어 있다'))
def _webhooks(world, first, second):
    for index, name in enumerate((first, second), start=1):
        url = f"https://discord.com/api/webhooks/{index}/tok{index}"
        world.parts.settings.add_webhook(name, url)


@given("설정을 한 번 바꿨다")
def _changed(world):
    world.parts.settings.update({"service_base_url": "https://rss.example.com"})


@given("주제가 하나 있다")
def _topic(world, ctx):
    ctx.topic = world.topics.add(TopicFields("게임", "게임 소식", ("steam",)))


@when(parsers.re(r"(?P<name>.+?)[을를] 연다$"))
def _open(world, ctx, name):
    if name == "주제 키워드 개선 제안":
        topic = ctx.topic or world.topics.list_all()[0].id
        path = f"/topics/{topic}/suggestions"
    elif name == "복원 결과":
        _, data = download_backup(world)
        ctx.response = restore_backup(world, data)
        ctx.html = ctx.response.text
        return
    else:
        path = PAGES[name]
    ctx.response = world.get(path)
    ctx.html = ctx.response.text
    assert ctx.response.status_code == 200, path


@when("모델 화면에서 OpenRouter 키를 저장한다")
def _save_key(world, ctx):
    ctx.response = post(world, "/settings/openrouter-key", openrouter_key=KEY, next="/models")


@when(parsers.parse('모델 화면에서 LLM 하루 상한에 "{value}"를 저장한다'))
def _bad_cap(world, ctx, value):
    ctx.results["models"] = post(world, "/models/settings", llm_daily_cap=value, next="/models")


@when(parsers.parse('Discord 화면에서 알림 쿨다운에 "{value}"를 저장한다'))
def _bad_cooldown(world, ctx, value):
    ctx.results["discord"] = post(
        world, "/discord/settings", alert_cooldown_hours=value, next="/discord"
    )


@then(parsers.parse('환경 설정 메뉴는 "{names}" 순서이다'))
def _menu(ctx, names):
    menu = ctx.html.split('id="sec-settings"')[1].split("</details>")[0]
    shown = [t.strip() for t in re.findall(r'<span class="sb-text">([^<]+)</span>', menu)]
    assert shown == names.split(", ")


@then(parsers.parse('항목은 "{names}" 순서이다'))
def _accordions(ctx, names):
    assert accordion_titles(ctx.html) == names.split(", ")


@then("OpenRouter 키, 웹훅, 변경 이력, 백업은 이 화면에 없다")
def _absent(ctx):
    text = text_of(ctx.response)
    for word in ("OpenRouter 키", "Discord 웹훅", "변경 이력", "백업 파일"):
        assert word not in text


@then("웹훅마다 한 줄에 이름과 시험 전송과 삭제가 있다")
def _webhook_rows(ctx):
    rows = re.findall(r'<li class="wh-row">(.*?)</li>', ctx.html, re.S)
    assert len(rows) == 2
    for row, name in zip(rows, ("RSS", "OTT"), strict=True):
        assert name in row and "시험" in row and "삭제" in row


@then("웹훅 추가 양식과 역할 지정과 알림 쿨다운이 있다")
def _discord_forms(ctx):
    for needle in ('action="/settings/webhooks"', 'action="/settings/webhook-roles"'):
        assert needle in ctx.html
    assert 'name="alert_cooldown_hours"' in ctx.html


@then("OpenRouter 키, 모델 체인, 호출 한도, 무료 모델 스캔이 한 화면에 있다")
def _models_page(ctx):
    for needle in (
        'action="/settings/openrouter-key"',
        'name="model_chain"',
        'name="llm_daily_cap"',
        'action="/models/scan"',
    ):
        assert needle in ctx.html


@then("모델 화면으로 돌아오고 키는 설정됨으로 보인다")
def _back_to_models(world, ctx):
    assert ctx.response.status_code == 303
    assert ctx.response.headers["location"].startswith("/models")
    assert "설정됨" in text_of(world.get("/models"))


@then("각각 그 화면에서 오류가 보이고 값은 바뀌지 않는다")
def _errors(world, ctx):
    for name in ("models", "discord"):
        response = ctx.results[name]
        assert response.status_code == 400 and "숫자만 입력" in text_of(response)
    snapshot = world.parts.settings.snapshot()
    assert (snapshot.llm_daily_cap, snapshot.alert_cooldown_hours) == (700, 6)


@then("내려받기 링크와 파일 올리기 양식이 있다")
def _backup_page(ctx):
    assert 'href="/backup/export"' in ctx.html
    assert 'action="/backup/restore"' in ctx.html and 'type="file"' in ctx.html


@then("변경 이력 항목에 방금 바꾼 설정이 보인다")
def _audit(ctx):
    text = text_of(ctx.response)
    assert "변경 이력" in text and "서비스 주소" in text


@then("설정 항목마다 한 줄 설명이 있다")
def _every_help():
    assert all(definition.help for definition in SETTING_DEFS)


@then("설정, Discord, 모델 화면의 입력 칸마다 그 설명이 보인다")
def _help_shown(world):
    html = "".join(world.get(path).text for path in ("/settings", "/discord", "/models"))
    for definition in SETTING_DEFS:
        assert definition.help in html, definition.key


@then(parsers.re(r'"(?P<label>[^"]+)" 링크가 "(?P<up>[^"]+)"로 연결된다'))
def _back_link(ctx, label, up):
    assert re.search(
        rf'<a class="back-link" href="{re.escape(up)}">← {re.escape(label)}</a>', ctx.html
    )


@then(parsers.parse('제목은 "{names}" 순서로 나온다'))
def _topic_order(ctx, names):
    wanted = names.split('", "')
    shown = [h for h in headings(ctx.html) if h in wanted]
    assert shown == wanted
