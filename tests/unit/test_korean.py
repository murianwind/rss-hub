import pytest

from rss_hub.domain.korean import is_korean


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("가" + "a" * 8, True),
        ("가" + "a" * 9, True),  # 정확히 10%
        ("가" + "a" * 10, False),  # 약 9.1%
        ("hello world", False),
        ("", False),
        (None, False),
        ("<p></p>", False),
    ],
)
def test_korean_ratio_threshold(text, expected):
    assert is_korean(text) is expected


def test_html_tags_do_not_count_toward_length():
    assert is_korean("<div class='aaaaaaaaaaaaaaaaaa'>가</div>") is True


def test_custom_threshold():
    assert is_korean("가" + "a" * 9, threshold=0.5) is False
