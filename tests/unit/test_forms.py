import pytest

from rss_hub.web.forms import id_or_none


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("7", 7),
        (" 12 ", 12),
        ("007", 7),
        ("", None),
        (None, None),
        ("abc", None),
        ("-3", None),
        ("1.5", None),
        ("²", None),  # isdigit()은 참이지만 int()가 예외를 내는 위첨자
    ],
)
def test_an_id_field_is_a_number_or_nothing(value, expected):
    assert id_or_none(value) == expected
