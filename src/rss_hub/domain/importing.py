"""구독 가져오기: OPML 파일 해석, 미리보기(신규, 중복, 오류), 프리셋 제안.

파일은 인증 없이 열린 업로드 창구로 들어오므로 모두 믿지 않는다.
- XML은 defusedxml로 읽고, DTD와 엔티티가 있으면 거부한다(외부 엔티티, 엔티티 폭탄 방지).
- 크기(5MB)와 개수(2000개)를 제한하고, 깊이가 깊은 파일도 반복문으로 읽어서 서버가 죽지 않게 한다.
- 오류 메시지에는 파일 내용을 되돌려 주지 않는다.
"""

import json
from collections.abc import Collection, Sequence
from dataclasses import asdict, dataclass
from xml.etree.ElementTree import Element, ParseError

from defusedxml import ElementTree as SafeElementTree
from defusedxml.common import DefusedXmlException

from rss_hub.domain.feed_url import FeedUrlError, feed_url_key, validate_feed_url
from rss_hub.domain.schedule import PRIORITY_EVERY_SLOT

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_FEEDS = 2000
MAX_NAME_LENGTH = 200
MAX_CATEGORY_LENGTH = 100
MAX_URL_TEXT_LENGTH = 2048

STATUS_NEW = "new"
STATUS_DUPLICATE = "duplicate"
STATUS_ERROR = "error"


OPML_ERROR = "OPML 형식이 올바르지 않음"
UNSAFE_XML = "안전하지 않은 XML(DTD, 엔티티)은 허용하지 않음"
TOO_MANY = f"한 번에 가져올 수 있는 피드는 {MAX_FEEDS}개까지"


