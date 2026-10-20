"""원문 페이지(HTML)에서 본문만 뽑는다. 외부 라이브러리 없이 표준 라이브러리로 만든다.

방법: 페이지를 가벼운 트리로 읽고, 메뉴, 스크립트, 댓글 같은 덩어리를 빼고, 문단 글자 수는 많고
링크는 적은 덩어리를 본문으로 고른다(큰 덩어리를 골라도 그 안에 거의 같은 점수의 자식이 있으면
자식으로 내려간다). 점수는 덩어리마다 한 번만 계산한다(악의적으로 큰 페이지에서도 선형 시간).
뽑은 HTML은 반드시 sanitize_html을 거쳐 돌려준다(스크립트, 이벤트 속성,
위험한 주소는 여기서 사라진다).
"""

import re
from html import escape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from rss_hub.domain.sanitize import sanitize_html

MIN_TEXT_LENGTH = 200  # 이보다 짧으면 본문을 찾지 못한 것으로 본다
MAX_DEPTH = 120  # 이보다 깊은 중첩은 잘라서 재귀가 넘치지 않게 한다
MAX_NODES = 60000
MAX_OUTPUT_CHARS = 400_000

_VOID = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "wbr"}
)
# 본문이 아닌 것: 통째로 버린다
_DROP = frozenset(
    {
        "script", "style", "noscript", "nav", "aside", "footer", "header", "form", "iframe",
        "svg", "button", "select", "template", "object", "canvas", "dialog", "head", "title",
    }
)  # fmt: skip
_CANDIDATES = frozenset({"article", "main", "section", "div", "td", "body"})
_KEEP_ATTRS = frozenset(
    {"href", "src", "alt", "title", "colspan", "rowspan", "lang", "width", "height"}
)
# 본문이 아닌 덩어리의 클래스/아이디. 이름 전체(공백으로 나눈 토큰)가 이 낱말로 시작할 때만 본다.
# 그래서 "has-sidebar" 같은 래퍼 이름은 걸리지 않는다.
_NEGATIVE_TOKEN = re.compile(
    r"^(comments?|respond|reply|related|share|sharing|social|sidebar|widgets?|promo|banner|sponsor|"
    r"advert\w*|ads?|breadcrumbs?|pagination|recommend\w*|subscribe|newsletter|cookie\w*|"
    r"popup|modal|"
    r"menu|nav\w*|footer)([-_].*)?$",
    re.I,
)
_STRUCTURAL = frozenset({"body", "main", "article"})

# 영상은 재생하지 않고 "영상 보기" 링크로 바꾼다. 프레임은 알려진 영상 사이트의 것만 바꾼다
# (아무 프레임이나 영상으로 취급하면 광고와 지도가 "영상 보기"로 둔갑한다).
_VIDEO_HOSTS = (
    "youtube.com", "youtube-nocookie.com", "youtu.be", "vimeo.com", "dailymotion.com",
    "tv.naver.com", "nmv.naver.com", "tv.kakao.com", "twitch.tv",
)  # fmt: skip
_FRAME_TAGS = frozenset({"iframe", "embed", "object"})
_MEDIA_TAGS = _FRAME_TAGS | {"video", "audio"}  # 주소가 없거나 쓸 수 없으면 대체 문구까지 지운다
_YOUTUBE_EMBED = re.compile(r"^/(?:embed|v)/([\w-]{6,20})$")
_VIMEO_EMBED = re.compile(r"^/video/(\d{1,12})$")
MAX_MEDIA_LINKS = 20
VIDEO_LABEL = "영상 보기"
AUDIO_LABEL = "오디오 듣기"
_POSITIVE = re.compile(r"article|post|entry|content|story|text|body|main", re.I)
_PLACEHOLDER = re.compile(r"^data:", re.I)


def _is_negative(attrs: dict[str, str]) -> bool:
    tokens = f"{attrs.get('class', '')} {attrs.get('id', '')}".split()
    return any(_NEGATIVE_TOKEN.match(token) for token in tokens)


