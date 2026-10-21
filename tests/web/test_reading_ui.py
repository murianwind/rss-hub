"""새 읽기 화면: 읽음, 북마크, 검색과 필터, 돌아갈 곳, 사이드바 개수, 정적 파일."""

import re
from urllib.parse import quote

import pytest

from tests.keywords.browser import post
from tests.keywords.page import card


def side_count(world, href):
    """사이드바 항목의 (읽지 않은 글 스타일인가, 숫자). 숫자가 없으면 None."""
    html = world.get("/reader").text
    link = re.search(rf'<a class="nav-item" href="{re.escape(href)}"[^>]*>(.*?)</a>', html, re.S)
    count = re.search(r'<span class="count( unread)?"[^>]*>(\d+)</span>', link.group(1))
    return (bool(count.group(1)), int(count.group(2))) if count else None


# ---------- 읽음 ----------


def test_new_articles_are_unread_in_the_list_and_become_read_when_opened(world):
    article = world.article(title="Fresh post")
    before = card(world.get("/reader").text, "Fresh post")
    assert before.startswith(" unread") and 'class="dot"' in before
    world.get(f"/a/{article}")
    after = card(world.get("/reader").text, "Fresh post")
    assert not after.startswith(" unread") and 'class="dot"' not in after


def test_opening_an_article_lowers_the_unread_badges(world):
    first, _second = (
        world.article(world.f_free, title="One"),
        world.article(world.f_free, title="Two"),
    )
    assert side_count(world, f"/reader/feed/{world.f_free}") == (True, 2)
    world.get(f"/a/{first}")
    assert side_count(world, f"/reader/feed/{world.f_free}") == (True, 1)


def test_when_everything_is_read_the_site_has_no_number_bubble_at_all(world):
    article = world.article(world.f_free)
    assert side_count(world, f"/reader/feed/{world.f_free}") == (True, 1)  # 읽지 않은 글 수
    world.get(f"/a/{article}")
    assert side_count(world, f"/reader/feed/{world.f_free}") is None  # 다 읽으면 숫자가 없다


def test_the_unread_filter_hides_read_articles(world):
    read = world.article(title="Already read", minutes=1)
    world.article(title="Still unread", minutes=2)
    world.get(f"/a/{read}")
    html = world.get("/reader?only=unread").text
    assert "Still unread" in html and "Already read" not in html
    assert '<option value="unread" selected>' in html


def test_marking_unread_returns_to_the_list_and_shows_a_toast(world):
    article = world.article(title="Post")
    world.get(f"/a/{article}")
    response = post(
        world, f"/a/{article}/read", state="unread", next=f"/reader/feed/{world.f_free}"
    )
    assert response.status_code == 303
    assert response.headers["location"] == f"/reader/feed/{world.f_free}?toast=marked_unread"
    html = world.get(response.headers["location"]).text
    assert "읽지 않음으로 표시했습니다." in html and card(html, "Post").startswith(" unread")


def test_the_read_button_with_any_other_state_marks_read(world):
    article = world.article()
    post(world, f"/a/{article}/read", state="read", next="/reader")
    assert world.articles.get(article).read_at is not None


def test_mark_all_read_marks_only_the_chosen_list(world):
    mine, other = world.article(world.f_free), world.article(world.f_news)
    response = post(
        world,
        "/reader/mark-read",
        kind="feed",
        ident=str(world.f_free),
        next=f"/reader/feed/{world.f_free}",
    )
    assert response.headers["location"] == f"/reader/feed/{world.f_free}?toast=read_all"
    assert (
        world.articles.get(mine).read_at is not None and world.articles.get(other).read_at is None
    )
    assert "모두 읽음으로 표시했습니다." in world.get(response.headers["location"]).text


def test_mark_all_read_works_for_everything_categories_topics_and_bookmarks(world):
    topic = world.topics.list_all()[0].id
    a, b, c, d = (
        world.article(world.f_news),
        world.article(world.f_free),
        world.article(world.f_free),
        world.article(world.f_free),
    )
    world.topics.record_matches(b, {topic: ()})
    world.articles.set_bookmark(c, True)
    post(world, "/reader/mark-read", kind="category", ident=str(world.news), next="/reader")
    post(world, "/reader/mark-read", kind="topic", ident=str(topic), next="/reader")
    post(world, "/reader/mark-read", kind="bookmarks", ident="", next="/reader")
    assert (
        all(world.articles.get(i).read_at for i in (a, b, c))
        and world.articles.get(d).read_at is None
    )
    post(world, "/reader/mark-read", kind="all", ident="", next="/reader")
    assert world.articles.get(d).read_at is not None


