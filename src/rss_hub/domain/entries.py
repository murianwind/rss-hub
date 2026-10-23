"""피드 항목(entry)에서 글로 저장할 필드를 뽑는다."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from rss_hub.domain.text import clean_title, strip_html


@dataclass(frozen=True)
class ArticleFields:
    title: str
    link: str
    content_html: str
    published_raw: str


def _text(value: Any) -> str:
    return str(value).strip() if value else ""


def _body(entry: Mapping[str, Any]) -> str:
    """RSS 본문: summary(없으면 description)와 content 중 글자가 더 많은 쪽의 HTML 원본.

    Atom 피드는 잘린 요약(끝이 […])과 전체 본문(content)을 함께 보내기도 한다."""
    candidates = [_text(entry.get("summary") or entry.get("description"))]
    for part in entry.get("content") or ():
        candidates.append(_text(part.get("value")))
    return max(candidates, key=lambda html: len(strip_html(html)))


def extract_article_fields(entry: Mapping[str, Any]) -> ArticleFields:
    """제목, 링크, 본문(HTML 원본), 발행 시각 원문."""
    return ArticleFields(
        title=clean_title(_text(entry.get("title"))),
        link=_text(entry.get("link")),
        content_html=_body(entry),
        published_raw=str(entry.get("published") or entry.get("updated") or ""),
    )
