"""키워드 일치 규칙: 주제 판별에서 LLM이 고른 글을 키워드로 한 번 더 확인한다(LLM 환각 방지)."""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache

from rss_hub.domain.text import strip_html

_HANGUL = re.compile(r"[가-힣]")


@dataclass(frozen=True)
class KeywordSet:
    """한국어 키워드는 부분 문자열로, 영문 키워드는 단어 단위로 일치시킨다."""

    ko: tuple[str, ...]
    en: tuple[str, ...]


DEFAULT_OTT_KEYWORDS = KeywordSet(
    ko=(
        "드라마", "방송", "예능", "영화", "스트리밍", "디지털 공개", "개봉", "방영", "프리미어",
        "시즌", "에피소드", "예고편", "단편", "애니메이션", "넷플릭스", "디즈니+", "티빙", "웨이브",
        "쿠팡플레이", "왓챠", "애플tv+", "프라임비디오",
    ),
    en=(
        "ott", "vod", "netflix", "disney+", "hbo max", "hbo original", "hbo series", "prime video",
        "amazon prime", "apple tv+", "apple tv", "peacock", "paramount+", "movie", "film",
        "horror film", "horror movie", "short film", "animated film", "theatrical release",
        "animation series", "streaming service", "tv show", "tv series", "new season",
        "final season", "season", "series", "anime", "manga", "season 1", "season 2", "season 3",
        "season 4", "season 5", "release date", "premiere", "trailer", "blu-ray", "bluray",
        "dvd release", "4k ultra hd", "steelbook", "physical release", "digital release",
        "movie release", "film release", "box office", "sequel", "prequel", "spin-off", "reboot",
        "pixar",
    ),
)  # fmt: skip


@lru_cache(maxsize=8)
def _english_pattern(keywords: tuple[str, ...]) -> re.Pattern[str] | None:
    """영문 키워드를 "앞뒤에 영문자, 숫자, _가 붙지 않은" 경우에만 일치시키는 정규식.

    \\b 대신 이 규칙을 쓰는 이유: "disney+"처럼 기호로 끝나는 키워드는 \\b로는 뒤에 공백이 올 때
    일치하지 않는다. 한글은 영문 단어의 일부로 보지 않아서 "OTT서비스"는 일치한다.
    """
    if not keywords:
        return None
    alternatives = "|".join(re.escape(k) for k in keywords)
    return re.compile(rf"(?<![A-Za-z0-9_])(?:{alternatives})(?![A-Za-z0-9_])")


def split_keywords(words: Sequence[str]) -> KeywordSet:
    """등록한 키워드를 한글이 든 것(부분 문자열 일치)과 아닌 것(단어 단위 일치)으로 나눈다."""
    ko = tuple(w for w in words if _HANGUL.search(w))
    return KeywordSet(ko=ko, en=tuple(w for w in words if not _HANGUL.search(w)))


def find_keywords(
    title: str, content_html: str, keywords: KeywordSet = DEFAULT_OTT_KEYWORDS
) -> tuple[str, ...]:
    """제목과 본문(HTML 제거 후)에서 일치한 키워드. 없으면 빈 튜플."""
    text = f"{title} {strip_html(content_html)}".lower()
    found = [keyword for keyword in keywords.ko if keyword.lower() in text]
    pattern = _english_pattern(tuple(k.lower() for k in keywords.en))
    if pattern:
        found.extend(dict.fromkeys(match.group(0) for match in pattern.finditer(text)))
    return tuple(found)


def passes_keyword_gate(
    title: str, content_html: str, keywords: KeywordSet = DEFAULT_OTT_KEYWORDS
) -> bool:
    """제목과 본문(HTML 제거 후)에 키워드가 하나라도 있는지."""
    return bool(find_keywords(title, content_html, keywords))
