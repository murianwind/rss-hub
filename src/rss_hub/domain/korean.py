"""한국어 글 판별."""

import re

from rss_hub.domain.text import strip_html

KOREAN_RATIO_THRESHOLD = 0.1
_HANGUL = re.compile(r"[\uAC00-\uD7A3]")


def is_korean(text: str | None, threshold: float = KOREAN_RATIO_THRESHOLD) -> bool:
    """HTML을 제외한 텍스트에서 한글 비율이 threshold 이상이면 한국어 글로 본다."""
    plain = strip_html(text)
    if not plain:
        return False
    return len(_HANGUL.findall(plain)) / len(plain) >= threshold
