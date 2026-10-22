"""주제 알림: 입력 규칙과 판별 규칙.

주제는 이름, 키워드, 웹훅, (선택) LLM이 읽는 설명으로 이루어진다. 키워드는 필수다.
글의 제목이나 본문에 키워드가 하나라도 있어야 후보가 되고(`is_candidate`), OpenRouter 키가 있으면
LLM이 그 후보만 설명을 보고 최종 확인한다. LLM이 후보가 아닌 주제를 고르는 것(환각)은 구조적으로
불가능하다. 키가 없으면 키워드만으로 판정한다. 키워드가 없는 옛 주제는 판정에서 빠진다.
"""

import re
from collections.abc import Collection
from dataclasses import dataclass

from rss_hub.domain.keywords import find_keywords, split_keywords

MAX_TOPICS = 20
MAX_NAME_LENGTH = 40
MAX_DESCRIPTION_LENGTH = 200
MAX_KEYWORDS = 100
MAX_KEYWORD_LENGTH = 40

_SEPARATORS = re.compile(r"[,，\r\n]+")


class TopicInputError(Exception):
    """사용자가 입력한 주제 값이 규칙에 맞지 않는다. message는 화면에 그대로 보여 줄 수 있다."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class Topic:
    id: int
    name: str
    description: str
    keywords: tuple[str, ...]
    webhook_id: int | None


@dataclass(frozen=True)
class TopicFields:
    name: str
    description: str
    keywords: tuple[str, ...]


def parse_keywords(text: str) -> tuple[str, ...]:
    """쉼표나 줄바꿈으로 구분한 키워드. 공백을 다듬고 대소문자 구분 없이 중복을 없앤다."""
    seen: set[str] = set()
    keywords: list[str] = []
    for piece in _SEPARATORS.split(text):
        keyword = piece.strip()
        if not keyword or keyword.lower() in seen:
            continue
        if len(keyword) > MAX_KEYWORD_LENGTH:
            raise TopicInputError(f"키워드는 {MAX_KEYWORD_LENGTH}자까지")
        seen.add(keyword.lower())
        keywords.append(keyword)
    if len(keywords) > MAX_KEYWORDS:
        raise TopicInputError(f"키워드는 {MAX_KEYWORDS}개까지")
    return tuple(keywords)


def validate_topic_fields(name: str, description: str, keywords_text: str) -> TopicFields:
    name = name.strip()
    description = description.strip()
    if not name:
        raise TopicInputError("이름이 필요함")
    if len(name) > MAX_NAME_LENGTH:
        raise TopicInputError(f"이름은 {MAX_NAME_LENGTH}자까지")
    if len(description) > MAX_DESCRIPTION_LENGTH:
        raise TopicInputError(f"설명은 {MAX_DESCRIPTION_LENGTH}자까지")
    keywords = parse_keywords(keywords_text)
    if not keywords:
        raise TopicInputError("키워드가 필요함")
    return TopicFields(name=name, description=description, keywords=keywords)


def is_candidate(topic: Topic, title: str, content_html: str) -> bool:
    """후보인가: 제목이나 본문에 키워드가 하나라도 있다. 키워드가 없는 옛 주제는 후보가 아니다."""
    if not topic.keywords:
        return False
    return bool(find_keywords(title, content_html, split_keywords(topic.keywords)))


def match_topic(
    topic: Topic, llm_topic_ids: Collection[int] | None, title: str, content_html: str
) -> tuple[str, ...] | None:
    """해당하면 일치한 키워드를, 아니면 None을 돌려준다."""
    if llm_topic_ids is None or topic.id not in llm_topic_ids or not topic.keywords:
        return None
    hits = find_keywords(title, content_html, split_keywords(topic.keywords))
    return hits or None
