import pytest

from rss_hub.domain.topic_suggestions import suggest_additions, suggest_removals, title_tokens


def words(suggestions):
    return [s.keyword for s in suggestions]


# ---------- 제목에서 단어 뽑기 ----------


def test_tokens_are_lowercase_words_without_stop_words_or_numbers():
    assert title_tokens("The New Squid Game: Season 2 is Out!") == {
        "squid",
        "game",
        "season",
        "out",
    }


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("오징어 게임 시즌2 공개", {"오징어", "게임", "시즌2", "공개"}),
        ("넷플릭스가 새 시리즈를 공개했다", {"넷플릭스", "새", "시리즈", "공개했다"} - {"새"}),
        ("C++ and C# tips", {"c++", "c#", "tips"}),
        ("", set()),
        ("a b 1 22 ??", {"22"} - {"22"}),
    ],
)
def test_korean_particles_are_stripped_and_short_or_numeric_tokens_dropped(title, expected):
    assert title_tokens(title) == expected


# ---------- 키워드 추가 제안 ----------


def test_a_word_shared_by_at_least_two_manually_added_titles_is_suggested():
    manual = ["Squid Game season 2 trailer", "Squid Game cast revealed", "Another Squid Game clip"]
    found = suggest_additions(manual, [], ["netflix"])
    assert set(words(found)[:2]) == {"squid", "game"} and found[0].support == 3
    assert "trailer" not in words(found)  # 한 글에만 나온다


def test_a_word_in_a_single_title_is_not_enough():
    assert suggest_additions(["Squid Game news"], [], []) == []
    assert suggest_additions([], [], []) == []


def test_words_that_also_appear_in_rejected_titles_are_penalized_or_dropped():
    manual = ["Squid Game trailer", "Squid Game cast", "Gaming news"]
    rejected = ["Squid Game board game review", "Squid Game merch", "Game store sale"]
    found = suggest_additions(manual, rejected, [])
    assert "squid" not in words(found)  # 2 대 2라서 근거가 더 많다고 할 수 없다


def test_existing_keywords_and_their_overlaps_are_not_suggested_again():
    manual = ["Netflix drama premieres", "Netflix drama returns", "Netflixing drama night"]
    assert "netflix" not in words(suggest_additions(manual, [], ["netflix"]))
    assert "drama" not in words(suggest_additions(manual, [], ["Drama"]))
    assert "dram" not in words(suggest_additions(manual, [], []))


def test_a_token_that_contains_or_is_contained_in_an_existing_keyword_is_skipped():
    manual = ["OTT service launch", "OTTs and streaming", "Streaming launch dates"]
    assert "ott" not in words(suggest_additions(manual, [], ["ott"]))
    assert "otts" not in words(suggest_additions(manual, [], ["ott"]))


def test_suggestions_are_ranked_and_limited_and_carry_examples():
    manual = [f"alpha beta gamma delta epsilon zeta eta theta iota kappa item{n}" for n in range(3)]
    found = suggest_additions(manual, [], [], limit=4)
    assert len(found) == 4 and words(found) == sorted(words(found))[:4]
    assert all(len(s.examples) <= 3 and s.support == 3 for s in found)


def test_korean_titles_work_the_same_way():
    manual = ["오징어 게임 시즌2 예고편", "오징어 게임 출연진 공개", "신작 오징어 소식"]
    found = suggest_additions(manual, [], [])
    assert words(found)[0] == "오징어"


def test_the_minimum_support_can_be_changed():
    assert words(suggest_additions(["Squid Game news"], [], [], min_support=1)) == [
        "game",
        "news",
        "squid",
    ]


# ---------- 키워드 제거 제안 ----------


def test_a_keyword_that_most_of_its_matches_were_rejected_for_is_suggested_for_removal():
    outcomes = [
        (("trailer",), True),
        (("trailer",), True),
        (("trailer", "netflix"), False),
        (("netflix",), False),
        (("netflix",), False),
    ]
    found = suggest_removals(outcomes)
    assert [(s.keyword, s.rejected, s.total) for s in found] == [("trailer", 2, 3)]


def test_two_rejections_are_needed_and_the_ratio_must_reach_half():
    assert suggest_removals([(("a",), True), (("a",), False)]) == []
    assert (
        suggest_removals(
            [(("a",), True), (("a",), True), (("a",), False), (("a",), False), (("a",), False)]
        )
        == []
    )
    assert [s.keyword for s in suggest_removals([(("a",), True)] * 2 + [(("a",), False)] * 2)] == [
        "a"
    ]


def test_removal_suggestions_are_ranked_by_how_often_they_misled():
    outcomes = [(("x",), True)] * 2 + [(("y",), True)] * 3 + [(("y",), False)]
    assert [s.keyword for s in suggest_removals(outcomes)] == ["x", "y"]


def test_no_outcomes_no_removal_suggestions():
    assert suggest_removals([]) == []
