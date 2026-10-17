from rss_hub.domain.entries import extract_article_fields


def test_fields_are_taken_and_trimmed():
    fields = extract_article_fields(
        {
            "title": "  제목  ",
            "link": " https://x.com/a ",
            "summary": " <p>본문</p> ",
            "published": "Fri, 16 Oct 2026 01:30:00 +0900",
        }
    )
    assert fields.title == "제목"
    assert fields.link == "https://x.com/a"
    assert fields.content_html == "<p>본문</p>"
    assert fields.published_raw == "Fri, 16 Oct 2026 01:30:00 +0900"


def test_content_falls_back_from_summary_to_description():
    assert extract_article_fields({"description": "설명"}).content_html == "설명"
    assert extract_article_fields({"summary": "요약", "description": "설명"}).content_html == "요약"


def test_published_raw_falls_back_to_updated():
    assert extract_article_fields({"updated": "2026-10-16"}).published_raw == "2026-10-16"


def test_missing_fields_become_empty_strings():
    fields = extract_article_fields({})
    assert (fields.title, fields.link, fields.content_html, fields.published_raw) == (
        "",
        "",
        "",
        "",
    )


def test_none_values_are_treated_as_missing():
    fields = extract_article_fields({"title": None, "link": None, "summary": None})
    assert fields.title == "" and fields.link == "" and fields.content_html == ""
