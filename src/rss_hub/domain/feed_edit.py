"""피드 편집 입력 규칙: 이름, 머리말 이모지, 점검 우선순위, 최대 검사 항목 수."""

from dataclasses import dataclass

from rss_hub.domain.schedule import PRIORITY_EVERY_SLOT, PRIORITY_NORMAL

MAX_NAME_LENGTH = 200
MAX_EMOJI_LENGTH = 8
MAX_ENTRIES_LIMIT = 500


class FeedEditError(Exception):
    """입력이 규칙에 맞지 않는다. message는 화면에 그대로 보여 줄 수 있다."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class FeedEdit:
    name: str
    emoji: str
    poll_priority: str
    max_entries: int | None  # None이면 설정의 기본값을 쓴다


def validate_feed_edit(name: str, emoji: str, priority: str, max_entries: str) -> FeedEdit:
    name, emoji, max_text = name.strip(), emoji.strip(), max_entries.strip()
    if not name:
        raise FeedEditError("이름이 필요함")
    if len(name) > MAX_NAME_LENGTH:
        raise FeedEditError(f"이름은 {MAX_NAME_LENGTH}자까지")
    if not emoji:
        raise FeedEditError("머리말 이모지가 필요함")
    if len(emoji) > MAX_EMOJI_LENGTH:
        raise FeedEditError(f"머리말 이모지는 {MAX_EMOJI_LENGTH}자까지")
    if priority not in (PRIORITY_NORMAL, PRIORITY_EVERY_SLOT):
        raise FeedEditError("점검 우선순위는 보통 또는 매 슬롯")
    limit: int | None = None
    if max_text:
        if (
            not (max_text.isascii() and max_text.isdigit())
            or not 1 <= int(max_text) <= MAX_ENTRIES_LIMIT
        ):
            raise FeedEditError(f"최대 검사 항목 수는 1~{MAX_ENTRIES_LIMIT} 사이의 숫자")
        limit = int(max_text)
    return FeedEdit(name=name, emoji=emoji, poll_priority=priority, max_entries=limit)
