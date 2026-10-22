"""글 페이지의 발행일 찾기: 메타, JSON-LD, time 태그, 본문 글자와 잘못된 값."""

from datetime import date, timedelta, timezone

import pytest

from rss_hub.domain.page_date import extract_published_date

KST = timezone(timedelta(hours=9))


def page(head="", body=""):
    return f"<html><head>{head}</head><body>{body}</body></html>"


def meta(content, key="article:published_time"):
    return f'<meta property="{key}" content="{content}">'


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-09-28", date(2026, 9, 28)),
        ("2026-09-28T09:00:00+09:00", date(2026, 9, 28)),
        ("2026-09-27T20:30:00Z", date(2026, 9, 28)),  # UTC 밤은 서비스 시간대로는 다음 날
        ("2026-09-28T23:30:00", date(2026, 9, 28)),  # 시간대가 없으면 그대로
        ("Mon, 28 Sep 2026 10:00:00 +0900", date(2026, 9, 28)),
        ("2026/9/28", date(2026, 9, 28)),
    ],
)
def test_meta_dates_in_common_formats(raw, expected):
    assert extract_published_date(page(meta(raw)), KST) == expected


@pytest.mark.parametrize("raw", ["", "어제", "2026-13-45", "1970-01-01", "1989-12-31"])
def test_unusable_meta_dates_are_ignored(raw):
    assert extract_published_date(page(meta(raw)), KST) is None


def test_other_meta_keys_work_and_unrelated_ones_do_not():
    assert extract_published_date(page(meta("2026-09-28", "og:article:published_time")), KST)
    assert extract_published_date(page(meta("2026-09-28", "description")), KST) is None


def test_json_ld_object_list_and_nested_graph():
    one = '{"@type":"Article","datePublished":"2026-09-28"}'
    graph = '{"@graph":[{"@type":"WebSite"},{"@type":"Article","datePublished":"2026-09-28"}]}'
    listed = '[{"@type":"Thing"},{"datePublished":"2026-09-28"}]'
    for blob in (one, graph, listed):
        head = f'<script type="application/ld+json">{blob}</script>'
        assert extract_published_date(page(head), KST) == date(2026, 9, 28)


def test_broken_json_ld_falls_back_to_a_pattern_search():
    head = '<script type="application/ld+json">{"datePublished": "2026-09-28", oops}</script>'
    assert extract_published_date(page(head), KST) == date(2026, 9, 28)


def test_json_ld_without_a_date_string_is_ignored():
    head = '<script type="application/ld+json">{"datePublished": 5}</script>'
    assert extract_published_date(page(head), KST) is None


def test_the_first_usable_time_tag_wins_and_invalid_ones_are_skipped():
    body = '<time datetime="soon">곧</time><time datetime="2026-09-28">9월 28일</time>'
    assert extract_published_date(page(body=body), KST) == date(2026, 9, 28)


def test_meta_beats_json_ld_beats_time_beats_text():
    head = (
        meta("2026-01-01")
        + '<script type="application/ld+json">{"datePublished":"2026-02-02"}</script>'
    )
    body = '<time datetime="2026-03-03">x</time><p>April 4, 2026</p>'
    assert extract_published_date(page(head, body), KST) == date(2026, 1, 1)
    assert extract_published_date(page(body=body), KST) == date(2026, 3, 3)
    assert extract_published_date(page(body="<p>April 4, 2026</p>"), KST) == date(2026, 4, 4)


@pytest.mark.parametrize(
    "text",
    [
        "September 28, 2026",
        "Posted on September 28, 2026",
        "Published: Sep 28, 2026",
        "28 September 2026",
        "2026.09.28",
        "2026년 9월 28일",
        "게시일: 2026년 9월 28일",
        "작성일 2026-09-28",
    ],
)
def test_visible_dates_near_the_top_of_the_page(text):
    assert extract_published_date(page(body=f"<p>{text}</p>"), KST) == date(2026, 9, 28)


def test_dates_inside_scripts_and_styles_are_not_text():
    body = "<script>var d='September 28, 2026'</script><style>/* 2026-09-28 */</style><p>안녕</p>"
    assert extract_published_date(page(body=body), KST) is None


def test_a_page_without_any_date_gives_none():
    assert extract_published_date(page(body="<p>날짜가 없는 글입니다</p>"), KST) is None


def test_an_impossible_visible_date_is_ignored():
    assert extract_published_date(page(body="<p>February 31, 2026</p>"), KST) is None


def test_a_visible_date_before_the_minimum_year_is_ignored():
    assert extract_published_date(page(body="<p>January 1, 1970</p>"), KST) is None


def test_only_the_first_text_pieces_are_scanned():
    filler = "".join(f"<p>문단 {n}</p>" for n in range(100))
    assert extract_published_date(page(body=filler + "<p>September 28, 2026</p>"), KST) is None


def test_whitespace_between_tags_is_not_a_text_piece():
    html = "<html>\n <body>\n  <p>\n   September 28, 2026\n  </p>\n </body>\n</html>"
    assert extract_published_date(html, KST) == date(2026, 9, 28)


def test_an_html_the_parser_cannot_handle_gives_none(monkeypatch):
    def boom(self, data):
        raise AssertionError("깨진 HTML")

    monkeypatch.setattr("rss_hub.domain.page_date._Finder.feed", boom)
    assert extract_published_date("<p>September 28, 2026</p>", KST) is None
