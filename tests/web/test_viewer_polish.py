"""사용 피드백 3차: 차단 규칙 회피, 글 화면, 북마크 위치, 모델 사용량, 피드 검색."""

# ruff: noqa: E501  (HTML 견본과 긴 정규식은 한 줄이 읽기 쉽다)

import re

import pytest

from tests.keywords.browser import post
from tests.keywords.page import category_section, feed_ids, heading_link, rss_section

KEY = "sk-or-v1-abcdefghijklmnop"
ENGLISH = "This is a long English article body about software design and testing. " * 12
# 프록시(NPM의 Block Common Exploits 등)가 막는 모양: 쿼리의 이름=/글자/
WAF_SHAPE = re.compile(r"[?&;][A-Za-z0-9_]+=/")


# ---------- 프록시 차단 규칙(403) 회피 ----------


def links_with_queries(html):
    return re.findall(r'(?:href|action)="([^"]*\?[^"]*)"', html)


def test_no_link_has_an_unencoded_slash_after_an_equals_sign_in_its_query(world):
    article = world.article(world.f_news, content=f"<p>{ENGLISH}</p>")
    world.article(world.f_free)
    pages = [
        "/reader",
        f"/reader/feed/{world.f_free}?page=1&q=Title",
        f"/a/{article}?back=%2Freader%2Ffeed%2F{world.f_news}",
        "/feeds",
        "/topics",
        "/settings",
        "/models",
        f"/panel/settings/feed/{world.f_free}?next=%2Fa%2F{article}",
        f"/panel/delete/feed/{world.f_free}?next=%2Fa%2F{article}",
        "/panel/add/category?next=%2Fa%2F1",
    ]
    for path in pages:
        for link in links_with_queries(world.get(path).text):
            assert not WAF_SHAPE.search(link.replace("&amp;", "&")), (path, link)


def test_the_panel_links_on_an_article_page_encode_the_return_address_completely(world):
    article = world.article(world.f_news)
    html = world.get(f"/a/{article}?back=%2Freader").text
    link = re.search(r'href="(/panel/settings/feed/\d+\?next=[^"]+)"', html).group(1)
    assert "next=%2Fa%2F" in link and "next=/" not in link  # 글 화면에서도 '/'가 그대로 남지 않는다


def test_an_encoded_return_address_still_works_for_the_panel_itself(world):
    article = world.article(world.f_news)
    html = world.client.get(
        f"/panel/settings/feed/{world.f_news}?next=%2Fa%2F{article}", headers={"x-panel": "1"}
    ).text
    assert f'name="next" value="/a/{article}"' in html


# ---------- 번역(Safari): 페이지 언어가 글 언어를 따른다 ----------


def test_the_page_language_follows_the_article_so_the_browser_offers_translation(world):
    english = world.article(title="English post", content=f"<p>{ENGLISH}</p>")
    korean = world.article(
        title="한글 글", content="<p>이것은 한국어로 쓴 충분히 긴 본문입니다. " * 20 + "</p>"
    )
    assert world.get(f"/a/{english}").text.startswith('<!doctype html>\n<html lang="en"')
    assert '<html lang="ko"' in world.get(f"/a/{korean}").text
    assert '<html lang="ko"' in world.get("/reader").text  # 화면 틀은 한국어


# ---------- 글 화면 ----------


def test_the_title_links_to_the_original_and_the_fixed_header_holds_the_summary_and_the_refetch_button(
    world,
):
    article = world.article(world.f_news, link="https://blog.example.com/p/1", summary="요약입니다")
    html = world.get(f"/a/{article}").text
    assert html.count("목록으로 돌아가기") == 1 and "출처" not in html
    assert "원문 보기" not in html and "doc-foot" not in html  # 원문 보기 버튼은 없고 제목이 링크다
    assert "원문 페이지에서 가져온 전문입니다" not in html  # 안내 문구는 없다
    fixed = html.split('<div class="doc-fixed">')[1].split('<div class="doc-scroll">')[0]
    scroll = html.split('<div class="doc-scroll">')[1]
    link = f'<h1><a class="title-link" href="/a/{article}/original" target="_blank" rel="noopener noreferrer"'
    assert link in fixed and "요약입니다" in fixed
    assert re.search(
        r'<button type="submit" class="back">.*?<span>전문 다시 가져오기</span>', fixed, re.S
    )
    assert (
        'class="article-body"' in scroll
        and "전문 다시 가져오기" not in scroll
        and "요약입니다" not in scroll
    )


