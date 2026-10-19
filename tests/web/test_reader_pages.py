"""뷰어: 사이드바, 글 목록, 글 페이지."""

import re

import pytest

from tests.fakes.viewer_world import World, groups
from tests.fakes.web_parts import start_app


@pytest.fixture
def world(tmp_path):
    parts, client = start_app(tmp_path)
    with client:
        yield World(parts)


# ---------- 사이드바 ----------


def test_the_sidebar_has_three_groups_at_the_same_level(world):
    html = world.get("/reader").text
    assert list(groups(html)) == ["RSS", "카테고리", "주제"]


def test_the_rss_group_lists_every_registered_site_including_those_in_categories(world):
    rss = groups(world.get("/reader").text)["RSS"]
    assert "뉴스 블로그" in rss and "자유 블로그" in rss and ">전체<" in rss


def test_the_category_group_nests_each_categorys_sites(world):
    category = groups(world.get("/reader").text)["카테고리"]
    assert "뉴스" in category and "기술" in category and "뉴스 블로그" in category
    assert "자유 블로그" not in category  # 카테고리에 속하지 않은 사이트는 카테고리 아래에 없다
    assert "피드 없음" in category  # 비어 있는 카테고리는 그렇게 표시한다


def test_the_topic_group_has_topic_names_only_without_any_site(world):
    topic = groups(world.get("/reader").text)["주제"]
    assert "OTT" in topic and "뉴스 블로그" not in topic and "자유 블로그" not in topic


def test_the_sidebar_is_on_every_viewer_page_and_also_as_a_collapsible_mobile_menu(world):
    article_id = world.article()
    for path in ("/reader", f"/reader/feed/{world.f_free}", f"/a/{article_id}", "/reader/feed/999"):
        html = world.get(path).text
        assert html.count('<nav aria-label="구독 목록">') == 2
        assert 'class="side"' in html and 'class="menu-mobile"' in html


def test_the_current_list_is_marked_in_the_sidebar(world):
    topic_id = world.topics.list_all()[0].id
    expectations = {
        "/reader": "/reader",
        f"/reader/feed/{world.f_free}": f"/reader/feed/{world.f_free}",
        f"/reader/category/{world.news}": f"/reader/category/{world.news}",
        f"/reader/topic/{topic_id}": f"/reader/topic/{topic_id}",
    }
    for path, current in expectations.items():
        marked = re.findall(r'<a href="([^"]+)" aria-current="page"', world.get(path).text)
        assert set(marked) == {current}


def test_the_main_navigation_links_to_the_viewer(world):
    assert 'href="/reader"' in world.get("/").text


def test_site_and_category_names_are_escaped_in_the_sidebar(world):
    world.feeds.add("https://e.example.com/rss", "<script>alert(1)</script>")
    html = world.get("/reader").text
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html


# ---------- 목록 ----------


def test_the_list_shows_newest_first_with_site_time_and_a_link_to_the_article_page(world):
    old = world.article(minutes=0, title="Older post")
    new = world.article(world.f_news, minutes=30, title="Newer post")
    html = world.get("/reader").text
    assert html.index("Newer post") < html.index("Older post")
    assert f'href="/a/{new}"' in html and f'href="/a/{old}"' in html
    assert "뉴스 블로그 · 10-16 10:30" in html  # 서비스 시간대(Asia/Seoul)로 표시한다


def test_a_translated_title_and_a_summary_snippet_are_shown(world):
    world.article(title="Original", ko="번역된 제목", summary="요약 내용입니다")
    html = world.get("/reader").text
    assert "번역된 제목" in html and "요약 내용입니다" in html and ">Original<" not in html


def test_a_long_summary_is_cut_in_the_list(world):
    world.article(ko="t", summary="가" * 500)
    snippet = re.search(r'<p class="snippet">(.*?)</p>', world.get("/reader").text).group(1)
    assert len(snippet) == 140 and snippet.endswith("…")


def test_topic_badges_are_shown_in_the_list(world):
    ott = world.topics.list_all()[0]
    article_id = world.article(title="Netflix post")
    world.topics.record_matches(article_id, {ott.id: ("netflix",)})
    assert f'<span class="badge">{ott.name}</span>' in world.get("/reader").text


def test_archived_articles_are_listed_too(world):
    world.article(title="Archived post", status="archived")
    assert "Archived post" in world.get("/reader").text


