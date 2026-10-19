import pytest

from rss_hub.domain.importing import parse_import_file
from rss_hub.domain.opml_export import ExportFeed, build_opml


def parse(xml):
    return parse_import_file("subscriptions.opml", xml.encode("utf-8"))


def feeds():
    return [
        ExportFeed("블로그 A", "https://a.example.com/rss", "https://a.example.com", "IT"),
        ExportFeed("블로그 B", "https://b.example.com/rss", "", "IT"),
        ExportFeed("뉴스", "https://n.example.com/rss", "https://n.example.com", "뉴스"),
        ExportFeed("카테고리 없음", "https://c.example.com/rss", "", None),
    ]


def test_categories_become_folders_and_uncategorized_feeds_stay_at_the_top_level():
    xml = build_opml(feeds())
    entries = parse(xml)
    assert [(e.name, e.category) for e in entries] == [
        ("카테고리 없음", None),
        ("블로그 A", "IT"),
        ("블로그 B", "IT"),
        ("뉴스", "뉴스"),
    ]


def test_every_feed_keeps_its_name_address_and_site_address():
    by_url = {e.url: e for e in parse(build_opml(feeds()))}
    assert by_url["https://a.example.com/rss"].html_url == "https://a.example.com"
    assert by_url["https://b.example.com/rss"].html_url == ""
    assert by_url["https://c.example.com/rss"].name == "카테고리 없음"


def test_the_file_is_a_utf8_opml_document_with_a_declaration():
    xml = build_opml(feeds())
    assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert '<opml version="2.0">' in xml and 'type="rss"' in xml


@pytest.mark.parametrize(
    "name",
    [
        "따옴표 \" 와 ' 있는 이름",
        "꺾쇠 <b>태그</b> & 앰퍼샌드",
        "줄바꿈\n과\t탭",
        "이모지 🧪 와 한글",
        "]]> CDATA 끝 표시",
    ],
)
def test_special_characters_in_names_still_make_valid_xml_that_round_trips(name):
    xml = build_opml([ExportFeed(name, "https://a.example.com/rss?x=1&y=2", "", None)])
    entry = parse(xml)[0]
    assert entry.url == "https://a.example.com/rss?x=1&y=2"
    assert entry.name.replace("\n", " ").replace("\t", " ") == name.replace("\n", " ").replace(
        "\t", " "
    )


def test_characters_that_xml_forbids_are_removed_instead_of_breaking_the_file():
    xml = build_opml([ExportFeed("나쁜\x00이름\x1f", "https://a.example.com/rss", "", "폴더\x00")])
    entry = parse(xml)[0]
    assert entry.name == "나쁜이름" and entry.category == "폴더"


def test_an_empty_subscription_list_is_still_a_valid_document():
    xml = build_opml([])
    assert "<body />" in xml or "<body></body>" in xml


def test_the_export_can_be_imported_again_and_every_feed_is_a_duplicate():
    from rss_hub.domain.feed_url import feed_url_key
    from rss_hub.domain.importing import build_preview

    entries = parse(build_opml(feeds()))
    preview = build_preview(entries, {feed_url_key(f.url) for f in feeds()})
    assert (preview.new_count, preview.duplicate_count, preview.error_count) == (0, 4, 0)