class _Node:
    __slots__ = ("attrs", "children", "dropped", "metrics", "parent", "score", "tag")

    def __init__(self, tag: str, attrs: dict[str, str], parent: "_Node | None") -> None:
        self.tag = tag
        self.attrs = attrs
        self.parent = parent
        self.children: list[_Node | str] = []
        self.metrics: tuple[int, int, int] | None = None  # (글자 수, 링크 글자 수, 문단 수)
        self.score: float | None = None
        self.dropped = tag in _DROP or (tag not in _STRUCTURAL and _is_negative(attrs))


class _Builder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("root", {}, None)
        self._current = self.root
        self._depth = 0
        self._count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._count += 1
        if self._count > MAX_NODES:
            return
        node = _Node(tag, {k: (v or "") for k, v in attrs}, self._current)
        self._current.children.append(node)
        if tag not in _VOID and self._depth < MAX_DEPTH:
            self._current = node
            self._depth += 1

    def handle_endtag(self, tag: str) -> None:
        walker = self._current
        while walker is not self.root:
            if walker.tag == tag:
                self._current = walker.parent or self.root
                self._depth = max(0, self._depth - 1)
                return
            walker = walker.parent or self.root  # 열려 있는 것 중에 없으면(짝 없는 닫는 태그) 무시

    def handle_data(self, data: str) -> None:
        if data.strip():
            self._current.children.append(data)


def _signature(node: _Node) -> str:
    return f"{node.attrs.get('class', '')} {node.attrs.get('id', '')}"


def _measure(node: _Node) -> tuple[int, int, int]:
    """(글자 수, 링크 안의 글자 수, 문단 수). 버리는 덩어리는 세지 않고, 결과는 노드에 저장한다."""
    if node.metrics is not None:
        return node.metrics
    if node.dropped:
        node.metrics = (0, 0, 0)
        return node.metrics
    text = links = paragraphs = 0
    for child in node.children:
        if isinstance(child, str):
            text += len(child.strip())
        else:
            t, link, p = _measure(child)
            text, links, paragraphs = text + t, links + link, paragraphs + p
    if node.tag == "a":
        links = text  # 링크 안의 글자는 모두 링크 글자다
    node.metrics = (text, links, paragraphs + (1 if node.tag == "p" else 0))
    return node.metrics


def _score(node: _Node) -> float:
    if node.score is None:
        text, links, paragraphs = _measure(node)
        score = float(text - 2 * links + 25 * paragraphs)  # 링크가 많으면 크게 깎는다
        signature = _signature(node)
        if node.tag in ("article", "main"):
            score *= 1.2
        elif _POSITIVE.search(signature):
            score *= 1.15
        node.score = score
    return node.score


def _candidates(node: _Node, found: list[_Node], depth: int = 0) -> None:
    if node.dropped or depth > MAX_DEPTH:
        return
    if node.tag in _CANDIDATES:
        found.append(node)
    for child in node.children:
        if not isinstance(child, str):
            _candidates(child, found, depth + 1)


def _nearest_candidates(node: _Node) -> list[_Node]:
    """node 바로 아래에서 처음 만나는 후보들(후보 안으로는 더 들어가지 않는다)."""
    found: list[_Node] = []
    pending = [c for c in node.children if not isinstance(c, str)]
    while pending:
        child = pending.pop()
        if child.dropped:
            continue
        if child.tag in _CANDIDATES:
            found.append(child)
        else:
            pending.extend(c for c in child.children if not isinstance(c, str))
    return found


def _best(root: _Node) -> _Node | None:
    found: list[_Node] = []
    _candidates(root, found)
    if not found:
        return None
    scored = [(_score(node), index, node) for index, node in enumerate(found)]
    scored.sort(key=lambda item: (-item[0], item[1]))  # 점수 높은 순, 같으면 문서에서 먼저 나온 것
    best_score, _, best = scored[0]
    while True:  # 거의 같은 점수의 자식이 있으면 더 좁은 쪽(본문에 가까운 쪽)으로 내려간다
        deeper = [(_score(c), c) for c in _nearest_candidates(best)]
        deeper = [item for item in deeper if item[0] >= 0.85 * best_score]
        if not deeper:
            return best
        deeper.sort(key=lambda item: -item[0])
        best_score, best = deeper[0]


def _host_is_video_site(host: str) -> bool:
    host = host.lower().rstrip(".")
    return any(host == site or host.endswith("." + site) for site in _VIDEO_HOSTS)


