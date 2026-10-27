"""원문 페이지에서 본문만 뽑는 규칙(광고, 메뉴, 댓글, 스크립트는 빼고 정제한다)."""

# ruff: noqa: E501  (HTML 견본은 한 줄로 두는 편이 읽기 쉽다)

import re
import time

import pytest

from rss_hub.domain.fulltext import (
    MAX_SHELL_LENGTH,
    MIN_TEXT_LENGTH,
    extract_article,
    extract_main_content,
    find_page_redirect,
    reference_coverage,
    reference_is_complete,
)

LONG = "본문 문장입니다. " * 40  # 충분히 긴 본문


def page(body: str, head: str = "") -> str:
    return f"<!doctype html><html><head><title>t</title>{head}</head><body>{body}</body></html>"


def test_the_article_element_is_the_body_and_menus_footers_and_sidebars_are_dropped():
    html = page(
        f"<header><nav><a href='/'>홈</a></nav></header>"
        f"<article><p>{LONG}</p><h2>소제목</h2><p>둘째 문단</p></article>"
        f"<aside>관련 글 목록</aside><footer>저작권 안내</footer>"
    )
    text = extract_main_content(html, "https://x.example.com/post")
    assert text is not None
    assert "소제목" in text and "둘째 문단" in text and "본문 문장입니다" in text
    assert "홈" not in text and "관련 글 목록" not in text and "저작권 안내" not in text


def test_a_div_based_page_without_an_article_element_still_finds_the_content():
    menu = "<div class='menu'><a href='/a'>메뉴1</a><a href='/b'>메뉴2</a></div>"
    body = f"<div class='post-content'><p>{LONG}</p><p>끝 문단</p></div>"
    text = extract_main_content(page(f"<div id='top'>{menu}{body}</div>"), "https://x.example.com/")
    assert text and "끝 문단" in text and "메뉴1" not in text


def test_comments_and_related_blocks_are_not_chosen_over_the_article():
    comments = "".join(f"<p>댓글 {n} " + "좋아요 " * 30 + "</p>" for n in range(12))
    html = page(
        f"<main><div class='entry'><p>{LONG}</p></div></main><div id='comments'>{comments}</div>"
    )
    text = extract_main_content(html, "https://x.example.com/")
    assert text and "본문 문장입니다" in text and "댓글 3" not in text


def test_a_block_full_of_links_is_not_the_content():
    links = "".join(
        f"<li><a href='/p{n}'>다른 글 제목 {n} " + "더보기 " * 10 + "</a></li>" for n in range(30)
    )
    html = page(f"<div class='list'><ul>{links}</ul></div><div class='story'><p>{LONG}</p></div>")
    text = extract_main_content(html, "https://x.example.com/")
    assert text and "본문 문장입니다" in text and "다른 글 제목" not in text


def test_the_script_style_form_and_iframe_never_survive():
    junk = "<script>alert(1)</script><style>p{color:red}</style><form><input name=x></form>"
    junk += "<iframe src='https://evil.example.com'></iframe>"
    text = extract_main_content(
        page(f"<article>{junk}<p>{LONG}</p></article>"), "https://x.example.com/"
    )
    assert text and "alert" not in text and "color:red" not in text
    assert "<form" not in text and "iframe" not in text and "<input" not in text


def test_dangerous_attributes_and_links_are_removed_by_the_sanitizer():
    bad = "<a href='javascript:alert(1)'>나쁜 링크</a><img src='x' onerror='alert(1)'>"
    para = f"<p onclick='x()' style='position:fixed'>{LONG}</p>"
    text = extract_main_content(page(f"<article>{para}{bad}</article>"), "https://x.example.com/")
    assert text and "onclick" not in text and "onerror" not in text
    assert "javascript:" not in text and "style=" not in text


def test_relative_links_and_images_are_resolved_against_the_final_address():
    html = page(
        f"<article><p>{LONG}</p><a href='/more'>더 보기</a><img src='pic.png' alt='그림'></article>"
    )
    text = extract_main_content(html, "https://x.example.com/blog/post")
    assert (
        text
        and 'href="https://x.example.com/more"' in text
        and "https://x.example.com/blog/pic.png" in text
    )


def test_lazy_loaded_images_use_the_data_src_address():
    image = "<img src='data:image/gif;base64,R0lGOD' alt='지연'"
    image += " data-src='https://cdn.example.com/real.jpg'>"
    text = extract_main_content(
        page(f"<article><p>{LONG}</p>{image}</article>"), "https://x.example.com/"
    )
    assert text and "https://cdn.example.com/real.jpg" in text and "base64" not in text


@pytest.mark.parametrize(
    "body",
    [
        "",
        "<p>짧은 글</p>",
        "<article><p>너무 짧다</p></article>",
        "<nav>" + "메뉴 " * 100 + "</nav>",
    ],
)
def test_a_page_without_enough_text_gives_nothing(body):
    assert extract_main_content(page(body), "https://x.example.com/") is None


def test_the_minimum_length_is_applied_to_the_real_text():
    assert (
        extract_main_content(
            page(f"<article><p>{'가' * (MIN_TEXT_LENGTH - 1)}</p></article>"),
            "https://x.example.com/",
        )
        is None
    )
    assert extract_main_content(
        page(f"<article><p>{'가' * (MIN_TEXT_LENGTH + 5)}</p></article>"), "https://x.example.com/"
    )


