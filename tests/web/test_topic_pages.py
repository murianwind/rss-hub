import logging

import pytest
from fastapi.testclient import TestClient

from rss_hub.domain.topics import MAX_TOPICS
from rss_hub.storage.database import Database
from rss_hub.storage.feeds import FeedRepository
from rss_hub.web.app import create_app
from tests.fakes.clock import FakeClock

BASE = "https://rss.example.com"
WEBHOOK = "https://discord.com/api/webhooks/9/abc"


@pytest.fixture
def app(tmp_path):
    return create_app(data_dir=tmp_path, clock=FakeClock())


@pytest.fixture
def client(app):
    with TestClient(
        app, base_url=BASE, follow_redirects=False
    ) as running:  # 시작 절차(기본 주제)를 돌린다
        yield running


@pytest.fixture
def topics(app):
    return app.state.topics


def add(client, **data):
    form = {
        "name": "게임",
        "description": "",
        "keywords": "",
        "webhook_id": "",
        "enabled": "yes",
    } | data
    return client.post("/topics/add", data=form)


def only(topics, name):
    return next(t for t in topics.list_all() if t.name == name)


# ---------- 시작할 때 ----------


def test_the_server_start_creates_the_default_ott_topic(client, topics):
    assert [t.name for t in topics.list_all()] == ["OTT"]
    assert "OTT" in client.get("/topics").text


def test_restarting_the_server_does_not_create_it_again(tmp_path):
    for _ in range(2):
        with TestClient(create_app(data_dir=tmp_path, clock=FakeClock()), base_url=BASE):
            pass
    with TestClient(create_app(data_dir=tmp_path, clock=FakeClock()), base_url=BASE) as client:
        assert client.app.state.topics.list_all()[0].name == "OTT"
        assert len(client.app.state.topics.list_all()) == 1


def test_creating_the_app_alone_touches_no_disk(tmp_path):
    create_app(data_dir=tmp_path / "data", clock=FakeClock())
    assert not (tmp_path / "data").exists()


def test_a_start_that_cannot_create_the_topic_is_logged_and_the_server_still_answers(
    tmp_path, caplog
):
    caplog.set_level(logging.ERROR)
    app = create_app(data_dir=tmp_path / "missing" / "dir", clock=FakeClock())
    with TestClient(app, base_url=BASE) as client:
        assert client.get("/healthz").status_code == 503
    assert "기본 주제를 만들지 못했습니다" in caplog.text


# ---------- 화면 ----------


def test_the_page_shows_each_topic_with_its_fields_and_the_webhooks(client, app):
    app.state.settings_service.add_webhook("dev", WEBHOOK)
    html = client.get("/topics").text
    assert 'name="keywords"' in html and "netflix" in html and ">dev</option>" in html
    assert 'action="/topics/add"' in html


def test_the_menu_links_to_topics_and_categories(client):
    html = client.get("/").text
    assert 'href="/topics"' in html and 'href="/categories"' in html


def test_text_entered_by_the_user_is_escaped(client, topics):
    add(client, name="<script>alert(1)</script>", description='"><img src=x onerror=alert(1)>')
    html = client.get("/topics").text
    assert "<script>alert(1)</script>" not in html and "<img src=x" not in html
    assert "&lt;script&gt;" in html


# ---------- 추가 ----------


def test_adding_a_topic_saves_it_and_goes_back_to_the_list(client, topics):
    response = add(
        client, name="  게임 할인  ", description="가격 소식", keywords="steam, 스팀\nsteam"
    )
    assert response.status_code == 303 and response.headers["location"] == "/topics?saved=1"
    topic = only(topics, "게임 할인")
    assert (topic.description, topic.keywords, topic.enabled) == (
        "가격 소식",
        ("steam", "스팀"),
        True,
    )
    assert "저장했습니다" in client.get("/topics?saved=1").text


