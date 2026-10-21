import re

import pytest
from fastapi.testclient import TestClient

from rss_hub.web.app import create_app
from tests.fakes.clock import FakeClock

WEBHOOK = "https://discord.com/api/webhooks/123/abcDEF"
KEY = "sk-or-test-1234567890"
BASE = "https://rss.example.com"


@pytest.fixture
def app(tmp_path):
    return create_app(data_dir=tmp_path, clock=FakeClock())


@pytest.fixture
def client(app):
    return TestClient(app, base_url=BASE, follow_redirects=False)


@pytest.fixture
def service(app):
    return app.state.settings_service


def post(client, path, data, **headers):
    return client.post(path, data=data, headers=headers)


# ---------- 상태 화면 ----------


def test_status_page_lists_missing_settings(client):
    html = client.get("/status").text
    for label in ("OpenRouter 키", "기본 웹훅", "서비스 주소"):
        assert label in html
    assert html.count("미설정") == 2  # OpenRouter 키는 선택 항목이다


def test_status_page_has_no_missing_marker_once_everything_is_set(client, service):
    service.set_openrouter_key(KEY)
    wid = service.add_webhook("rss", WEBHOOK)
    service.set_webhook_roles(default_id=wid, system_id=None)
    service.update({"service_base_url": BASE})
    html = client.get("/status").text
    assert "미설정" not in html
    assert html.count("설정됨") == 3


def test_app_starts_and_serves_pages_with_a_blank_database(client):
    assert client.get("/healthz").status_code == 200
    assert client.get("/status").status_code == 200
    assert client.get("/settings").status_code == 200


# ---------- 설정 화면 ----------


def test_settings_page_shows_current_values_and_defaults(client, service):
    service.update({"llm_daily_cap": "123"})
    html = client.get("/settings").text
    assert 'name="llm_daily_cap"' in html and 'value="123"' in html
    assert 'name="collect_interval_minutes"' in html and 'value="5"' in html
    assert 'name="service_timezone"' in html and "Asia/Seoul" in html


def test_saving_valid_settings_redirects_and_persists(client, service):
    response = post(client, "/settings", {"llm_daily_cap": "321", "summarize_batch": "7"})
    assert response.status_code == 303
    assert response.headers["location"] == "/settings?saved=1"
    assert service.snapshot().llm_daily_cap == 321
    assert service.snapshot().summarize_batch == 7
    assert "저장했습니다" in client.get("/settings?saved=1").text


def test_invalid_settings_show_messages_keep_input_and_save_nothing(client, service):
    response = post(client, "/settings", {"collect_interval_minutes": "7", "llm_daily_cap": "321"})
    assert response.status_code == 400
    assert "60의 약수만 가능" in response.text
    assert 'value="7"' in response.text  # 입력한 값을 그대로 보여 준다
    assert service.snapshot().collect_interval_minutes == 5
    assert service.snapshot().llm_daily_cap == 700


def test_unknown_form_fields_are_ignored_not_stored(client, service):
    response = post(
        client, "/settings", {"llm_daily_cap": "321", "evil": "x", "openrouter_key": KEY}
    )
    assert response.status_code == 303
    assert service.has_openrouter_key() is False


def test_html_special_characters_are_escaped(client, service):
    post(client, "/settings/webhooks", {"name": "<script>alert(1)</script>", "url": WEBHOOK})
    html = client.get("/settings").text
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


# ---------- OpenRouter 키 ----------


def test_saving_the_key_never_shows_it_again(client, service):
    response = post(client, "/settings/openrouter-key", {"openrouter_key": KEY})
    assert response.status_code == 303
    assert service.get_openrouter_key() == KEY
    for path in ("/", "/settings"):
        html = client.get(path).text
        assert KEY not in html
    assert "설정됨" in client.get("/settings").text


def test_blank_key_is_rejected_and_old_key_stays(client, service):
    service.set_openrouter_key(KEY)
    response = post(client, "/settings/openrouter-key", {"openrouter_key": "  "})
    assert response.status_code == 400
    assert service.get_openrouter_key() == KEY


def test_deleting_the_key_requires_confirmation(client, service):
    service.set_openrouter_key(KEY)
    assert post(client, "/settings/openrouter-key/delete", {}).status_code == 400
    assert service.has_openrouter_key() is True
    assert post(client, "/settings/openrouter-key/delete", {"confirm": "yes"}).status_code == 303
    assert service.has_openrouter_key() is False


# ---------- 웹훅 ----------


