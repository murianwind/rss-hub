"""09_settings.feature 중 화면과 저장소가 필요한 시나리오를 실제 앱으로 검증한다.

실제 앱은 TestClient와 SQLite 임시 파일로 띄운다.

SET-03(주기 반영), SET-04, SET-13, SET-14, SET-16, SET-17, SET-21은 잡, 어댑터, 글 저장소가 생기는
단계에서 연결한다.
"""

import logging
import re
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, then, when

from rss_hub.web.app import create_app
from tests.bdd.binding import bind
from tests.fakes.clock import FakeClock

bind(
    globals(),
    "09_settings.feature",
    ["SET-01", "SET-02", "SET-05", "SET-06", "SET-07", "SET-15", "SET-18", "SET-19", "SET-20"],
)

PUBLIC = "https://rss.example.com"
OLD_KEY = "sk-or-OLD-1111111111"
KEY = "sk-or-NEW-2222222222"
WEBHOOK = "https://discord.com/api/webhooks/123/abcDEF"
LEGACY_ENV_NAMES = (
    "OPENROUTER_API_KEY",
    "PUBLIC_BASE_URL",
    "TZ",
    "WEBHOOK_DEFAULT_URL",
    "WEBHOOK_OTT_URL",
)


@pytest.fixture
def env(tmp_path):
    app = create_app(data_dir=tmp_path, clock=FakeClock())
    return SimpleNamespace(
        app=app,
        service=app.state.settings_service,
        client=TestClient(app, base_url=PUBLIC, follow_redirects=False),
        pages={},
        restarts=0,
        result=None,
    )


def fill_required_settings(env):
    env.client.post("/settings/openrouter-key", data={"openrouter_key": KEY})
    env.client.post("/settings/webhooks", data={"name": "rss", "url": WEBHOOK})
    wid = env.service.list_webhooks()[0].id
    env.client.post("/settings/webhook-roles", data={"default_id": str(wid), "system_id": ""})
    env.client.post("/settings", data={"service_base_url": PUBLIC})


# ---------- SET-01, SET-02 ----------


@given("컨테이너에 사용자가 정한 환경 변수가 하나도 없다")
def _no_env(monkeypatch):
    for name in LEGACY_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


@given("저장된 설정이 비어 있다")
def _empty_settings(env):
    assert env.service.snapshot().base_url == ""
    assert env.service.has_openrouter_key() is False


@given("서비스가 설정 없이 시작되어 있다")
def _started_without_settings(env):
    assert env.client.get("/healthz").status_code == 200


@when("서비스를 시작한다")
def _start(env):
    env.pages["health"] = env.client.get("/healthz")
    env.pages["status"] = env.client.get("/status")


@then("서비스는 정상적으로 시작된다")
def _started(env):
    assert env.pages["health"].status_code == 200
    assert env.pages["status"].status_code == 200


@then(parsers.parse('상태 화면에 다음 항목이 "미설정"으로 표시된다'))
def _missing_items(env, datatable):
    html = env.pages["status"].text
    items = re.findall(r"<li[^>]*class=\"check\"[^>]*>(.*?)</li>", html, re.DOTALL)
    labels = [row[0] for row in datatable[1:]]
    assert len(labels) == 2
    for label in labels:
        row = next(i for i in items if label in i)
        assert "미설정" in row


@then('상태 화면에 "OpenRouter 키"는 선택 항목으로 표시된다')
def _key_is_optional(env):
    html = env.pages["status"].text
    items = re.findall(r"<li[^>]*class=\"check\"[^>]*>(.*?)</li>", html, re.DOTALL)
    row = next(i for i in items if "OpenRouter 키" in i)
    assert "선택" in row and "미설정" not in row


@when("OpenRouter 키, 기본 웹훅, 서비스 주소를 저장한다")
def _save_required(env):
    fill_required_settings(env)


@then('상태 화면의 "미설정" 안내가 사라진다')
def _no_missing(env):
    assert "미설정" not in env.client.get("/status").text


@then("서비스를 다시 시작하지 않았다")
def _no_restart(env):
    assert env.restarts == 0


# ---------- SET-05, SET-06, SET-07 ----------


@given("OpenRouter 키와 웹훅 주소를 저장했다")
def _saved_secrets(env, caplog):
    caplog.set_level(logging.DEBUG)
    env.client.post("/settings/openrouter-key", data={"openrouter_key": KEY})
    env.client.post("/settings/webhooks", data={"name": "dev", "url": WEBHOOK})


@when("설정 화면과 설정 API 응답을 확인한다")
def _view_everything(env):
    env.pages = {
        path: env.client.get(path).text
        for path in ("/", "/settings", "/discord", "/models", "/healthz")
    }


@then('각 항목은 "설정됨"으로만 표시된다')
def _shown_as_set(env):
    assert "설정됨" in env.pages["/models"]
    assert "dev" in env.pages["/discord"]  # 웹훅은 이름만 보인다


@then("키와 웹훅 주소의 값은 어디에도 없다")
def _no_values(env):
    for html in env.pages.values():
        assert KEY not in html
        assert "abcDEF" not in html and "discord.com/api/webhooks" not in html


@then("서버 로그에도 값이 남아 있지 않다")
def _no_values_in_logs(caplog):
    assert KEY not in caplog.text and "abcDEF" not in caplog.text


@given("OpenRouter 키가 이미 저장되어 있다")
def _key_saved(env):
    env.service.set_openrouter_key(KEY)