def test_the_viewer_has_no_grid_background_and_fills_the_area_with_equal_margins(world):
    css = world.client.get("/static/app.css").text
    assert "linear-gradient" not in css  # 격자무늬 배경 없음
    assert (
        ".detail-scroll { display: flex; flex-direction: column; overflow: hidden; padding: 24px; }"
        in css
    )
    assert (
        ".detail-scroll .doc { display: flex; flex: 1; flex-direction: column; min-height: 0;"
        in css
        and "overflow-y: auto" in css
    )


def test_the_unread_wording_is_the_new_one_everywhere_a_user_sees_it(world):
    article = world.article(world.f_news)
    world.articles.mark_read(article)
    for path in ("/reader", f"/a/{article}", "/settings", "/feeds"):
        text = world.get(path).text
        assert "안 읽" not in text, path
    assert '<span class="label-long">읽지 않음으로</span>' in world.get(f"/a/{article}").text
    assert "읽지 않음으로 표시" in world.get("/reader").text
    assert "안 읽" not in world.client.get("/static/app.js").text


# ---------- 사이드바: 북마크 위치, 기본 접힘, 숫자 버블, 루트 ----------


def test_only_the_rss_section_starts_open_with_the_bookmark_link_between_rss_and_categories(world):
    html = world.get("/reader").text
    assert re.findall(r'<details class="sec" id="sec-(\w+)" open>', html) == ["rss"]
    rss = html.split('id="sec-rss"')[1].split("</details>")[0]
    assert "/reader/bookmarks" not in rss and "전체 글" in rss
    assert (
        html.index('id="sec-rss"')
        < html.index('href="/reader/bookmarks"')
        < html.index('id="sec-categories"')
    )


def test_the_bubble_counts_unread_articles_only_and_disappears_when_all_are_read(world):
    a = world.article(world.f_news)
    world.article(world.f_news)
    html = world.get("/reader").text
    assert re.search(rf'data-count="feed:{world.f_news}"[^>]*>2</span>', html)
    world.articles.mark_read(a)
    world.articles.mark_read(world.articles.get(a + 1).id)
    html = world.get("/reader").text
    bubble = re.search(
        rf'<span class="count[^"]*" data-count="feed:{world.f_news}"[^>]*>([^<]*)</span>', html
    )
    assert bubble.group(0).count("hidden") == 1 and bubble.group(1) == ""
    assert world.get("/ui/state").json()["feeds"][str(world.f_news)]["unread"] == 0


def test_the_bookmark_count_is_still_the_number_of_bookmarks(world):
    article = world.article(world.f_news)
    world.articles.set_bookmark(article, on=True)
    assert re.search(r'data-count="bookmarks"[^>]*>1</span>', world.get("/reader").text)


# ---------- 모델 잔여 사용량 ----------


def model_text(html):
    found = re.search(r"모델 잔여 사용량 <b data-model-usage>([^<]+)</b>", html)
    return found.group(1) if found else None


def test_the_remaining_model_usage_is_shown_only_when_a_model_is_configured(world):
    server_says(world, 33)
    assert (
        model_text(world.get("/reader").text) is None
    )  # 모델(키)이 없으면 서버 값이 있어도 표시하지 않는다
    assert world.get("/ui/state").json()["model_usage"] is None
    configure_model(world)
    assert model_text(world.get("/reader").text) == "967/1000"
    assert without_time(world.get("/ui/state").json()["model_usage"]) == {
        "remaining": 967,
        "cap": 1000,
    }


def test_every_model_call_lowers_the_remaining_number_wherever_it_came_from(world):
    from rss_hub.storage.llm_usage import LlmUsageRepository

    configure_model(world)
    server_says(world, 33)
    assert model_text(world.get("/reader").text) == "967/1000"
    usage = LlmUsageRepository(world.parts.db, world.parts.clock)
    usage.record(model="m/free", outcome="success", status=200)
    usage.record(
        model="m/free", outcome="rate_limit", status=429
    )  # 실패한 호출도 서버는 한 번으로 센다
    server_says(world, 35)
    assert model_text(world.get("/reader").text) == "965/1000"
    assert world.get("/ui/state").json()["model_usage"]["remaining"] == 965


