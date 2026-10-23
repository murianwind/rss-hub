"""문자열을 다루는 작은 순수 함수."""

import html
import re

_TAG = re.compile(r"<[^>]+>")
# 세미콜론이 있는 문자 참조만 푼다("R&D", "Q&A"처럼 세미콜론 없는 글자는 건드리지 않는다)
_ENTITY = re.compile(r"&(?:#\d{1,7}|#[xX][0-9a-fA-F]{1,6}|[A-Za-z][A-Za-z0-9]{1,31});")
MAX_UNESCAPE_PASSES = 3  # &amp;amp;middot;처럼 여러 번 감싼 글자도 풀되 무한히 풀지는 않는다
_SPACES = re.compile(r"[\s\u00a0\u3000]+")
_INVISIBLE = re.compile(r"[\u200b-\u200d\u2060\ufeff\u00ad\x00-\x08\x0b-\x1f\x7f]")
FULLWIDTH_FIRST, FULLWIDTH_LAST, FULLWIDTH_OFFSET = 0xFF01, 0xFF5E, 0xFEE0

ELLIPSIS = "…"
EXCERPT_LIMIT = 300
EXCERPT_SUFFIX = "..."


def unescape_entities(text: str) -> str:
    """&middot; 같은 문자 참조를 글자로 푼다. 이중으로 감싼 것도 풀고, 못 푸는 것은 둔다."""
    for _ in range(MAX_UNESCAPE_PASSES):
        decoded = _ENTITY.sub(lambda found: html.unescape(found.group(0)), text)
        if decoded == text:
            break
        text = decoded
    return text


def strip_html(text: str | None) -> str:
    """HTML 태그를 지우고 사람이 읽는 텍스트만 남긴다(문자 참조는 글자로 푼다).

    태그 안의 속성과 주소는 함께 사라진다."""
    if not text:
        return ""
    return unescape_entities(_TAG.sub("", text)).replace("\u00a0", " ")


def clean_title(text: str | None) -> str:
    """제목, 사이트 이름 같은 한 줄 글자를 다듬는다.

    문자 참조를 풀고, 전각 영문자, 숫자, 부호는 반각으로 바꾸고, 전각 공백과 줄바꿈 없는 공백은
    보통 공백으로, 보이지 않는 글자(너비 없는 공백, 제어 문자)는 지우고, 공백은 하나로 줄인다.
    한글 자모와 가운뎃점(·, ㆍ)처럼 호환 정규화가 모양을 바꾸는 글자는 그대로 둔다."""
    if not text:
        return ""
    plain = _INVISIBLE.sub("", unescape_entities(text))
    narrowed = "".join(
        chr(ord(c) - FULLWIDTH_OFFSET) if FULLWIDTH_FIRST <= ord(c) <= FULLWIDTH_LAST else c
        for c in plain
    )
    return _SPACES.sub(" ", narrowed).strip()


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