@pytest.mark.parametrize(
    "html",
    [
        "",
        "<<<>>>",
        "<div><p>닫지 않음" * 50,
        "</div></p></article>" * 20,
        "\x00\x01<article>",
        "<article>" * 300 + LONG,
    ],
)
def test_broken_html_never_crashes(html):
    extract_main_content(html, "https://x.example.com/")  # 예외가 없으면 된다


def test_very_deep_nesting_is_cut_off_instead_of_blowing_the_stack():
    html = page("<div>" * 5000 + f"<p>{LONG}</p>" + "</div>" * 5000)
    started = time.monotonic()
    extract_main_content(html, "https://x.example.com/")
    assert time.monotonic() - started < 10  # 제곱 시간이면 몇십 초가 걸린다


def test_the_result_is_deterministic():
    html = page(f"<article><p>{LONG}</p></article><div class='post'><p>{LONG}</p></div>")
    assert extract_main_content(html, "https://x.example.com/") == extract_main_content(
        html, "https://x.example.com/"
    )


def test_text_with_special_characters_is_escaped_not_executed():
    html = page(
        f"<article><p>{LONG} &lt;script&gt;alert(1)&lt;/script&gt; 1 &lt; 2 &amp; 3</p></article>"
    )
    text = extract_main_content(html, "https://x.example.com/")
    assert (
        text and "<script>" not in text and "&lt;script&gt;" in text and "1 &lt; 2 &amp; 3" in text
    )


def test_a_wrapper_named_has_sidebar_is_not_thrown_away():
    html = page(
        f"<div class='site has-sidebar'><div class='content-area'><p>{LONG}</p></div></div>"
    )
    assert extract_main_content(html, "https://x.example.com/")


@pytest.mark.parametrize(
    "name",
    [
        "comments",
        "comment-list",
        "related-posts",
        "share-bar",
        "sidebar-left",
        "ad-slot",
        "newsletter",
        "cookie-banner",
    ],
)
def test_blocks_named_like_noise_are_left_out_even_inside_the_article(name):
    html = page(f"<article><p>{LONG}</p><div class='{name}'><p>잡음 블록</p></div></article>")
    text = extract_main_content(html, "https://x.example.com/")
    assert text and "잡음 블록" not in text


def test_the_article_element_itself_is_never_dropped_by_its_class():
    html = page(f"<article class='comments-enabled sidebar'><p>{LONG}</p></article>")
    assert extract_main_content(html, "https://x.example.com/")


def test_self_closing_tags_are_handled_like_open_and_close_pairs():
    html = page(
        f"<article><p>첫 줄입니다.<br/>둘째 줄입니다.</p><div/><p>{LONG}</p><hr/></article>"
    )
    text = extract_main_content(html, "https://x.example.com/")
    assert text and "첫 줄입니다" in text and "둘째 줄입니다" in text and "본문 문장입니다" in text


def test_a_page_with_far_more_tags_than_the_limit_still_finds_the_text_and_is_fast():
    junk = "<i>x</i>" * 62000  # 노드 수 상한(60000)을 넘긴다
    started = time.monotonic()
    text = extract_main_content(
        page(f"<article><p>{LONG}</p></article>{junk}"), "https://x.example.com/"
    )
    assert text and "본문 문장입니다" in text and time.monotonic() - started < 10


def test_a_huge_article_is_cut_at_the_output_limit():
    from rss_hub.domain.fulltext import MAX_OUTPUT_CHARS

    paragraphs = f"<p>{LONG}</p>" * 400  # 출력 상한보다 훨씬 크다
    text = extract_main_content(page(f"<article>{paragraphs}</article>"), "https://x.example.com/")
    assert text and len(text) < MAX_OUTPUT_CHARS * 1.1


def test_a_parser_failure_means_no_text_instead_of_an_error(monkeypatch):
    from rss_hub.domain import fulltext

    def explode(self, data):
        raise RuntimeError("파서 내부 오류")

    monkeypatch.setattr(fulltext._Builder, "feed", explode)
    assert (
        extract_main_content(page(f"<article><p>{LONG}</p></article>"), "https://x.example.com/")
        is None
    )


def test_a_closing_tag_without_a_matching_open_tag_is_ignored():
    html = page(f"<article><p>{LONG}</p></span></b><p>뒤 문단</p></article>")
    text = extract_main_content(html, "https://x.example.com/")
    assert text and "뒤 문단" in text


def test_the_descent_goes_through_non_candidate_wrappers_to_the_content_block():
    html = page(
        f"<div class='wrap'><center><div class='entry-content'><p>{LONG}</p></div></center></div>"
    )
    assert extract_main_content(html, "https://x.example.com/")


def test_whitespace_between_tags_is_ignored_when_measuring_and_kept_readable():
    html = page(f"<article>\n  <p>{LONG}</p>\n  <p>둘째 문단</p>\n</article>")
    text = extract_main_content(html, "https://x.example.com/")
    assert text and "둘째 문단" in text


def test_the_choice_descends_from_a_wrapper_with_stray_text_to_the_content_block():
    html = page(
        f"<div class='page'><p>래퍼에 섞인 잡음 한 줄</p><div class='blk'><p>{LONG}</p></div></div>"
    )
    text = extract_main_content(html, "https://x.example.com/")
    assert text and "본문 문장입니다" in text and "래퍼에 섞인 잡음" not in text