@when("키 입력칸을 비워 둔 채 다른 설정만 바꿔 저장한다")
def _save_without_key(env):
    env.client.post("/settings", data={"llm_daily_cap": "100"})


@then("저장된 OpenRouter 키는 그대로이다")
def _key_unchanged(env):
    assert env.service.get_openrouter_key() == KEY


@given(parsers.parse('웹훅 "{name}"가 저장되어 있고 시스템 알림 웹훅으로 지정되어 있다'))
def _webhook_as_system(env, name):
    wid = env.service.add_webhook(name, WEBHOOK)
    env.service.set_webhook_roles(default_id=None, system_id=wid)
    env.webhook_id = wid


@when(parsers.parse('웹훅 "{name}"를 삭제한다'))
def _delete_webhook(env, name):
    response = env.client.post(
        f"/settings/webhooks/{env.webhook_id}/delete", data={"confirm": "yes"}
    )
    assert response.status_code == 303


@then(parsers.parse('웹훅 "{name}"는 목록에서 사라진다'))
def _webhook_gone(env, name):
    assert all(w.name != name for w in env.service.list_webhooks())
    assert f">{name}<" not in env.client.get("/settings").text


@then("시스템 알림 웹훅 지정은 비워진다")
def _system_role_cleared(env):
    assert env.service.snapshot().webhook_system_id is None


# ---------- SET-15 ----------


@given(parsers.parse('설정 화면을 "{url}"으로 열었다'))
def _open_settings_at(env, url):
    client = TestClient(env.app, base_url=url, follow_redirects=False)
    env.pages["settings"] = client.get("/settings").text


@given("서비스 주소가 비어 있다")
def _base_url_empty(env):
    assert env.service.snapshot().base_url == ""


@then(parsers.parse('"{url}"이 후보로 표시된다'))
def _suggested(env, url):
    assert f'value="{url}"' in env.pages["settings"]
    assert "이 주소를 서비스 주소로 사용" in env.pages["settings"]


@then("후보를 확인하기 전에는 저장되지 않는다")
def _not_saved(env):
    assert env.service.snapshot().base_url == ""


# ---------- SET-18 ----------


@when("서비스 주소를 바꾸고 OpenRouter 키를 새로 저장한다")
def _change_url_and_key(env):
    env.client.post("/settings/openrouter-key", data={"openrouter_key": OLD_KEY})
    env.client.post("/settings", data={"service_base_url": PUBLIC})
    env.client.post("/settings/openrouter-key", data={"openrouter_key": KEY})
    env.pages["settings"] = env.client.get("/settings").text


@then('변경 이력에 "서비스 주소 변경"과 "OpenRouter 키 변경됨"이 시각과 함께 남는다')
def _history(env):
    summaries = [e.summary for e in env.service.audit_log()]
    assert any(s.startswith("서비스 주소 변경") for s in summaries)
    assert "OpenRouter 키 변경됨" in summaries
    assert all(e.changed_at is not None for e in env.service.audit_log())
    assert "서비스 주소 변경" in env.client.get("/status").text


@then("이력에는 이전 키 값도 새 키 값도 없다")
def _no_keys_in_history(env):
    text = env.pages["settings"] + " ".join(e.summary for e in env.service.audit_log())
    assert OLD_KEY not in text and KEY not in text


# ---------- SET-19 ----------

CROSS_SITE_HEADERS = {
    "같은 주소의 화면(Origin이 서비스 주소와 같음)": {"origin": PUBLIC},
    "다른 사이트(Origin이 다른 주소)": {"origin": "https://evil.example.com"},
    '브라우저가 "cross-site"로 표시한 요청': {"sec-fetch-site": "cross-site"},
    "프록시가 넘긴 공개 주소와 Origin이 같은 요청": {
        "host": "192.168.0.5:8000",
        "x-forwarded-host": "rss.example.com",
        "origin": PUBLIC,
    },
}


@given(parsers.parse('서비스 주소가 "{url}"으로 저장되어 있다'))
def _base_url_saved(env, url):
    env.service.update({"service_base_url": url})


@when(parsers.parse('{source}에서 서비스 주소를 "{new_url}"으로 바꾸는 요청이 온다'))
def _change_request(env, source, new_url):
    env.result = env.client.post(
        "/settings", data={"service_base_url": new_url}, headers=CROSS_SITE_HEADERS[source]
    )
    env.new_url = new_url


@then(parsers.parse("요청은 {outcome}"))
def _request_outcome(env, outcome):
    if outcome == "받아들여지고 주소가 바뀐다":
        assert env.result.status_code == 303
        assert env.service.snapshot().base_url == env.new_url
    else:
        assert outcome == "거부되고 주소는 그대로이다"
        assert env.result.status_code == 403
        assert env.service.snapshot().base_url == "https://old.example.com"


# ---------- SET-20 ----------


@when("설정 화면을 연다")
def _open_settings(env):
    env.result = env.client.get("/settings")


@then("응답에 캐시를 막는 헤더가 있다")
def _no_cache(env):
    assert "no-store" in env.result.headers["cache-control"]


@then("응답에 다른 사이트의 프레임 삽입과 외부 스크립트 실행을 막는 헤더가 있다")
def _frame_and_script_headers(env):
    csp = env.result.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in csp and "default-src 'none'" in csp
    assert env.result.headers["x-frame-options"] == "DENY"
