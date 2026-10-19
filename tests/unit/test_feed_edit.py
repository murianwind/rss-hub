import pytest

from rss_hub.domain.feed_edit import FeedEditError, validate_feed_edit


def error_of(**values):
    fields = {"name": "블로그", "emoji": "📢", "priority": "normal", "max_entries": ""} | values
    with pytest.raises(FeedEditError) as info:
        validate_feed_edit(**fields)
    return info.value.message


def edit(**values):
    fields = {"name": "블로그", "emoji": "📢", "priority": "normal", "max_entries": ""} | values
    return validate_feed_edit(**fields)


def test_valid_values_are_trimmed_and_a_blank_max_means_the_default():
    result = edit(name="  스프링 블로그  ", emoji=" 🧪 ", priority="every_slot", max_entries="")
    assert (result.name, result.emoji, result.poll_priority, result.max_entries) == (
        "스프링 블로그",
        "🧪",
        "every_slot",
        None,
    )


@pytest.mark.parametrize("text", ["1", "50", "500", " 120 "])
def test_a_max_between_one_and_five_hundred_is_accepted(text):
    assert edit(max_entries=text).max_entries == int(text)


@pytest.mark.parametrize("text", ["0", "501", "-5", "abc", "1.5", "１２"])
def test_other_max_values_are_refused(text):
    assert error_of(max_entries=text) == "최대 검사 항목 수는 1~500 사이의 숫자"


@pytest.mark.parametrize(
    ("name", "message"),
    [("", "이름이 필요함"), ("   ", "이름이 필요함"), ("가" * 201, "이름은 200자까지")],
)
def test_the_name_is_required_and_limited(name, message):
    assert error_of(name=name) == message


def test_a_two_hundred_character_name_is_fine():
    assert len(edit(name="가" * 200).name) == 200


@pytest.mark.parametrize(
    ("emoji", "message"),
    [
        ("", "머리말 이모지가 필요함"),
        ("   ", "머리말 이모지가 필요함"),
        ("가" * 9, "머리말 이모지는 8자까지"),
    ],
)
def test_the_emoji_is_required_and_short(emoji, message):
    assert error_of(emoji=emoji) == message


@pytest.mark.parametrize("priority", ["", "high", "EVERY_SLOT", "every-slot"])
def test_only_the_two_known_priorities_are_accepted(priority):
    assert error_of(priority=priority) == "점검 우선순위는 보통 또는 매 슬롯"
