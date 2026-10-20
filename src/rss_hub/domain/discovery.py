"""피드 자동 탐색: 웹페이지가 알려 주는 피드 링크 찾기, 가져오기 실패 이유 설명."""

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

FEED_TYPES = frozenset({"application/rss+xml", "application/atom+xml"})
MAX_LINKS = 10


@dataclass(frozen=True)
class FeedLink:
    url: str
    title: str


class _LinkParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self._base = base_url
        self.links: list[FeedLink] = []
        self._seen: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "link" or len(self.links) >= MAX_LINKS:
            return
        values = {key.lower(): (value or "") for key, value in attrs}
        if "alternate" not in values.get("rel", "").lower().split():
            return
        if values.get("type", "").split(";")[0].strip().lower() not in FEED_TYPES:
            return
        href = values.get("href", "").strip()
        if not href:
            return
        try:
            url = urljoin(self._base, href)
            parts = urlsplit(url)
        except ValueError:
            return
        if parts.scheme not in ("http", "https") or not parts.netloc or url in self._seen:
            return
        self._seen.add(url)
        self.links.append(FeedLink(url=url, title=values.get("title", "").strip()))


def find_feed_links(html: str, base_url: str) -> list[FeedLink]:
    """<link rel="alternate" type="application/rss+xml|atom+xml">로 알려 준 피드(최대 10개)."""
    parser = _LinkParser(base_url)
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # 깨진 HTML에서도 지금까지 찾은 것은 돌려준다
        pass
    return parser.links


def describe_fetch_failure(reason: str) -> str:
    """수집기가 알려 준 실패 분류를 사용자에게 보여 줄 문구로. 주소는 넣지 않는다."""
    if reason == "ForbiddenAddress":
        return "사설망·내부 주소는 허용하지 않음"
    if reason == "NotAFeed":
        return "피드가 아닙니다"
    if reason == "NoItems":
        return "글 목록을 찾지 못했습니다(사이트 구조가 바뀌었을 수 있습니다)"
    if reason == "TooLarge":
        return "응답이 너무 큽니다"
    if reason.startswith("HTTP "):
        return f"주소를 열지 못했습니다({reason})"
    if reason in ("ConnectTimeout", "ReadTimeout", "Timeout"):
        return "응답이 없습니다(시간 초과)"
    if reason == "ConnectionError":
        return "주소에 연결하지 못했습니다"
    if reason == "SSLError":
        return "보안 연결(HTTPS)을 확인하지 못했습니다"
    if re.fullmatch(
        r"[A-Za-z][A-Za-z0-9_.]{0,39}", reason
    ):  # 분류 이름(예: 예외 이름)만 그대로 보여 준다
        return f"가져오지 못했습니다({reason})"
    return "가져오지 못했습니다"  # 주소나 긴 글이 섞인 사유는 보여 주지 않는다
