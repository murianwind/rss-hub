"""웹페이지 구독: RSS가 없는 사이트의 글 목록 페이지에서 글(제목, 주소, 날짜)을 뽑는다.

표준 라이브러리만 쓴다. 규칙(위에서부터 먼저 걸리는 것):

1. 목록 페이지 주소의 경로 아래에 있는 같은 사이트 링크를 글로 본다
   (예: 목록이 /Insights/Blog 이면 /Insights/Blog/글이름). 3개 미만이면 같은 상위 경로를 가진
   링크가 가장 많은 묶음을 글로 본다(목록이 사이트 맨 앞이거나 글이 다른 경로에 있는 경우).
2. 메뉴, 푸터, 사이드, 폼, 스크립트 안의 링크와 태그, 분류, 쪽 번호, 작성자, 검색 링크,
   이미지와 문서 파일은 뺀다. 다른 사이트의 링크, 계정 정보가 든 주소, http(s)가 아닌 주소도 뺀다.
3. 같은 글에 링크가 여러 개(이미지, 제목, "더 보기")면 하나로 합치고, 제목은 앵커 글자, title 속성,
   aria-label, 이미지 설명 중에서 잘리지 않은 가장 긴 것을 고른다. 앞에 붙은 날짜와 분류 이름
   (예: "29 jul 2026 ", "Blog: ")은 제목에서 뺀다.
"""

import re
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

MAX_ITEMS = 50  # 한 번에 다루는 글의 최대 수
MIN_ITEMS = 3  # 등록할 때 글 목록으로 인정하는 최소 글 수
MAX_ANCHORS = 5000
MAX_TITLE = 200
_SKIP_TAGS = frozenset(
    {
        "nav",
        "footer",
        "aside",
        "script",
        "style",
        "noscript",
        "template",
        "form",
        "select",
        "button",
    }
)
_GENERIC = frozenset(
    {
        "read more", "more", "learn more", "continue reading", "read article", "view more",
        "view all", "see more", "read", "블로그", "더보기", "자세히 보기", "자세히", "읽기",
        "바로가기", "blog", "news", "상세보기",
    }
)  # fmt: skip
_NOISE_SEGMENTS = frozenset(
    {"tag", "tags", "category", "categories", "page", "author", "authors", "feed", "rss", "search"}
    | {"login"}
)
_NOISE_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".pdf", ".zip",
    ".mp4", ".mp3", ".css", ".js", ".xml",
)  # fmt: skip
_TRACKING = re.compile(r"^(utm_|fbclid$|gclid$|mc_|ref$|source$)", re.I)
_LABEL_PREFIX = re.compile(r"^(?:read more|learn more|continue reading|view)\s*[:：-]\s+", re.I)
_MONTHS = {
    name: number
    for number, names in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"),
        start=1,
    )
    for name in (names,)
}
_MONTH = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
_DATE_PATTERNS = (
    (re.compile(r"^(\d{4})[-./](\d{1,2})[-./](\d{1,2})\b[\s:|·-]*"), "ymd"),
    (re.compile(r"^(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일\s*"), "ymd"),
    (re.compile(rf"^(\d{{1,2}})\s+{_MONTH},?\s+(\d{{4}})\b[\s:|·-]*", re.I), "dmy"),
    (re.compile(rf"^{_MONTH}\s+(\d{{1,2}}),?\s+(\d{{4}})\b[\s:|·-]*", re.I), "mdy"),
)


@dataclass(frozen=True)
class PageItem:
    title: str
    url: str
    date: str | None  # 목록에 적힌 날짜(ISO). 없으면 None


@dataclass(frozen=True)
class PageListing:
    title: str  # 페이지 제목(구독 이름의 기본값)
    items: tuple[PageItem, ...]


class _Anchor:
    def __init__(self, href: str, title: str, label: str) -> None:
        self.href = href
        self.texts = [title, label]  # title 속성과 aria-label
        self.parts: list[str] = []
        self.time = ""


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.anchors: list[_Anchor] = []
        self.title = ""
        self._skip: dict[str, int] = {}
        self._current: _Anchor | None = None
        self._in_title = False

    def _skipping(self) -> bool:
        return any(self._skip.values())

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): (value or "") for key, value in attrs}
        if tag in _SKIP_TAGS:
            self._skip[tag] = self._skip.get(tag, 0) + 1
        elif tag == "title":
            self._in_title = True
        elif tag == "a" and not self._skipping() and len(self.anchors) < MAX_ANCHORS:
            href = values.get("href", "").strip()
            if href:
                self._current = _Anchor(href, values.get("title", ""), values.get("aria-label", ""))
        elif self._current is not None and tag == "img":
            self._current.texts.append(values.get("alt", ""))
        elif self._current is not None and tag == "time":
            self._current.time = values.get("datetime", "")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip.get(tag, 0) > 0:
            self._skip[tag] -= 1
        elif tag == "title":
            self._in_title = False
        elif tag == "a" and self._current is not None:
            self._current.texts.insert(0, " ".join("".join(self._current.parts).split()))
            self.anchors.append(self._current)
            self._current = None

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif self._current is not None:
            self._current.parts.append(data)


def _clean_url(url: str) -> str | None:
    """http(s)이고 계정 정보가 없는 주소만. 조각(#)과 추적용 쿼리를 빼고 끝의 /도 뺀다."""
    try:
        parts = urlsplit(url.strip())
        host = parts.hostname or ""
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not host or "@" in parts.netloc:
        return None
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if not _TRACKING.match(k)])
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, query, ""))


