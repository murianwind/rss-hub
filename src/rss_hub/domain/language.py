"""글의 언어 추정(한국어/영어). 글 영역에 lang을 붙여서 브라우저의 페이지 번역이 동작하게 한다."""

import re

_TAGS = re.compile(r"<[^>]*>")
_HANGUL = re.compile(r"[\u3131-\u318e\uac00-\ud7a3]")
_LATIN = re.compile(r"[A-Za-z]")
KOREAN_SHARE = 0.2  # 한글과 영문 글자 중 한글이 이 비율 이상이면 한국어로 본다
MIN_LETTERS = 4


def detect_language(text: str) -> str | None:
    """'ko', 'en' 또는 알 수 없으면 None. 일본어, 중국어 같은 다른 문자는 판단하지 않는다."""
    plain = _TAGS.sub(" ", text)
    hangul = len(_HANGUL.findall(plain))
    latin = len(_LATIN.findall(plain))
    total = hangul + latin
    if total < MIN_LETTERS:
        return None
    return "ko" if hangul / total >= KOREAN_SHARE else "en"