def test_a_topic_can_be_added_with_a_webhook_and_turned_off(client, app, topics):
    webhook_id = app.state.settings_service.add_webhook("dev", WEBHOOK)
    data = {"name": "만화", "description": "", "keywords": "", "webhook_id": str(webhook_id)}
    client.post("/topics/add", data=data)  # 사용 체크박스를 보내지 않음 = 끔
    topic = only(topics, "만화")
    assert (topic.webhook_id, topic.enabled) == (webhook_id, False)


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"name": ""}, "이름이 필요함"),
        ({"name": "가" * 41}, "이름은 40자까지"),
        ({"description": "가" * 201}, "설명은 200자까지"),
        ({"keywords": "가" * 41}, "키워드는 40자까지"),
        ({"keywords": ",".join(f"k{i}" for i in range(101))}, "키워드는 100개까지"),
        ({"name": "ott"}, "같은 이름의 주제가 이미 있음"),
        ({"webhook_id": "999"}, "웹훅을 찾을 수 없음"),
    ],
)
def test_a_bad_topic_is_refused_with_a_message_and_not_saved(client, topics, data, message):
    before = len(topics.list_all())
    response = add(client, **data)
    assert response.status_code == 400 and message in response.text
    assert len(topics.list_all()) == before


def test_a_webhook_choice_that_is_not_a_number_means_no_webhook(client, topics):
    assert add(client, webhook_id="abc").status_code == 303
    assert only(topics, "게임").webhook_id is None


def test_the_twenty_first_topic_is_refused(client, topics):
    for number in range(MAX_TOPICS - 1):  # 기본 주제가 이미 하나 있다
        assert add(client, name=f"주제{number}").status_code == 303
    response = add(client, name="하나 더")
    assert response.status_code == 400 and "주제는 20개까지" in response.text


# ---------- 수정과 삭제 ----------


def update(client, topic_id, **data):
    form = {
        "name": "OTT",
        "description": "",
        "keywords": "",
        "webhook_id": "",
        "enabled": "yes",
    } | data
    return client.post(f"/topics/{topic_id}/update", data=form)


def test_a_topic_can_be_edited(client, app, topics):
    webhook_id = app.state.settings_service.add_webhook("dev", WEBHOOK)
    ott = only(topics, "OTT")
    response = update(
        client, ott.id, name="스트리밍", keywords="netflix", webhook_id=str(webhook_id)
    )
    assert response.status_code == 303
    topic = topics.get(ott.id)
    assert (topic.name, topic.keywords, topic.webhook_id) == ("스트리밍", ("netflix",), webhook_id)


def test_clearing_the_enabled_box_turns_the_topic_off(client, topics):
    ott = only(topics, "OTT")
    update(client, ott.id, enabled="")
    assert topics.get(ott.id).enabled is False


def test_editing_with_a_bad_value_is_refused_and_nothing_changes(client, topics):
    ott = only(topics, "OTT")
    response = update(client, ott.id, name="")
    assert response.status_code == 400 and "이름이 필요함" in response.text
    assert topics.get(ott.id).name == "OTT"


def test_renaming_to_another_topics_name_is_refused(client, topics):
    add(client, name="게임")
    response = update(client, only(topics, "OTT").id, name="게임")
    assert response.status_code == 400 and "같은 이름의 주제가 이미 있음" in response.text


def test_editing_an_unknown_topic_gives_404(client):
    assert update(client, 999).status_code == 404


def test_deleting_needs_the_confirmation_box(client, topics):
    ott = only(topics, "OTT")
    response = client.post(f"/topics/{ott.id}/delete", data={})
    assert response.status_code == 400 and "확인란" in response.text
    assert topics.get(ott.id) is not None


def test_a_confirmed_delete_removes_the_topic(client, topics):
    ott = only(topics, "OTT")
    response = client.post(f"/topics/{ott.id}/delete", data={"confirm": "yes"})
    assert response.status_code == 303 and response.headers["location"] == "/topics?deleted=1"
    assert topics.get(ott.id) is None
    assert "삭제했습니다" in client.get("/topics?deleted=1").text


