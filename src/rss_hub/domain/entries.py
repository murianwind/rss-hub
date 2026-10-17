"""피드 항목(entry)에서 글로 저장할 필드를 뽑는다."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ArticleFields:
    title: str
    link: str
    content_html: str
    published_raw: str


def _text(value: Any) -> str:
    return str(value).strip() if value else ""


def extract_article_fields(entry: Mapping[str, Any]) -> ArticleFields:
    """제목, 링크, 본문(summary, 없으면 description의 HTML 원본), 발행 시각 원문."""
    return ArticleFields(
        title=_text(entry.get("title")),
        link=_text(entry.get("link")),
        content_html=_text(entry.get("summary") or entry.get("description")),
        published_raw=str(entry.get("published") or entry.get("updated") or ""),
    )
