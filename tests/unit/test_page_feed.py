"""웹페이지 구독: 글 목록 페이지에서 글(제목, 주소, 날짜)을 뽑는 규칙."""

# ruff: noqa: E501  (HTML 견본은 한 줄이 읽기 쉽다)

import pytest

from rss_hub.domain.page_feed import MAX_ITEMS, MIN_ITEMS, extract_page_items, split_leading_date
from tests.fakes.page_html import BASE, listing, sample_items

PAGE = f"{BASE}/news"

COMSCORE = """<html><head><title>Blog - Comscore, Inc.</title></head><body>
<nav><a href="/Insights/Blog">Blog</a><a href="/ger/Insights/Blog">Deutsch</a><a href="/Insights/Blog/Menu-Link-Should-Not-Count">Menu</a></nav>
<h2>Latest</h2>
<div><a href="/Insights/Blog/The-Slow-Death-of-Age-and-Gender" title="Blog: The Slow Death of Age and Gender"><img alt="/Insights/Blog/The-Slow-Death-of-Age-and-Gender"></a>
<a href="/Insights/Blog/The-Slow-Death-of-Age-and-Gender" title="Read more: The Slow Death of Age and Gender">Read more</a></div>
<div><a href="/Insights/Blog/Summer-Signals" title="Summer Signals: Comscore’s Reading Guide to the Season That Was">Blog Summer Signals: Comscore’s Reading Guide to the Season That Was</a></div>
<a href="/Insights/Blog/The-New-Front-Door-to-Financial-Decision-Making" title="Blog: The New Front Door to Financial Decision Making: How AI Is Reshaping Credit Card Acquisition">29 jul 2026 The New Front Door to Financial Decision Making:...</a>
<a href="/Insights/Blog/Marketings-Next-Era" title="Blog: Marketing's Next Era: How AI and Creators are reshaping the Consumer Journey">9 jul 2026 Marketing's Next Era: How AI and Creators are...</a>
<ul><li><a href="/Insights/Blog?page=2">2</a></li><li><a href="/Insights/Blog/tag/ai">AI</a></li></ul>
<footer><a href="/Insights/Blog/Footer-Link-Should-Not-Count">Footer</a></footer></body></html>"""


def titles(listing_result):
    return [item.title for item in listing_result.items]


def urls(listing_result):
    return [item.url for item in listing_result.items]


# ---------- 실제 모양(comscore 블로그)의 견본 ----------


def test_the_comscore_style_page_gives_clean_titles_dates_and_only_real_posts():
    result = extract_page_items(COMSCORE, "https://www.comscore.com/Insights/Blog")
    assert result.title == "Blog - Comscore, Inc."
    assert [(i.date, i.title) for i in result.items] == [
        (None, "The Slow Death of Age and Gender"),
        (None, "Summer Signals: Comscore’s Reading Guide to the Season That Was"),
        (
            "2026-07-29",
            "The New Front Door to Financial Decision Making: How AI Is Reshaping Credit Card Acquisition",
        ),
        (
            "2026-07-09",
            "Marketing's Next Era: How AI and Creators are reshaping the Consumer Journey",
        ),
    ]
    assert all(u.startswith("https://www.comscore.com/Insights/Blog/") for u in urls(result))


# ---------- 글로 보는 링크와 거르는 링크 ----------


def test_posts_under_the_list_path_are_found_in_page_order_without_the_noise():
    result = extract_page_items(listing(sample_items(5)), PAGE)
    assert [i.url for i in result.items] == [f"{BASE}/news/post-{n}" for n in range(1, 6)]
    assert titles(result)[0] == "새 소식 1번: 목록에 나오는 글의 제목입니다"
    shown = " ".join(urls(result))
    for noise in ("menu-link", "footer-link", "page", "tag", "category", "elsewhere", "about"):
        assert noise not in shown


@pytest.mark.parametrize(
    "tag",
    [
        "nav",
        "footer",
        "aside",
        "form",
        "button",
        "select",
        "script",
        "style",
        "noscript",
        "template",
    ],
)
def test_links_inside_menus_footers_forms_and_scripts_are_skipped(tag):
    extra = f'<{tag}><a href="/news/inside-{tag}">{tag} 안의 링크 제목입니다</a></{tag}>'
    result = extract_page_items(listing(sample_items(4), extra=extra), PAGE)
    assert f"inside-{tag}" not in " ".join(urls(result))


def test_links_inside_a_header_element_are_kept_because_posts_often_have_one():
    extra = '<article><header><a href="/news/in-header">헤더 안에 있는 글 제목입니다</a></header></article>'
    assert any(
        u.endswith("/in-header")
        for u in urls(extract_page_items(listing(sample_items(3), extra=extra), PAGE))
    )


