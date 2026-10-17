"""문자열을 다루는 작은 순수 함수."""

import re

_TAG = re.compile(r"<[^>]+>")

ELLIPSIS = "…"
EXCERPT_LIMIT = 300
EXCERPT_SUFFIX = "..."


def strip_html(text: str | None) -> str:
    """HTML 태그를 지우고 텍스트만 남긴다. 태그 안의 속성과 주소는 함께 사라진다."""
    if not text:
        return ""
    return _TAG.sub("", text)


def fallback_excerpt(plain: str, limit: int = EXCERPT_LIMIT) -> str:
    """요약에 끝까지 실패한 글의 대체 요약. 앞부분만 자르고 잘렸으면 말줄임표를 붙인다."""
    if len(plain) <= limit:
        return plain
    return plain[:limit] + EXCERPT_SUFFIX


def truncate_with_ellipsis(text: str, limit: int) -> str:
    """길이를 limit(말줄임표 포함) 이하로 줄인다. 줄였다면 …로 끝난다."""
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    return text[: limit - 1] + ELLIPSIS