# ---------- 영상은 재생하지 않고 "영상 보기" 링크로 바꾼다(주소는 글자로 보이지 않는다) ----------


def visible(text: str) -> str:
    """태그를 뺀 화면에 보이는 글자."""
    import re

    return re.sub(r"<[^>]*>", " ", text)


def media_page(media: str) -> str:
    return page(f"<article><p>{LONG}</p>{media}<p>뒤 문단</p></article>")


@pytest.mark.parametrize(
    ("embed", "watch"),
    [
        (
            "https://www.youtube.com/embed/dQw4w9WgXcQ",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        ),
        (
            "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ?rel=0",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        ),
        ("//www.youtube.com/embed/dQw4w9WgXcQ", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
        ("https://player.vimeo.com/video/123456789", "https://vimeo.com/123456789"),
        (
            "https://www.dailymotion.com/embed/video/x8abc",
            "https://www.dailymotion.com/embed/video/x8abc",
        ),
        ("https://tv.naver.com/embed/12345", "https://tv.naver.com/embed/12345"),
        (
            "https://tv.kakao.com/embed/player/cliplink/1",
            "https://tv.kakao.com/embed/player/cliplink/1",
        ),
        ("https://player.twitch.tv/?video=1", "https://player.twitch.tv/?video=1"),
    ],
)
def test_a_known_video_embed_becomes_a_link_that_opens_in_a_new_window(embed, watch):
    text = extract_main_content(
        media_page(f"<iframe src='{embed}' width='560'></iframe>"), "https://x.example.com/"
    )
    assert text and f'href="{watch}"' in text.replace("&amp;", "&")
    assert 'target="_blank"' in text and "noopener" in text and "<iframe" not in text
    assert "영상 보기" in visible(text)


def test_the_address_is_never_shown_as_text_and_the_label_is_fixed():
    text = extract_main_content(
        media_page("<iframe src='https://www.youtube.com/embed/dQw4w9WgXcQ'></iframe>"),
        "https://x.example.com/",
    )
    shown = visible(text)
    assert "youtube" not in shown and "dQw4w9WgXcQ" not in shown and "http" not in shown
    assert shown.count("영상 보기") == 1


def test_the_link_sits_where_the_video_was():
    text = extract_main_content(
        media_page("<iframe src='https://player.vimeo.com/video/1'></iframe>"),
        "https://x.example.com/",
    )
    assert text.index("본문 문장입니다") < text.index("영상 보기") < text.index("뒤 문단")


@pytest.mark.parametrize(
    "src",
    [
        "https://ads.example.com/banner",
        "https://maps.example.org/embed",
        "https://evil.youtube.com.attacker.example/embed/x",
        "javascript:alert(1)",
        "data:text/html,<script>1</script>",
        "ftp://www.youtube.com/embed/x",
        "https://user:pw@www.youtube.com/embed/abcdefgh",
        "",
    ],
)
def test_other_frames_and_unusable_addresses_are_dropped_without_any_link(src):
    text = extract_main_content(
        media_page(f"<iframe src='{src}'></iframe>"), "https://x.example.com/"
    )
    assert (
        text
        and "영상 보기" not in text
        and "<iframe" not in text
        and "attacker" not in text
        and "banner" not in text
    )


def test_a_video_element_with_a_file_address_becomes_a_link():
    media = "<video src='https://cdn.example.com/clip.mp4' controls>"
    media += "지원하지 않는 브라우저입니다</video>"
    text = extract_main_content(media_page(media), "https://x.example.com/")
    assert 'href="https://cdn.example.com/clip.mp4"' in text and "영상 보기" in visible(text)
    assert "지원하지 않는 브라우저" not in text  # 대체 문구는 남기지 않는다


def test_a_video_with_a_source_child_uses_the_first_source():
    media = "<video controls><source src='https://cdn.example.com/a.mp4'><source src='https://cdn.example.com/b.webm'></video>"
    text = extract_main_content(media_page(media), "https://x.example.com/")
    assert 'href="https://cdn.example.com/a.mp4"' in text and "b.webm" not in text


def test_a_relative_video_address_is_resolved_against_the_final_address():
    text = extract_main_content(
        media_page("<video src='/media/clip.mp4'></video>"), "https://x.example.com/blog/post"
    )
    assert 'href="https://x.example.com/media/clip.mp4"' in text


def test_audio_gets_its_own_label():
    text = extract_main_content(
        media_page("<audio src='https://cdn.example.com/a.mp3'></audio>"), "https://x.example.com/"
    )
    assert "오디오 듣기" in visible(text) and "영상 보기" not in text


@pytest.mark.parametrize(
    "media",
    [
        "<video></video>",
        "<video controls>대체 문구</video>",
        "<audio></audio>",
        "<embed>",
        "<object></object>",
    ],
)
def test_media_without_an_address_leaves_nothing_behind(media):
    text = extract_main_content(media_page(media), "https://x.example.com/")
    assert text and "영상 보기" not in text and "오디오" not in text and "대체 문구" not in text


def test_media_inside_dropped_blocks_is_not_turned_into_links():
    top = "<nav><iframe src='https://www.youtube.com/embed/abcdefgh1'></iframe></nav>"
    bottom = "<footer><video src='https://cdn.example.com/f.mp4'></video></footer>"
    text = extract_main_content(
        page(f"{top}<article><p>{LONG}</p></article>{bottom}"), "https://x.example.com/"
    )
    assert text and "영상 보기" not in text


def test_embed_and_object_with_a_known_host_also_become_links():
    text = extract_main_content(
        media_page(
            "<embed src='https://www.youtube.com/v/abcdefgh1'><object data='https://player.vimeo.com/video/42'></object>"
        ),
        "https://x.example.com/",
    )
    assert "https://www.youtube.com/watch?v=abcdefgh1" in text and "https://vimeo.com/42" in text


def test_the_number_of_media_links_is_capped():
    media = "".join(f"<video src='https://cdn.example.com/{n}.mp4'></video>" for n in range(60))
    text = extract_main_content(media_page(media), "https://x.example.com/")
    assert text.count("영상 보기") == 20


def test_a_video_site_address_of_an_unknown_shape_is_kept_as_it_is():
    media = "<iframe src='https://www.youtube.com/playlist?list=PL123'></iframe>"
    media += "<iframe src='https://player.vimeo.com/video/not-a-number'></iframe>"
    text = extract_main_content(media_page(media), "https://x.example.com/")
    assert 'href="https://www.youtube.com/playlist?list=PL123"' in text
    assert 'href="https://player.vimeo.com/video/not-a-number"' in text


def test_a_broken_address_never_crashes_and_makes_no_link():
    text = extract_main_content(
        media_page("<video src='https://[broken/x.mp4'></video>"), "https://x.example.com/"
    )
    assert text and "영상 보기" not in text


def test_a_source_without_an_address_is_skipped_for_the_next_source():
    media = "<video controls><source type='video/mp4'><source src='https://cdn.example.com/c.mp4'></video>"
    text = extract_main_content(media_page(media), "https://x.example.com/")
    assert 'href="https://cdn.example.com/c.mp4"' in text


# ---------- 글과 상관없는 덩어리 정리: 링크 목록, 태그, 공유 막대, 로고, 제목, 하단 안내 ----------

LINK_LIST = (
    "<ul>"
    + "".join(
        f"<li><a href='/p{n}'>다른 글 제목 {n}번: 길게 이어지는 링크 글자</a></li>"
        for n in range(5)
    )
    + "</ul>"
)
SHARE_BAR = (
    "<ul><li><a href='https://twitter.com/x'>Post</a></li><li><a href='https://facebook.com/x'>Post</a></li>"
    "<li><a href='https://linkedin.com/x'>Share</a></li><li>Annotate</li><li><a href='#'>Save</a></li><li>Print</li></ul>"
)


def clean(body: str, title: str = "") -> str:
    text = extract_main_content(
        page(f"<article>{body}</article>"), "https://x.example.com/p", title
    )
    assert text is not None
    return text


def test_a_list_made_only_of_links_is_dropped_together_with_its_label():
    text = clean(f"<p>{LONG}</p><h4>Cybersecurity Guides</h4>{LINK_LIST}<p>뒤 문단</p>")
    assert "본문 문장입니다" in text and "뒤 문단" in text
    assert "Cybersecurity Guides" not in text and "다른 글 제목" not in text


def test_a_share_bar_with_mixed_links_and_labels_is_dropped():
    text = clean(f"<p>{LONG}</p>{SHARE_BAR}<p>뒤 문단</p>")
    for word in ("Post", "Share", "Annotate", "Save", "Print"):
        assert word not in text
    assert "뒤 문단" in text


def test_the_same_share_bar_twice_is_dropped_twice():
    text = clean(f"{SHARE_BAR}<p>{LONG}</p>{SHARE_BAR}")
    assert "Annotate" not in text and "본문 문장입니다" in text


def test_normal_lists_stay():
    items = "<ul><li>첫째 항목은 설명이 충분히 깁니다 그리고 계속됩니다</li><li>둘째 항목도 마찬가지로 설명이 깁니다</li><li>셋째 항목은 <a href='/x'>링크</a>가 섞여 있습니다 그래도 본문입니다</li></ul>"
    words = "<ul><li>사과</li><li>배</li><li>귤</li><li>감</li></ul>"
    text = clean(f"<p>{LONG}</p>{items}{words}")
    assert "첫째 항목" in text and "셋째 항목" in text and "사과" in text and "귤" in text


def test_two_links_in_a_list_are_not_enough_to_call_it_noise():
    text = clean(
        f"<p>{LONG}</p><ul><li><a href='/a'>참고 자료 하나</a></li><li><a href='/b'>참고 자료 둘</a></li></ul>"
    )
    assert "참고 자료 하나" in text


def test_a_row_of_tag_links_and_its_label_are_dropped():
    tags = "<p>Explore more on these topics</p><div><a href='/t/a'>Crypto</a> <a href='/t/b'>Privacy</a> <a href='/t/c'>Sam Altman</a></div>"
    text = clean(f"<p>{LONG}</p>{tags}")
    assert "Explore more" not in text and "Crypto" not in text and "Sam Altman" not in text


@pytest.mark.parametrize(
    "marker",
    [
        "Related Articles",
        "Share this story",
        "Follow Us",
        "Sign up for our newsletters",
        "You might also like",
        "Comments",
        "Read next",
        "관련 기사",
        "댓글",
        "Explore more on these topics",
    ],
)
def test_a_closing_marker_cuts_everything_after_it(marker):
    text = clean(
        f"<p>{LONG}</p><h3>{marker}</h3><p>끝에 붙은 군더더기 문단</p><div><p>더 많은 군더더기</p></div>"
    )
    assert "본문 문장입니다" in text and "군더더기" not in text and marker not in text


def test_a_marker_word_early_in_the_article_does_not_cut_the_real_text():
    text = clean(f"<h3>Related</h3><p>{LONG}</p><p>뒷부분 문단</p>")
    assert "뒷부분 문단" in text  # 글의 앞쪽(40% 이전)에 나온 낱말은 끝 안내로 보지 않는다


def test_a_heading_that_only_starts_like_a_marker_is_kept():
    text = clean(f"<p>{LONG}</p><h3>Related Work and Background</h3><p>이어지는 실제 내용</p>")
    assert "Related Work and Background" in text and "이어지는 실제 내용" in text


def test_the_heading_that_repeats_the_article_title_is_dropped_once():
    text = clean(
        f"<h1>Build a Board That Challenges Your Thinking</h1><p>{LONG}</p><h2>소제목</h2>",
        "Build a Board That Challenges Your Thinking",
    )
    assert "Build a Board" not in text and "소제목" in text


def test_a_title_that_is_contained_in_the_heading_or_the_other_way_around_also_matches():
    assert "Spec Driven" not in clean(
        f"<h2>Spec Driven Development: The Challenges</h2><p>{LONG}</p>", "Spec Driven Development"
    )
    assert "Challenges Of Boards" not in clean(
        f"<h2>Challenges Of Boards</h2><p>{LONG}</p>",
        "Challenges Of Boards | Harvard Business Review",
    )


def test_an_unrelated_heading_is_kept_even_when_a_title_is_given():
    text = clean(
        f"<p>{LONG}</p><h2>완전히 다른 소제목</h2><p>뒷 문단</p>",
        "Build a Board That Challenges Your Thinking",
    )
    assert "완전히 다른 소제목" in text


def test_without_a_title_no_heading_is_removed():
    text = clean(f"<p>{LONG}</p><h2>Build a Board That Challenges Your Thinking</h2><p>뒷 문단</p>")
    assert "Build a Board" in text  # 제목을 모르면 머리글을 빼지 않는다


@pytest.mark.parametrize(
    "image",
    [
        "<img src='https://cdn.example.com/brand.svg' alt='Harvard Business Review'>",
        "<img src='https://cdn.example.com/a.png' alt='site logo'>",
        "<img src='https://cdn.example.com/logo-dark.png'>",
        "<img class='avatar' src='https://cdn.example.com/me.jpg'>",
        "<img src='https://cdn.example.com/sprite.png'>",
    ],
)
def test_logos_and_decorative_images_are_dropped(image):
    assert "<img" not in clean(f"{image}<p>{LONG}</p>")


def test_content_images_stay():
    text = clean(
        f"<p>{LONG}</p><figure><img src='https://cdn.example.com/chart.png' alt='매출 추이'><figcaption>그림 1</figcaption></figure>"
    )
    assert "https://cdn.example.com/chart.png" in text and "그림 1" in text


def test_a_truncated_teaser_ending_with_an_ellipsis_bracket_is_dropped():
    text = clean(
        f"<p>이 글은 요약문입니다. 길게 이어지다가 잘리는 부분 […]</p><p>{LONG}</p><p>일반 문단은 말줄임표로 끝나도 남습니다…</p>"
    )
    assert "요약문입니다" not in text and "일반 문단은" in text


def test_a_standalone_date_line_near_the_top_is_dropped_but_a_date_deep_in_the_text_stays():
    top = clean(f"<p>October 20, 2026</p><p>{LONG}</p>")
    assert "October 20, 2026" not in top
    deep = clean(f"<p>{LONG * 6}</p><p>October 20, 2026</p><p>그날의 일정</p>")
    assert "October 20, 2026" in deep


@pytest.mark.parametrize("date", ["2026-10-20", "2026.10.20", "2026년 10월 20일", "Oct 20, 2026"])
def test_other_date_shapes_near_the_top_are_dropped_too(date):
    assert date not in clean(f"<p>{date}</p><p>{LONG}</p>")


def test_the_harvard_business_review_page_is_reduced_to_its_body():
    share = "<ul><li><a href='http://twitter.com/HarvardBiz'>Post</a></li><li><a href='http://www.facebook.com/HBR'>Post</a></li><li><a href='https://www.linkedin.com/company/hbr'>Share</a></li><li>Annotate</li><li><a href='#'>Save</a></li><li>Print</li></ul>"
    body = (
        "<img src='https://hbr.org/resources/images/logo.svg' alt='Harvard Business Review'>"
        "<h1>Build a Board That Challenges Your Thinking</h1>"
        "<p>An effective board should challenge the forces shaping decision-making at your company. Define what your […]</p>"
        f"<p>October 20, 2026</p>{share}{share}"
        f"<p>{LONG}</p><p>Source: <a href='https://hbr.org/2026/11/building-a-board-that-fits'>This tip is adapted from a book.</a></p>{share}"
    )
    text = clean(body, "Build a Board That Challenges Your Thinking")
    assert "본문 문장입니다" in text and "Source:" in text
    for noise in (
        "Annotate",
        "Print",
        "Save",
        "Post",
        "<img",
        "Build a Board",
        "Define what your",
        "October 20",
    ):
        assert noise not in text, noise


def test_the_gizmodo_page_loses_its_guides_tags_follow_and_newsletter_tail():
    tail = (
        "<h4>Cybersecurity Guides</h4><ul>"
        + "".join(
            f"<li><a href='/vpn/{n}'>Best VPNs for Place {n} in 2026</a></li>" for n in range(5)
        )
        + "</ul>"
        "<p>Explore more on these topics</p><div><a href='/t/crypto'>Crypto</a><a href='/t/privacy'>Privacy</a><a href='/t/zoom'>Zoom</a></div>"
        "<p>Share this story</p><ul><li></li></ul><p><a href='/follow'>Follow Us</a></p><p><a href='/google'>Add Gizmodo on Google</a></p>"
        "<h3>Sign up for our newsletters</h3><p>Subscribe and interact with our community.</p><h3>Related Articles</h3>"
    )
    text = clean(
        f"<p>{LONG}</p><p>{LONG}</p><h3>A Long List of Controversies</h3><p>마지막 본문 문단</p>{tail}"
    )
    assert "마지막 본문 문단" in text and "A Long List of Controversies" in text
    for noise in (
        "Cybersecurity",
        "VPN",
        "Explore more",
        "Crypto",
        "Share this",
        "Follow Us",
        "Gizmodo on Google",
        "newsletters",
        "Related Articles",
    ):
        assert noise not in text, noise


def test_a_sentence_or_a_line_with_a_link_before_a_noise_list_is_not_mistaken_for_its_label():
    text = clean(
        f"<p>{LONG}</p><p>이 문장은 목록 앞에 있지만 문장입니다.</p>{LINK_LIST}<p>Source: <a href='/s'>원문</a></p>{SHARE_BAR}"
    )
    assert "이 문장은 목록 앞에" in text and "Source:" in text and "다른 글 제목" not in text


def test_a_list_of_long_link_texts_is_a_reading_list_not_a_navigation_bar():
    long_item = "함께 읽으면 좋은 긴 글의 제목입니다. " * 6  # 항목 하나가 100자를 넘는다
    items = "".join(f"<li><a href='/r{n}'>{long_item}{n}</a></li>" for n in range(3))
    assert "함께 읽으면 좋은" in clean(f"<p>{LONG}</p><ul>{items}</ul>")


def test_a_label_like_line_at_the_very_end_or_followed_by_plain_text_is_kept():
    assert "마지막 줄" in clean(f"<p>{LONG}</p><h4>마지막 줄</h4>")
    text = clean(f"<p>{LONG}</p><h4>짧은 소제목</h4>바로 이어지는 글자{LINK_LIST}")
    assert "짧은 소제목" in text and "바로 이어지는 글자" in text


@pytest.mark.parametrize("ending", ["[…]", "[...]"])
def test_both_bracket_shapes_of_a_cut_off_summary_are_dropped(ending):
    text = clean(f"<p>요약이 중간에서 잘린 문단입니다 {ending}</p><p>{LONG}</p>")
    assert "잘린 문단" not in text and "본문 문장입니다" in text


def test_a_very_short_heading_is_never_taken_for_the_title():
    text = clean(
        f"<p>{LONG}</p><h2>설계</h2><p>뒷 문단</p>", "설계"
    )  # 너무 짧아서 같은 제목인지 알 수 없다
    assert "설계" in text


# ---------- 실제 페이지(Gizmodo, InfoQ, HBR) 검토에서 나온 규칙 ----------


def giz(body: str) -> str:
    """Gizmodo 모양: 머리 영역(분류, 제목, 요약, 기자 줄, 대표 이미지)은 본문 영역(entry-content) 바깥."""
    hero = (
        "<div class='giz-bg'><span class='giz-cat'><a href='/c/tv'>Television</a></span>"
        "<h1>‘Daredevil: Born Again’ Star Felt Like Season 3 Might Be the End</h1>"
        "<div class='post-excerpt'>According to Woll, who plays Karen Page, the ending felt very different.</div>"
        "<div class='meta'><span>By</span><a href='/a/jen'>Jen Lennon</a>"
        "<time>Published October 20, 2026, 8:00 am ET</time></div><p>Reading time 2 minutes</p>"
        "<figure><img src='https://cdn.example.com/hero.jpg' alt=''><figcaption>© Marvel Studios</figcaption></figure></div>"
    )
    wrap = (
        "<div class='wrap'><div class='col'><article class='post'>"
        f"<div class='entry-content'>{body}</div></article></div></div>"
    )
    return page(f"<main>{hero}{wrap}</main>")


def test_the_header_area_outside_the_article_body_is_left_out():
    body = "".join(f"<p>{LONG}{n}</p>" for n in range(6)) + "<p>둘째 문단입니다.</p>"
    title = "‘Daredevil: Born Again’ Star Felt Like Season 3 Might Be the End"
    text = extract_main_content(giz(body), "https://x.example.com/p", title)
    assert text and "본문 문장입니다" in text and "둘째 문단" in text
    noise = ("Television", "Daredevil", "According to Woll", "By", "Jen Lennon", "Published")
    for word in (*noise, "Reading time", "Marvel"):
        assert word not in text, word


def test_a_promo_paragraph_at_the_end_of_the_article_is_dropped_even_inside_a_blockquote():
    promo = "<blockquote><p>Want more io9 news? Check out <a href='/best'>the best movies and TV shows</a> and <a href='/books'>upcoming books</a> on your radar.</p></blockquote>"
    text = extract_main_content(
        giz(f"<p>{LONG}</p><p>{LONG}</p>{promo}"), "https://x.example.com/p"
    )
    assert text and "본문 문장입니다" in text and "Want more" not in text and "radar" not in text


@pytest.mark.parametrize(
    "promo",
    [
        "Read more about this topic on our site.",
        "Sign up for our newsletter to get updates.",
        "Check out our other stories today.",
        "Subscribe to our channel for more videos.",
    ],
)
def test_promo_openers_at_the_very_end_are_dropped_but_not_in_the_middle(promo):
    end = clean(f"<p>{LONG}</p><p>{promo}</p>")
    assert promo.split()[0] not in end or promo not in end
    middle = clean(f"<p>{LONG}</p><p>{promo}</p><p>{LONG}</p><p>{LONG}</p><p>{LONG}</p>")
    assert promo in middle  # 글 가운데의 같은 문장은 본문일 수 있다


def test_lead_furniture_before_the_first_real_paragraph_is_dropped():
    lead = (
        "<p>InfoQ HomepageNewsGitHub Actions Runner Controller 0.15.0 Targets Reliability at Scale</p>"
        "<div>DevOps</div><h1>GitHub Actions Runner Controller 0.15.0 Targets Reliability at Scale</h1>"
        "<div>Oct 20, 2026 3 min read</div><div>Listen to this article - 0:00</div>"
        "<div>Audio ready to play</div><div>0:00</div><div>0:00</div><div>Reading list</div>"
    )
    text = clean(
        f"{lead}<p>{LONG}</p><p>둘째 문단입니다.</p>",
        "GitHub Actions Runner Controller 0.15.0 Targets Reliability at Scale",
    )
    assert "본문 문장입니다" in text and "둘째 문단" in text
    for noise in (
        "InfoQ",
        "DevOps",
        "min read",
        "Listen to this",
        "Audio ready",
        "0:00",
        "Reading list",
        "Runner Controller",
    ):
        assert noise not in text, noise


def test_a_short_real_first_sentence_is_not_mistaken_for_furniture():
    text = clean(f"<p>이 글은 짧은 첫 문장으로 시작합니다.</p><p>{LONG}</p>")
    assert "짧은 첫 문장" in text


def test_short_labels_after_the_first_real_text_are_kept():
    text = clean(f"<p>{LONG}</p><h3>소제목</h3><p>이어지는 문단입니다.</p><div>짧은 표 제목</div>")
    assert "소제목" in text and "짧은 표 제목" in text  # 앞머리(첫 본문 이전)에서만 군더더기로 본다


def test_a_header_with_an_image_keeps_the_image():
    text = clean(
        f"<div>Reading list</div><div><img src='https://cdn.example.com/a.png' alt='그림'><span>캡션</span></div><p>{LONG}</p>"
    )
    assert "https://cdn.example.com/a.png" in text and "Reading list" not in text


def test_the_same_paragraph_twice_is_kept_once():
    teaser = "An effective board should challenge the forces shaping decision-making at your company, not reinforce them."
    text = clean(f"<div class='dek'><p>{teaser}</p></div><p>{teaser}</p><p>{LONG}</p>")
    assert text.count("An effective board") == 1


def test_short_repeated_lines_are_not_treated_as_duplicates():
    text = clean(f"<p>{LONG}</p><p>네.</p><p>네.</p>")
    assert text.count("네.") == 2


@pytest.mark.parametrize(
    "cls",
    [
        "crumbs",
        "notice",
        "dropdown",
        "reading-list",
        "event__list-box",
        "recorded",
        "typo-eyebrow-2",
        "excerpt",
        "post-excerpt",
        "post-meta",
    ],
)
def test_blocks_with_ui_class_names_from_real_sites_are_dropped(cls):
    text = clean(f"<p>{LONG}</p><div class='{cls}'><p>UI 군더더기 {cls}</p></div>")
    assert "UI 군더더기" not in text and "본문 문장입니다" in text


@pytest.mark.parametrize("marker", ["See more presentations with transcripts", "Recorded at:"])
def test_infoq_style_closing_labels_cut_the_rest(marker):
    text = clean(f"<p>{LONG}</p><p>{LONG}</p><p>{marker}</p><p>Oct 20, 2026</p><p>by</p>")
    assert "본문 문장입니다" in text and "Oct 20, 2026" not in text and marker not in text


def test_the_choice_descends_by_the_plain_score_so_a_boosted_wrapper_does_not_win():
    # article/main 가산점이 붙은 바깥 덩어리가 본문 블록(점수 0.85 이상)을 가리지 못한다
    html = page(
        f"<main><div class='head'><p>머리 영역 문장입니다. 짧은 소개글 하나.</p></div><div class='body'><p>{LONG}</p></div></main>"
    )
    text = extract_main_content(html, "https://x.example.com/")
    assert text and "머리 영역" not in text and "본문 문장입니다" in text


@pytest.mark.parametrize(
    "inline",
    [
        "<i>Daredevil: Born Again</i>",
        "<a href='/s'>Born Again</a>",
        "<strong>Season 3</strong>",
        "<em>The Cycle</em>",
        "<span>Karen Page</span>",
        "<code>ARC</code>",
    ],
)
def test_a_short_inline_element_at_the_start_of_the_first_paragraph_is_part_of_the_text(inline):
    text = clean(
        f"<p>The news that {inline} would end came as a shock to fans of the show. {LONG}</p>"
    )
    label = re.sub(r"<[^>]+>", "", inline)
    assert f"The news that {label}" in re.sub(r"<[^>]+>", "", text)


def test_inline_text_that_starts_a_paragraph_is_kept_even_before_any_other_text():
    text = clean(f"<p><em>Daredevil: Born Again</em> would end with season three. {LONG}</p>")
    assert "Daredevil: Born Again" in text


def test_a_category_span_in_the_same_block_as_the_text_is_removed_and_the_image_stays():
    block = (
        "<div><span class='cat'><a href='/c/tv'>Television</a></span>"
        f"<figure><img src='https://cdn.example.com/hero.jpg' alt=''></figure><p>{LONG}</p></div>"
    )
    html = extract_main_content(page(f"<main>{block}</main>"), "https://x.example.com/p") or ""
    assert "Television" not in re.sub(r"<[^>]+>", " ", html)
    assert "https://cdn.example.com/hero.jpg" in html


def test_a_bare_url_after_only_short_blocks_does_not_remove_the_whole_text():
    """주소 줄 앞이 처음까지 짧은 덩어리뿐이면 본문이 통째로 사라지므로 주소 줄만 뺀다."""
    paras = [("가나다 " * 30) + f"끝{n}." for n in range(3)]
    html = page(
        "<article>" + "".join(f"<p>{para}</p>" for para in paras) + ""
        "<p><a href='https://a.example.com/x'>https://a.example.com/x</a></p></article>"
    )
    text = extract_main_content(html, "https://x.example.com/post")
    assert text is not None and all(para in text for para in paras)
    assert "a.example.com" not in text


def test_the_walk_back_stops_at_a_long_paragraph_and_at_the_size_budget():
    paras = [("가나다 " * 47) + f"끝{n}." for n in range(5)]  # 약 190자: 600자 안에서 셋까지 빠진다
    shorts = "".join(f"<p>{para}</p>" for para in paras)
    html = page(
        f"<article><p>{LONG}</p>{shorts}"
        "<p><a href='https://a.example.com/x'>https://a.example.com/x</a></p></article>"
    )
    text = extract_main_content(html, "https://x.example.com/post")
    assert text is not None and "본문 문장입니다" in text and "a.example.com" not in text
    assert [para in text for para in paras] == [True, True, False, False, False]


NAVER_SHELL = (
    "<script language='JavaScript'>\n\ttop.location.replace('https:\\/\\/m.blog.naver.com"
    "\\/PostView.naver?blogId=a&logNo=1');\n</script>"
)


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        (NAVER_SHELL, "https://m.blog.naver.com/PostView.naver?blogId=a&logNo=1"),
        ("<script>window.location.href = '/next';</script>", "https://a.example.com/next"),
        ('<script>location = "https://b.example.com/x"</script>', "https://b.example.com/x"),
        ('<meta http-equiv="refresh" content="0; url=/moved">', "https://a.example.com/moved"),
        ("<p>그냥 짧은 글입니다.</p>", None),
        ("<script>location.replace('javascript:alert(1)')</script>", None),
        ("<script>location.replace('/x')</script>" + "x" * MAX_SHELL_LENGTH, None),
    ],
)
def test_a_short_shell_page_that_only_redirects_gives_its_target(html, expected):
    assert find_page_redirect(html, "https://a.example.com/post") == expected


