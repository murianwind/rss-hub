import pytest

from rss_hub.domain.importing import (
    EVERY_SLOT,
    GIZMODO,
    MAX_FEEDS,
    MAX_UPLOAD_BYTES,
    ImportFileError,
    RawEntry,
    build_preview,
    parse_import_file,
    preview_from_json,
    preview_to_json,
    suggest_preset,
)


def parse(name, content):
    data = content if isinstance(content, bytes) else content.encode("utf-8")
    return parse_import_file(name, data)


def error_of(name, content):
    with pytest.raises(ImportFileError) as info:
        parse(name, content)
    return info.value.message


def opml(body, head=""):
    return f'<?xml version="1.0" encoding="UTF-8"?>{head}<opml version="2.0"><body>{body}</body></opml>'


ONE_FEED = opml('<outline xmlUrl="https://a.example.com/rss"/>')


# ---------- 파일 자체의 문제 ----------


@pytest.mark.parametrize(
    "name",
    [
        "feeds.txt",
        "feeds",
        "feeds.csv",
        "feeds.json",
        "feeds.JSON",
        "feeds.opml.bak",
        "feeds.xml.txt",
    ],
)
def test_only_opml_files_are_accepted(name):
    assert error_of(name, ONE_FEED) == "OPML 파일만 올릴 수 있음"


@pytest.mark.parametrize("name", ["a.opml", "A.OPML", "a.xml", "A.Xml"])
def test_extensions_are_case_insensitive_and_xml_counts_as_opml(name):
    assert len(parse(name, ONE_FEED)) == 1


@pytest.mark.parametrize("content", [b"", b"   \n\t ", b"\xef\xbb\xbf"])
def test_empty_files_are_reported(content):
    assert error_of("a.opml", content) == "파일이 비어 있음"


def test_files_over_five_megabytes_are_refused_without_parsing():
    assert (
        error_of("a.opml", ONE_FEED.encode() + b" " * MAX_UPLOAD_BYTES)
        == "파일이 너무 큼(최대 5MB)"
    )


def test_a_file_of_exactly_five_megabytes_is_accepted():
    padding = b" " * (MAX_UPLOAD_BYTES - len(ONE_FEED.encode()))
    assert len(parse("a.opml", ONE_FEED.encode() + padding)) == 1


def test_a_file_without_any_feed_is_reported():
    assert error_of("a.opml", opml("")) == "피드가 하나도 없음"
    assert error_of("a.opml", opml('<outline text="빈 폴더"/>')) == "피드가 하나도 없음"


def test_an_empty_xmlurl_is_kept_as_a_feed_without_an_address_so_the_preview_can_explain_it():
    entries = parse("a.opml", opml('<outline text="주소 없음" xmlUrl=""/>'))
    assert [(e.name, e.url) for e in entries] == [("주소 없음", "")]


def test_very_long_names_are_shortened():
    body = f'<outline text="{"가" * 500}" xmlUrl="https://a.example.com/rss"/>'
    assert len(parse("a.opml", opml(body))[0].name) == 200


# ---------- OPML ----------


@pytest.mark.parametrize(
    ("attributes", "expected"),
    [
        ('text="이름A" title="제목B"', "이름A"),
        ('title="제목B"', "제목B"),
        ('text="" title="제목B"', "제목B"),
        ("", "https://n.example.com/rss"),
    ],
)
def test_opml_name_priority_is_text_then_title_then_address(attributes, expected):
    body = f'<outline {attributes} xmlUrl="https://n.example.com/rss"/>'
    assert parse("a.opml", opml(body))[0].name == expected


def test_opml_keeps_the_site_address():
    body = '<outline text="N" xmlUrl="https://n.example.com/rss" htmlUrl="https://n.example.com"/>'
    assert parse("a.opml", opml(body))[0].html_url == "https://n.example.com"


def test_opml_attribute_names_are_case_insensitive():
    body = '<outline text="N" XMLURL="https://n.example.com/rss" HTMLURL="https://n.example.com"/>'
    entry = parse("a.opml", opml(body))[0]
    assert (entry.url, entry.html_url) == ("https://n.example.com/rss", "https://n.example.com")


def test_opml_folders_become_categories():
    body = (
        '<outline text="IT"><outline text="a" xmlUrl="https://a.example.com/rss"/>'
        '<outline text="b" xmlUrl="https://b.example.com/rss"/></outline>'
        '<outline text="뉴스"><outline text="c" xmlUrl="https://c.example.com/rss"/></outline>'
        '<outline text="d" xmlUrl="https://d.example.com/rss"/>'
    )
    assert [(e.name, e.category) for e in parse("a.opml", opml(body))] == [
        ("a", "IT"),
        ("b", "IT"),
        ("c", "뉴스"),
        ("d", None),
    ]


