"""M5 화면: 글 페이지와 주제 목록의 버튼, 키워드 개선 제안."""

import pytest

from rss_hub.domain.topics import TopicFields
from rss_hub.web.feedback import safe_next
from tests.fakes.viewer_world import World
from tests.fakes.web_parts import start_app
from tests.keywords.browser import post


@pytest.fixture
def world(tmp_path):
    parts, client = start_app(tmp_path)
    with client:
        w = World(parts)
        w.ott = w.topics.list_all()[0].id
        w.game = w.topics.add(TopicFields("게임", "게임 소식", ("steam",)))
        yield w


def membership(world, article, topic):
    return {m.topic_id: m for m in world.topics.memberships(article)}.get(topic)


# ---------- 글 페이지의 버튼 ----------


def test_the_article_page_offers_dislike_for_member_topics_and_add_for_the_others(world):
    article = world.article(title="Netflix post")
    world.topics.record_matches(article, {world.ott: ("netflix",)})
    html = world.get(f"/a/{article}").text
    assert f'action="/a/{article}/topics/{world.ott}/reject"' in html and ">싫어요<" in html
    assert f'action="/a/{article}/topics/{world.game}/add"' in html and "특정 주제로" in html


def test_a_rejected_topic_shows_the_restore_button_instead(world):
    article = world.article()
    world.topics.record_matches(article, {world.ott: ()})
    world.topics.reject(article, world.ott)
    html = world.get(f"/a/{article}").text
    assert f'action="/a/{article}/topics/{world.ott}/restore"' in html
    assert (
        "(제외됨)" in html and "특정 주제로" in html and f"/topics/{world.ott}/reject" not in html
    )


def test_the_dislike_button_removes_the_article_from_that_topic_list_only(world):
    article = world.article(title="Netflix post")
    world.topics.record_matches(article, {world.ott: ("netflix",)})
    response = post(world, f"/a/{article}/topics/{world.ott}/reject", next=f"/a/{article}")
    assert response.status_code == 303 and response.headers["location"] == f"/a/{article}"
    assert "Netflix post" not in world.get(f"/reader/topic/{world.ott}").text
    assert "Netflix post" in world.get("/reader").text
    assert "Netflix post" in world.get(f"/reader/feed/{world.f_free}").text


def test_restore_brings_it_back_to_the_topic_list(world):
    article = world.article(title="Netflix post")
    world.topics.record_matches(article, {world.ott: ()})
    post(world, f"/a/{article}/topics/{world.ott}/reject")
    post(world, f"/a/{article}/topics/{world.ott}/restore")
    assert "Netflix post" in world.get(f"/reader/topic/{world.ott}").text


def test_the_add_button_puts_the_article_into_the_topic_list(world):
    article = world.article(title="Stream night")
    assert "Stream night" not in world.get(f"/reader/topic/{world.ott}").text
    post(world, f"/a/{article}/topics/{world.ott}/add")
    assert "Stream night" in world.get(f"/reader/topic/{world.ott}").text
    assert membership(world, article, world.ott).source == "manual"


def test_after_adding_the_page_offers_dislike_for_that_topic(world):
    article = world.article()
    post(world, f"/a/{article}/topics/{world.game}/add")
    assert f"/a/{article}/topics/{world.game}/reject" in world.get(f"/a/{article}").text


def test_buttons_work_the_same_way_with_the_browsers_own_headers(world):
    article = world.article()
    response = world.client.post(
        f"/a/{article}/topics/{world.ott}/add",
        data={},
        headers={"origin": "null", "sec-fetch-site": "same-origin"},
    )
    assert response.status_code == 303


# ---------- 주제 목록의 싫어요 ----------


def test_each_item_in_a_topic_list_has_a_dislike_button_that_returns_to_the_list(world):
    article = world.article(title="Netflix post")
    world.topics.record_matches(article, {world.ott: ()})
    html = world.get(f"/reader/topic/{world.ott}").text
    assert f'action="/a/{article}/topics/{world.ott}/reject"' in html
    assert f'name="next" value="/reader/topic/{world.ott}"' in html
    response = post(
        world, f"/a/{article}/topics/{world.ott}/reject", next=f"/reader/topic/{world.ott}"
    )
    assert response.headers["location"] == f"/reader/topic/{world.ott}"


