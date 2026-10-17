"""LLM 응답 검증: 채택해도 되는 응답인지 판정하고, 아니면 이유를 돌려준다."""

import json
import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from enum import StrEnum

DEFAULT_FORBIDDEN_PHRASES = ("We need to translate", "Korean summary")
FORMAT_MARKERS = ("TITLE:", "SUMMARY:")

_HANJA = re.compile(r"[\u4E00-\u9FFF]")
_FENCE = re.compile(r"^```[a-zA-Z0-9]*\s*\n?(.*?)\n?```$", re.DOTALL)


class RejectReason(StrEnum):
    NOT_JSON = "not_json"
    MISSING_FIELD = "missing_field"
    EMPTY_TITLE = "empty_title"
    EMPTY_SUMMARY = "empty_summary"
    HANJA = "hanja"
    REASONING_LEAK = "reasoning_leak"
    FORMAT_MARKER = "format_marker"
    TRUNCATED = "truncated"


@dataclass(frozen=True)
class SummaryDraft:
    title_ko: str
    summary_ko: str
    topics: tuple[int, ...]  # LLM이 고른 주제 번호(알 수 없는 번호는 걸러낸다)


@dataclass(frozen=True)
class ValidationResult:
    draft: SummaryDraft | None = None
    reason: RejectReason | None = None

    @property
    def ok(self) -> bool:
        return self.draft is not None


def find_bad_content(
    text: str, forbidden_phrases: Sequence[str] = DEFAULT_FORBIDDEN_PHRASES
) -> RejectReason | None:
    """형식 표지, 사고 과정 문구, 한자가 섞여 있으면 그 이유를, 깨끗하면 None을 돌려준다."""
    if any(marker in text for marker in FORMAT_MARKERS):
        return RejectReason.FORMAT_MARKER
    if any(phrase in text for phrase in forbidden_phrases):
        return RejectReason.REASONING_LEAK
    if _HANJA.search(text):
        return RejectReason.HANJA
    return None


def _load_json_object(raw: str) -> dict[str, object] | None:
    text = raw.strip()
    fenced = _FENCE.match(text)
    if fenced:
        text = fenced.group(1).strip()
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _topic_numbers(value: object, valid: Collection[int]) -> tuple[int, ...]:
    """요청한 주제의 번호만 남긴다. 숫자 문자열은 받고 참/거짓은 받지 않는다."""
    if not isinstance(value, list):
        return ()
    numbers: list[int] = []
    for item in value:
        if isinstance(item, bool):
            continue
        if isinstance(item, int):
            number = item
        elif isinstance(item, str) and item.strip().isdigit():
            number = int(item.strip())
        else:
            continue
        if number in valid and number not in numbers:
            numbers.append(number)
    return tuple(numbers)


def validate_summary(
    raw: str,
    finish_reason: str | None,
    forbidden_phrases: Sequence[str] = DEFAULT_FORBIDDEN_PHRASES,
    valid_topic_ids: Collection[int] = (),
) -> ValidationResult:
    """응답 원문을 검사해서 채택 가능하면 draft를, 아니면 거부 이유를 돌려준다."""
    if finish_reason == "length":
        return ValidationResult(reason=RejectReason.TRUNCATED)

    data = _load_json_object(raw)
    if data is None:
        return ValidationResult(reason=RejectReason.NOT_JSON)

    title, summary = data.get("title_ko"), data.get("summary_ko")
    if not isinstance(title, str) or not isinstance(summary, str):
        return ValidationResult(reason=RejectReason.MISSING_FIELD)
    title, summary = title.strip(), summary.strip()
    if not title:
        return ValidationResult(reason=RejectReason.EMPTY_TITLE)
    if not summary:
        return ValidationResult(reason=RejectReason.EMPTY_SUMMARY)

    for text in (title, summary):
        bad = find_bad_content(text, forbidden_phrases)
        if bad is not None:
            return ValidationResult(reason=bad)

    topics = _topic_numbers(data.get("topics"), valid_topic_ids)
    return ValidationResult(draft=SummaryDraft(title_ko=title, summary_ko=summary, topics=topics))
