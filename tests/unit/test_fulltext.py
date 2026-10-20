"""원문 페이지에서 본문만 뽑는 규칙(광고, 메뉴, 댓글, 스크립트는 빼고 정제한다)."""

import time

import pytest

from rss_hub.domain.fulltext import MIN_TEXT_LENGTH, extract_main_content

LONG = "본문 문장입니다. " * 40  # 충분히 긴 본문


def page(body: str, head: str = "") -> str:
    return f"<!doctype html><html><head><title>t</title>{head}</head><body>{body}</body></html>"


def test_the_article_element_is_the_body_and_menus_footers_and_sidebars_are_dropped():
    html = page(
        f"<header><nav><a href='/'>홈</a></nav></header>"
        f"<article><h2>소제목</h2><p>{LONG}</p><p>둘째 문단</p></article>"
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
    html = page(f"<article><p>첫 줄<br/>둘째 줄</p><div/><p>{LONG}</p><hr/></article>")
    text = extract_main_content(html, "https://x.example.com/")
    assert text and "첫 줄" in text and "둘째 줄" in text and "본문 문장입니다" in text


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