def sentences(tag, count):
    return " ".join(
        f"{tag} {n}번째로 나오는 문장이고 다른 문장과 겹치지 않도록 길게 씁니다."
        for n in range(count)
    )


def test_the_coverage_is_the_share_of_rss_sentences_found_in_the_extracted_text():
    reference = f"<p>{sentences('가', 4)}</p>"
    assert reference_coverage(reference, f"<p>{sentences('가', 4)}</p>") == 1.0
    assert reference_coverage(reference, f"<p>{sentences('가', 2)}</p>") == 0.5
    assert reference_coverage(reference, "<p>전혀 다른 글</p>") == 0.0


def test_a_short_rss_body_is_not_compared():
    assert reference_coverage("<p>짧은 요약</p>", "<p>아무 글</p>") is None
    assert reference_coverage("<p>" + "가 " * 80 + "</p>", "<p>아무 글</p>") is None  # 문장이 없다


@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        (sentences("전", 12), True),
        (sentences("전", 12) + " […]", False),
        (sentences("전", 12) + " Read more", False),
        (sentences("전", 12) + "...", False),
        (sentences("전", 2), False),
    ],
)
def test_the_rss_body_is_complete_only_when_long_and_not_cut_off(reference, expected):
    assert reference_is_complete(f"<p>{reference}</p>") is expected


def test_a_page_whose_text_never_reaches_the_rss_is_returned_with_the_best_coverage():
    reference = f"<p>{sentences('RSS', 8)}</p>"
    html = page(f"<article><p>{sentences('딴', 8)}</p></article>")
    result = extract_article(html, "https://x.example.com/post", "", reference)
    assert result is not None and result.coverage == 0.0
    assert extract_article(html, "https://x.example.com/post").coverage is None
    assert extract_article("", "https://x.example.com/post", "", reference) is None