@pytest.mark.parametrize(
    "href",
    [
        "javascript:alert(1)",
        "mailto:a@b.example.com",
        "ftp://blog.example.com/news/x",
        "#top",
        "https://user:pw@blog.example.com/news/secret",
        "https://other.example.org/news/x",
    ],
)
def test_unusable_addresses_and_other_sites_are_never_posts(href):
    extra = f'<a href="{href}">이런 링크는 글이 아닙니다 제목 길이는 충분합니다</a>'
    result = extract_page_items(listing(sample_items(4), extra=extra), PAGE)
    assert len(result.items) == 4


@pytest.mark.parametrize(
    "path",
    [
        "/news/tag/ai",
        "/news/category/x",
        "/news/page/2",
        "/news/author/kim",
        "/news/feed",
        "/news/search",
        "/news/photo.jpg",
        "/news/report.pdf",
    ],
)
def test_taxonomy_pagination_media_and_file_links_are_not_posts(path):
    extra = f'<a href="{path}">분류나 파일 링크입니다 제목 길이는 충분합니다</a>'
    assert len(extract_page_items(listing(sample_items(3), extra=extra), PAGE).items) == 3


def test_the_list_page_itself_and_its_query_variants_are_not_posts():
    extra = '<a href="/news">목록으로 돌아가기 링크입니다 제목 길이</a><a href="/news?page=2">다음 쪽 목록 링크입니다 제목 길이</a>'
    assert len(extract_page_items(listing(sample_items(3), extra=extra), PAGE).items) == 3


def test_www_and_plain_host_are_the_same_site():
    html = listing(sample_items(3), base="https://www.blog.example.com").replace(
        'href="/news/', 'href="https://blog.example.com/news/'
    )
    assert len(extract_page_items(html, "https://www.blog.example.com/news").items) == 3


def test_tracking_parameters_fragments_and_trailing_slashes_make_the_same_post():
    extra = '<a href="/news/post-1/?utm_source=x&fbclid=y#comments">같은 글의 다른 링크 모양입니다 제목 길이</a>'
    result = extract_page_items(listing(sample_items(3), extra=extra), PAGE)
    assert urls(result).count(f"{BASE}/news/post-1") == 1 and len(result.items) == 3


def test_a_real_query_parameter_is_kept_because_it_may_identify_the_post():
    html = '<a href="/news?id=1">첫째 글 제목은 충분히 깁니다 정말로</a><a href="/news?id=2">둘째 글 제목은 충분히 깁니다 정말로</a><a href="/news?id=3">셋째 글 제목은 충분히 깁니다 정말로</a>'
    result = extract_page_items(f"<body>{html}</body>", f"{BASE}/")
    assert result.items == () or all("id=" in u for u in urls(result))


# ---------- 목록 경로를 못 쓸 때의 대체 규칙 ----------


def test_when_the_list_is_the_site_front_page_the_biggest_group_of_same_parent_links_is_used():
    posts = "".join(
        f'<a href="/posts/{n}-slug">홈 화면에 있는 글 {n}번의 제목입니다</a>' for n in range(1, 6)
    )
    other = '<a href="/products/a-thing">상품 하나 제목입니다 꽤 깁니다</a><a href="/products/b-thing">상품 둘 제목입니다 꽤 깁니다</a>'
    result = extract_page_items(
        f"<body><nav><a href='/posts/1-slug'>메뉴</a></nav>{posts}{other}</body>", f"{BASE}/"
    )
    assert len(result.items) == 5 and all("/posts/" in u for u in urls(result))


def test_fewer_than_the_minimum_posts_is_not_a_list():
    assert extract_page_items(listing(sample_items(MIN_ITEMS - 1)), PAGE).items == ()


def test_a_page_without_posts_gives_nothing_and_still_reports_its_title():
    result = extract_page_items(
        "<html><head><title> 빈  페이지 </title></head><body><p>글 없음</p></body></html>", PAGE
    )
    assert result.items == () and result.title == "빈 페이지"


def test_at_most_the_maximum_number_of_posts_is_returned_in_order():
    result = extract_page_items(listing(sample_items(MAX_ITEMS + 25)), PAGE)
    assert len(result.items) == MAX_ITEMS and result.items[0].url.endswith("/post-1")


def test_broken_html_and_an_unusable_page_address_do_not_crash():
    assert extract_page_items("<a href='/news/x'>제목" + "<div" * 50, PAGE).items == ()
    assert extract_page_items(listing(sample_items(4)), "ftp://x.example.com/").items == ()
    assert extract_page_items(listing(sample_items(4)), "not a url").items == ()


# ---------- 제목 고르기 ----------