def test_a_site_list_shows_only_that_site(world):
    world.article(world.f_news, title="News post")
    world.article(world.f_free, title="Free post")
    html = world.get(f"/reader/feed/{world.f_news}").text
    assert "News post" in html and "Free post" not in html and "<h1>뉴스 블로그</h1>" in html


def test_a_category_list_shows_only_its_sites_articles(world):
    world.article(world.f_news, title="News post")
    world.article(world.f_free, title="Free post")
    html = world.get(f"/reader/category/{world.news}").text
    assert "News post" in html and "Free post" not in html and "<h1>뉴스</h1>" in html


def test_a_topic_list_shows_only_articles_of_that_topic(world):
    ott = world.topics.list_all()[0]
    inside = world.article(title="OTT post")
    world.article(title="Other post")
    world.topics.record_matches(inside, {ott.id: ()})
    html = world.get(f"/reader/topic/{ott.id}").text
    assert "OTT post" in html and "Other post" not in html and f"<h1>{ott.name}</h1>" in html


@pytest.mark.parametrize("kind", ["feed", "category", "topic"])
def test_an_unknown_list_gives_404_with_the_sidebar_still_there(world, kind):
    response = world.get(f"/reader/{kind}/9999")
    assert response.status_code == 404 and "찾을 수 없는 목록" in response.text
    assert 'class="side"' in response.text


@pytest.mark.parametrize(
    ("path", "message"),
    [
        ("/reader", "아직 글이 없습니다"),
        ("/reader/feed/{free}", "이 사이트에서 수집된 글이 아직 없습니다"),
        ("/reader/category/{news}", "이 카테고리의 피드에서 수집된 글이 아직 없습니다"),
        ("/reader/topic/{topic}", "이 주제에 해당한 글이 아직 없습니다"),
    ],
)
def test_empty_lists_explain_themselves(world, path, message):
    topic = world.topics.list_all()[0].id
    assert message in world.get(path.format(free=world.f_free, news=world.news, topic=topic)).text


def test_pagination_links_follow_thirty_per_page(world):
    for number in range(35):
        world.article(minutes=number, title=f"Post {number:02d}")
    first = world.get("/reader").text
    assert (
        first.count('class="item"') == 30
        and 'href="/reader?page=2"' in first
        and "← 이전" not in first
    )
    second = world.get("/reader?page=2").text
    assert (
        second.count('class="item"') == 5
        and 'href="/reader?page=1"' in second
        and "다음 →" not in second
    )


def test_pagination_keeps_the_scope_in_its_links(world):
    for number in range(31):
        world.article(world.f_news, minutes=number)
    assert (
        f'href="/reader/feed/{world.f_news}?page=2"'
        in world.get(f"/reader/feed/{world.f_news}").text
    )


@pytest.mark.parametrize("raw", ["abc", "0", "-1", "1.5", "", "٣", "1; DROP TABLE articles"])
def test_a_bad_page_number_means_the_first_page(world, raw):
    world.article(title="Only post")
    response = world.client.get("/reader", params={"page": raw})
    assert response.status_code == 200 and "Only post" in response.text


def test_a_page_far_past_the_end_is_an_empty_list_not_an_error(world):
    world.article()
    response = world.get("/reader?page=99999999999")
    assert response.status_code == 200 and "아직 글이 없습니다" in response.text


def test_titles_are_escaped_in_the_list(world):
    world.article(title="<img src=x onerror=alert(1)>")
    html = world.get("/reader").text
    assert "<img src=x" not in html and "&lt;img src=x onerror=alert(1)&gt;" in html


# ---------- 글 페이지 ----------


def test_the_article_page_shows_titles_site_time_summary_and_the_original_button(world):
    article_id = world.article(
        world.f_news,
        30,
        title="Original title",
        ko="번역된 제목",
        summary="요약입니다",
        link="https://x.example.com/orig",
    )
    html = world.get(f"/a/{article_id}").text
    assert "<h1>번역된 제목</h1>" in html and "Original title" in html
    assert f'href="/reader/feed/{world.f_news}"' in html and "2026-10-16 10:30" in html
    assert "요약입니다" in html and f'href="/a/{article_id}/original"' in html
    assert 'target="_blank"' in html and "noopener noreferrer" in html


def test_an_article_without_a_translation_shows_its_own_title_once(world):
    article_id = world.article(title="Plain title")
    html = world.get(f"/a/{article_id}").text
    assert "<h1>Plain title</h1>" in html and html.count("Plain title") == 2  # 제목 태그와 h1


