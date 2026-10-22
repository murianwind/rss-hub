"""글 페이지에서 발행일 찾기.

RSS와 달리 웹페이지 구독은 목록에 날짜가 없을 수 있어서, 글 페이지가 알려 주는 발행일을 찾아 쓴다.
찾는 순서: 메타 태그 → JSON-LD → time 태그 → 본문 위쪽의 날짜 글자. 찾지 못하면 None이다.
"""

import json
import re
from datetime import date, datetime, tzinfo
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser

from rss_hub.domain.page_feed import split_leading_date

MIN_YEAR = 1990  # 이보다 오래된 날짜는 잘못된 값(1970-01-01 같은)으로 본다
TEXT_NODES_SCANNED = 80  # 본문 위쪽에서 날짜 글자를 찾아볼 글자 조각 수
META_KEYS = frozenset(
    {
        "article:published_time",
        "og:article:published_time",
        "datepublished",
        "pubdate",
        "publishdate",
        "publish_date",
        "date",
        "dc.date",
        "dc.date.issued",
        "sailthru.date",
        "parsely-pub-date",
    }
)
_LABEL = re.compile(
    r"^(?:published|posted|updated|date)(?:\s+on)?\s*[:：]?\s*|^(?:게시일|작성일|발행일|등록일)\s*[:：]?\s*",
    re.I,
)
_HIDDEN_TAGS = frozenset({"script", "style", "noscript", "template"})


def _parse(raw: str, tz: tzinfo) -> date | None:
    """ISO 8601, RFC 822, 날짜만 있는 값을 서비스 시간대의 날짜로 바꾼다."""
    raw = raw.strip()
    moment: datetime | None = None
    try:
        moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            moment = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            moment = None
    if moment is None:
        found = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", raw)
        if found is None:
            return None
        try:
            return _valid(date(int(found.group(1)), int(found.group(2)), int(found.group(3))))
        except ValueError:
            return None
    if moment.tzinfo is not None:
        moment = moment.astimezone(tz)
    return _valid(moment.date())


def _valid(day: date) -> date | None:
    return day if day.year >= MIN_YEAR else None


class _Finder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: list[str] = []
        self.times: list[str] = []
        self.json_ld: list[str] = []
        self.texts: list[str] = []
        self._hidden = 0
        self._in_json_ld = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta":
            key = (
                values.get("property") or values.get("name") or values.get("itemprop") or ""
            ).lower()
            if key in META_KEYS and values.get("content"):
                self.meta.append(values["content"])
        elif tag == "time" and values.get("datetime"):
            self.times.append(values["datetime"])
        elif tag == "script" and "ld+json" in values.get("type", "").lower():
            self._in_json_ld = True
        if tag in _HIDDEN_TAGS:
            self._hidden += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _HIDDEN_TAGS and self._hidden:
            self._hidden -= 1
        if tag == "script":
            self._in_json_ld = False

    def handle_data(self, data: str) -> None:
        if self._in_json_ld:
            self.json_ld.append(data)
        elif not self._hidden and len(self.texts) < TEXT_NODES_SCANNED:
            text = " ".join(data.split())
            if text:
                self.texts.append(text)


def _json_ld_dates(blobs: list[str]) -> list[str]:
    found: list[str] = []
    for blob in blobs:
        try:
            data = json.loads(blob)
        except ValueError:
            found.extend(re.findall(r'"datePublished"\s*:\s*"([^"]+)"', blob))
            continue
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                value = node.get("datePublished")
                if isinstance(value, str):
                    found.append(value)
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)
    return found


def extract_published_date(html: str, tz: tzinfo) -> date | None:
    """글 페이지의 발행일(서비스 시간대 기준). 찾지 못하면 None."""
    finder = _Finder()
    try:
        finder.feed(html)
        finder.close()
    except Exception:  # 해석할 수 없는 HTML도 있다: 날짜 없음으로 처리한다
        return None
    for raw in (*finder.meta, *_json_ld_dates(finder.json_ld), *finder.times):
        day = _parse(raw, tz)
        if day is not None:
            return day
    for text in finder.texts:
        iso, _ = split_leading_date(_LABEL.sub("", text))
        if iso is not None:
            return _valid(date.fromisoformat(iso))
    return None