def _host_key(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _is_noise_path(path: str) -> bool:
    lowered = path.lower()
    segments = [s for s in lowered.split("/") if s]
    return lowered.endswith(_NOISE_EXTENSIONS) or any(s in _NOISE_SEGMENTS for s in segments)


def split_leading_date(text: str) -> tuple[str | None, str]:
    """글자 맨 앞의 날짜(ISO 날짜)와 나머지. 날짜가 없거나 올바르지 않으면 (None, 원래 글자)."""
    for pattern, order in _DATE_PATTERNS:
        found = pattern.match(text)
        if not found:
            continue
        groups = found.groups()
        try:
            if order == "ymd":
                moment = date(int(groups[0]), int(groups[1]), int(groups[2]))
            elif order == "dmy":
                moment = date(int(groups[2]), _MONTHS[groups[1][:3].lower()], int(groups[0]))
            else:
                moment = date(int(groups[2]), _MONTHS[groups[0][:3].lower()], int(groups[1]))
        except ValueError:
            return None, text
        return moment.isoformat(), text[found.end() :].strip()
    return None, text


def _candidates(texts: list[str]) -> tuple[str, str | None]:
    """글 하나의 후보 글자들에서 (제목, 날짜). 쓸 만한 제목이 없으면 ("", 날짜)."""
    found_date: str | None = None
    cleaned: list[str] = []
    for raw in texts:
        text = " ".join(raw.split())
        if not text or text.startswith(("/", "http://", "https://")):
            continue
        moment, text = split_leading_date(text)
        found_date = found_date or moment
        text = _LABEL_PREFIX.sub("", text).strip()
        if len(text) < 4 or text.lower() in _GENERIC:
            continue
        cleaned.append(text[:MAX_TITLE])
    whole = [t for t in cleaned if not t.endswith(("...", "…"))]
    pool = whole or cleaned
    return (max(pool, key=len) if pool else ""), found_date


def _strip_labels(titles: list[str], section: str) -> list[str]:
    """제목 앞에 모든 글이 공통으로 붙인 분류 이름("Blog:", "Blog ")을 뺀다."""
    if section:
        pattern = re.compile(rf"^{re.escape(section)}s?\s*[:：-]?\s+", re.I)
        titles = [
            pattern.sub("", t, count=1) if len(pattern.sub("", t, count=1)) >= 4 else t
            for t in titles
        ]
    labels = [
        t.split(": ", 1)[0].lower() for t in titles if ": " in t and len(t.split(": ", 1)[0]) <= 20
    ]
    if len(titles) >= MIN_ITEMS and labels:
        common = max(set(labels), key=labels.count)
        if labels.count(common) >= 0.8 * len(titles):
            titles = [
                t.split(": ", 1)[1] if t.lower().startswith(common + ": ") else t for t in titles
            ]
    return titles


def extract_page_items(html: str, page_url: str) -> PageListing:
    """목록 페이지 HTML에서 글을 뽑는다(최대 MAX_ITEMS개). 못 찾으면 items가 비어 있다."""
    parser = _PageParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # 깨진 HTML에서도 지금까지 읽은 것으로 계속한다
        pass
    base = _clean_url(page_url)
    page_title = " ".join(parser.title.split())[:MAX_TITLE]
    if base is None:
        return PageListing(page_title, ())
    host = _host_key(base)
    order: list[str] = []
    texts: dict[str, list[str]] = {}
    times: dict[str, str] = {}
    for anchor in parser.anchors:
        try:
            url = _clean_url(urljoin(base, anchor.href))
        except ValueError:
            continue
        if url is None or _host_key(url) != host:
            continue
        if url not in texts:
            order.append(url)
            texts[url] = []
        texts[url].extend(anchor.texts)
        if anchor.time:
            times.setdefault(url, anchor.time)
    list_path = urlsplit(base).path.rstrip("/").lower()
    chosen = _choose(order, texts, base, list_path)
    section = list_path.rsplit("/", 1)[-1]
    rows: list[tuple[str, str, str | None]] = []
    for url in chosen:
        title, moment = _candidates(texts[url])
        if title:
            rows.append((url, title, moment or _iso_date(times.get(url, ""))))
    labelled = _strip_labels([title for _, title, _ in rows], section)
    items = tuple(
        PageItem(title, url, moment) for (url, _, moment), title in zip(rows, labelled, strict=True)
    )
    return PageListing(page_title, items[:MAX_ITEMS])


def _iso_date(raw: str) -> str | None:
    found = re.match(r"^(\d{4})-(\d{2})-(\d{2})", raw.strip())
    if not found:
        return None
    try:
        return date(int(found.group(1)), int(found.group(2)), int(found.group(3))).isoformat()
    except ValueError:
        return None


def _choose(order: list[str], texts: dict[str, list[str]], base: str, list_path: str) -> list[str]:
    usable = [u for u in order if u != base and not _is_noise_path(urlsplit(u).path)]
    if list_path:
        under = [
            u
            for u in usable
            if urlsplit(u).path.lower().startswith(list_path + "/")
            and urlsplit(u).path != list_path
        ]
        if len(under) >= MIN_ITEMS:
            return under
    groups: dict[str, list[str]] = {}
    for url in usable:
        title, _ = _candidates(texts[url])
        if len(title) >= 12:
            groups.setdefault(urlsplit(url).path.rsplit("/", 1)[0], []).append(url)
    best = max(groups.items(), key=lambda kv: (len(kv[1]), kv[0].count("/")), default=("", []))[1]
    return best if len(best) >= MIN_ITEMS else []
