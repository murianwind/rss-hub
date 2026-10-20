"""키워드 개선 제안: 사용자가 누른 "주제로"와 "싫어요"를 근거로 키워드를 더하거나 빼자고 제안한다.

- 더하기: "주제로"로 직접 넣은 글(키워드가 놓친 글)의 제목에서 둘 이상의 글에 공통으로 나오는 단어.
- 빼기: 자동으로 들어온 글 중 싫어요로 뺀 비율이 높은 키워드.
제안은 근거를 보여 주기만 하고, 키워드를 바꾸는 것은 사용자가 승인할 때뿐이다.
한국어 조사는 흔한 것만 떼어 내므로 완벽하지 않다(그래서 사람이 승인한다).
"""

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

MIN_SUPPORT = 2
MAX_SUGGESTIONS = 8
MIN_REJECTED = 2
MIN_REJECTED_RATIO = 0.5

STOP_WORDS = frozenset(
    {
        *("the", "an", "of", "to", "in", "on", "for", "and", "or", "is", "are", "was", "were"),
        *("with", "from", "by", "at", "as", "it", "its", "this", "that", "be", "has", "have"),
        *("will", "how", "why", "what", "who", "you", "your", "new", "after", "into", "about"),
    }
)
_WORD = re.compile(r"[0-9a-z가-힣+#]+")
_HANGUL = re.compile(r"[가-힣]")
_PARTICLES = (
    *("에서는", "에서", "으로", "에는", "까지", "부터", "에게", "한테", "처럼", "보다"),
    *("은", "는", "이", "가", "을", "를", "의", "에", "와", "과", "도", "로"),
)


@dataclass(frozen=True)
class AddSuggestion:
    keyword: str
    support: int  # 이 단어가 들어 있는 "주제로" 글 수
    against: int  # 이 단어가 들어 있는 "싫어요" 글 수
    examples: tuple[str, ...]


@dataclass(frozen=True)
class RemoveSuggestion:
    keyword: str
    rejected: int  # 이 키워드로 들어왔다가 싫어요로 뺀 글 수
    total: int  # 이 키워드로 자동으로 들어온 글 수


def _strip_particle(token: str) -> str:
    if not _HANGUL.search(token):
        return token
    for particle in _PARTICLES:
        if token.endswith(particle) and len(token) - len(particle) >= 2:
            return token[: -len(particle)]
    return token


def title_tokens(title: str) -> set[str]:
    """제목의 단어 집합(소문자, 조사 제거). 한 글자, 숫자만 있는 것, 흔한 영어 단어는 뺀다."""
    found: set[str] = set()
    for raw in _WORD.findall(title.lower()):
        token = _strip_particle(raw)
        if len(token) >= 2 and not token.isdigit() and token not in STOP_WORDS:
            found.add(token)
    return found


def suggest_additions(
    manual_titles: Sequence[str],
    rejected_titles: Sequence[str],
    existing_keywords: Sequence[str],
    *,
    min_support: int = MIN_SUPPORT,
    limit: int = MAX_SUGGESTIONS,
) -> list[AddSuggestion]:
    existing = [keyword.lower() for keyword in existing_keywords]
    manual = [(title, title_tokens(title)) for title in manual_titles]
    support = Counter(token for _, tokens in manual for token in tokens)
    against = Counter(token for title in rejected_titles for token in title_tokens(title))
    found = []
    for token, count in support.items():
        if count < min_support or count <= against[token]:
            continue
        if any(token in keyword or keyword in token for keyword in existing):
            continue
        examples = tuple(title for title, tokens in manual if token in tokens)[:3]
        found.append(AddSuggestion(token, count, against[token], examples))
    found.sort(key=lambda s: (-(s.support - s.against), -s.support, s.keyword))
    return found[:limit]


def suggest_removals(
    outcomes: Sequence[tuple[tuple[str, ...], bool]],
    *,
    min_rejected: int = MIN_REJECTED,
    min_ratio: float = MIN_REJECTED_RATIO,
) -> list[RemoveSuggestion]:
    total: Counter[str] = Counter()
    rejected: Counter[str] = Counter()
    for keywords, was_rejected in outcomes:
        for keyword in set(keywords):
            total[keyword] += 1
            rejected[keyword] += was_rejected
    found = [
        RemoveSuggestion(keyword, rejected[keyword], count)
        for keyword, count in total.items()
        if rejected[keyword] >= min_rejected and rejected[keyword] / count >= min_ratio
    ]
    found.sort(key=lambda s: (-s.rejected / s.total, -s.rejected, s.keyword))
    return found