def test_nested_folders_use_the_innermost_name_and_unnamed_folders_inherit():
    body = (
        '<outline text="IT"><outline text="웹"><outline text="a" xmlUrl="https://a.example.com/rss"/></outline>'
        '<outline><outline text="b" xmlUrl="https://b.example.com/rss"/></outline></outline>'
    )
    assert [e.category for e in parse("a.opml", opml(body))] == ["웹", "IT"]


def test_a_feed_outline_with_children_is_still_just_a_feed():
    body = (
        '<outline text="a" xmlUrl="https://a.example.com/rss">'
        '<outline text="child" xmlUrl="https://child.example.com/rss"/></outline>'
    )
    assert [e.name for e in parse("a.opml", opml(body))] == ["a"]


def test_the_document_order_is_kept():
    body = "".join(
        f'<outline text="f{i}" xmlUrl="https://f{i}.example.com/rss"/>' for i in range(5)
    )
    assert [e.name for e in parse("a.opml", opml(body))] == [f"f{i}" for i in range(5)]


def test_opml_with_a_utf8_bom_and_korean_text():
    content = opml('<outline text="스프링 블로그" xmlUrl="https://s.example.com/rss"/>').encode(
        "utf-8-sig"
    )
    assert parse("a.opml", content)[0].name == "스프링 블로그"


@pytest.mark.parametrize(
    "content", ["<not xml", "그냥 글자", "<html><body>hi</body></html>", "<feed/>"]
)
def test_files_that_are_not_opml_are_rejected(content):
    assert error_of("a.opml", content) == "OPML 형식이 올바르지 않음"


def test_an_opml_without_a_body_is_rejected():
    assert (
        error_of("a.opml", '<?xml version="1.0"?><opml version="2.0"></opml>')
        == "OPML 형식이 올바르지 않음"
    )


UNSAFE = "안전하지 않은 XML(DTD, 엔티티)은 허용하지 않음"


@pytest.mark.parametrize(
    "head",
    [
        '<!DOCTYPE opml [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>',
        '<!DOCTYPE opml [<!ENTITY xxe SYSTEM "http://127.0.0.1:9/x">]>',
        '<!DOCTYPE opml [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">'
        '<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;"><!ENTITY d "&c;&c;&c;&c;&c;&c;&c;&c;&c;&c;">]>',
        "<!DOCTYPE opml>",  # 아무 일도 하지 않는 DTD도 필요 없으므로 거부한다
    ],
)
def test_dtd_and_entities_are_rejected_without_echoing_anything(head):
    body = '<outline text="&xxe;&d;" xmlUrl="https://a.example.com/rss"/>'
    message = error_of("a.opml", opml(body, head))
    assert message == UNSAFE
    assert "root:" not in message and "etc/passwd" not in message


def test_a_very_deeply_nested_opml_does_not_crash_the_parser():
    depth = 5000
    body = (
        '<outline text="f">' * depth
        + '<outline xmlUrl="https://a.example.com/rss"/>'
        + "</outline>" * depth
    )
    try:
        entries = parse("a.opml", opml(body))
    except ImportFileError:
        return  # 거부해도 괜찮다. 중요한 것은 서버가 죽지 않는 것
    assert len(entries) == 1


# ---------- 미리보기 ----------


def entries(*urls, names=None):
    return [RawEntry((names or {}).get(u, u), u) for u in urls]


def test_new_and_duplicate_are_separated_and_existing_feeds_are_not_listed_as_new():
    preview = build_preview(
        entries(
            "https://a.example.com/feed", "https://c.example.com/rss", "https://d.example.com/rss"
        ),
        existing_keys={"https://a.example.com/feed", "https://b.example.com/rss"},
    )
    assert (preview.new_count, preview.duplicate_count, preview.error_count) == (2, 1, 0)
    assert preview.items[0].status == "duplicate" and preview.items[0].reason == "이미 구독 중"


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("https://n.example.com/rss", "https://n.example.com/rss"),
        ("https://n.example.com/rss", "https://N.Example.com/rss"),
        ("https://n.example.com/rss/", "https://n.example.com/rss"),
    ],
)
def test_the_same_address_in_one_file_is_counted_once(first, second):
    preview = build_preview(entries(first, second), existing_keys=set())
    assert (preview.new_count, preview.duplicate_count) == (1, 1)
    assert preview.items[1].reason == "파일 안에서 중복"


def test_existing_feeds_match_after_normalization():
    preview = build_preview(
        entries("https://N.Example.com/rss/"), existing_keys={"https://n.example.com/rss"}
    )
    assert preview.duplicate_count == 1


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("", "주소 없음"),
        ("ftp://x.example.com/feed", "http, https만 가능"),
        ("javascript:alert(1)", "http, https만 가능"),
        ("https://", "호스트 없음"),
        ("http://192.168.0.10/rss", "사설망·내부 주소는 허용하지 않음"),
        ("http://localhost/rss", "사설망·내부 주소는 허용하지 않음"),
        ("http://2130706433/rss", "사설망·내부 주소는 허용하지 않음"),
    ],
)
def test_bad_addresses_are_skipped_with_a_reason(url, reason):
    preview = build_preview(
        [*entries("https://a.example.com/rss", "https://b.example.com/rss"), RawEntry("x", url)],
        set(),
    )
    assert (preview.new_count, preview.error_count) == (2, 1)
    bad = preview.items[2]
    assert (bad.status, bad.reason) == ("error", reason)


