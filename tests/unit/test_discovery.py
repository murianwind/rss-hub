import pytest

from rss_hub.domain.discovery import describe_fetch_failure, find_feed_links


def links(html, base="https://blog.example.com/posts/1"):
    return [(link.url, link.title) for link in find_feed_links(html, base)]


def test_rss_and_atom_alternate_links_are_found_in_order():
    html = """<html><head>
    <link rel="alternate" type="application/rss+xml" title="글 피드" href="/feed.xml">
    <link rel="alternate" type="application/atom+xml" title="Atom" href="https://blog.example.com/atom.xml">
    </head></html>"""
    assert links(html) == [
        ("https://blog.example.com/feed.xml", "글 피드"),
        ("https://blog.example.com/atom.xml", "Atom"),
    ]


@pytest.mark.parametrize(
    ("href", "expected"),
    [
        ("/feed.xml", "https://blog.example.com/feed.xml"),
        ("feed.xml", "https://blog.example.com/posts/feed.xml"),
        ("../feed.xml", "https://blog.example.com/feed.xml"),
        ("//cdn.example.com/feed.xml", "https://cdn.example.com/feed.xml"),
        ("https://other.example.com/rss", "https://other.example.com/rss"),
        ("/feed.xml?a=1&amp;b=2", "https://blog.example.com/feed.xml?a=1&b=2"),
    ],
)
def test_relative_addresses_are_resolved_against_the_final_page_address(href, expected):
    html = f'<link rel="alternate" type="application/rss+xml" href="{href}">'
    assert links(html)[0][0] == expected


def test_attribute_case_and_extra_rel_values_are_tolerated():
    html = '<LINK REL="Alternate Home" TYPE="Application/RSS+XML; charset=utf-8" HREF="/f.xml">'
    assert links(html) == [("https://blog.example.com/f.xml", "")]


@pytest.mark.parametrize(
    "html",
    [
        '<link rel="stylesheet" href="/a.css">',
        '<link rel="alternate" type="text/html" href="/ko/">',
        '<link rel="alternate" type="application/json" href="/feed.json">',
        '<link rel="alternate" type="application/rss+xml">',
        '<link rel="alternate" type="application/rss+xml" href="">',
        '<link rel="alternate" type="application/rss+xml" href="javascript:alert(1)">',
        '<link rel="alternate" type="application/rss+xml" href="ftp://x.example.com/f">',
        '<link rel="alternate" type="application/rss+xml" href="data:text/xml,x">',
        '<a href="/feed.xml">RSS</a>',
        "",
    ],
)
def test_links_that_are_not_usable_feeds_are_ignored(html):
    assert links(html) == []


def test_duplicates_are_removed_and_at_most_ten_are_returned():
    html = "".join(
        f'<link rel="alternate" type="application/rss+xml" href="/f{i}.xml">' for i in range(15)
    )
    html += '<link rel="alternate" type="application/rss+xml" href="/f0.xml">'
    found = links(html)
    assert len(found) == 10 and len({url for url, _ in found}) == 10


def test_a_title_is_trimmed_and_missing_titles_are_empty():
    html = '<link rel="alternate" type="application/rss+xml" title="  글 피드  " href="/f.xml">'
    assert links(html)[0][1] == "글 피드"


def test_broken_markup_does_not_raise():
    assert (
        links('<link rel="alternate" type="application/rss+xml" href="/f.xml"<<<>>><p') is not None
    )


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        ("ForbiddenAddress", "사설망·내부 주소는 허용하지 않음"),
        ("NotAFeed", "피드가 아닙니다"),
        ("TooLarge", "응답이 너무 큽니다"),
        ("HTTP 404", "주소를 열지 못했습니다(HTTP 404)"),
        ("HTTP 503", "주소를 열지 못했습니다(HTTP 503)"),
        ("ConnectTimeout", "응답이 없습니다(시간 초과)"),
        ("ReadTimeout", "응답이 없습니다(시간 초과)"),
        ("ConnectionError", "주소에 연결하지 못했습니다"),
        ("SSLError", "보안 연결(HTTPS)을 확인하지 못했습니다"),
        ("SomethingElse", "가져오지 못했습니다(SomethingElse)"),
    ],
)
def test_fetch_failures_are_described_without_any_address(reason, expected):
    assert describe_fetch_failure(reason) == expected


def test_an_unusable_base_address_yields_no_links_instead_of_an_error():
    html = '<link rel="alternate" type="application/rss+xml" href="/feed.xml">'
    assert links(html, base="http://[not-an-address") == []


def test_a_parser_failure_returns_what_was_found_so_far_without_raising(monkeypatch):
    from rss_hub.domain import discovery

    def explode(self, data):
        raise RuntimeError("parser failure")

    monkeypatch.setattr(discovery._LinkParser, "feed", explode)
    assert find_feed_links("<html>", "https://blog.example.com/") == []
