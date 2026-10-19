from rss_hub.domain.prompts import CONTENT_LIMIT, build_summary_prompt, summary_excerpt
from rss_hub.domain.topics import Topic


def test_excerpt_removes_html_and_keeps_the_first_1500_characters():
    html = "<p>" + "가" * 3000 + "</p>"
    excerpt = summary_excerpt(html)
    assert "<" not in excerpt
    assert len(excerpt) == CONTENT_LIMIT == 1500
    assert excerpt == "가" * 1500


def test_short_content_is_kept_whole():
    assert summary_excerpt("<b>짧은 글</b>") == "짧은 글"


def test_missing_content_becomes_empty():
    assert summary_excerpt(None) == "" and summary_excerpt("") == ""


def test_prompt_contains_the_title_and_the_excerpt():
    prompt = build_summary_prompt("Apple unveils new phone", "The phone lasts longer.")
    assert "Title: Apple unveils new phone" in prompt
    assert prompt.endswith("Content: The phone lasts longer.")


def test_prompt_asks_for_one_json_object_with_the_two_fields_when_there_are_no_topics():
    prompt = build_summary_prompt("t", "c")
    for field in ('"title_ko"', '"summary_ko"'):
        assert field in prompt
    assert '"topics"' not in prompt and "is_ott" not in prompt and "Candidate topics:" not in prompt
    assert "ONLY one JSON object" in prompt
    assert "Chinese characters" in prompt


def test_prompt_lists_the_topics_with_numbers_and_descriptions_and_asks_for_the_numbers():
    topics = [
        Topic(1, "OTT", "스트리밍 소식", ("netflix",), None, True),
        Topic(7, "게임", "", (), None, True),
    ]
    prompt = build_summary_prompt("t", "c", topics)
    assert "Candidate topics:\n1. OTT: 스트리밍 소식\n7. 게임\n" in prompt
    assert '"topics": [' in prompt and "using the topic numbers" in prompt
    assert "ONLY one JSON object" in prompt


def test_the_keywords_are_not_sent_to_the_llm():
    topic = Topic(1, "OTT", "설명", ("secret-keyword",), None, True)
    assert "secret-keyword" not in build_summary_prompt("t", "c", [topic])


def test_curly_braces_and_markers_in_the_article_do_not_break_the_prompt():
    prompt = build_summary_prompt("{title}", "{content} <<TITLE>> %s")
    assert "Title: {title}" in prompt
    assert prompt.endswith("Content: {content} <<TITLE>> %s")