def _watch_address(url: str) -> str:
    """재생용 임베드 주소를 사람이 보는 영상 페이지 주소로 바꾼다(모르는 모양이면 그대로)."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if host.endswith(("youtube.com", "youtube-nocookie.com")):
        found = _YOUTUBE_EMBED.match(parts.path)
        if found:
            return f"https://www.youtube.com/watch?v={found.group(1)}"
    if host == "player.vimeo.com":
        found = _VIMEO_EMBED.match(parts.path)
        if found:
            return f"https://vimeo.com/{found.group(1)}"
    return url


def _media_link(node: _Node, base_url: str) -> tuple[str, str] | None:
    """영상, 소리, 영상 프레임이면 (글자, 주소). 쓸 수 없으면 None."""
    tag = node.tag
    if tag not in _FRAME_TAGS and tag not in ("video", "audio"):
        return None
    raw = node.attrs.get("src") or (node.attrs.get("data") if tag == "object" else "")
    if not raw and tag in ("video", "audio"):
        for child in node.children:
            if not isinstance(child, str) and child.tag == "source" and child.attrs.get("src"):
                raw = child.attrs["src"]
                break
    if not raw:
        return None
    try:
        url = urljoin(base_url, re.sub(r"[\x00-\x20\x7f-\x9f]", "", raw))
        parts = urlsplit(url)
        host = parts.hostname or ""
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not host or "@" in parts.netloc:
        return None
    if tag in _FRAME_TAGS:
        if not _host_is_video_site(host):
            return None
        return VIDEO_LABEL, _watch_address(url)
    return (AUDIO_LABEL if tag == "audio" else VIDEO_LABEL), url


def _emit(out: list[str], used: list[int], piece: str) -> None:
    out.append(piece)
    used[0] += len(piece)  # used = [누적 글자 수, 만든 영상 링크 수]
    # 누적 길이만 센다(매번 전체를 다시 합산하면 제곱 시간이 된다)


def _serialize(node: _Node, out: list[str], used: list[int], base_url: str, depth: int = 0) -> None:
    if depth > MAX_DEPTH or used[0] > MAX_OUTPUT_CHARS:
        return
    media = _media_link(node, base_url)
    if media is not None:  # 버리는 덩어리 안이 아니면, 영상 자리에 링크를 둔다
        if used[1] < MAX_MEDIA_LINKS:
            used[1] += 1
            label, url = media
            _emit(out, used, f'<div><a href="{escape(url, quote=True)}">{label}</a></div>')
        return
    if node.dropped or node.tag in _MEDIA_TAGS:
        return
    attrs = {k: v for k, v in node.attrs.items() if k in _KEEP_ATTRS}
    lazy = node.attrs.get("data-src") or node.attrs.get("data-original")
    if node.tag == "img" and lazy and (not attrs.get("src") or _PLACEHOLDER.match(attrs["src"])):
        attrs["src"] = lazy
    rendered = "".join(f' {k}="{escape(v, quote=True)}"' for k, v in attrs.items())
    _emit(out, used, f"<{node.tag}{rendered}>")
    if node.tag in _VOID:
        return
    for child in node.children:
        if isinstance(child, str):
            _emit(out, used, escape(child, quote=False))
        else:
            _serialize(child, out, used, base_url, depth + 1)
    _emit(out, used, f"</{node.tag}>")


def _plain_length(clean_html: str) -> int:
    return len(re.sub(r"\s+", "", re.sub(r"<[^>]*>", "", clean_html)))


def extract_main_content(html: str, base_url: str) -> str | None:
    """원문 페이지에서 본문 HTML(정제됨)을 뽑는다. 본문을 찾지 못하면 None."""
    builder = _Builder()
    try:
        builder.feed(html)
        builder.close()
    except Exception:  # 해석할 수 없는 HTML도 있다: 본문 없음으로 처리한다
        return None
    best = _best(builder.root)
    if best is None:
        return None
    out: list[str] = []
    _serialize(best, out, [0, 0], base_url)
    clean = sanitize_html("".join(out), base_url)
    return clean if _plain_length(clean) >= MIN_TEXT_LENGTH else None
