import pytest

from rss_hub.domain.keywords import DEFAULT_OTT_KEYWORDS
from rss_hub.domain.topics import (
    MAX_KEYWORDS,
    Topic,
    TopicInputError,
    match_topic,
    parse_keywords,
    validate_topic_fields,
)


def topic(keywords=("netflix", "드라마"), *, enabled=True, topic_id=1):
    return Topic(topic_id, "OTT", "스트리밍", tuple(keywords), None, enabled)


def error_of(**fields):
    values = {"name": "게임", "description": "", "keywords_text": ""} | fields
    with pytest.raises(TopicInputError) as info:
        validate_topic_fields(**values)
    return info.value.message


# ---------- 키워드 입력 ----------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("netflix, 드라마, disney+", ("netflix", "드라마", "disney+")),
        ("netflix\n드라마\r\ndisney+", ("netflix", "드라마", "disney+")),
        ("  netflix  ,,  , 드라마 ,", ("netflix", "드라마")),
        ("Netflix, netflix, NETFLIX, 드라마", ("Netflix", "드라마")),
        ("넷플릭스，티빙", ("넷플릭스", "티빙")),  # 전각 쉼표
        ("", ()),
        (" \n ,, \n", ()),
    ],
)
def test_keywords_are_split_trimmed_and_deduplicated(text, expected):
    assert parse_keywords(text) == expected


def test_keywords_may_contain_spaces_inside_a_phrase():
    assert parse_keywords("hbo max, 디지털 공개") == ("hbo max", "디지털 공개")


def test_up_to_one_hundred_keywords_are_accepted_and_more_are_not():
    assert len(parse_keywords(",".join(f"k{i}" for i in range(MAX_KEYWORDS)))) == MAX_KEYWORDS
    with pytest.raises(TopicInputError) as info:
        parse_keywords(",".join(f"k{i}" for i in range(MAX_KEYWORDS + 1)))
    assert info.value.message == "키워드는 100개까지"


def test_a_keyword_may_be_forty_characters_but_not_more():
    assert parse_keywords("가" * 40) == ("가" * 40,)
    with pytest.raises(TopicInputError) as info:
        parse_keywords("가" * 41)
    assert info.value.message == "키워드는 40자까지"


# ---------- 주제 입력 ----------


def test_valid_fields_are_trimmed():
    fields = validate_topic_fields("  게임 할인  ", "  게임 가격 소식  ", "steam, 스팀")
    assert (fields.name, fields.description, fields.keywords) == (
        "게임 할인",
        "게임 가격 소식",
        ("steam", "스팀"),
    )


def test_the_description_and_keywords_are_optional():
    fields = validate_topic_fields("보안", "", "")
    assert (fields.description, fields.keywords) == ("", ())


@pytest.mark.parametrize(
    ("name", "message"),
    [("", "이름이 필요함"), ("   ", "이름이 필요함"), ("가" * 41, "이름은 40자까지")],
)
def test_the_name_is_required_and_limited(name, message):
    assert error_of(name=name) == message


def test_a_forty_character_name_is_fine():
    assert validate_topic_fields("가" * 40, "", "").name == "가" * 40


def test_the_description_is_limited_to_two_hundred_characters():
    assert validate_topic_fields("a", "가" * 200, "").description == "가" * 200
    assert error_of(description="가" * 201) == "설명은 200자까지"


# ---------- 주제 판별: LLM이 고르고 키워드가 보완한다 ----------


def test_the_llm_choice_and_a_keyword_hit_together_make_a_match():
    assert match_topic(topic(), {1}, "New Netflix drama", "") == ("netflix",)


def test_the_llm_choice_without_any_keyword_hit_is_not_a_match():
    assert match_topic(topic(), {1}, "Apple event recap", "") is None


def test_a_keyword_hit_without_the_llm_choice_is_not_a_match():
    assert match_topic(topic(), set(), "New Netflix drama", "") is None
    assert match_topic(topic(), {2, 3}, "New Netflix drama", "") is None


def test_an_article_without_a_summary_result_matches_nothing():
    assert match_topic(topic(), None, "New Netflix drama", "") is None


def test_a_topic_without_keywords_follows_the_llm_alone():
    assert match_topic(topic(()), {1}, "Anything at all", "") == ()
    assert match_topic(topic(()), set(), "Anything at all", "") is None


def test_a_disabled_topic_never_matches():
    assert match_topic(topic(enabled=False), {1}, "New Netflix drama", "") is None


def test_each_topic_is_judged_by_its_own_number():
    games = Topic(2, "게임", "", ("steam",), None, True)
    assert match_topic(games, {1}, "Steam sale", "") is None
    assert match_topic(games, {2}, "Steam sale", "") == ("steam",)


def test_keywords_match_the_visible_body_text_but_not_markup():
    body = '<p>New <b>trailer</b> released</p><img src="movie.jpg">'
    assert match_topic(topic(("trailer",)), {1}, "Weekend picks", body) == ("trailer",)
    assert match_topic(topic(("movie",)), {1}, "Weekend picks", body) is None


@pytest.mark.parametrize(
    ("title", "matched"),
    [
        ("A bottle of water", False),
        ("OTT 서비스", True),
        ("Disney+ announces", True),
        ("disney+x launch", False),
    ],
)
def test_the_word_rules_of_the_old_ott_check_still_apply(title, matched):
    result = match_topic(topic(("ott", "disney+")), {1}, title, "")
    assert (result is not None) is matched


def test_the_default_ott_keywords_work_as_a_topic():
    words = (*DEFAULT_OTT_KEYWORDS.ko, *DEFAULT_OTT_KEYWORDS.en)
    assert match_topic(topic(words), {1}, "스트리밍 서비스 요금", "") == ("스트리밍",)


# ---------- 키워드가 먼저 거른다(후보) ----------

from rss_hub.domain.topics import is_candidate  # noqa: E402


def test_a_topic_is_a_candidate_when_its_keywords_match():
    assert is_candidate(topic(), "New Netflix drama", "") is True
    assert is_candidate(topic(), "Weekend picks", "<p>A new 드라마 tonight</p>") is True


def test_a_topic_is_not_a_candidate_without_a_keyword_match():
    assert is_candidate(topic(), "Spring gardening", "<p>roses</p>") is False
    assert is_candidate(topic(), "Weekend picks", '<img src="x/netflix.jpg">') is False


def test_a_topic_without_keywords_is_always_a_candidate():
    assert is_candidate(topic(()), "Anything at all", "") is True


def test_a_disabled_topic_is_never_a_candidate():
    assert is_candidate(topic(enabled=False), "New Netflix drama", "") is False
    assert is_candidate(topic((), enabled=False), "Anything", "") is False


def test_candidates_follow_the_same_word_rules_as_the_final_check():
    candidate = topic(("ott", "disney+"))
    assert is_candidate(candidate, "A bottle of water", "") is False
    assert is_candidate(candidate, "OTT 서비스", "") is True
    assert is_candidate(candidate, "Disney+ announces", "") is True
