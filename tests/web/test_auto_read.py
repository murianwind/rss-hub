"""읽음 버튼(화면을 다시 불러오지 않음)과 스크롤 자동 읽음, 읽지 않음 고정."""

import pytest

from tests.fakes.viewer_world import World
from tests.fakes.web_parts import start_app

BROWSER = {"origin": "null", "sec-fetch-site": "same-origin"}
CROSS = {"origin": "https://evil.example.com", "sec-fetch-site": "cross-site"}


@pytest.fixture
def world(tmp_path):
    parts, client = start_app(tmp_path)
    with client:
        yield World(parts)


def post(world, path, headers=BROWSER, **data):
    return world.client.post(path, data=data, headers=headers)


def card(html, title):
    return next(
        c for c in html.split('<article class="card')[1:] if title in c.split("</article>")[0]
    )


# ---------- 읽음 버튼 ----------


def test_the_read_button_marks_read_and_returns_the_new_counts(world):
    article = world.article(world.f_free, title="Post")
    data = post(world, "/ui/read-state", id=str(article), state="read").json()
    assert data["ok"] is True and data["read"] is True
    assert (
        data["state"]["feeds"][str(world.f_free)]["unread"] == 0
        and data["state"]["all_unread"] == 0
    )
    assert world.articles.get(article).read_at is not None


def test_the_unread_button_pins_the_article_and_the_counts_rise(world):
    article = world.article(world.f_free)
    world.articles.mark_read(article)
    data = post(world, "/ui/read-state", id=str(article), state="unread").json()
    assert data["read"] is False and data["state"]["all_unread"] == 1
    assert world.articles.get(article).read_at is None


@pytest.mark.parametrize(
    ("data", "status"),
    [
        ({"id": "abc", "state": "read"}, 400),
        ({"id": "1", "state": "x"}, 400),
        ({"id": "", "state": "read"}, 400),
        ({"id": "999", "state": "read"}, 404),
        ({"id": "-1", "state": "read"}, 400),
    ],
)
def test_a_bad_read_request_is_refused(world, data, status):
    world.article()
    assert post(world, "/ui/read-state", **data).status_code == status


@pytest.mark.security
def test_other_sites_cannot_change_the_read_state(world):
    article = world.article()
    assert (
        post(world, "/ui/read-state", headers=CROSS, id=str(article), state="read").status_code
        == 403
    )
    assert world.articles.get(article).read_at is None
    assert world.client.get("/ui/read-state").status_code == 405


# ---------- 자동 읽음 ----------


def test_auto_read_marks_the_listed_articles_and_returns_the_counts(world):
    a, b = world.article(world.f_free), world.article(world.f_free)
    data = post(world, "/ui/auto-read", ids=f"{a},{b}").json()
    assert data["ok"] and data["marked"] == 2 and data["state"]["all_unread"] == 0


def test_auto_read_never_touches_what_the_user_set_to_unread(world):
    free, pinned = world.article(), world.article()
    post(world, "/ui/read-state", id=str(pinned), state="unread")
    data = post(world, "/ui/auto-read", ids=f"{free},{pinned}").json()
    assert data["marked"] == 1 and world.articles.get(pinned).read_at is None
    assert world.articles.get(free).read_at is not None


def test_clicking_a_pinned_article_to_read_it_makes_it_auto_readable_again(world):
    article = world.article()
    post(world, "/ui/read-state", id=str(article), state="unread")
    world.get(f"/a/{article}")  # 사용자가 클릭해서 읽는다
    post(world, "/ui/read-state", id=str(article), state="unread")  # 다시 읽지 않음으로 고정
    assert post(world, "/ui/auto-read", ids=str(article)).json()["marked"] == 0
    post(world, "/ui/read-state", id=str(article), state="read")
    post(world, "/ui/read-state", id=str(article), state="unread")
    assert post(world, "/ui/auto-read", ids=str(article)).json()["marked"] == 0


@pytest.mark.parametrize(
    "ids", ["", " , ", "abc", "1,x", "1;2", "-1", ",".join(str(n) for n in range(201))]
)
def test_a_bad_auto_read_request_is_refused(world, ids):
    world.article()
    assert post(world, "/ui/auto-read", ids=ids).status_code == 400


def test_two_hundred_ids_are_accepted_and_unknown_ids_are_ignored(world):
    article = world.article()
    ids = ",".join(str(n) for n in range(1, 201))
    assert post(world, "/ui/auto-read", ids=ids).json()["marked"] == (1 if article <= 200 else 0)
    assert post(world, "/ui/auto-read", ids="999,1000").json()["marked"] == 0


@pytest.mark.security
def test_other_sites_cannot_trigger_auto_read(world):
    article = world.article()
    assert post(world, "/ui/auto-read", headers=CROSS, ids=str(article)).status_code == 403
    assert world.articles.get(article).read_at is None


# ---------- 목록 화면 ----------


def test_cards_carry_their_id_and_the_pin_and_a_read_toggle_form(world):
    free, pinned = world.article(title="Free", minutes=1), world.article(title="Pinned", minutes=2)
    world.articles.mark_unread(pinned)
    html = world.get("/reader").text
    assert f'data-id="{free}"' in card(html, "Free") and "data-keep" not in card(html, "Free")
    assert 'data-keep="1"' in card(html, "Pinned")
    assert f'data-read-toggle="{free}"' in card(
        html, "Free"
    ) and 'name="state" value="read"' in card(html, "Free")
    assert "읽음으로 표시" in card(html, "Free")


def test_a_read_card_offers_to_make_it_unread_and_explains_the_pin(world):
    article = world.article(title="Seen")
    world.articles.mark_read(article)
    seen = card(world.get("/reader").text, "Seen")
    assert (
        'name="state" value="unread"' in seen
        and "읽지 않음으로 표시" in seen
        and "자동으로 읽음 처리되지 않습니다" in seen
    )


def test_the_page_tells_the_script_whether_auto_read_is_on(world):
    assert 'data-auto-read="on"' in world.get("/reader").text
    post(world, "/settings", ui_auto_read="off", next="/settings")
    assert 'data-auto-read="off"' in world.get("/reader").text
    assert world.get("/settings").text.count('<option value="off" selected>') >= 1


def test_the_auto_read_option_rejects_unknown_values(world):
    assert post(world, "/settings", ui_auto_read="maybe").status_code == 400
    assert 'data-auto-read="on"' in world.get("/reader").text


def test_the_detail_page_buttons_set_and_release_the_pin_with_the_right_toast(world):
    article = world.article()
    unread = post(world, f"/a/{article}/read", state="unread", next="/reader")
    assert unread.headers["location"] == "/reader?toast=marked_unread"
    assert post(world, "/ui/auto-read", ids=str(article)).json()["marked"] == 0
    read = post(world, f"/a/{article}/read", state="read", next="/reader")
    assert read.headers["location"] == "/reader?toast=marked_read"
    assert "읽음으로 표시했습니다." in world.get("/reader?toast=marked_read").text


def test_the_read_all_button_releases_the_pins(world):
    article = world.article(world.f_free)
    post(world, "/ui/read-state", id=str(article), state="unread")
    post(world, "/reader/mark-read", kind="feed", ident=str(world.f_free), next="/reader")
    assert world.articles.get(article).read_at is not None
