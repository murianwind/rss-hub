"""구독 목록을 OPML로 내보내기. 카테고리는 폴더가 된다.

피드의 웹훅은 내보내지 않는다(OPML에 없는 개념이고, 주소가 비밀 값이다).
XML이 허용하지 않는 문자는 지워서, 어떤 이름이 들어 있어도 올바른 파일이 나온다.
"""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

_INVALID_XML = re.compile("[^\u0009\u000a\u000d\u0020-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]")


@dataclass(frozen=True)
class ExportFeed:
    name: str
    url: str
    html_url: str
    category: str | None


def _clean(text: str) -> str:
    return _INVALID_XML.sub("", text)


def _outline(parent: ET.Element, feed: ExportFeed) -> None:
    name = _clean(feed.name)
    attributes = {"text": name, "title": name, "type": "rss", "xmlUrl": _clean(feed.url)}
    if feed.html_url:
        attributes["htmlUrl"] = _clean(feed.html_url)
    ET.SubElement(parent, "outline", attributes)


def build_opml(feeds: list[ExportFeed]) -> str:
    root = ET.Element("opml", {"version": "2.0"})
    ET.SubElement(ET.SubElement(root, "head"), "title").text = "RSS Hub 구독 목록"
    body = ET.SubElement(root, "body")
    for feed in feeds:
        if feed.category is None:
            _outline(body, feed)
    folders = sorted({f.category for f in feeds if f.category is not None}, key=str.lower)
    for folder in folders:
        name = _clean(folder)
        element = ET.SubElement(body, "outline", {"text": name, "title": name})
        for feed in feeds:
            if feed.category == folder:
                _outline(element, feed)
    ET.indent(root)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"