@pytest.mark.parametrize(
    ("kind", "ident"),
    [("nonsense", ""), ("feed", ""), ("feed", "abc"), ("topic", "1; DROP"), ("category", "-1")],
)
def test_a_bad_list_for_mark_all_read_is_refused_and_nothing_changes(world, kind, ident):
    article = world.article()
    assert (
        post(world, "/reader/mark-read", kind=kind, ident=ident, next="/reader").status_code == 400
    )
    assert world.articles.get(article).read_at is None


# ---------- 북마크 ----------


def test_the_bookmark_button_toggles_and_the_list_shows_it(world):
    article = world.article(title="Keep me")
    assert "북마크</button>" in card(world.get("/reader").text, "Keep me")
    response = post(world, f"/a/{article}/bookmark", on="1", next="/reader")
    assert response.headers["location"] == "/reader?toast=bookmarked"
    html = world.get(response.headers["location"]).text
    assert "북마크에 추가했습니다." in html and "북마크 해제</button>" in card(html, "Keep me")
    assert 'aria-pressed="true"' in card(html, "Keep me")
    post(world, f"/a/{article}/bookmark", on="0", next="/reader")
    assert "북마크</button>" in card(world.get("/reader").text, "Keep me")


def test_the_bookmarks_page_lists_only_bookmarked_articles_and_has_no_filter_menu(world):
    saved = world.article(title="Saved post")
    world.article(title="Other post")
    world.articles.set_bookmark(saved, True)
    html = world.get("/reader/bookmarks").text
    assert "Saved post" in html and "Other post" not in html
    assert "<span>북마크</span>" in html and 'name="only"' not in html and "1개의 게시물" in html


def test_an_empty_bookmarks_page_explains_how_to_add_one(world):
    assert "북마크한 글이 없습니다" in world.get("/reader/bookmarks").text


def test_the_bookmarks_page_can_be_searched_and_marked_read(world):
    saved = world.article(title="Squid post")
    world.articles.set_bookmark(saved, True)
    world.articles.set_bookmark(world.article(title="Gardening post"), True)
    assert "Gardening post" not in world.get("/reader/bookmarks?q=squid").text
    post(world, "/reader/mark-read", kind="bookmarks", ident="", next="/reader/bookmarks")
    assert world.articles.get(saved).read_at is not None


def test_the_article_page_bookmark_button_returns_to_the_same_article_with_its_list(world):
    article = world.article()
    html = world.get(f"/a/{article}?back=%2Freader%2Fbookmarks").text
    assert f'name="next" value="/a/{article}?back=%2Freader%2Fbookmarks"' in html
    response = post(
        world, f"/a/{article}/bookmark", on="1", next=f"/a/{article}?back=%2Freader%2Fbookmarks"
    )
    assert (
        response.headers["location"] == f"/a/{article}?back=%2Freader%2Fbookmarks&toast=bookmarked"
    )


def test_bookmarked_articles_show_in_the_sidebar_count(world):
    world.articles.set_bookmark(world.article(), True)
    html = world.get("/reader").text
    assert re.search(r'href="/reader/bookmarks"[^>]*>.*?<span class="count"[^>]*>1</span>', html)


@pytest.mark.parametrize("path", ["/a/999/bookmark", "/a/999/read"])
def test_buttons_for_a_missing_article_give_404(world, path):
    assert post(world, path, on="1", next="/reader").status_code == 404


@pytest.mark.parametrize("path", ["/a/{a}/bookmark", "/a/{a}/read", "/reader/mark-read"])
@pytest.mark.security
def test_other_sites_cannot_press_these_buttons(world, path):
    article = world.article()
    response = world.client.post(
        path.format(a=article),
        data={"on": "1", "kind": "all", "next": "/reader"},
        headers={"origin": "https://evil.example.com", "sec-fetch-site": "cross-site"},
    )
    assert response.status_code == 403
    assert (
        world.articles.get(article).bookmarked_at is None
        and world.articles.get(article).read_at is None
    )


