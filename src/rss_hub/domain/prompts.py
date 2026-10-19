"""LLM에 보내는 요약 요청 만들기. 호출 방식의 근거는 docs/07-spike-s1-result.md."""

from collections.abc import Sequence

from rss_hub.domain.text import strip_html
from rss_hub.domain.topics import Topic

CONTENT_LIMIT = 1500

_TASK = "Translate the title to Korean and summarize the article in Korean in 2-3 sentences."
_TOPIC_TASK = (
    " Also check the candidate topics below, which were suggested by keywords found in the article."
    " Decide which of them the article is primarily about, using the topic numbers."
)
_RULES = """Rules:
- No markdown code fences, no explanations, no reasoning text.
- Do NOT use Chinese characters. Use pure Korean or English terms only.
- No HTML tags."""
_SHAPE = '{"title_ko": "<Korean translated title>", "summary_ko": "<2-3 sentence Korean summary>"}'
_SHAPE_WITH_TOPICS = (
    '{"title_ko": "<Korean translated title>", "summary_ko": "<2-3 sentence Korean summary>",'
    ' "topics": [<numbers of the matching topics, or an empty list>]}'
)


def summary_excerpt(content_html: str | None) -> str:
    """LLM에 보낼 본문: HTML을 지우고 앞 1500자만."""
    return strip_html(content_html)[:CONTENT_LIMIT]


def build_summary_prompt(title: str, excerpt: str, topics: Sequence[Topic] = ()) -> str:
    """요약 요청. 키워드가 맞은 후보 주제가 있으면 번호와 설명을 함께 보내서 한 번의 호출로 확인한다."""
    if topics:
        listing = "\n".join(
            f"{t.id}. {t.name}" + (f": {t.description}" if t.description else "") for t in topics
        )
        task = f"{_TASK}{_TOPIC_TASK}\n\nCandidate topics:\n{listing}"
        shape = _SHAPE_WITH_TOPICS
    else:
        task, shape = _TASK, _SHAPE
    # 글 안의 중괄호나 자리표시자가 틀을 깨지 않도록 문자열을 이어 붙여서 만든다
    return (
        f"{task}\n\nRespond with ONLY one JSON object and nothing else, in exactly this shape:\n"
        f"{shape}\n\n{_RULES}\n\nTitle: {title}\nContent: {excerpt}"
    )
