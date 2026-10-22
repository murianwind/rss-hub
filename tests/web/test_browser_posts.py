"""실제 브라우저가 보내는 헤더 조합으로, 상태를 바꾸는 모든 화면이 막히지 않는지 확인한다.

테스트 클라이언트는 Origin 헤더를 보내지 않아서 "헤더 없음" 경로만 시험하게 된다.
여기서는 크롬이 같은 사이트 폼 제출에 보내는 헤더(Origin: null, Sec-Fetch-Site: same-origin)와
다른 사이트에서 온 요청의 헤더를 직접 만든다.
"""

import pytest
from fastapi.testclient import TestClient

from rss_hub.web.app import create_app
from tests.fakes.clock import FakeClock

BASE = "https://rss.example.com"
OPML = b'<?xml version="1.0"?><opml version="2.0"><body><outline text="a" xmlUrl="https://a.example.com/rss"/></body></opml>'

# 크롬, 사파리 등이 같은 사이트 폼 제출에 보내는 값(정책에 따라 Origin이 null일 수도 있다)
SAME_SITE_NULL_ORIGIN = {
    "origin": "null",
    "sec-fetch-site": "same-origin",
    "sec-fetch-mode": "navigate",
}
SAME_SITE_REAL_ORIGIN = {
    "origin": BASE,
    "sec-fetch-site": "same-origin",
    "sec-fetch-mode": "navigate",
}
CROSS_SITE = {
    "origin": "https://evil.example.com",
    "sec-fetch-site": "cross-site",
    "sec-fetch-mode": "navigate",
}
CROSS_SITE_NULL_ORIGIN = {
    "origin": "null",
    "sec-fetch-site": "cross-site",
    "sec-fetch-mode": "navigate",
}

FORMS = [
    ("/settings", {"service_base_url": BASE}),
    (
        "/topics/add",
        {"name": "게임", "description": "", "keywords": "steam", "webhook_id": ""},
    ),
    ("/categories/add", {"name": "뉴스"}),
    ("/feeds/999/category", {"category_id": ""}),
    ("/import/cancel", {"token": "x"}),
]


@pytest.fixture
def client(tmp_path):
    app = create_app(data_dir=tmp_path, clock=FakeClock())
    with TestClient(app, base_url=BASE, follow_redirects=False) as running:
        yield running


@pytest.mark.parametrize(
    "headers", [SAME_SITE_NULL_ORIGIN, SAME_SITE_REAL_ORIGIN], ids=["origin-null", "origin-real"]
)
@pytest.mark.parametrize(("path", "data"), FORMS)
def test_every_form_works_with_a_real_browsers_same_site_headers(client, headers, path, data):
    response = client.post(path, data=data, headers=headers)
    assert response.status_code != 403, response.text[:200]


@pytest.mark.parametrize(
    "headers", [SAME_SITE_NULL_ORIGIN, SAME_SITE_REAL_ORIGIN], ids=["origin-null", "origin-real"]
)
def test_the_opml_upload_works_with_a_real_browsers_same_site_headers(client, headers):
    response = client.post("/import/preview", files={"file": ("a.opml", OPML)}, headers=headers)
    assert response.status_code == 200 and "미리보기" in response.text


@pytest.mark.security
@pytest.mark.parametrize(
    "headers", [CROSS_SITE, CROSS_SITE_NULL_ORIGIN], ids=["foreign-origin", "null-origin"]
)
@pytest.mark.parametrize(("path", "data"), FORMS)
def test_every_form_still_rejects_requests_from_other_sites(client, headers, path, data):
    assert client.post(path, data=data, headers=headers).status_code == 403


@pytest.mark.security
def test_the_opml_upload_still_rejects_requests_from_other_sites(client):
    response = client.post("/import/preview", files={"file": ("a.opml", OPML)}, headers=CROSS_SITE)
    assert response.status_code == 403


def test_the_policy_sends_the_origin_on_same_site_forms_and_nothing_to_other_sites(client):
    # same-origin: 같은 사이트로는 Origin을 보내고 다른 사이트로는 아무것도 보내지 않는다
    assert client.get("/").headers["referrer-policy"] == "same-origin"
