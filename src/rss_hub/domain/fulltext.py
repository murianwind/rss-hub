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


_MARKERS = frozenset({
    "related", "related articles", "related posts", "related stories", "related reading",
    "related content", "you may also like", "you might also like", "recommended",
    "recommended for you", "read more", "read next", "advertisement", "comments",
    "leave a reply", "share this story", "share this article", "share this post", "tags",
    "explore more on these topics", "follow us", "about the author", "about the authors",
    "관련 글", "관련 기사", "관련 포스트", "함께 읽으면 좋은 글", "공유하기", "댓글", "태그",
    "이전 글", "다음 글",
})  # fmt: skip
_MARKER_PREFIXES = ("sign up for", "subscribe to", "subscribe and", "join our", "follow us",
                    "share this", "explore more", "more from")  # fmt: skip
CUT_AFTER_SHARE = 0.4  # 글의 이만큼 이후에 나온 끝 안내만 자른다(앞쪽의 같은 낱말은 본문일 수 있다)
_BLOCKS = frozenset(
    {"p", "div", "span", "section", "strong", "b", "h1", "h2", "h3", "h4", "h5", "h6"}
)
_LOGO = re.compile(r"(^|[^a-z])(logo|sprite|favicon|avatar|emoji|badge|icon)s?([^a-z]|$)", re.I)
_DATE = re.compile(
    r"^(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.? \d{1,2},? \d{4}"
    r"|\d{4}[-./]\d{1,2}[-./]\d{1,2}\.?|\d{4}년 ?\d{1,2}월 ?\d{1,2}일)$",
    re.I,
)
MAX_DATE_ZONE = 1500  # 글 맨 앞 이만큼 안의 날짜만 한 줄 날짜로 본다
MAX_LABEL = 40  # 목록 바로 앞의 짧은 이름표(예: Cybersecurity Guides)


def _own_text(node: _Node, limit: int = 200) -> str:
    """노드 안의 글자(버리는 덩어리는 뺀 것)를 한 줄로 이어 limit자까지."""
    pieces: list[str] = []
    size = 0
    stack: list[_Node | str] = [node]
    while stack and size < limit:
        item = stack.pop()
        if isinstance(item, str):
            pieces.append(item.strip())
            size += len(item.strip()) + 1
        elif not item.dropped:
            stack.extend(reversed(item.children))
    return " ".join(p for p in pieces if p)[:limit]


def _normal(text: str) -> str:
    return re.sub(r"[^\w]+", "", text.lower())


def _is_marker(text: str) -> bool:
    cleaned = re.sub(r"\s*\(\d+\)\s*$", "", text.strip().strip(":：").lower())
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned in _MARKERS or cleaned.startswith(_MARKER_PREFIXES)


def _matches_title(text: str, title: str) -> bool:
    a, b = _normal(text), _normal(title)
    if len(a) < 8 or len(b) < 8:
        return False
    return a in b or b in a


def _anchor_count(node: _Node) -> int:
    count = 0
    stack: list[_Node | str] = [node]
    while stack:
        item = stack.pop()
        if isinstance(item, str) or item.dropped:
            continue
        count += 1 if item.tag == "a" else 0
        stack.extend(item.children)
    return count


def _is_noise_list(node: _Node) -> bool:
    """링크 목록이나 공유 막대: 항목 3개 이상, 대부분이 링크로만 된 항목이거나 짧은 이름표."""
    if node.tag not in ("ul", "ol") or node.dropped:
        return False
    items = [c for c in node.children if not isinstance(c, str) and c.tag == "li"]
    if len(items) < 3:
        return False
    pure = short = 0
    for item in items:
        text, links, _ = _measure(item)
        if text > 100:
            return False
        pure += 1 if text > 0 and links == text else 0
        short += 1 if text <= 12 else 0
    return pure * 10 >= len(items) * 6 and (pure + short) * 10 >= len(items) * 8


def _is_link_row(node: _Node) -> bool:
    """링크만 늘어놓은 줄(태그 목록 등): 링크 2개 이상이고 글자가 모두 링크 안에 있다."""
    if node.tag not in ("p", "div", "span", "section") or node.dropped:
        return False
    text, links, _ = _measure(node)
    return 0 < text <= 300 and links == text and _anchor_count(node) >= 2


def _is_noise_block(node: _Node) -> bool:
    return _is_noise_list(node) or _is_link_row(node)


def _is_decor_image(node: _Node) -> bool:
    if node.tag != "img":
        return False
    src = node.attrs.get("src", "") or node.attrs.get("data-src", "")
    if src.split("?")[0].lower().endswith(".svg"):
        return True
    blob = " ".join(node.attrs.get(k, "") for k in ("alt", "class", "id")) + " " + src
    return bool(_LOGO.search(blob))