def test_the_internal_cap_setting_does_not_change_the_server_numbers(world):
    configure_model(world)
    post(world, "/settings", llm_daily_cap="100", next="/settings")
    server_says(world, 33)
    assert model_text(world.get("/reader").text) == "967/1000"  # 분모는 서버가 알려 준 한도다


def test_the_refresh_json_and_the_script_keep_the_model_usage_current(world):
    js = world.client.get("/static/app.js").text
    assert "[data-model-usage]" in js and "state.model_usage" in js
    assert (
        'fetch("/ui/state"' in js and "30000" in js
    )  # 백그라운드 요약이 바꾸므로 가끔 새로 받는다


# ---------- 피드 관리 검색 ----------


def listing(html):
    return html.split('<ul class="feed-list">')[1].split("</ul>")[0]


def test_the_feed_page_search_matches_name_address_and_category_ignoring_case(world):
    assert "뉴스 블로그" in listing(world.get("/feeds?q=뉴스").text)
    assert "자유 블로그" not in listing(world.get("/feeds?q=뉴스").text)
    assert "자유 블로그" in listing(world.get("/feeds?q=F.EXAMPLE").text)  # 주소, 대소문자 무시
    by_category = listing(world.get("/feeds?q=기술").text)
    assert "뉴스 블로그" not in by_category  # 카테고리 '기술'에는 피드가 없다
    assert "맞는 피드가 없습니다" in world.get("/feeds?q=존재하지않는").text


def test_the_search_box_keeps_its_text_and_the_state_chips_count_inside_the_results(world):
    world.feeds.record_failure(world.f_news, "x")
    html = world.get("/feeds?q=블로그").text
    assert 'name="q" value="블로그"' in html and "전체 2" in html and "오류 1" in html
    narrowed = world.get("/feeds?q=뉴스&state=error").text
    assert "전체 1" in narrowed and 'name="state" value="error"' in narrowed
    assert "q=%EB%89%B4%EC%8A%A4" in narrowed  # 칩 링크가 검색어를 이어 간다


@pytest.mark.security
def test_the_search_text_is_escaped_and_length_limited(world):
    html = world.get('/feeds?q="><script>alert(1)</script>').text
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html
    long = world.get("/feeds?q=" + "가" * 500).text
    assert 'value="' + "가" * 100 + '"' in long and "가" * 101 not in long


def test_an_empty_search_shows_every_feed_and_the_form_is_live_searchable(world):
    html = world.get("/feeds?q=").text
    assert "뉴스 블로그" in listing(html) and "자유 블로그" in listing(html)
    assert (
        '<form class="searchform feed-search" method="get" action="/feeds" role="search">' in html
    )


# ---------- 사이트 제목 링크, 이어 보기, 진하게/연하게 ----------


def test_the_feed_title_links_to_the_site_in_a_new_window(world):
    sited = world.feeds.add(
        "https://blog.example.com/rss", "블로그", html_url="https://blog.example.com/"
    )
    href, rel = heading_link(world.get(f"/reader/feed/{sited}").text)
    assert href == "https://blog.example.com/" and "noopener" in rel and "noreferrer" in rel
    assert 'title="사이트로 이동"' in world.get(f"/reader/feed/{sited}").text


def test_without_a_site_address_the_title_links_to_the_front_of_the_feed_host(world):
    plain = world.feeds.add("https://news.example.org/feeds/all.xml", "뉴스")
    assert heading_link(world.get(f"/reader/feed/{plain}").text)[0] == "https://news.example.org/"


@pytest.mark.security
@pytest.mark.parametrize(
    "bad",
    [
        "javascript:alert(1)",
        "ftp://x.example.com/",
        "data:text/html,1",
        "https://user:pw@evil.example.com/",
    ],
)
def test_an_unusable_site_address_is_never_linked(world, bad):
    feed = world.feeds.add("https://good.example.com/rss", "좋은 피드")
    with world.parts.db.connect() as conn:
        conn.execute("UPDATE feeds SET html_url = ? WHERE id = ?", (bad, feed))
    link = heading_link(world.get(f"/reader/feed/{feed}").text)
    assert link is not None and link[0] == "https://good.example.com/" and bad not in link[0]


