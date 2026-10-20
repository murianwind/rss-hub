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


def _emit(out: list[str], used: list[int], piece: str) -> None:
    out.append(piece)
    used[0] += len(piece)  # 누적 길이만 센다(매번 전체를 다시 합산하면 제곱 시간이 된다)


def _serialize(node: _Node, out: list[str], used: list[int], depth: int = 0) -> None:
    if node.dropped or depth > MAX_DEPTH or used[0] > MAX_OUTPUT_CHARS:
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
            _serialize(child, out, used, depth + 1)
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
    _serialize(best, out, [0])
    clean = sanitize_html("".join(out), base_url)
    return clean if _plain_length(clean) >= MIN_TEXT_LENGTH else None