class ImportFileError(Exception):
    """파일 자체의 문제. message는 사용자에게 그대로 보여 줄 수 있다."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class RawEntry:
    name: str
    url: str
    html_url: str = ""
    category: str | None = None


def _clip(text: str, limit: int) -> str:
    return text.strip()[:limit]


# ---------- 파일 해석 ----------


def parse_import_file(filename: str, data: bytes) -> list[RawEntry]:
    """업로드한 파일에서 피드 목록을 읽는다. 파일 자체가 잘못되면 ImportFileError."""
    if not filename.lower().endswith((".opml", ".xml")):
        raise ImportFileError("OPML 파일만 올릴 수 있음")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ImportFileError("파일이 너무 큼(최대 5MB)")
    if not data.lstrip(b"\xef\xbb\xbf").strip():
        raise ImportFileError("파일이 비어 있음")
    entries = _parse_opml(data)
    if not entries:
        raise ImportFileError("피드가 하나도 없음")
    return entries


def _parse_opml(data: bytes) -> list[RawEntry]:
    try:
        root = SafeElementTree.fromstring(data, forbid_dtd=True)
    except DefusedXmlException as error:
        raise ImportFileError(UNSAFE_XML) from error
    except (ParseError, ValueError, RecursionError) as error:
        raise ImportFileError(OPML_ERROR) from error
    if root.tag.lower() != "opml":
        raise ImportFileError(OPML_ERROR)
    body = next((child for child in root if child.tag.lower() == "body"), None)
    if body is None:
        raise ImportFileError(OPML_ERROR)

    entries: list[RawEntry] = []
    # 깊은 파일도 안전하게 반복문으로 읽는다
    stack: list[tuple[Element, str | None]] = [(child, None) for child in reversed(list(body))]
    while stack:
        element, category = stack.pop()
        if element.tag.lower() != "outline":
            continue
        attributes = {key.lower(): value for key, value in element.attrib.items()}
        feed_url = (attributes.get("xmlurl") or "").strip()
        text = (attributes.get("text") or "").strip()
        title = (attributes.get("title") or "").strip()
        # 폴더에는 xmlUrl이 없다. 있는데 비어 있으면 주소 없는 피드 항목이다
        if "xmlurl" in attributes:
            entries.append(
                RawEntry(
                    name=_clip(text or title or feed_url, MAX_NAME_LENGTH),
                    url=feed_url,
                    html_url=_clip(attributes.get("htmlurl") or "", MAX_URL_TEXT_LENGTH),
                    category=category,
                )
            )
            if len(entries) > MAX_FEEDS:
                raise ImportFileError(TOO_MANY)
        else:  # 폴더: 이름이 있으면 가장 안쪽 폴더 이름을, 없으면 바깥 폴더의 이름을 그대로 쓴다
            folder = _clip(text or title, MAX_CATEGORY_LENGTH) or category
            stack.extend((child, folder) for child in reversed(list(element)))
    return entries


# ---------- 프리셋 ----------


@dataclass(frozen=True)
class Preset:
    key: str
    label: str
    poll_priority: str
    max_entries: int | None
    emoji: str


GIZMODO = Preset("gizmodo", "Gizmodo", PRIORITY_EVERY_SLOT, 120, "🧪")
EVERY_SLOT = Preset("every_slot", "매 슬롯 점검", PRIORITY_EVERY_SLOT, 50, "📢")
PRESETS = {preset.key: preset for preset in (GIZMODO, EVERY_SLOT)}


def suggest_preset(name: str, url: str, html_url: str) -> Preset | None:
    """기존 코드에 숨어 있던 규칙(Gizmodo, awesome-blogs)을 사용자가 고르는 제안으로 바꾼 것."""
    haystack = f"{name} {url} {html_url}".lower()
    if "gizmodo" in haystack:
        return GIZMODO
    if "awesome-blogs" in haystack:
        return EVERY_SLOT
    return None


# ---------- 미리보기 ----------


@dataclass(frozen=True)
class PreviewItem:
    index: int  # 파일 안에서의 위치(화면 입력칸을 구분하는 데 쓴다)
    name: str
    url: str
    html_url: str
    category: str | None
    status: str
    reason: str = ""
    preset: str | None = None


@dataclass(frozen=True)
class Preview:
    items: tuple[PreviewItem, ...]
    new_categories: tuple[str, ...]

    def _count(self, status: str) -> int:
        return sum(1 for item in self.items if item.status == status)

    @property
    def new_count(self) -> int:
        return self._count(STATUS_NEW)

    @property
    def duplicate_count(self) -> int:
        return self._count(STATUS_DUPLICATE)

    @property
    def error_count(self) -> int:
        return self._count(STATUS_ERROR)


def _item(
    index: int,
    name: str,
    entry: RawEntry,
    url: str,
    status: str,
    reason: str = "",
    preset: str | None = None,
) -> PreviewItem:
    return PreviewItem(
        index=index,
        name=name,
        url=url,
        html_url=entry.html_url,
        category=entry.category,
        status=status,
        reason=reason,
        preset=preset,
    )


def build_preview(
    entries: Sequence[RawEntry],
    existing_keys: Collection[str],
    existing_categories: Collection[str] = (),
) -> Preview:
    """저장하기 전에 항목마다 신규, 중복, 오류를 가른다(저장하지 않는다)."""
    in_file: set[str] = set()
    items: list[PreviewItem] = []
    categories: list[str] = []
    for index, entry in enumerate(entries):
        raw_url = entry.url.strip()
        name = entry.name.strip() or raw_url

        try:
            url = validate_feed_url(raw_url)
        except FeedUrlError as error:
            items.append(_item(index, name, entry, raw_url, STATUS_ERROR, error.message))
            continue
        key = feed_url_key(url)
        if key in existing_keys:
            items.append(_item(index, name, entry, url, STATUS_DUPLICATE, "이미 구독 중"))
        elif key in in_file:
            items.append(_item(index, name, entry, url, STATUS_DUPLICATE, "파일 안에서 중복"))
        else:
            in_file.add(key)
            preset = suggest_preset(name, url, entry.html_url)
            items.append(
                _item(
                    index,
                    name,
                    entry,
                    url,
                    STATUS_NEW,
                    preset=None if preset is None else preset.key,
                )
            )
            category = entry.category
            if category and category not in existing_categories and category not in categories:
                categories.append(category)
    return Preview(items=tuple(items), new_categories=tuple(categories))


def preview_to_json(preview: Preview) -> str:
    return json.dumps(
        {
            "items": [asdict(item) for item in preview.items],
            "new_categories": preview.new_categories,
        },
        ensure_ascii=False,
    )


def preview_from_json(text: str) -> Preview:
    data = json.loads(text)
    return Preview(
        items=tuple(PreviewItem(**item) for item in data["items"]),
        new_categories=tuple(data["new_categories"]),
    )