def test_only_a_single_site_list_has_the_site_link(world):
    for path in ("/reader", "/reader/bookmarks", f"/reader/category/{world.news}"):
        assert heading_link(world.get(path).text) is None, path
    assert heading_link(world.get(f"/reader/feed/{world.f_news}").text) is not None


def test_the_pager_shows_the_page_and_pretty_previous_and_next_buttons(world):
    for number in range(65):
        world.article(minutes=number)
    middle = world.get("/reader?page=2").text
    assert re.search(
        r'<a class="pager-btn" data-prev href="/reader">.*?<span>이전</span>', middle, re.S
    )
    assert re.search(
        r'<a class="pager-btn" data-next href="/reader\?page=3"><span>다음</span>', middle
    )
    assert '<span class="pager-info">2 / 3</span>' in middle and 'aria-label="쪽 이동"' in middle
    last = world.get("/reader?page=3").text
    assert "data-next" not in last and "data-prev" in last


def test_a_single_page_list_shows_one_of_one_with_no_buttons(world):
    world.article()
    html = world.get("/reader").text
    assert (
        '<span class="pager-info">1 / 1</span>' in html
        and "data-next" not in html
        and "data-prev" not in html
    )


def test_the_script_appends_the_next_page_when_the_end_comes_near_and_falls_back_to_buttons(world):
    js = world.client.get("/static/app.js").text
    assert "IntersectionObserver" in js and "a[data-next]" in js and "DOMParser" in js
    assert 'pagerBox.classList.add("auto")' in js and 'pagerBox.classList.remove("auto")' in js
    css = world.client.get("/static/app.css").text
    assert ".pager.auto a[data-next]" in css and ".pager-btn {" in css
    assert "불러오는 중…" in css and "마지막 글입니다" in css


def test_unread_sites_are_bold_and_sites_without_unread_articles_are_light(world):
    article = world.article(world.f_news)
    html = world.get("/reader").text
    rows = re.findall(
        r'<li class="nav-row( has-unread)?" draggable="true" data-drag-kind="feed" data-drag-id="(\d+)"',
        html,
    )
    by_feed = {int(feed): bool(flag) for flag, feed in rows}
    assert by_feed[world.f_news] is True and by_feed[world.f_free] is False
    assert by_feed.keys() >= {world.f_news, world.f_free}
    world.articles.mark_read(article)
    again = re.findall(
        r'<li class="nav-row( has-unread)?" draggable="true" data-drag-kind="feed" data-drag-id="(\d+)"',
        world.get("/reader").text,
    )
    assert not any(flag for flag, _ in again)


def test_the_bold_and_light_styles_and_the_live_update_exist(world):
    css = world.client.get("/static/app.css").text
    assert ".nav-row[data-drag-kind=feed] .sb-text { font-weight: 400; opacity: 0.55; }" in css
    assert (
        ".nav-row[data-drag-kind=feed].has-unread .sb-text { font-weight: 700; opacity: 1; }" in css
    )
    js = world.client.get("/static/app.js").text
    assert 'row.classList.toggle("has-unread", feed.unread > 0)' in js


@pytest.mark.parametrize(
    ("html_url", "feed_url", "expected"),
    [
        ("https://a.example.com/", "https://feed.example.org/rss", "https://a.example.com/"),
        ("", "https://feed.example.org/x/rss", "https://feed.example.org/"),
        (
            "javascript:alert(1)",
            "http://feed.example.org:8080/rss",
            "http://feed.example.org:8080/",
        ),
        ("https://u:p@a.example.com/", "https://feed.example.org/rss", "https://feed.example.org/"),
        ("", "ftp://feed.example.org/rss", ""),
        ("", "https://u:p@feed.example.org/rss", ""),
        ("", "", ""),
    ],
)
def test_the_site_address_for_the_title_link_is_chosen_safely(html_url, feed_url, expected):
    from rss_hub.web.reader import _site_of

    assert _site_of(html_url, feed_url) == expected