def test_deleting_an_unknown_topic_gives_404(client):
    assert client.post("/topics/999/delete", data={"confirm": "yes"}).status_code == 404


# ---------- 보안 ----------


@pytest.mark.security
@pytest.mark.parametrize(
    "path",
    [
        "/topics/add",
        "/topics/1/update",
        "/topics/1/delete",
        "/categories/add",
        "/categories/1/webhook",
    ],
)
def test_cross_site_posts_are_rejected(client, path):
    response = client.post(path, data={"name": "x"}, headers={"origin": "https://evil.example.com"})
    assert response.status_code == 403


def test_the_state_changing_routes_do_not_accept_get(client):
    for path in (
        "/topics/add",
        "/topics/1/update",
        "/topics/1/delete",
        "/categories/add",
        "/categories/1/webhook",
    ):
        assert client.get(path).status_code == 405


# ---------- 카테고리 ----------


@pytest.fixture
def feeds(app, tmp_path):
    return FeedRepository(Database(tmp_path / "rss_hub.db"), FakeClock())


def test_the_category_page_lists_categories_with_feed_counts(client, feeds):
    news = feeds.add_category("뉴스")
    feeds.add("https://a.example.com/rss", "A", category_id=news)
    html = client.get("/categories").text
    assert "뉴스" in html and "피드 1개" in html


def test_without_categories_the_page_says_so(client):
    assert "아직 카테고리가 없습니다" in client.get("/categories").text


def test_a_category_can_be_added(client, feeds):
    response = client.post("/categories/add", data={"name": "  뉴스  "})
    assert response.status_code == 303 and response.headers["location"] == "/categories?saved=1"
    assert [c.name for c in feeds.list_categories()] == ["뉴스"]
    assert "저장했습니다" in client.get("/categories?saved=1").text


@pytest.mark.parametrize(
    ("name", "message"), [("", "이름이 필요함"), ("가" * 41, "이름은 40자까지")]
)
def test_a_bad_category_name_is_refused(client, feeds, name, message):
    response = client.post("/categories/add", data={"name": name})
    assert response.status_code == 400 and message in response.text
    assert feeds.list_categories() == []


def test_a_category_name_that_already_exists_is_refused(client, feeds):
    feeds.add_category("뉴스")
    response = client.post("/categories/add", data={"name": "뉴스"})
    assert response.status_code == 400 and "같은 이름의 카테고리가 이미 있음" in response.text
    assert len(feeds.list_categories()) == 1


def test_a_category_webhook_can_be_set_and_cleared(client, app, feeds):
    webhook_id = app.state.settings_service.add_webhook("dev", WEBHOOK)
    category_id = feeds.add_category("뉴스")
    assert (
        client.post(
            f"/categories/{category_id}/webhook", data={"webhook_id": str(webhook_id)}
        ).status_code
        == 303
    )
    assert feeds.list_categories()[0].webhook_id == webhook_id
    assert f'value="{webhook_id}" selected' in client.get("/categories").text
    client.post(f"/categories/{category_id}/webhook", data={"webhook_id": ""})
    assert feeds.list_categories()[0].webhook_id is None


def test_an_unknown_webhook_is_refused_for_a_category(client, feeds):
    category_id = feeds.add_category("뉴스")
    response = client.post(f"/categories/{category_id}/webhook", data={"webhook_id": "999"})
    assert response.status_code == 400 and "웹훅을 찾을 수 없음" in response.text
    assert feeds.list_categories()[0].webhook_id is None


def test_the_webhook_of_an_unknown_category_gives_404(client):
    assert client.post("/categories/999/webhook", data={"webhook_id": ""}).status_code == 404


# ---------- 피드 화면 ----------


def test_the_feed_page_lists_feeds_with_category_and_webhook_controls(client, app, feeds):
    app.state.settings_service.add_webhook("dev", WEBHOOK)
    feeds.add("https://a.example.com/rss", "A 블로그")
    html = client.get("/feeds").text
    assert "A 블로그" in html and 'name="category_id"' in html and 'name="webhook_id"' in html
    assert "첫 점검 대기" in html


