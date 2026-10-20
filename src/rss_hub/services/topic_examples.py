"""요약 요청에 넣을, 사용자가 확인한 예시(주제로, 싫어요)를 후보 주제마다 불러온다."""

from collections.abc import Sequence

from rss_hub.domain.prompts import TopicExamples
from rss_hub.domain.topics import Topic
from rss_hub.storage.topics import TopicRepository


def load_examples(
    repo: TopicRepository, candidates: Sequence[Topic], per_kind: int
) -> dict[int, TopicExamples]:
    """후보 주제마다 최근 예시를 종류별로 per_kind개까지. 0이면 아무것도 넣지 않는다."""
    if per_kind <= 0:
        return {}
    found: dict[int, TopicExamples] = {}
    for topic in candidates:
        samples = repo.feedback_samples(topic.id)
        belongs = tuple(s.title for s in samples if not s.rejected)[:per_kind]
        not_belongs = tuple(s.title for s in samples if s.rejected)[:per_kind]
        if belongs or not_belongs:
            found[topic.id] = TopicExamples(belongs, not_belongs)
    return found
