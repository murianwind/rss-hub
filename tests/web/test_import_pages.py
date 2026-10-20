from xml.sax.saxutils import escape

import pytest
from fastapi.testclient import TestClient

from rss_hub.domain.importing import MAX_UPLOAD_BYTES
from rss_hub.web.app import create_app
from tests.fakes.clock import FakeClock

BASE = "https://rss.example.com"


@pytest.fixture
def app(tmp_path):
    return create_app(data_dir=tmp_path, clock=FakeClock())


@pytest.fixture
def client(app):
    return TestClient(app, base_url=BASE, follow_redirects=False)


@pytest.fixture
def importer(app):
    return app.state.importer


@pytest.fixture
def feeds(app, tmp_path):
    from rss_hub.storage.database import Database
    from rss_hub.storage.feeds import FeedRepository

    return FeedRepository(Database(tmp_path / "rss_hub.db"), FakeClock())


def upload(client, name, content, **headers):
    data = content if isinstance(content, bytes) else content.encode("utf-8")
    return client.post("/import/preview", files={"file": (name, data)}, headers=headers)


def items_to_opml(items):
    body = "".join(
        f'<outline text="{escape(i.get("name", ""))}" xmlUrl="{escape(i["url"])}" '
        f'htmlUrl="{escape(i.get("html_url", ""))}"/>'
        for i in items
    )
    return f'<?xml version="1.0"?><opml version="2.0"><body>{body}</body></opml>'


def feed_file(*urls):
    return items_to_opml([{"name": u.split("//")[1].split(".")[0], "url": u} for u in urls])


def token_of(response):
    marker = 'name="token" value="'
    start = response.text.index(marker) + len(marker)
    return response.text[start : response.text.index('"', start)]


# ---------- 화면 ----------


def test_the_import_page_has_a_multipart_form_and_is_linked_from_the_menu(client):
    html = client.get("/import").text
    assert 'enctype="multipart/form-data"' in html and 'type="file"' in html
    assert 'href="/import"' in client.get("/feeds").text  # 구독 & OPML 관리 화면에서 간다


# ---------- 미리보기 ----------


def test_a_preview_shows_the_counts_and_changes_nothing(client, feeds):
    response = upload(
        client, "feeds.opml", feed_file("https://a.example.com/rss", "https://b.example.com/rss")
    )
    assert response.status_code == 200
    assert "신규 <strong>2</strong>" in response.text
    assert "아직 저장하지 않았습니다" in response.text
    assert feeds.list_all() == []


def test_duplicates_and_errors_are_explained_in_the_preview(client, feeds):
    feeds.add("https://dup.example.com/rss", "dup")
    content = feed_file(
        "https://dup.example.com/rss",
        "https://new.example.com/rss",
        "ftp://bad.example.com/x",
        "http://192.168.0.10/rss",
    )
    html = upload(client, "feeds.opml", content).text
    assert "신규 <strong>1</strong> · 중복 <strong>1</strong> · 오류 <strong>2</strong>" in html
    assert (
        "이미 구독 중" in html
        and "http, https만 가능" in html
        and "사설망·내부 주소는 허용하지 않음" in html
    )


def test_opml_folders_offer_a_category_toggle(client):
    body = '<outline text="IT"><outline text="a" xmlUrl="https://a.example.com/rss"/></outline>'
    opml = f'<?xml version="1.0"?><opml version="2.0"><body>{body}</body></opml>'
    html = upload(client, "feeds.opml", opml).text
    assert 'name="import_categories"' in html and "새 카테고리: IT" in html


def test_a_gizmodo_feed_gets_a_preset_checkbox_but_no_webhook_choice(client):
    html = upload(
        client, "feeds.opml", items_to_opml([{"name": "Gizmodo", "url": "https://gizmodo.com/rss"}])
    ).text
    assert 'name="preset_0"' in html and "프리셋 제안: Gizmodo" in html
    assert 'name="webhook_0"' not in html  # 피드별 웹훅 지정은 없어졌다. 카테고리로 모은다


