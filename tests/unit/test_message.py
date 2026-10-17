from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from rss_hub.domain.message import (
    MAX_MESSAGE_LENGTH,
    article_url,
    build_message,
    format_published_time,
)

SEOUL = ZoneInfo("Asia/Seoul")
LINK = "https://rss.example.com/a/123"


def build(**overrides):
    args = {
        "site": "Blog",
        "emoji": "📢",
        "title": "새 아이폰 배터리",
        "summary": "배터리가 커졌다.",
        "published": "2026-10-16T14:32:00+09:00",
        "link_url": LINK,
        "tz": SEOUL,
    }
    args.update(overrides)
    return build_message(**args)


def test_message_layout():
    assert build() == (
        "📢 **[Blog] 새 글 알림** `14:32`\n"
        "**새 아이폰 배터리**\n"
        "배터리가 커졌다.\n"
        f"🔗 [글 읽기]({LINK})"
    )


@pytest.mark.parametrize(
    ("published", "expected"),
    [
        ("2026-10-16T14:32:00+09:00", "14:32"),
        ("2026-10-16T05:32:00+00:00", "14:32"),
        ("2026-10-16T14:32:00", "14:32"),
        (datetime(2026, 10, 16, 5, 32, tzinfo=UTC), "14:32"),
        ("", None),
        (None, None),
        ("해석할 수 없는 값", None),
    ],
)
def test_format_published_time(published, expected):
    assert format_published_time(published, SEOUL) == expected


def test_header_has_no_time_when_published_is_unknown():
    assert build(published=None).splitlines()[0] == "📢 **[Blog] 새 글 알림**"


@pytest.mark.parametrize(("site", "emoji"), [("Gizmodo", "🧪"), ("Blog", "📢")])
def test_header_uses_feed_emoji(site, emoji):
    assert build(site=site, emoji=emoji).startswith(f"{emoji} **[{site}] 새 글 알림**")


def test_long_summary_is_shortened_and_link_survives():
    message = build(summary="가" * 2500)
    assert len(message) <= MAX_MESSAGE_LENGTH
    assert message.endswith(f"🔗 [글 읽기]({LINK})")
    summary_line = message.splitlines()[2]
    assert summary_line.endswith("…")
    assert "**[Blog] 새 글 알림**" in message


def test_huge_title_is_shortened_and_link_survives():
    message = build(title="제" * 3000)
    assert len(message) <= MAX_MESSAGE_LENGTH
    assert message.endswith(f"🔗 [글 읽기]({LINK})")


def test_short_message_is_not_touched_by_length_limit():
    message = build()
    assert "…" not in message


def test_original_link_is_not_part_of_the_message():
    assert "example.com/original" not in build()


def test_custom_max_length_is_respected():
    message = build(summary="가" * 500, max_length=200)
    assert len(message) <= 200
    assert message.endswith(f"🔗 [글 읽기]({LINK})")


def test_article_url():
    assert article_url("https://rss.example.com", 123) == "https://rss.example.com/a/123"
    assert article_url("https://example.com/rss", 7) == "https://example.com/rss/a/7"


def test_when_even_the_fixed_parts_do_not_fit_the_summary_is_dropped_but_link_stays():
    message = build(summary="가" * 500, max_length=10)
    lines = message.splitlines()
    assert len(lines) == 3  # 머리말, 제목, 링크
    assert lines[-1] == f"🔗 [글 읽기]({LINK})"