@pytest.mark.security
@pytest.mark.parametrize(
    "target",
    ["https://evil.example.com/", "//evil.example.com", "/settings", "javascript:alert(1)"],
)
def test_the_return_address_of_every_button_is_restricted_to_reading_pages(world, target):
    article = world.article()
    assert (
        post(world, f"/a/{article}/bookmark", on="1", next=target).headers["location"]
        == f"/a/{article}?toast=bookmarked"
    )
    assert (
        post(world, "/reader/mark-read", kind="all", ident="", next=target).headers["location"]
        == "/reader?toast=read_all"
    )


# ---------- 검색 ----------


def test_search_narrows_the_list_and_the_count_and_keeps_the_query_in_the_box(world):
    world.article(title="Squid Game news", minutes=1)
    world.article(title="Gardening tips", minutes=2)
    html = world.get("/reader?q=squid").text
    assert "Squid Game news" in html and "Gardening tips" not in html
    assert "1개의 게시물" in html and 'value="squid"' in html


def test_a_search_with_no_match_says_so(world):
    world.article(title="One")
    assert "조건에 맞는 글이 없습니다" in world.get("/reader?q=zzz").text


@pytest.mark.security
def test_the_search_text_is_escaped_in_the_page(world):
    html = world.get(
        "/reader",
    ).text
    attack = '"><script>alert(1)</script>'
    html = world.client.get("/reader", params={"q": attack}).text
    assert "<script>alert(1)</script>" not in html and "&#34;&gt;&lt;script&gt;" in html


def test_search_and_filter_stay_in_the_pagination_links_and_the_back_link(world):
    for number in range(31):
        world.article(minutes=number, title=f"Squid {number:02d}")
    html = world.get("/reader?q=squid&only=unread").text
    assert 'href="/reader?page=2&amp;q=squid&amp;only=unread"' in html
    back = quote("/reader?q=squid&only=unread", safe="")  # '/'도 인코딩한다(프록시 차단 규칙 회피)
    assert f"?back={back}" in html


def test_every_scope_has_search_and_a_mark_all_read_button(world):
    topic = world.topics.list_all()[0].id
    for path in (
        "/reader",
        f"/reader/feed/{world.f_free}",
        f"/reader/category/{world.news}",
        f"/reader/topic/{topic}",
    ):
        html = world.get(path).text
        assert 'type="search"' in html and 'action="/reader/mark-read"' in html


def test_the_count_pill_shows_the_total_not_just_this_page(world):
    for number in range(35):
        world.article(minutes=number)
    assert "35개의 게시물" in world.get("/reader").text


# ---------- 상세와 돌아가기 ----------


def test_the_back_button_returns_to_the_list_and_page_the_user_came_from(world):
    for number in range(31):
        world.article(world.f_news, minutes=number)
    listing = world.get(f"/reader/feed/{world.f_news}?page=2&q=Title").text
    href = re.search(r'<a class="title" href="(/a/\d+\?back=[^"]+)"', listing).group(1)
    html = world.get(href.replace("&amp;", "&")).text
    assert f'<a class="back" href="/reader/feed/{world.f_news}?page=2&amp;q=Title">' in html
    assert html.count("목록으로 돌아가기") == 1  # 위쪽에만 있다(아래쪽 중복 버튼은 없앴다)


def test_without_a_back_address_the_button_goes_to_the_articles_site_list(world):
    article = world.article(world.f_news)
    assert f'<a class="back" href="/reader/feed/{world.f_news}">' in world.get(f"/a/{article}").text


@pytest.mark.security
@pytest.mark.parametrize(
    "back",
    [
        "https://evil.example.com/",
        "//evil.example.com",
        "/settings",
        "javascript:alert(1)",
        '"><script>alert(1)</script>',
    ],
)
def test_a_dangerous_back_address_is_ignored(world, back):
    article = world.article(world.f_news)
    html = world.client.get(f"/a/{article}", params={"back": back}).text
    assert (
        f'<a class="back" href="/reader/feed/{world.f_news}">' in html
        and "evil.example.com" not in html
    )
    assert "<script>alert(1)</script>" not in html