def test_page_text_from_the_file_is_escaped_and_site_addresses_are_never_links(client):
    data = [
        {
            "name": "<script>alert(1)</script>",
            "url": "https://x.example.com/rss",
            "html_url": "javascript:alert(1)",
        }
    ]
    html = upload(client, "feeds.opml", items_to_opml(data)).text
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html
    assert 'href="javascript' not in html


# ---------- 파일이 잘못된 경우 ----------


@pytest.mark.parametrize(
    ("name", "content", "message"),
    [
        ("feeds.opml", "그냥 글자", "OPML 형식이 올바르지 않음"),
        ("feeds.txt", "https://a.example.com/rss", "OPML 파일만 올릴 수 있음"),
        ("feeds.json", '[{"url": "https://a.example.com/rss"}]', "OPML 파일만 올릴 수 있음"),
        ("feeds.opml", "", "파일이 비어 있음"),
    ],
)
def test_a_bad_file_gets_a_fixed_message_and_nothing_is_stored(
    client, importer, name, content, message
):
    response = upload(client, name, content)
    assert response.status_code == 400 and message in response.text
    assert importer._staging.count() == 0


def test_the_content_of_a_bad_file_is_never_echoed_back(client):
    response = upload(client, "feeds.opml", "<opml><body>SUPER-SECRET-CONTENT")
    assert "SUPER-SECRET-CONTENT" not in response.text


@pytest.mark.security
@pytest.mark.parametrize(
    "head",
    [
        '<!DOCTYPE opml [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>',
        '<!DOCTYPE opml [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;"><!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">]>',
    ],
)
def test_xml_attacks_are_rejected_without_leaking_anything_and_the_server_keeps_working(
    client, head
):
    opml = f'<?xml version="1.0"?>{head}<opml><body><outline text="&xxe;&c;" xmlUrl="https://a.example.com/rss"/></body></opml>'
    response = upload(client, "feeds.opml", opml)
    assert response.status_code == 400 and "안전하지 않은 XML" in response.text
    assert "root:" not in response.text
    assert client.get("/healthz").status_code == 200


def test_a_file_over_five_megabytes_is_refused(client):
    response = upload(
        client,
        "feeds.opml",
        feed_file("https://a.example.com/rss").encode() + b" " * (MAX_UPLOAD_BYTES + 1000),
    )
    assert response.status_code == 400 and "파일이 너무 큼(최대 5MB)" in response.text


def test_a_request_declaring_a_huge_body_is_refused_before_reading_it(client):
    response = client.post(
        "/import/preview",
        content=b"x",
        headers={
            "content-length": str(MAX_UPLOAD_BYTES + 1_000_000),
            "content-type": "multipart/form-data; boundary=x",
        },
    )
    assert response.status_code == 413


@pytest.mark.parametrize(
    "files", [None, {"file": ("", b"data")}, {"other": ("a.opml", b"<opml/>")}]
)
def test_a_missing_file_is_reported(client, files):
    response = client.post("/import/preview", files=files or {"x": (None, "y")})
    assert response.status_code == 400 and "파일을 선택해 주세요" in response.text


def test_a_plain_text_field_instead_of_a_file_is_refused(client):
    response = client.post("/import/preview", data={"file": "not a file"})
    assert response.status_code == 400 and "파일을 선택해 주세요" in response.text


# ---------- 확정과 취소 ----------


def test_confirming_registers_the_new_feeds_and_shows_the_result(client, feeds):
    preview = upload(
        client, "feeds.opml", feed_file("https://a.example.com/rss", "https://b.example.com/rss")
    )
    response = client.post("/import/confirm", data={"token": token_of(preview)})
    assert response.status_code == 200
    assert "신규 2개 · 중복 0개 · 오류 0개" in response.text
    assert {f.status for f in feeds.list_all()} == {"baseline_pending"} and len(
        feeds.list_all()
    ) == 2


