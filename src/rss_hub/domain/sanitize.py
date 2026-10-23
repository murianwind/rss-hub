"""글 본문 정제: 외부 사이트가 준 HTML에서 읽는 데 필요한 것만 남긴다(허용 목록 방식).

- 입력을 그대로 되돌려 쓰지 않고, 토큰을 하나씩 읽어서 허용한 태그와 속성만 새로 만들어 낸다.
  텍스트와 속성값은 모두 이스케이프하므로 입력이 어떤 모양이어도 출력에서 태그를 만들 수 없다.
- 스크립트, 스타일, 프레임, 폼 같은 위험한 요소는 내용까지 지운다.
  모르는 태그는 벗기고 글자만 남긴다.
- 주소는 http, https만 허용하고(javascript:, data: 등과 계정 정보가 든 주소는 버린다)
  상대 주소는 글의 주소 기준으로 푼다.
- 링크는 새 탭에서 열고(noopener, noreferrer), 이미지는 https만 허용하고 referrer 없이 지연 로딩하며
  추적용 1px 이미지는 지운다.
"""

import html
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from rss_hub.domain.text import unescape_entities

MAX_INPUT_LENGTH = 500_000
MAX_DEPTH = 40
MAX_URL_LENGTH = 2048

ALLOWED_TAGS = frozenset(
    {
        *("a", "abbr", "b", "blockquote", "caption", "code", "dd", "del", "div", "dl", "dt"),
        *("em", "figcaption", "figure", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "i", "ins"),
        *("li", "mark", "ol", "p", "pre", "q", "s", "small", "span", "strong", "sub", "sup"),
        *("table", "tbody", "td", "tfoot", "th", "thead", "tr", "u", "ul", "br", "img"),
    }
)
VOID_TAGS = frozenset({"br", "hr", "img"})
DROP_WITH_CONTENT = frozenset(
    {
        *("script", "style", "iframe", "object", "noscript", "template", "svg", "math"),
        *("form", "select", "textarea", "title", "head"),
    }
)
HEADING = {"h1": "h3", "h2": "h3", "h3": "h4", "h4": "h5", "h5": "h6", "h6": "h6"}
SPAN_ATTRS = frozenset({"colspan", "rowspan"})
_CONTROLS = re.compile(r"[\x00-\x20\x7f-\x9f]")


def _safe_url(raw: str, base_url: str) -> str | None:
    cleaned = _CONTROLS.sub("", raw)  # "java\tscript:"처럼 숨겨 넣은 공백과 제어 문자를 먼저 없앤다
    if not cleaned:
        return None
    try:
        url = urljoin(base_url, cleaned) if base_url else cleaned
        parts = urlsplit(url)
        parts.port  # noqa: B018 - 범위를 벗어난 포트는 접근할 때 예외가 난다
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.netloc or "@" in parts.netloc:
        return None
    return url if len(url) <= MAX_URL_LENGTH else None


def _small_number(value: str) -> str | None:
    text = value.strip()
    return text if text.isascii() and text.isdigit() and 1 <= int(text) <= 1000 else None


def _is_tiny(value: str | None) -> bool:
    """폭이나 높이가 2픽셀 이하면 추적용 이미지로 본다."""
    if value is None:
        return False
    digits = value.strip().lower().removesuffix("px")
    return digits.isascii() and digits.isdigit() and int(digits) <= 2


class _Cleaner(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self._base = base_url
        self._out: list[str] = []
        self._open: list[tuple[str, str | None]] = []  # (원래 태그, 내보낸 태그 또는 None)
        self._dropping: list[str] = []

    def result(self) -> str:
        while self._open:
            self._close_last()
        return "".join(self._out)

    # ---------- 태그 ----------

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in DROP_WITH_CONTENT:
            self._dropping.append(tag)
            return
        if self._dropping or tag not in ALLOWED_TAGS:
            return  # 모르는 태그는 벗기고 글자만 남긴다
        values = {name.lower(): (value or "") for name, value in attrs}
        if tag == "img":
            self._image(values)
        elif tag in VOID_TAGS:
            self._out.append(f"<{tag}>")
        elif len(self._open) < MAX_DEPTH:
            self._push(tag, values)

    def _push(self, tag: str, values: dict[str, str]) -> None:
        emitted = HEADING.get(tag, tag)
        if tag == "a":
            url = _safe_url(values.get("href", ""), self._base)
            if url is None:
                self._open.append((tag, None))  # 주소가 없는 링크는 글자만 남긴다
                return
            title = f' title="{html.escape(values["title"])}"' if values.get("title") else ""
            link = f'<a href="{html.escape(url)}"{title}'
            self._out.append(f'{link} target="_blank" rel="noopener noreferrer nofollow">')
        else:
            extra = ""
            if tag in ("td", "th"):
                for name in sorted(SPAN_ATTRS):
                    number = _small_number(values.get(name, ""))
                    extra += f' {name}="{number}"' if number else ""
            if tag == "ol" and (start := _small_number(values.get("start", ""))):
                extra += f' start="{start}"'
            self._out.append(f"<{emitted}{extra}>")
        self._open.append((tag, emitted))

    def _image(self, values: dict[str, str]) -> None:
        url = _safe_url(values.get("src", ""), self._base)
        if (
            url is None
            or not url.startswith("https://")
            or _is_tiny(values.get("width"))
            or _is_tiny(values.get("height"))
        ):
            return
        alt = f' alt="{html.escape(values["alt"])}"' if values.get("alt") else ""
        title = f' title="{html.escape(values["title"])}"' if values.get("title") else ""
        self._out.append(
            f'<img src="{html.escape(url)}"{alt}{title} loading="lazy" decoding="async"'
            ' referrerpolicy="no-referrer">'
        )

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._dropping:
            if tag == self._dropping[-1]:
                self._dropping.pop()
            return
        for index in range(len(self._open) - 1, -1, -1):
            if self._open[index][0] == tag:
                while len(self._open) > index:
                    self._close_last()
                return

    def _close_last(self) -> None:
        _, emitted = self._open.pop()
        if emitted is not None:
            self._out.append(f"</{emitted}>")

    # ---------- 글자 ----------

    def handle_data(self, data: str) -> None:
        if self._dropping:
            return
        in_code = any(tag in ("pre", "code") for tag, _ in self._open)
        # 사이트가 &amp;middot;처럼 두 번 감싸 보낸 글자를 풀되, 코드 안은 보이는 그대로 둔다
        self._out.append(html.escape(data if in_code else unescape_entities(data)))


def sanitize_html(content: str, base_url: str = "") -> str:
    """정제한 HTML. 입력이 비어 있거나 공백뿐이면 빈 문자열."""
    if not content.strip():
        return ""
    cleaner = _Cleaner(base_url)
    try:
        cleaner.feed(content[:MAX_INPUT_LENGTH])
        cleaner.close()
    except Exception:  # 해석기가 실패해도 지금까지 만든 안전한 부분만 돌려준다
        pass
    return cleaner.result()
