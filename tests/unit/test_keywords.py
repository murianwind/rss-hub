import pytest

from rss_hub.domain.keywords import (
    DEFAULT_OTT_KEYWORDS,
    KeywordSet,
    find_keywords,
    passes_keyword_gate,
    split_keywords,
)


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("New Netflix drama", True),
        ("Apple event recap", False),
        ("스트리밍 서비스 요금", True),
        ("movie night", True),
        ("Season finale", True),
        ("filmmaker interview", False),
        ("seasoning tips", False),
    ],
)
def test_keyword_gate_basic(title, expected):
    assert passes_keyword_gate(title, "") is expected


@pytest.mark.parametrize("title", ["A bottle of water", "Lotto results", "gotta love it"])
def test_ott_abbreviation_does_not_match_inside_words(title):
    assert passes_keyword_gate(title, "") is False


def test_ott_abbreviation_matches_as_a_word():
    assert passes_keyword_gate("OTT 요금제 비교", "") is True
    assert passes_keyword_gate("the OTT market", "") is True


def test_english_keyword_next_to_korean_text_still_matches():
    # 한글은 영문 단어의 일부로 보지 않는다 (예: "OTT서비스", "movie를")
    assert passes_keyword_gate("OTT서비스 요금", "") is True
    assert passes_keyword_gate("신작 movie를 봤다", "") is True


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Disney+ announces a new slate", True),
        ("Paramount+ pricing", True),
        ("Apple TV+ renewals", True),
        ("disney+x launch", False),
        ("(Disney+)", True),
    ],
)
def test_keywords_ending_with_plus(title, expected):
    assert passes_keyword_gate(title, "") is expected


@pytest.mark.parametrize(
    "content",
    ['<img src="https://x.com/movie.jpg"> text', '<a class="trailer-link">text</a>'],
)
def test_words_inside_html_markup_are_ignored(content):
    assert passes_keyword_gate("Apple event recap", content) is False


def test_words_in_visible_text_are_found():
    assert passes_keyword_gate("Weekend picks", "<p>New <b>trailer</b> released today</p>") is True


def test_matching_is_case_insensitive():
    assert passes_keyword_gate("NETFLIX", "") is True


def test_korean_keywords_match_as_substrings():
    assert passes_keyword_gate("신작드라마추천", "") is True


def test_custom_keywords():
    keywords = KeywordSet(ko=(), en=("stage play",))
    assert passes_keyword_gate("Stage play adaptation announced", "", keywords) is True
    assert passes_keyword_gate("New Netflix drama", "", keywords) is False


def test_default_keywords_do_not_contain_the_substring_prone_abbreviation_in_korean_list():
    assert "ott" not in DEFAULT_OTT_KEYWORDS.ko
    assert "ott" in DEFAULT_OTT_KEYWORDS.en


def test_empty_english_keyword_list_only_uses_korean_keywords():
    keywords = KeywordSet(ko=("드라마",), en=())
    assert passes_keyword_gate("Netflix", "", keywords) is False
    assert passes_keyword_gate("새 드라마", "", keywords) is True


@pytest.mark.parametrize(
    "title", ["Scott said hello", "a bigmovie night", "xnetflix tips", "preseason notes"]
)
def test_keyword_at_the_end_of_a_longer_word_does_not_match(title):
    # 앞에 글자가 붙은 경우: Scott(…ott), bigmovie(…movie), preseason(…season)
    assert passes_keyword_gate(title, "") is False


def test_keyword_at_the_start_of_a_longer_word_does_not_match():
    assert passes_keyword_gate("Ottawa weather", "") is False
    assert passes_keyword_gate("movies tonight", "") is False


def test_find_keywords_returns_what_matched_in_the_order_korean_then_english():
    found = find_keywords("New Netflix 드라마 trailer", "", DEFAULT_OTT_KEYWORDS)
    assert found == ("드라마", "netflix", "trailer")


def test_find_keywords_reports_each_english_keyword_once():
    assert find_keywords("movie movie MOVIE night", "", KeywordSet(ko=(), en=("movie",))) == (
        "movie",
    )


def test_find_keywords_finds_nothing_in_markup():
    html = '<img src="https://x.com/movie.jpg"><a class="trailer-link">text</a>'
    assert find_keywords("Apple event recap", html, DEFAULT_OTT_KEYWORDS) == ()


def test_find_keywords_reads_the_visible_text_of_the_body():
    assert find_keywords("Weekend picks", "<p>New <b>trailer</b> today</p>") == ("trailer",)


def test_registered_keywords_are_split_by_whether_they_contain_hangul():
    keywords = split_keywords(["드라마", "Netflix", "디즈니+", "disney+", "OTT서비스"])
    assert keywords.ko == ("드라마", "디즈니+", "OTT서비스")
    assert keywords.en == ("Netflix", "disney+")


def test_an_empty_registered_list_matches_nothing():
    assert split_keywords([]) == KeywordSet(ko=(), en=())
    assert find_keywords("Netflix", "", split_keywords([])) == ()