@pytest.mark.parametrize("link", ["javascript:alert(1)", "", "ftp://x.example.com/a"])
def test_a_title_without_a_followable_original_is_plain_text(world, link):
    article = world.article(world.f_news, link=link, title="Plain")
    html = world.get(f"/a/{article}").text
    assert 'class="title-link"' not in html and "<h1>Plain</h1>" in html


def test_the_refetch_button_is_shown_only_when_there_is_something_to_refetch(world):
    article = world.article(world.f_news, link="")  # 원문 주소가 없으면 가져온 적도 없다
    assert "전문 다시 가져오기" not in world.get(f"/a/{article}").text


def test_pressing_the_same_panel_button_again_closes_the_panel(world):
    js = world.client.get("/static/app.js").text
    assert 'slot.getAttribute("data-open") === opener.href' in js
    assert 'slot.setAttribute("data-open", url)' in js and 'slot.removeAttribute("data-open")' in js
    toggle = js.split('slot.getAttribute("data-open") === opener.href')[1].split(
        "openPanel(opener.href)"
    )[0]
    assert "closePanel()" in toggle and "return;" in toggle


def test_the_fixed_header_and_the_scrolling_body_have_their_own_layout_rules(world):
    css = world.client.get("/static/app.css").text
    assert ".doc-fixed { flex: none; max-height: 55%; overflow-y: auto;" in css  # 위쪽은 고정
    assert ".doc-scroll { flex: 1; min-height: 0; overflow-y: auto;" in css  # 본문만 스크롤
    assert ".doc-summary { max-height: 26vh; overflow-y: auto; }" in css
    assert "button.back { font: inherit;" in css and ".title-link {" in css


# ---------- 모델 잔여 사용량: 서버가 알려 준 값("남은 호출/한도")을 쓴다 ----------


def without_time(usage):
    """갱신 시각은 따로 시험한다(37번 기능)."""
    return {key: value for key, value in usage.items() if key != "updated"}


def server_says(world, used, limit=1000):
    from rss_hub.services.ports import ServerUsage

    world.parts.llm.usage = ServerUsage(used=used, limit=limit)


def configure_model(world):
    world.parts.settings.set_openrouter_key(KEY)


def test_the_server_numbers_are_shown_with_the_server_limit(world):
    configure_model(world)
    server_says(world, 33)
    assert model_text(world.get("/reader").text) == "967/1000"
    assert without_time(world.get("/ui/state").json()["model_usage"]) == {
        "remaining": 967,
        "cap": 1000,
    }


def test_calls_by_other_programs_with_the_same_key_are_counted_because_the_server_sums_them(world):
    configure_model(world)
    server_says(world, 600)  # 이 서비스가 부르지 않은 호출도 서버 합계에는 들어 있다
    assert model_text(world.get("/reader").text) == "400/1000"


def test_a_call_made_through_this_service_refreshes_the_number_right_away(world):
    from rss_hub.storage.llm_usage import LlmUsageRepository

    configure_model(world)
    server_says(world, 33)
    assert model_text(world.get("/reader").text) == "967/1000"
    LlmUsageRepository(world.parts.db, world.parts.clock).record(
        model="m/free", outcome="success", status=200
    )
    server_says(world, 34)
    assert model_text(world.get("/reader").text) == "966/1000"  # 시간이 지나지 않아도 갱신


def test_calls_by_other_programs_show_up_after_the_refresh_interval(world):
    configure_model(world)
    server_says(world, 33)
    assert model_text(world.get("/reader").text) == "967/1000"
    server_says(world, 500)
    assert model_text(world.get("/reader").text) == "967/1000"  # 1분 안에는 같은 값을 다시 쓴다
    world.parts.clock.advance(minutes=2)
    assert model_text(world.get("/reader").text) == "500/1000"


def test_the_server_is_asked_at_most_once_per_interval_and_never_when_no_model_is_set(world):
    assert model_text(world.get("/reader").text) is None and world.parts.llm.usage_queries == 0
    configure_model(world)
    server_says(world, 33)
    for _ in range(5):
        world.get("/reader")
        world.get("/ui/state")
    assert world.parts.llm.usage_queries == 1


