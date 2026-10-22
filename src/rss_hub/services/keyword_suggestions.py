"""주제 하나의 키워드 개선 제안: 근거가 되는 글과 더하면 좋을 단어, 빼면 좋을 키워드.

사용자가 지운 제안은 다시 내놓지 않는다.
"""

from dataclasses import dataclass

from rss_hub.domain.topic_suggestions import (
    AddSuggestion,
    RemoveSuggestion,
    suggest_additions,
    suggest_removals,
)
from rss_hub.domain.topics import Topic
from rss_hub.storage.topics import FeedbackSample, TopicRepository

KIND_ADD = "add"
KIND_REMOVE = "remove"


@dataclass(frozen=True)
class KeywordSuggestions:
    additions: tuple[AddSuggestion, ...]
    removals: tuple[RemoveSuggestion, ...]
    manual: tuple[FeedbackSample, ...]  # "주제로"로 직접 넣은 글
    rejected: tuple[FeedbackSample, ...]  # 싫어요로 뺀 글

    @property
    def count(self) -> int:
        return len(self.additions) + len(self.removals)


def keyword_suggestions(topics: TopicRepository, topic: Topic) -> KeywordSuggestions:
    samples = topics.feedback_samples(topic.id)
    manual = tuple(s for s in samples if s.source == "manual" and not s.rejected)
    rejected = tuple(s for s in samples if s.rejected)
    dismissed = topics.dismissed_suggestions(topic.id)
    additions = suggest_additions(
        [s.title for s in manual], [s.title for s in rejected], topic.keywords
    )
    removals = suggest_removals(topics.keyword_outcomes(topic.id))
    return KeywordSuggestions(
        tuple(a for a in additions if (KIND_ADD, a.keyword) not in dismissed),
        tuple(r for r in removals if (KIND_REMOVE, r.keyword) not in dismissed),
        manual,
        rejected,
    )