class _Walk:
    """직렬화 상태: 출력과 길이, 영상 링크 수, 본문 글자 수, 제목 제거 여부, 끝 안내 만남 여부."""

    def __init__(self, base_url: str, title: str, total_text: int) -> None:
        self.out: list[str] = []
        self.chars = 0
        self.media = 0
        self.text = 0
        self.total = total_text
        self.base_url = base_url
        self.title = title
        self.title_done = False
        self.cut = False

    def emit(self, piece: str) -> None:
        self.out.append(piece)
        self.chars += len(piece)  # 누적 길이만 센다(매번 전체를 다시 합산하면 제곱 시간이 된다)


def _skip_block(node: _Node, walk: _Walk) -> bool:
    """글에 속하지 않는 한 덩어리인가(끝 안내는 walk.cut을 켠다)."""
    if node.tag in ("ul", "ol", "p", "div", "span", "section") and _is_noise_block(node):
        return True
    own = _own_text(node, 100)
    if node.tag in _BLOCKS and 0 < len(own) <= 60:
        if _is_marker(own) and walk.text >= CUT_AFTER_SHARE * walk.total:
            walk.cut = True
            return True
        is_title = node.tag in ("h1", "h2", "h3") and _matches_title(own, walk.title)
        if walk.title and not walk.title_done and is_title:
            walk.title_done = True
            return True
        in_date_zone = node.tag in ("p", "div", "span", "time") and walk.text < MAX_DATE_ZONE
        if in_date_zone and _DATE.match(own):
            return True
    # 요약문 끝의 "[…]"는 길이와 상관없이 문단의 끝에서 본다(RSS 요약이 잘린 흔적)
    return node.tag == "p" and _own_text(node, 3000).endswith(("[…]", "[...]"))


def _serialize(node: _Node, walk: _Walk, depth: int = 0) -> None:
    if depth > MAX_DEPTH or walk.chars > MAX_OUTPUT_CHARS or walk.cut:
        return
    media = _media_link(node, walk.base_url)
    if media is not None:  # 버리는 덩어리 안이 아니면, 영상 자리에 링크를 둔다
        if walk.media < MAX_MEDIA_LINKS:
            walk.media += 1
            label, url = media
            walk.emit(f'<div><a href="{escape(url, quote=True)}">{label}</a></div>')
        return
    if node.dropped or node.tag in _MEDIA_TAGS or _is_decor_image(node) or _skip_block(node, walk):
        return
    attrs = {k: v for k, v in node.attrs.items() if k in _KEEP_ATTRS}
    lazy = node.attrs.get("data-src") or node.attrs.get("data-original")
    if node.tag == "img" and lazy and (not attrs.get("src") or _PLACEHOLDER.match(attrs["src"])):
        attrs["src"] = lazy
    rendered = "".join(f' {k}="{escape(v, quote=True)}"' for k, v in attrs.items())
    walk.emit(f"<{node.tag}{rendered}>")
    if node.tag in _VOID:
        return
    children = [c for c in node.children if not (isinstance(c, str) and not c.strip())]
    for index, child in enumerate(node.children):
        if isinstance(child, str):
            walk.text += len(child.strip())
            walk.emit(escape(child, quote=False))
            continue
        if _is_label_of_noise(node, index):
            continue  # 링크 목록 바로 앞의 이름표(예: Cybersecurity Guides)는 목록과 함께 뺀다
        _serialize(child, walk, depth + 1)
    del children
    walk.emit(f"</{node.tag}>")


def _is_label_of_noise(parent: _Node, index: int) -> bool:
    child = parent.children[index]
    if isinstance(child, str) or child.tag not in _BLOCKS:
        return False
    label = _own_text(child, MAX_LABEL + 1)
    if (
        not 0 < len(label) <= MAX_LABEL
        or _anchor_count(child)
        or label.endswith((".", "。", "!", "?"))
    ):
        return False  # 링크가 있거나 문장으로 끝나면 본문이다(예: "Source: ...")
    following = parent.children[index + 1] if index + 1 < len(parent.children) else None
    if following is None or isinstance(following, str):
        return False  # 바로 뒤가 글자거나 없으면 이름표가 아니다
    return _is_noise_block(following)


def _plain_length(clean_html: str) -> int:
    return len(re.sub(r"\s+", "", re.sub(r"<[^>]*>", "", clean_html)))


def extract_main_content(html: str, base_url: str, title: str = "") -> str | None:
    """원문 페이지에서 본문 HTML(정제됨)을 뽑는다. 본문을 찾지 못하면 None.

    title(글 제목)을 주면 본문 맨 앞의 같은 제목 머리글은 뺀다(화면이 이미 제목을 보여 주므로).
    """
    builder = _Builder()
    try:
        builder.feed(html)
        builder.close()
    except Exception:  # 해석할 수 없는 HTML도 있다: 본문 없음으로 처리한다
        return None
    best = _best(builder.root)
    if best is None:
        return None
    walk = _Walk(base_url, title, _measure(best)[0])
    _serialize(best, walk)
    clean = sanitize_html("".join(walk.out), base_url)
    return clean if _plain_length(clean) >= MIN_TEXT_LENGTH else None