def test_adding_a_webhook_shows_only_its_name(client, service):
    response = post(client, "/settings/webhooks", {"name": "dev", "url": WEBHOOK})
    assert response.status_code == 303
    html = client.get("/settings").text
    assert "dev" in html
    assert "abcDEF" not in html and "discord.com/api/webhooks" not in html
    assert service.list_webhooks()[0].name == "dev"


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (
            {"name": "x", "url": "https://evil.example.com/api/webhooks/1/a"},
            "Discord 웹훅 주소가 아님",
        ),
        ({"name": "x", "url": "http://discord.com/api/webhooks/1/a"}, "https만 가능"),
        ({"name": "", "url": WEBHOOK}, "이름이 필요함"),
    ],
)
def test_invalid_webhooks_are_rejected_with_a_message_that_hides_the_value(
    client, service, data, message
):
    response = post(client, "/settings/webhooks", data)
    assert response.status_code == 400
    assert message in response.text
    assert "evil.example.com" not in response.text
    assert service.list_webhooks() == []


def test_duplicate_webhook_name_is_rejected(client, service):
    service.add_webhook("dev", WEBHOOK)
    response = post(client, "/settings/webhooks", {"name": "dev", "url": WEBHOOK})
    assert response.status_code == 400
    assert "같은 이름의 웹훅이 이미 있음" in response.text


def test_deleting_a_webhook_requires_confirmation_and_clears_its_role(client, service):
    wid = service.add_webhook("dev", WEBHOOK)
    service.set_webhook_roles(default_id=None, system_id=wid)
    assert post(client, f"/settings/webhooks/{wid}/delete", {}).status_code == 400
    assert service.list_webhooks() != []
    assert post(client, f"/settings/webhooks/{wid}/delete", {"confirm": "yes"}).status_code == 303
    assert service.list_webhooks() == []
    assert service.snapshot().webhook_system_id is None


def test_roles_can_be_assigned_and_cleared(client, service):
    a = service.add_webhook("rss", WEBHOOK)
    response = post(client, "/settings/webhook-roles", {"default_id": str(a), "system_id": ""})
    assert response.status_code == 303
    assert service.snapshot().webhook_default_id == a
    post(client, "/settings/webhook-roles", {"default_id": "", "system_id": ""})
    assert service.snapshot().webhook_default_id is None


def test_roles_with_an_unknown_webhook_are_rejected(client, service):
    response = post(client, "/settings/webhook-roles", {"default_id": "999", "system_id": ""})
    assert response.status_code == 400
    assert service.snapshot().webhook_default_id is None


def test_roles_with_garbage_ids_are_rejected(client):
    response = post(client, "/settings/webhook-roles", {"default_id": "abc", "system_id": ""})
    assert response.status_code == 400


# ---------- 서비스 주소 제안 ----------


def test_current_address_is_suggested_but_not_saved(client, service):
    html = client.get("/settings").text
    assert f'value="{BASE}"' in html and "이 주소를 서비스 주소로 사용" in html
    assert service.snapshot().base_url == ""


def test_suggestion_uses_proxy_headers_when_present(client):
    headers = {
        "host": "192.168.0.5:8000",
        "x-forwarded-host": "rss.example.com",
        "x-forwarded-proto": "https",
    }
    html = client.get("/settings", headers=headers).text
    assert 'value="https://rss.example.com"' in html
    assert "192.168.0.5" not in html


def test_no_suggestion_once_the_address_is_set(client, service):
    service.update({"service_base_url": "https://other.example.com"})
    assert "이 주소를 서비스 주소로 사용" not in client.get("/settings").text


def test_malformed_host_header_does_not_break_the_page(client):
    response = client.get(
        "/settings", headers={"x-forwarded-host": "bad host<>", "x-forwarded-proto": "ftp"}
    )
    assert response.status_code == 200
    assert "bad host" not in response.text


def test_accepting_the_suggestion_saves_it(client, service):
    post(client, "/settings", {"service_base_url": BASE})
    assert service.snapshot().base_url == BASE


# ---------- 변경 이력 ----------


def test_history_shows_changes_without_secrets(client, service):
    post(client, "/settings", {"service_base_url": BASE})
    post(client, "/settings/openrouter-key", {"openrouter_key": KEY})
    html = client.get("/settings").text
    assert "서비스 주소 변경" in html
    assert "OpenRouter 키 변경됨" in html
    assert KEY not in html


# ---------- 보안 ----------