def test_the_topics_and_matched_keywords_are_shown(world):
    ott = world.topics.list_all()[0]
    article_id = world.article()
    world.topics.record_matches(article_id, {ott.id: ("netflix", "drama")})
    html = world.get(f"/a/{article_id}").text
    assert ott.name in html and "키워드 netflix, drama" in html


def test_the_article_body_is_sanitized(world):
    content = (
        "<p>안전한 글</p><script>alert(1)</script><img src=x onerror=alert(2)>"
        '<a href="javascript:alert(3)">나쁜 링크</a><iframe src="https://evil.example.com"></iframe>'
        '<img src="https://img.example.com/a.png" alt="그림"><p onclick="alert(4)">클릭</p>'
    )
    article_id = world.article(content=content)
    html = world.get(f"/a/{article_id}").text
    body = html.split('class="article-body"')[1]
    for bad in ("<script>alert", "onerror", "javascript:", "<iframe", "onclick"):
        assert bad not in body
    assert "안전한 글" in body and 'src="https://img.example.com/a.png"' in body


def test_relative_links_and_images_in_the_body_resolve_against_the_articles_address(world):
    article_id = world.article(
        content='<a href="/more">더</a><img src="/i.png">', link="https://blog.example.com/p/1"
    )
    body = world.get(f"/a/{article_id}").text.split('class="article-body"')[1]
    assert (
        'href="https://blog.example.com/more"' in body
        and 'src="https://blog.example.com/i.png"' in body
    )


@pytest.mark.parametrize(
    ("content", "lang"),
    [
        ("<p>스프링 부트 마이그레이션 후기를 정리했다.</p>", 'lang="ko"'),
        ("<p>The new phone has a bigger battery and a better camera.</p>", 'lang="en"'),
        ("<p>これは日本語です</p>", ""),
    ],
)
def test_the_article_area_is_marked_with_its_language_for_the_browsers_translation(
    world, content, lang
):
    article_id = world.article(title="12345", content=content)
    area = re.search(
        r'<div class="article-body"([^>]*)>', world.get(f"/a/{article_id}").text
    ).group(1)
    assert (lang in area) if lang else ("lang=" not in area)


def test_an_article_without_a_body_says_so(world):
    article_id = world.article(content="")
    assert "본문이 없습니다. 원문에서 확인하세요" in world.get(f"/a/{article_id}").text


def test_an_archived_article_without_a_summary_has_no_summary_box(world):
    article_id = world.article(title="Archived", status="archived")
    html = world.get(f"/a/{article_id}").text
    assert "<h1>Archived</h1>" in html and "<strong>요약</strong>" not in html


@pytest.mark.parametrize("link", ["javascript:alert(1)", "", "ftp://x.example.com/a"])
def test_no_original_button_for_an_address_that_cannot_be_followed(world, link):
    article_id = world.article(link=link)
    assert "원문 보기" not in world.get(f"/a/{article_id}").text


def test_an_unknown_article_gives_404_with_the_sidebar(world):
    response = world.get("/a/999999")
    assert response.status_code == 404 and 'class="side"' in response.text


# ---------- 보안 헤더 ----------


@pytest.mark.security
def test_the_policy_allows_https_images_but_no_scripts_frames_or_other_sources(world):
    article_id = world.article()
    policy = world.get(f"/a/{article_id}").headers["content-security-policy"]
    assert "img-src https:" in policy and "default-src 'none'" in policy
    assert "script-src" not in policy and "unsafe-eval" not in policy and "frame-src" not in policy


@pytest.mark.security
def test_the_viewer_pages_cannot_change_anything(world):
    article_id = world.article()
    before = world.articles.count_by_status()
    for path in ("/reader", f"/a/{article_id}", f"/reader/feed/{world.f_free}"):
        assert world.client.post(path, data={}).status_code in (403, 405)
    assert world.articles.count_by_status() == before


def test_a_category_without_sites_has_an_empty_list_and_says_why(world):
    html = world.get(f"/reader/category/{world.tech}").text
    assert "<h1>기술</h1>" in html and "이 카테고리의 피드에서 수집된 글이 아직 없습니다" in html


def test_links_use_the_theme_color_so_they_stay_readable_in_dark_mode(world):
    html = world.get("/reader").text
    assert "a { color: var(--accent); }" in html
    assert "--accent: #7ea2ff" in html  # 다크 모드에서는 밝은 강조색


def test_the_top_menu_wraps_on_narrow_screens_instead_of_breaking_words(world):
    html = world.get("/reader").text
    assert "flex-wrap: wrap" in html and "header nav a { white-space: nowrap; }" in html
