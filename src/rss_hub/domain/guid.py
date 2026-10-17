"""글의 고유 식별자(GUID) 선택과 정규화."""

import hashlib
import urllib.parse
from collections.abc import Mapping
from typing import Any

# 네이버 블로그 등이 RSS로 접근할 때 붙이는 추적용 파라미터
TRACKING_PARAMS = ("fromRss", "trackingCode")


def normalize_guid(raw: str | None) -> str | None:
    """추적용 쿼리 파라미터를 지워서 같은 글이 같은 GUID가 되게 한다.

    기존 동작을 그대로 유지한다: 같은 이름의 파라미터가 여러 개면 첫 값만 남고,
    공백은 '+'로 인코딩된다. 해석할 수 없으면 원래 값을 돌려준다.
    """
    if not raw:
        return raw
    try:
        parsed = urllib.parse.urlparse(raw)
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        for name in TRACKING_PARAMS:
            query.pop(name, None)
        new_query = urllib.parse.urlencode({key: values[0] for key, values in query.items()})
        return urllib.parse.urlunparse(parsed._replace(query=new_query))
    except ValueError:
        return raw


def select_guid(entry: Mapping[str, Any]) -> str:
    """id → guid → link 순서로 고르고, 모두 없으면 제목과 요약의 해시를 쓴다."""
    raw = entry.get("id") or entry.get("guid") or entry.get("link")
    if not raw:
        text = (entry.get("title", "") + entry.get("summary", "")).encode("utf-8", "ignore")
        raw = hashlib.sha1(text).hexdigest()
    normalized = normalize_guid(str(raw))
    return normalized if normalized is not None else str(raw)