def test_the_longest_untruncated_text_wins_among_the_links_of_one_post():
    html = (
        '<a href="/news/a-post" title="이 글의 전체 제목은 이렇게 깁니다 정말로 깁니다"><img alt="그림"></a>'
        '<a href="/news/a-post">이 글의 전체 제목은 이렇게 깁니다 정말...</a><a href="/news/a-post">더 보기</a>'
        '<a href="/news/b-post">둘째 글 제목입니다 길이는 충분합니다</a><a href="/news/c-post">셋째 글 제목입니다 길이는 충분합니다</a>'
    )
    assert (
        titles(extract_page_items(f"<body>{html}</body>", PAGE))[0]
        == "이 글의 전체 제목은 이렇게 깁니다 정말로 깁니다"
    )


def test_a_truncated_title_is_used_only_when_nothing_better_exists():
    html = "".join(
        f'<a href="/news/p{n}">잘린 제목이 유일한 후보입니다 {n}번 글...</a>' for n in range(3)
    )
    assert titles(extract_page_items(f"<body>{html}</body>", PAGE))[0].endswith("...")


@pytest.mark.parametrize(
    "generic", ["Read more", "더보기", "자세히 보기", "Continue reading", "more", "abc"]
)
def test_generic_link_texts_are_not_titles(generic):
    html = f'<a href="/news/x">{generic}</a>' + "".join(
        f'<a href="/news/p{n}">진짜 제목 {n}번 글입니다 정말로</a>' for n in range(3)
    )
    assert all(
        generic.lower() not in t.lower()
        for t in titles(extract_page_items(f"<body>{html}</body>", PAGE))
    )


def test_alt_text_and_aria_labels_can_be_titles_but_address_like_texts_cannot():
    html = (
        '<a href="/news/img"><img alt="이미지 설명이 제목인 글입니다 길게"></a>'
        '<a href="/news/aria" aria-label="접근성 이름이 제목인 글입니다 길게">&nbsp;</a>'
        '<a href="/news/path">/news/path</a><a href="/news/plain">그냥 글자가 제목인 글입니다 길게</a>'
    )
    assert titles(extract_page_items(f"<body>{html}</body>", PAGE)) == [
        "이미지 설명이 제목인 글입니다 길게",
        "접근성 이름이 제목인 글입니다 길게",
        "그냥 글자가 제목인 글입니다 길게",
    ]


@pytest.mark.parametrize(
    ("raw", "date", "rest"),
    [
        ("2026-10-16 제목입니다", "2026-10-16", "제목입니다"),
        ("2026.10.16 | 제목입니다", "2026-10-16", "제목입니다"),
        ("2026/1/6 제목입니다", "2026-01-06", "제목입니다"),
        ("2026년 10월 16일 제목입니다", "2026-10-16", "제목입니다"),
        ("29 jul 2026 Title here", "2026-07-29", "Title here"),
        ("9 July 2026: Title here", "2026-07-09", "Title here"),
        ("Jul 9, 2026 Title here", "2026-07-09", "Title here"),
        ("Oct. 5 2026 Title here", "2026-10-05", "Title here"),
    ],
)
def test_a_date_in_front_of_the_text_is_split_off(raw, date, rest):
    assert split_leading_date(raw) == (date, rest)


@pytest.mark.parametrize(
    "raw",
    ["2026-13-40 제목", "31 feb 2026 Title", "제목 2026-10-16", "7/29/2026 Title", "그냥 제목"],
)
def test_an_invalid_ambiguous_or_trailing_date_is_left_alone(raw):
    assert split_leading_date(raw) == (None, raw)


def test_the_datetime_of_a_time_element_inside_the_link_gives_the_date():
    html = (
        '<a href="/news/t1">제목은 충분히 긴 글입니다 첫째 <time datetime="2026-10-16T09:00:00+09:00">오늘</time></a>'
        + "".join(f'<a href="/news/t{n}">제목은 충분히 긴 글입니다 {n}번째</a>' for n in (2, 3))
    )
    result = extract_page_items(f"<body>{html}</body>", PAGE)
    assert result.items[0].date == "2026-10-16" and result.items[1].date is None


def test_an_invalid_time_attribute_gives_no_date():
    html = '<a href="/news/t1">제목은 충분히 긴 글입니다 첫째 <time datetime="2026-99-99">?</time></a><a href="/news/t2">제목은 충분히 긴 글입니다 둘째</a><a href="/news/t3">제목은 충분히 긴 글입니다 셋째</a><a href="/news/t4">제목은 충분히 긴 글입니다 넷째 <time datetime="어제">?</time></a>'
    assert [i.date for i in extract_page_items(f"<body>{html}</body>", PAGE).items] == [
        None,
        None,
        None,
        None,
    ]