def test_other_lists_have_no_dislike_buttons(world):
    article = world.article()
    world.topics.record_matches(article, {world.ott: ()})
    for path in ("/reader", f"/reader/feed/{world.f_free}", f"/reader/category/{world.news}"):
        assert (
            "/reject" not in world.get(path).text
        )  # 싫어요 버튼의 전송 주소(삭제 안내문에도 낱말이 있다)


# ---------- 잘못된 요청 ----------


@pytest.mark.parametrize("action", ["reject", "restore", "add"])
def test_unknown_articles_or_topics_give_404(world, action):
    article = world.article()
    assert post(world, f"/a/999999/topics/{world.ott}/{action}").status_code == 404
    assert post(world, f"/a/{article}/topics/999999/{action}").status_code == 404


def test_an_unknown_action_gives_404(world):
    assert post(world, f"/a/{world.article()}/topics/{world.ott}/delete").status_code == 404


def test_rejecting_an_article_that_is_not_in_the_topic_changes_nothing(world):
    article = world.article()
    assert post(world, f"/a/{article}/topics/{world.ott}/reject").status_code == 303
    assert world.topics.memberships(article) == []


@pytest.mark.security
@pytest.mark.parametrize(
    "target",
    [
        "https://evil.example.com/",
        "//evil.example.com/",
        "/\\evil.example.com",
        "javascript:alert(1)",
        "/settings",
        "/a/1/../../x",
        "/reader?x=<script>",
        "/reader?x=1;2",
        "",
    ],
)
def test_the_return_address_can_only_be_a_reading_page_of_this_service(world, target):
    article = world.article()
    response = post(world, f"/a/{article}/topics/{world.ott}/add", next=target)
    assert response.headers["location"] == f"/a/{article}"


@pytest.mark.parametrize(
    "target",
    [
        "/reader",
        "/reader/feed/3",
        "/reader/category/2",
        "/reader/topic/1",
        "/reader/topic/1?page=2",
        "/a/5",
    ],
)
def test_reading_pages_are_valid_return_addresses(target):
    assert safe_next(target, "/default") == target


@pytest.mark.security
def test_other_sites_cannot_press_the_buttons_for_the_user(world):
    article = world.article()
    response = world.client.post(
        f"/a/{article}/topics/{world.ott}/add",
        data={},
        headers={"origin": "https://evil.example.com", "sec-fetch-site": "cross-site"},
    )
    assert response.status_code == 403 and world.topics.memberships(article) == []
    assert world.client.get(f"/a/{article}/topics/{world.ott}/add").status_code == 405


# ---------- 키워드 개선 제안(주제 카드 안) ----------


def card(world, topic_id):
    """주제 목록에서 그 주제의 카드 하나."""
    name = world.topics.get(topic_id).name
    cards = world.get("/topics").text.split('<article class="topic-card"')[1:]
    return next(c.split("</article>")[0] for c in cards if f'data-topic-name="{name}"' in c)


def test_the_card_shows_the_feedback_counts(world):
    world.topics.add_manual(world.article(), world.ott)
    assert "직접 넣은 글 1개 · 싫어요 0개" in card(world, world.ott)


def test_a_new_topic_has_no_suggestion_accordion(world):
    assert "suggest-acc" not in card(world, world.game)


def test_manually_added_titles_with_a_common_word_suggest_a_keyword(world):
    for title in ("Squid Game trailer", "Squid Game cast"):
        world.topics.add_manual(world.article(title=title), world.game)
    html = card(world, world.game)
    assert (
        "<strong>squid</strong>" in html and f'action="/topics/{world.game}/keywords/add"' in html
    )
    assert "키워드 개선 제안 (" in html and "Squid Game trailer" in html


def test_a_keyword_that_often_led_to_dislikes_is_suggested_for_removal(world):
    for number in range(2):
        article = world.article(title=f"Board game {number}")
        world.topics.record_matches(article, {world.game: ("steam",)})
        world.topics.reject(article, world.game)
    html = card(world, world.game)
    assert "<strong>steam</strong>" in html and "2개를 싫어요로 뺌" in html
    assert f'action="/topics/{world.game}/keywords/remove"' in html


