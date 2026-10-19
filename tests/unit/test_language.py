import pytest

from rss_hub.domain.language import detect_language


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("스프링 부트 4 마이그레이션 후기를 정리했다.", "ko"),
        ("Apple unveils the new iPhone with a bigger battery.", "en"),
        ("애플이 새 iPhone을 공개했다. The phone lasts longer.", "ko"),
        ("The new 스프링 release is out today for everyone to use.", "en"),
        ("これは日本語の文章です", None),
        ("12345 !!! ???", None),
        ("", None),
        ("   ", None),
    ],
)
def test_the_language_is_guessed_from_the_letters_or_left_unknown(text, expected):
    assert detect_language(text) == expected


def test_html_markup_is_not_counted():
    assert detect_language("<p class='korean-한글'>Plain English text here</p>") == "en"