def test_the_article_page_has_no_source_label_and_has_the_unread_button(world):
    article = world.article(world.f_news)
    html = world.get(f"/a/{article}").text
    assert "출처:" not in html and 'class="source"' not in html
    assert 'name="state" value="unread"' in html and ">읽지 않음으로</button>" in html


def test_opening_the_article_marks_it_read_even_when_the_list_was_not_used(world):
    article = world.article()
    world.get(f"/a/{article}")
    assert world.articles.get(article).read_at is not None


# ---------- 사이드바 ----------


def test_the_sidebar_shows_unread_counts_for_feeds_categories_and_topics(world):
    topic = world.topics.list_all()[0].id
    inside = world.article(world.f_news)
    world.topics.record_matches(inside, {topic: ()})
    world.article(world.f_news)
    html = world.get("/reader").text
    assert side_count(world, f"/reader/feed/{world.f_news}") == (True, 2)
    assert side_count(world, f"/reader/category/{world.news}") == (True, 2)
    assert side_count(world, f"/reader/topic/{topic}") == (True, 1)
    assert 'title="읽지 않은 글 2개"' in html


def test_the_all_articles_link_shows_the_unread_total(world):
    world.article()
    world.article(world.f_news)
    assert side_count(world, "/reader") == (True, 2)


def test_the_section_of_the_current_list_starts_open_and_the_others_closed(world):
    topic = world.topics.list_all()[0].id
    cases = {
        "/reader": None,
        "/reader/bookmarks": None,
        f"/reader/feed/{world.f_free}": "rss",
        f"/reader/category/{world.news}": "categories",
        f"/reader/topic/{topic}": "topics",
        "/settings": "settings",
        "/topics": "settings",
        "/models": "settings",
    }
    for path, section in cases.items():
        html = world.get(path).text
        opened = set(re.findall(r'<details class="sec" id="sec-(\w+)" open>', html))
        assert opened == ({section} if section else set()), path


def test_a_feed_inside_a_category_opens_the_category_tree_and_is_marked_current(world):
    html = world.get(f"/reader/feed/{world.f_news}").text
    assert re.search(r'<details class="tree"[^>]* open>', html)
    assert re.search(rf'href="/reader/feed/{world.f_news}"[^>]*aria-current="page"', html)


def test_the_sidebar_collapsed_state_comes_from_the_cookie(world):
    assert "sidebar-collapsed" not in world.get("/reader").text
    world.client.cookies.set("sidebar", "collapsed")
    html = world.get("/reader").text
    assert (
        '<body class="app sidebar-collapsed" data-auto-read="on">' in html
        and 'aria-expanded="false"' in html
    )
    world.client.cookies.set("sidebar", "expanded")
    assert "sidebar-collapsed" not in world.get("/reader").text


def test_an_unknown_toast_key_shows_nothing_and_text_cannot_be_injected(world):
    assert "data-toast" not in world.get("/reader?toast=whatever").text
    assert (
        "data-toast"
        not in world.client.get("/reader", params={"toast": "<script>alert(1)</script>"}).text
    )
    html = world.get("/reader?toast=read_all").text
    assert "data-toast" in html and "모두 읽음으로 표시했습니다." in html


def test_every_management_page_shows_the_same_sidebar_and_marks_its_menu_item(world):
    alias = {"/status": "/status", "/import": "/feeds", "/categories": "/feeds"}
    for path in (
        "/settings",
        "/feeds",
        "/categories",
        "/topics",
        "/models",
        "/status",
        "/import",
    ):
        html = world.get(path).text
        assert '<nav aria-label="구독 목록">' in html
        expected = alias.get(path, path)
        assert re.search(rf'href="{expected}"[^>]*aria-current="page"', html), path
        assert 'class="tabs"' not in html  # 설정 위쪽의 탭 네비게이션은 없다


# ---------- 정적 파일과 보안 ----------


@pytest.mark.parametrize(
    ("path", "kind"), [("/static/app.css", "text/css"), ("/static/app.js", "javascript")]
)
def test_static_files_are_served_with_a_cache_and_the_security_headers(world, path, kind):
    response = world.get(path)
    assert response.status_code == 200 and kind in response.headers["content-type"]
    assert response.headers["cache-control"] == "public, max-age=3600"
    assert "script-src 'self'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"


