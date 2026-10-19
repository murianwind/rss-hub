"""주제 알림: 입력 규칙과 판별 규칙.

주제는 이름, 설명, 키워드, 웹훅으로 이루어진다. 글이 주제에 해당하려면 LLM이 그 주제를 골랐고,
키워드가 등록되어 있다면 제목이나 본문에 키워드가 하나라도 있어야 한다("LLM 확인 + 키워드 보완").
키워드가 먼저 후보를 거르고(`is_candidate`), LLM은 그 후보만 확인한다. LLM이 후보가 아닌 주제를
고르는 것(환각)은 구조적으로 불가능하다.
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
    enabled: bool


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
    return TopicFields(name=name, description=description, keywords=parse_keywords(keywords_text))


def is_candidate(topic: Topic, title: str, content_html: str) -> bool:
    """LLM에게 물어볼 후보인가: 켜져 있고, 키워드가 맞거나 키워드가 없는(LLM만으로 정하는) 주제."""
    if not topic.enabled:
        return False
    if not topic.keywords:
        return True
    return bool(find_keywords(title, content_html, split_keywords(topic.keywords)))


def match_topic(
    topic: Topic, llm_topic_ids: Collection[int] | None, title: str, content_html: str
) -> tuple[str, ...] | None:
    """해당하면 일치한 키워드(키워드가 없는 주제는 빈 튜플)를, 아니면 None을 돌려준다."""
    if not topic.enabled or llm_topic_ids is None or topic.id not in llm_topic_ids:
        return None
    if not topic.keywords:
        return ()
    hits = find_keywords(title, content_html, split_keywords(topic.keywords))
    return hits or None