@pytest.mark.security
@pytest.mark.parametrize("path", ["/", "/settings"])
def test_security_headers_are_set(client, path):
    headers = client.get(path).headers
    assert "no-store" in headers["cache-control"]
    csp = headers["content-security-policy"]
    assert (
        "default-src 'none'" in csp
        and "frame-ancestors 'none'" in csp
        and "form-action 'self'" in csp
    )
    assert headers["x-frame-options"] == "DENY"
    assert headers["x-content-type-options"] == "nosniff"
    assert (
        headers["referrer-policy"] == "same-origin"
    )  # 같은 사이트 폼 제출에 Origin이 정상으로 붙는다


@pytest.mark.security
@pytest.mark.parametrize(
    ("headers", "accepted"),
    [
        ({"origin": BASE}, True),
        ({"origin": "https://evil.example.com"}, False),
        ({"sec-fetch-site": "cross-site"}, False),
        ({"host": "192.168.0.5:8000", "x-forwarded-host": "rss.example.com", "origin": BASE}, True),
        ({}, True),
    ],
)
def test_cross_site_changes_are_rejected(client, service, headers, accepted):
    service.update({"service_base_url": "https://old.example.com"})
    response = post(
        client, "/settings", {"service_base_url": "https://evil.example.com"}, **headers
    )
    expected = "https://evil.example.com" if accepted else "https://old.example.com"
    assert (response.status_code == 303) is accepted
    assert service.snapshot().base_url == expected
    if not accepted:
        assert response.status_code == 403


@pytest.mark.security
@pytest.mark.parametrize(
    "path",
    [
        "/settings/openrouter-key",
        "/settings/webhooks",
        "/settings/webhook-roles",
        "/settings/openrouter-key/delete",
    ],
)
def test_every_state_changing_route_rejects_cross_site_requests(client, service, path):
    response = post(
        client,
        path,
        {"confirm": "yes", "name": "x", "url": WEBHOOK, "openrouter_key": KEY},
        origin="https://evil.example.com",
    )
    assert response.status_code == 403
    assert service.has_openrouter_key() is False and service.list_webhooks() == []


def test_state_changing_routes_do_not_accept_get(client):
    for path in ("/settings/openrouter-key", "/settings/webhooks", "/settings/webhook-roles"):
        assert client.get(path).status_code == 405


@pytest.mark.security
def test_secrets_do_not_leak_into_logs(client, caplog):
    import logging

    caplog.set_level(logging.DEBUG)
    post(client, "/settings/openrouter-key", {"openrouter_key": KEY})
    post(client, "/settings/webhooks", {"name": "dev", "url": WEBHOOK})
    post(
        client,
        "/settings/webhooks",
        {"name": "bad", "url": "https://evil.example.com/api/webhooks/1/TOKENXYZ"},
    )
    client.get("/settings")
    assert KEY not in caplog.text
    assert "abcDEF" not in caplog.text and "TOKENXYZ" not in caplog.text


def test_html_pages_declare_the_language_and_a_mobile_viewport(client):
    html = client.get("/settings").text
    assert '<html lang="ko" data-theme="system" data-font="normal">' in html
    assert re.search(r'<meta name="viewport" content="width=device-width', html)


def test_suggestion_is_skipped_when_the_forwarded_scheme_is_not_http(client):
    html = client.get("/settings", headers={"x-forwarded-proto": "ftp"}).text
    assert "이 주소를 서비스 주소로 사용" not in html


# ---------- 서비스 주소가 없어서 발송을 기다리는 글 ----------


def make_ready_article(tmp_path):
    from datetime import UTC, datetime

    from rss_hub.storage.articles import ArticleRepository, NewArticle
    from rss_hub.storage.database import Database
    from rss_hub.storage.feeds import FeedRepository

    db = Database(tmp_path / "rss_hub.db")
    clock = FakeClock()
    feed_id = FeedRepository(db, clock).add("https://f.example.com/rss", "피드")
    articles = ArticleRepository(db, clock)
    article_id = articles.add(
        NewArticle(feed_id, "g1", "t", "https://x/1", "c", "", datetime.now(UTC), "2026-10-16")
    )
    articles.mark_ready(article_id, title_ko="t", summary_ko="s", topics=[], model="m")


def test_the_status_page_asks_for_the_service_address_when_articles_are_waiting(client, tmp_path):
    client.get("/status")  # DB를 만든다
    make_ready_article(tmp_path)
    html = client.get("/status").text
    assert "서비스 주소 필요" in html and "1개" in html


def test_no_address_notice_without_waiting_articles(client):
    assert "서비스 주소 필요" not in client.get("/status").text


def test_no_address_notice_once_the_address_is_set(client, service, tmp_path):
    client.get("/status")
    make_ready_article(tmp_path)
    service.update({"service_base_url": BASE})
    assert "서비스 주소 필요" not in client.get("/status").text