def test_when_the_server_cannot_be_reached_nothing_is_shown_and_it_returns_when_it_can(world):
    configure_model(world)
    world.parts.llm.usage = None
    assert model_text(world.get("/reader").text) is None  # 틀린 값 대신 표시하지 않는다
    assert world.get("/ui/state").json()["model_usage"] is None
    server_says(world, 33)
    world.parts.clock.advance(minutes=2)
    assert model_text(world.get("/reader").text) == "967/1000"


def test_a_server_that_raises_never_breaks_the_page_and_shows_nothing(world):
    configure_model(world)

    def boom():
        raise RuntimeError("서버 오류")

    world.parts.llm.server_usage = boom
    response = world.get("/reader")
    assert response.status_code == 200 and model_text(response.text) is None


def test_the_remaining_number_is_never_negative_even_if_the_server_says_over_the_limit(world):
    configure_model(world)
    server_says(world, 1005)
    assert model_text(world.get("/reader").text) == "0/1000"


# ---------- 사이드바: 카테고리에 넣은 피드는 카테고리에만, 세 구역이 한 화면에 ----------


def test_a_feed_in_a_category_is_listed_only_under_its_category(world):
    html = world.get("/reader").text
    assert world.f_news not in feed_ids(rss_section(html))  # 뉴스 블로그는 카테고리 '뉴스'에 있다
    assert world.f_news in feed_ids(category_section(html))
    assert world.f_free in feed_ids(rss_section(html)) and world.f_free not in feed_ids(
        category_section(html)
    )


def test_the_rss_list_gets_a_feed_back_when_its_category_is_removed(world):
    world.feeds.set_feed_category(world.f_news, None)
    html = world.get("/reader").text
    assert world.f_news in feed_ids(rss_section(html)) and world.f_news not in feed_ids(
        category_section(html)
    )


def test_the_rss_list_says_so_when_every_feed_is_in_a_category(world):
    world.feeds.set_feed_category(world.f_free, world.news)
    section = rss_section(world.get("/reader").text)
    assert not feed_ids(section) and "모든 피드가 카테고리에 들어 있습니다." in section
    assert "전체 글" in section  # 전체 글 항목은 그대로 있다


def test_the_rss_list_says_no_feed_when_none_are_registered(world):
    for feed in (world.f_news, world.f_free):
        world.feeds.delete(feed)
    section = rss_section(world.get("/reader").text)
    assert "등록된 피드가 없습니다." in section and "카테고리에 들어 있습니다" not in section


def test_the_rss_list_is_also_a_drop_target_that_removes_the_category(world):
    html = world.get("/reader").text
    assert '<ul class="sec-body" data-drop-category="">' in html
    assert (
        'data-drop-category=""' in html.split('id="sec-rss"')[1].split("<ul")[0]
    )  # 머리 줄도 그대로
    js = world.client.get("/static/app.js").text
    assert "target.contains(dragged)" in js  # 같은 목록 안의 순서 바꾸기는 옮기기로 처리하지 않는다


def test_unread_counts_and_bold_still_follow_the_feed_in_its_category(world):
    world.article(world.f_news)
    html = world.get("/reader").text
    row = re.search(
        rf'<li class="nav-row( has-unread)?"[^>]*data-drag-id="{world.f_news}"',
        category_section(html),
    )
    assert row is not None and row.group(1)


def test_the_three_sections_share_the_sidebar_height_and_scroll_inside(world):
    css = world.client.get("/static/app.css").text
    assert ".sb-body { --sb-free: calc(100vh - 460px); }" in css
    for section in ("rss", "categories", "topics"):
        assert f"#sec-{section} > .sec-body" in css
    assert "overflow-y: auto; overscroll-behavior: contain;" in css
    assert (
        ".sb-body:has(#sec-rss[open]):has(#sec-categories[open]):has(#sec-topics[open]) { --share-rss: 0.42;"
        in css
    )
    assert (
        "--share-cat: 0.6; --share-top: 0.4;" in css
        and "--share-rss: 0.55; --share-cat: 0.45;" in css
    )


def test_refreshing_the_usage_reports_when_the_server_gives_no_number(world):
    configure_model(world)
    world.parts.llm.usage = None
    response = post(world, "/ui/model-usage/refresh")
    assert response.status_code == 502 and "error" in response.json()
    server_says(world, 33)
    assert without_time(post(world, "/ui/model-usage/refresh").json()) == {
        "remaining": 967,
        "cap": 1000,
    }