def test_the_preset_checkbox_is_applied(client, feeds):
    preview = upload(
        client, "feeds.opml", items_to_opml([{"name": "Gizmodo", "url": "https://gizmodo.com/rss"}])
    )
    client.post("/import/confirm", data={"token": token_of(preview), "preset_0": "yes"})
    feed = feeds.list_all()[0]
    assert (feed.poll_priority, feed.max_entries, feed.emoji) == ("every_slot", 120, "🧪")


def test_an_unchecked_preset_registers_an_ordinary_feed(client, feeds):
    preview = upload(
        client, "feeds.opml", items_to_opml([{"name": "Gizmodo", "url": "https://gizmodo.com/rss"}])
    )
    client.post(
        "/import/confirm", data={"token": token_of(preview)}
    )  # 체크박스를 보내지 않았다 = 해제
    feed = feeds.list_all()[0]
    assert (feed.poll_priority, feed.max_entries, feed.emoji) == ("normal", None, "📢")


def test_categories_are_imported_only_when_the_box_is_checked(client, feeds):
    body = '<outline text="IT"><outline text="a" xmlUrl="https://a.example.com/rss"/></outline>'
    opml = f'<?xml version="1.0"?><opml version="2.0"><body>{body}</body></opml>'
    on = upload(client, "feeds.opml", opml)
    client.post("/import/confirm", data={"token": token_of(on), "import_categories": "yes"})
    assert feeds.category_names() == {"IT"}


def test_unchecking_the_category_box_creates_no_categories(client, feeds):
    body = '<outline text="IT"><outline text="a" xmlUrl="https://a.example.com/rss"/></outline>'
    opml = f'<?xml version="1.0"?><opml version="2.0"><body>{body}</body></opml>'
    off = upload(client, "feeds.opml", opml)
    client.post("/import/confirm", data={"token": token_of(off)})
    assert feeds.category_names() == set()


def test_an_expired_or_used_token_cannot_be_confirmed(client, feeds):
    preview = upload(client, "feeds.opml", feed_file("https://a.example.com/rss"))
    token = token_of(preview)
    client.post("/import/confirm", data={"token": token})
    again = client.post("/import/confirm", data={"token": token})
    assert again.status_code == 400 and "미리보기가 만료됨, 파일을 다시 올려 주세요" in again.text
    assert len(feeds.list_all()) == 1


def test_confirming_with_a_made_up_token_is_refused(client, feeds):
    response = client.post("/import/confirm", data={"token": "made-up"})
    assert response.status_code == 400 and feeds.list_all() == []


def test_cancelling_saves_nothing_and_goes_back_to_the_upload_page(client, feeds):
    preview = upload(client, "feeds.opml", feed_file("https://a.example.com/rss"))
    response = client.post("/import/cancel", data={"token": token_of(preview)})
    assert response.status_code == 303 and response.headers["location"] == "/import?cancelled=1"
    assert "구독 목록은 바뀌지 않았습니다" in client.get("/import?cancelled=1").text
    assert feeds.list_all() == []


@pytest.mark.security
@pytest.mark.parametrize("path", ["/import/preview", "/import/confirm", "/import/cancel"])
def test_cross_site_requests_to_the_import_routes_are_rejected(client, path):
    response = client.post(
        path, data={"token": "x"}, headers={"origin": "https://evil.example.com"}
    )
    assert response.status_code == 403


def test_the_state_changing_import_routes_do_not_accept_get(client):
    for path in ("/import/preview", "/import/confirm", "/import/cancel"):
        assert client.get(path).status_code == 405


def test_a_cancelled_preview_can_no_longer_be_confirmed(client, feeds):
    preview = upload(client, "feeds.opml", feed_file("https://a.example.com/rss"))
    token = token_of(preview)
    client.post("/import/cancel", data={"token": token})
    response = client.post("/import/confirm", data={"token": token})
    assert response.status_code == 400 and "미리보기가 만료됨" in response.text
    assert feeds.list_all() == []