def test_a_dismissed_suggestion_disappears_and_stays_gone(world):
    for title in ("Squid Game trailer", "Squid Game cast"):
        world.topics.add_manual(world.article(title=title), world.game)
    response = post(world, f"/topics/{world.game}/suggestions/dismiss", kind="add", keyword="squid")
    assert response.status_code == 303 and response.headers["location"] == "/topics"
    assert "<strong>squid</strong>" not in card(world, world.game)


@pytest.mark.parametrize(
    "data", [{"kind": "other", "keyword": "x"}, {"kind": "add", "keyword": " "}, {}]
)
def test_dismissing_an_unknown_kind_or_an_empty_word_is_refused(world, data):
    response = post(world, f"/topics/{world.game}/suggestions/dismiss", **data)
    assert response.status_code == 400


def test_dismissing_for_an_unknown_topic_gives_404(world):
    response = post(world, "/topics/999/suggestions/dismiss", kind="add", keyword="x")
    assert response.status_code == 404


def test_approving_an_addition_changes_the_topics_keywords(world):
    response = post(world, f"/topics/{world.game}/keywords/add", keyword="squid")
    assert response.status_code == 303 and response.headers["location"] == "/topics?saved=1"
    assert world.topics.get(world.game).keywords == ("steam", "squid")


def test_approving_the_same_keyword_twice_does_not_duplicate_it(world):
    post(world, f"/topics/{world.game}/keywords/add", keyword="squid")
    post(world, f"/topics/{world.game}/keywords/add", keyword="SQUID")
    assert world.topics.get(world.game).keywords == ("steam", "squid")


def test_approving_a_removal_changes_the_topics_keywords(world):
    world.topics.update(
        world.game, TopicFields("게임", "게임 소식", ("steam", "board")), webhook_id=None
    )
    response = post(world, f"/topics/{world.game}/keywords/remove", keyword="board")
    assert response.status_code == 303 and world.topics.get(world.game).keywords == ("steam",)


def test_the_last_keyword_cannot_be_removed_because_a_topic_needs_keywords(world):
    response = post(world, f"/topics/{world.game}/keywords/remove", keyword="steam")
    assert response.headers["location"] == "/topics?warn=last"
    assert "마지막 키워드는 지울 수 없습니다" in world.get("/topics?warn=last").text
    assert world.topics.get(world.game).keywords == ("steam",)


def test_removing_a_keyword_the_topic_does_not_have_is_refused(world):
    response = post(world, f"/topics/{world.game}/keywords/remove", keyword="nothing")
    assert response.headers["location"] == "/topics?warn=missing"
    assert "그런 키워드가 없습니다" in world.get("/topics?warn=missing").text


def test_keyword_limits_are_enforced_when_approving(world):
    response = post(world, f"/topics/{world.game}/keywords/add", keyword="가" * 41)
    assert response.headers["location"] == "/topics?warn=last"
    assert world.topics.get(world.game).keywords == ("steam",)


def test_the_other_settings_of_the_topic_survive_a_keyword_change(world):
    webhook = world.parts.settings.add_webhook("ott방", "https://discord.com/api/webhooks/5/abc")
    world.topics.update(
        world.game, TopicFields("게임", "게임 소식", ("steam",)), webhook_id=webhook
    )
    post(world, f"/topics/{world.game}/keywords/add", keyword="squid")
    topic = world.topics.get(world.game)
    assert (topic.name, topic.description, topic.webhook_id) == ("게임", "게임 소식", webhook)


def test_an_unknown_topic_gives_404_for_keyword_changes(world):
    assert post(world, "/topics/999/keywords/add", keyword="x").status_code == 404
    assert post(world, f"/topics/{world.game}/keywords/rename", keyword="x").status_code == 404


def test_titles_in_the_suggestions_are_escaped(world):
    for _ in range(2):
        world.topics.add_manual(world.article(title="<script>alert(1)</script> squid"), world.game)
    html = card(world, world.game)
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html


@pytest.mark.security
@pytest.mark.parametrize("path", ["keywords/add", "suggestions/dismiss"])
def test_other_sites_cannot_change_keywords_or_dismiss_suggestions(world, path):
    response = world.client.post(
        f"/topics/{world.game}/{path}",
        data={"keyword": "evil", "kind": "add"},
        headers={"origin": "https://evil.example.com", "sec-fetch-site": "cross-site"},
    )
    assert response.status_code == 403 and world.topics.get(world.game).keywords == ("steam",)
