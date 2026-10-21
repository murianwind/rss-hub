"""LLM에 보내는 요약 요청 만들기. 호출 방식의 근거:
추론 모델은 답보다 '생각'에 토큰을 먼저 써서 글자 수 한도 안에서 답이 잘리거나 비므로,
추론을 끄고(`reasoning.effort=none`) JSON 출력을 강제한다."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from rss_hub.domain.text import strip_html
from rss_hub.domain.topics import Topic

CONTENT_LIMIT = 1500
EXAMPLE_TITLE_LIMIT = 80

_TASK = "Translate the title to Korean and summarize the article in Korean in 2-3 sentences."
_TOPIC_TASK = (
    " Also check the candidate topics below, which were suggested by keywords found in the article."
    " Decide which of them the article is primarily about, using the topic numbers."
)
_EXAMPLES_HINT = (
    " The examples were confirmed by the user; use them as hints and judge this article itself."
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


@dataclass(frozen=True)
class TopicExamples:
    """사용자가 직접 확인해 준 글 제목: 그 주제에 속한다고("주제로") 한 것과 아니라고("싫어요") 한 것."""

    belongs: tuple[str, ...] = ()
    not_belongs: tuple[str, ...] = ()


def _example(title: str) -> str:
    one_line = " ".join(title.replace('"', "'").split())
    return f'"{one_line[:EXAMPLE_TITLE_LIMIT]}"'


def _example_lines(examples: TopicExamples) -> str:
    lines = ""
    if examples.belongs:
        lines += "\n   Confirmed by the user, belongs: " + "; ".join(
            map(_example, examples.belongs)
        )
    if examples.not_belongs:
        lines += "\n   Confirmed by the user, does NOT belong: " + "; ".join(
            map(_example, examples.not_belongs)
        )
    return lines


def summary_excerpt(content_html: str | None) -> str:
    """LLM에 보낼 본문: HTML을 지우고 앞 1500자만."""
    return strip_html(content_html)[:CONTENT_LIMIT]


def build_summary_prompt(
    title: str,
    excerpt: str,
    topics: Sequence[Topic] = (),
    examples: Mapping[int, TopicExamples] | None = None,
) -> str:
    """요약 요청. 키워드가 맞은 후보 주제가 있으면 번호와 설명을 함께 보내서 한 번의 호출로 확인한다."""
    if topics:
        shown = {k: v for k, v in (examples or {}).items() if v.belongs or v.not_belongs}
        listing = "\n".join(
            f"{t.id}. {t.name}"
            + (f": {t.description}" if t.description else "")
            + (_example_lines(shown[t.id]) if t.id in shown else "")
            for t in topics
        )
        hint = _EXAMPLES_HINT if any(t.id in shown for t in topics) else ""
        task = f"{_TASK}{_TOPIC_TASK}{hint}\n\nCandidate topics:\n{listing}"
        shape = _SHAPE_WITH_TOPICS
    else:
        task, shape = _TASK, _SHAPE
    # 글 안의 중괄호나 자리표시자가 틀을 깨지 않도록 문자열을 이어 붙여서 만든다
    return (
        f"{task}\n\nRespond with ONLY one JSON object and nothing else, in exactly this shape:\n"
        f"{shape}\n\n{_RULES}\n\nTitle: {title}\nContent: {excerpt}"
    )
