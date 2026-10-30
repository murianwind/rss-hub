"""요약 응답 검사를 게이트웨이의 거부 검사(Rejection)로 바꿔 준다."""

from collections.abc import Collection

from rss_hub.domain.validation import validate_summary
from rss_hub.services.llm_gateway import LlmAnswer, Rejection


def summary_rejection(valid_topic_ids: Collection[int] = ()) -> Rejection:
    """쓸 수 없는 요약 응답이면 거부 이유를 돌려주는 검사(모델 체인이 다음 모델로 넘어가는 기준)."""

    def check(answer: LlmAnswer) -> str | None:
        checked = validate_summary(
            answer.content, answer.finish_reason, valid_topic_ids=valid_topic_ids
        )
        return checked.reason.value if checked.reason else None

    return check
