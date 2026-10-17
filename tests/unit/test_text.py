import pytest

from rss_hub.domain.text import fallback_excerpt, strip_html, truncate_with_ellipsis


def test_strip_html_removes_tags_and_keeps_text():
    assert strip_html("<p>Hello <b>world</b></p>") == "Hello world"


@pytest.mark.parametrize("value", [None, "", "<p></p>"])
def test_strip_html_returns_empty_for_empty_input(value):
    assert strip_html(value) == ""


def test_strip_html_drops_attributes_and_urls_inside_tags():
    assert strip_html('<img src="https://x.com/movie.jpg"> text') == " text"


def test_fallback_excerpt_cuts_at_300_and_adds_dots():
    text = "가" * 500
    assert fallback_excerpt(text) == "가" * 300 + "..."


def test_fallback_excerpt_keeps_short_text_untouched():
    assert fallback_excerpt("가" * 300) == "가" * 300
    assert fallback_excerpt("짧은 글") == "짧은 글"


def test_truncate_keeps_text_that_fits():
    assert truncate_with_ellipsis("abc", 3) == "abc"


def test_truncate_result_never_exceeds_limit_and_ends_with_ellipsis():
    out = truncate_with_ellipsis("a" * 100, 10)
    assert len(out) == 10
    assert out.endswith("…")


@pytest.mark.parametrize(("limit", "expected"), [(0, ""), (-5, ""), (1, "…")])
def test_truncate_handles_tiny_limits(limit, expected):
    assert truncate_with_ellipsis("abcdef", limit) == expected