def test_without_feeds_the_page_points_to_the_import(client):
    assert (
        'href="/import"' in client.get("/feeds").text
        and "등록된 피드가 없습니다" in client.get("/feeds").text
    )


def test_a_feed_webhook_can_be_set_from_the_page(client, app, feeds):
    webhook_id = app.state.settings_service.add_webhook("dev", WEBHOOK)
    feed_id = feeds.add("https://a.example.com/rss", "A")
    response = client.post(f"/feeds/{feed_id}/webhook", data={"webhook_id": str(webhook_id)})
    assert response.status_code == 303 and response.headers["location"] == "/feeds?saved=1"
    assert feeds.get(feed_id).webhook_id == webhook_id
    assert f'value="{webhook_id}" selected' in client.get("/feeds").text
    client.post(f"/feeds/{feed_id}/webhook", data={"webhook_id": ""})
    assert feeds.get(feed_id).webhook_id is None


def test_a_feed_in_a_category_shows_the_category_instead_of_a_webhook_choice(client, feeds):
    category = feeds.add_category("뉴스")
    feed_id = feeds.add("https://a.example.com/rss", "A", category_id=category)
    html = client.get("/feeds").text
    assert f'action="/feeds/{feed_id}/webhook"' not in html
    assert "카테고리 '뉴스'의 설정을 따릅니다" in html


def test_a_webhook_cannot_be_forced_onto_a_feed_in_a_category(client, app, feeds):
    webhook_id = app.state.settings_service.add_webhook("dev", WEBHOOK)
    category = feeds.add_category("뉴스")
    feed_id = feeds.add("https://a.example.com/rss", "A", category_id=category)
    response = client.post(f"/feeds/{feed_id}/webhook", data={"webhook_id": str(webhook_id)})
    assert (
        response.status_code == 400
        and "카테고리에 속한 피드는 웹훅을 지정할 수 없음" in response.text
    )
    assert feeds.get(feed_id).webhook_id is None


def test_a_feed_can_join_and_leave_a_category(client, feeds):
    category = feeds.add_category("뉴스")
    feed_id = feeds.add("https://a.example.com/rss", "A")
    assert (
        client.post(f"/feeds/{feed_id}/category", data={"category_id": str(category)}).status_code
        == 303
    )
    assert feeds.get(feed_id).category_id == category
    client.post(f"/feeds/{feed_id}/category", data={"category_id": ""})
    assert feeds.get(feed_id).category_id is None


def test_a_feed_with_a_webhook_cannot_join_a_category_from_the_page(client, app, feeds):
    webhook_id = app.state.settings_service.add_webhook("dev", WEBHOOK)
    category = feeds.add_category("뉴스")
    feed_id = feeds.add("https://a.example.com/rss", "A", webhook_id=webhook_id)
    response = client.post(f"/feeds/{feed_id}/category", data={"category_id": str(category)})
    assert response.status_code == 400 and "먼저 웹훅 지정을 해제하세요" in response.text
    assert feeds.get(feed_id).category_id is None


def test_unknown_feeds_give_404(client):
    assert client.post("/feeds/999/category", data={"category_id": ""}).status_code == 404
    assert client.post("/feeds/999/webhook", data={"webhook_id": ""}).status_code == 404


def test_a_webhook_that_does_not_exist_is_refused_for_a_feed(client, feeds):
    feed_id = feeds.add("https://a.example.com/rss", "A")
    response = client.post(f"/feeds/{feed_id}/webhook", data={"webhook_id": "999"})
    assert response.status_code == 400 and "웹훅을 찾을 수 없음" in response.text


def test_feed_names_are_escaped_on_the_page(client, feeds):
    feeds.add("https://a.example.com/rss", "<script>alert(1)</script>")
    html = client.get("/feeds").text
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html