# ---------- 분류 이름 떼기 ----------


def test_the_section_name_in_front_of_titles_is_removed_with_or_without_a_colon():
    html = '<a href="/blog/a">Blog: 첫째 글의 제목은 이렇습니다</a><a href="/blog/b">Blog 둘째 글의 제목은 이렇습니다</a><a href="/blog/c">blogs - 셋째 글의 제목은 이렇습니다</a>'
    assert titles(extract_page_items(f"<body>{html}</body>", f"{BASE}/blog")) == [
        "첫째 글의 제목은 이렇습니다",
        "둘째 글의 제목은 이렇습니다",
        "셋째 글의 제목은 이렇습니다",
    ]


def test_a_title_that_would_become_too_short_keeps_its_section_name():
    html = '<a href="/blog/a">Blog: 짧음</a><a href="/blog/b">둘째 글의 제목은 이렇습니다 정말로</a><a href="/blog/c">셋째 글의 제목은 이렇습니다 정말로</a>'
    assert titles(extract_page_items(f"<body>{html}</body>", f"{BASE}/blog"))[0] == "Blog: 짧음"


def test_a_label_that_most_titles_share_is_removed_but_not_a_rare_one():
    common = "".join(
        f'<a href="/blog/c{n}">업데이트: {n}번째 글의 제목은 충분히 깁니다</a>' for n in range(4)
    )
    rare = '<a href="/blog/r1">업데이트: 첫째 글의 제목은 충분히 깁니다</a><a href="/blog/r2">둘째 글의 제목은 충분히 깁니다</a><a href="/blog/r3">셋째 글의 제목은 충분히 깁니다</a>'
    assert all(
        not t.startswith("업데이트")
        for t in titles(extract_page_items(f"<body>{common}</body>", f"{BASE}/x"))
    )
    assert titles(extract_page_items(f"<body>{rare}</body>", f"{BASE}/x"))[0].startswith("업데이트")


def test_a_long_label_before_a_colon_is_a_title_not_a_label():
    html = "".join(
        f'<a href="/blog/l{n}">아주 길어서 분류 이름이 아닌 앞부분이 있는 글: {n}번째 내용입니다</a>'
        for n in range(4)
    )
    assert all(
        t.startswith("아주 길어서")
        for t in titles(extract_page_items(f"<body>{html}</body>", f"{BASE}/blog"))
    )


# ---------- 깨진 입력에도 멈추지 않는다 ----------


@pytest.mark.parametrize(
    "anchor",
    [
        "<a>제목 없는 앵커 링크입니다 길게</a>",
        '<a href="">빈 주소 앵커 링크입니다 길게</a>',
        '<a href="   ">공백 주소 앵커 링크입니다 길게</a>',
        '<a name="x">이름만 있는 앵커입니다 길게</a>',
    ],
)
def test_anchors_without_an_address_are_ignored(anchor):
    assert len(extract_page_items(listing(sample_items(3), extra=anchor), PAGE).items) == 3


def test_an_address_that_cannot_be_parsed_is_skipped_and_the_rest_still_works():
    extra = '<a href="http://[broken/news/x">이런 주소는 해석할 수 없습니다 길게</a>'
    assert len(extract_page_items(listing(sample_items(3), extra=extra), PAGE).items) == 3
    assert extract_page_items(listing(sample_items(3)), "http://[broken/news").items == ()


def test_a_parser_that_raises_gives_an_empty_listing(monkeypatch):
    from rss_hub.domain import page_feed

    def boom(self, data):
        raise RuntimeError("파서 오류")

    monkeypatch.setattr(page_feed._PageParser, "feed", boom)
    assert extract_page_items(listing(sample_items(4)), PAGE).items == ()


def test_a_truncated_title_never_beats_a_complete_one_even_when_it_is_longer():
    html = (
        '<a href="/news/a" title="짧지만 완전한 제목입니다">이 글의 제목은 아주 길게 이어지다가 잘려서 끝나 버립니다 정말로 깁니다...</a>'
        '<a href="/news/b">둘째 글 제목입니다 길이는 충분합니다</a><a href="/news/c">셋째 글 제목입니다 길이는 충분합니다</a>'
    )
    assert titles(extract_page_items(f"<body>{html}</body>", PAGE))[0] == "짧지만 완전한 제목입니다"


def test_links_without_a_usable_title_do_not_count_toward_the_minimum_posts():
    html = '<a href="/news/a">진짜 제목 하나입니다 길게</a><a href="/news/b">진짜 제목 둘입니다 길게</a><a href="/news/c">Read more</a>'
    result = extract_page_items(f"<body>{html}</body>", PAGE)
    assert len(result.items) == 2  # 링크는 3개여도 글로 쓸 수 있는 것은 2개