def test_surrounding_spaces_in_addresses_are_ignored():
    preview = build_preview([RawEntry("a", "  https://a.example.com/rss \n")], set())
    assert preview.items[0].url == "https://a.example.com/rss"


def test_new_categories_are_suggested_in_order_without_those_that_already_exist():
    raw = [
        RawEntry("a", "https://a.example.com/rss", category="IT"),
        RawEntry("b", "https://b.example.com/rss", category="뉴스"),
        RawEntry("c", "https://c.example.com/rss", category="IT"),
        RawEntry("d", "https://d.example.com/rss", category="기존"),
        RawEntry("e", "https://e.example.com/rss"),
    ]
    preview = build_preview(raw, set(), existing_categories={"기존"})
    assert preview.new_categories == ("IT", "뉴스")


def test_categories_of_duplicates_and_errors_are_not_suggested():
    raw = [
        RawEntry("a", "https://a.example.com/rss", category="중복"),
        RawEntry("b", "ftp://b.example.com/rss", category="오류"),
    ]
    preview = build_preview(raw, {"https://a.example.com/rss"})
    assert preview.new_categories == ()


def test_the_position_in_the_file_is_kept_as_the_index():
    preview = build_preview(
        entries("https://a.example.com/rss", "ftp://x", "https://c.example.com/rss"), set()
    )
    assert [i.index for i in preview.items] == [0, 1, 2]


def test_the_preview_survives_being_stored_and_loaded():
    raw = [
        RawEntry("Gizmodo", "https://gizmodo.com/feed", "https://gizmodo.com", "뉴스"),
        RawEntry("bad", "ftp://x"),
        RawEntry("한글 이름", "https://k.example.com/rss"),
    ]
    preview = build_preview(raw, set())
    assert preview_from_json(preview_to_json(preview)) == preview


# ---------- 프리셋 제안 ----------


@pytest.mark.parametrize(
    ("name", "url", "html_url"),
    [
        ("Gizmodo", "https://x.example.com/rss", ""),
        ("gizmodo US", "https://x.example.com/rss", ""),
        ("Tech", "https://gizmodo.com/rss", ""),
        ("Tech", "https://x.example.com/rss", "https://gizmodo.com"),
        ("Tech", "https://x.example.com/rss", "https://us.gizmodo.example"),
    ],
)
def test_gizmodo_is_recognised_by_name_feed_address_or_site_address(name, url, html_url):
    assert suggest_preset(name, url, html_url) == GIZMODO


def test_awesome_blogs_gets_the_every_slot_preset():
    assert suggest_preset("목록", "https://awesome-blogs.petabytes.org/feed.xml", "") == EVERY_SLOT


@pytest.mark.parametrize(
    ("name", "url"), [("일반", "https://a.example.com/rss"), ("", "https://example.com/gizmo")]
)
def test_ordinary_feeds_get_no_preset(name, url):
    assert suggest_preset(name, url, "") is None


def test_preset_values_match_the_old_behaviour():
    assert (GIZMODO.poll_priority, GIZMODO.max_entries, GIZMODO.emoji) == ("every_slot", 120, "🧪")
    assert (EVERY_SLOT.poll_priority, EVERY_SLOT.max_entries, EVERY_SLOT.emoji) == (
        "every_slot",
        50,
        "📢",
    )


def test_presets_are_suggested_only_for_new_feeds():
    raw = [
        RawEntry("Gizmodo", "https://gizmodo.com/feed"),
        RawEntry("Gizmodo2", "https://gizmodo.com/feed2"),
        RawEntry("Gizmodo3", "ftp://gizmodo.com/feed3"),
    ]
    preview = build_preview(raw, {"https://gizmodo.com/feed2"})
    assert [i.preset for i in preview.items] == ["gizmodo", None, None]


def test_elements_other_than_outlines_inside_the_body_are_ignored():
    body = '<note>메모</note><outline text="a" xmlUrl="https://a.example.com/rss"/>'
    assert [e.name for e in parse("a.opml", opml(body))] == ["a"]


def test_more_than_two_thousand_opml_feeds_are_refused():
    body = "".join(
        f'<outline xmlUrl="https://f{i}.example.com/rss"/>' for i in range(MAX_FEEDS + 1)
    )
    assert error_of("a.opml", opml(body)) == "한 번에 가져올 수 있는 피드는 2000개까지"


def test_exactly_two_thousand_opml_feeds_are_accepted():
    body = "".join(f'<outline xmlUrl="https://f{i}.example.com/rss"/>' for i in range(MAX_FEEDS))
    assert len(parse("a.opml", opml(body))) == MAX_FEEDS