def test_pages_use_versioned_static_urls_and_pages_still_are_not_cached(world):
    response = world.get("/reader")
    assert re.search(r'href="/static/app.css\?v=[^"]+"', response.text)
    assert re.search(r'<script src="/static/app.js\?v=[^"]+" defer></script>', response.text)
    assert "no-store" in response.headers["cache-control"]


@pytest.mark.security
@pytest.mark.parametrize(
    "path", ["/static/../rss_hub.db", "/static/%2e%2e/app.py", "/static/missing.js", "/static/"]
)
def test_static_files_cannot_reach_anything_else(world, path):
    assert world.get(path).status_code == 404


@pytest.mark.security
def test_pages_have_no_inline_script_inline_style_or_event_handler_attributes(world):
    article = world.article(content='<p onclick="x()">본문</p><script>alert(1)</script>')
    for path in (
        "/reader",
        f"/a/{article}",
        "/settings",
        "/topics",
        "/feeds",
        "/models",
        "/status",
    ):
        html = world.get(path).text
        assert not re.search(r"<script(?![^>]*\ssrc=)", html), path
        assert " style=" not in html and not re.search(r"\son[a-z]+=", html), path
        assert "javascript:" not in html


def test_the_script_never_writes_html_or_style_attributes_and_only_sets_the_sidebar_width(
    world,
):
    js = world.get("/static/app.js").text
    assert "innerHTML" not in js and "eval(" not in js and 'setAttribute("style"' not in js
    assert "document.write" not in js and "insertAdjacentHTML" not in js
    # 보안 정책이 막는 것은 style 속성과 인라인 <style>이다. 폭 조절만 스크립트로 폭을 직접 바꾼다
    uses = re.findall(r"\w+\.style\.\w+", js)
    assert sorted(set(uses)) == ["sidebarBox.style.removeProperty", "sidebarBox.style.width"]


# ---------- 사이드바 폭 조절(PC만, 기억함) ----------


@pytest.mark.parametrize(
    ("cookie", "expected"),
    [
        ("300", 300),
        ("304", 300),
        ("305", 310),
        ("315", 320),
        ("304", 300),
        ("100", 220),
        ("9999", 480),
        ("220", 220),
        ("480", 480),
        ("", 0),
        ("abc", 0),
        ("-300", 0),
        ("30.5", 0),
        ("٣٠٠", 0),
        ("1" * 20, 0),
    ],
)
def test_the_remembered_sidebar_width_is_snapped_into_range_or_ignored(cookie, expected):
    from rss_hub.web.ui import sidebar_width

    assert sidebar_width(cookie) == expected


def test_the_page_uses_the_remembered_width_class(world):
    assert " sw-" not in world.get("/reader").text.split("<body")[1].split(">")[0]
    world.client.cookies.set("sbw", "340")
    assert 'class="app sw-340"' in world.get("/reader").text.replace(' data-auto-read="on"', "")
    world.client.cookies.set("sbw", 'evil" onload="x')
    assert " sw-" not in world.get("/reader").text.split("<body")[1].split(">")[0]


def test_the_stylesheet_has_a_rule_for_every_width_step_and_hides_the_handle_on_small_screens(
    world,
):
    css = world.client.get("/static/app.css").text
    for width in range(220, 481, 10):
        assert f"body:not(.sidebar-collapsed).sw-{width} .sidebar {{ width: {width}px; }}" in css
    assert "sw-210 " not in css and "sw-490 " not in css
    assert "@media (max-width: 820px), (pointer: coarse) { .resizer { display: none; } }" in css


def test_the_handle_and_full_feed_names_are_on_every_page(world):
    html = world.get("/reader").text
    assert 'id="resizer" role="separator"' in html and 'tabindex="0"' in html
    assert f'href="/reader/feed/{world.f_free}" title="자유 블로그"' in html


def test_the_script_only_resizes_on_a_desktop_pointer_and_limits_the_range(world):
    js = world.client.get("/static/app.js").text
    assert (
        "(min-width: 821px) and (pointer: fine)" in js
        and "var MIN = 220;" in js
        and "var MAX = 480;" in js
    )
    assert 'document.cookie = "sbw="' in js and "innerHTML" not in js
