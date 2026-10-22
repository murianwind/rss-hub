"""주제 판별 시험: 제목(과 본문)을 넣으면 실제 모델이 어떤 주제를 골랐는지, 키워드가 맞았는지,
최종적으로 해당하는지를 주제마다 보여 준다.

- 실제 요약과 같은 프롬프트와 같은 게이트웨이를 쓰므로 시험 한 번이 LLM 호출 1회(오늘 호출 수 +1)다.
- 글이나 알림을 만들지 않고, 아무것도 저장하지 않는다.
- 인증이 없는 화면에서 호출 한도를 소진하지 못하게 짧은 간격 제한을 둔다.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from rss_hub.domain.keywords import find_keywords, split_keywords
from rss_hub.domain.prompts import build_summary_prompt, summary_excerpt
from rss_hub.domain.topics import is_candidate
from rss_hub.domain.validation import validate_summary
from rss_hub.services.clock import Clock
from rss_hub.services.llm_gateway import BudgetBlocked, LlmGateway, LlmNotConfigured, LlmOutage
from rss_hub.services.ports import LlmErrorKind
from rss_hub.services.topic_examples import load_examples
from rss_hub.storage.topics import TopicRepository

MIN_INTERVAL = timedelta(seconds=5)
MAX_TITLE_LENGTH = 300
MAX_BODY_LENGTH = 5000


@dataclass(frozen=True)
class ProbeRow:
    name: str
    asked: bool  # 키워드가 맞아서(또는 키워드가 없는 주제라서) LLM에게 물었는가
    chosen: bool  # LLM이 이 주제를 골랐는가(물었을 때만 의미가 있다)
    keyword_hits: tuple[str, ...]  # 제목과 본문에서 일치한 키워드
    matched: bool  # 최종적으로 해당하는가(물었고 LLM이 골랐다)
    webhook_id: int | None


@dataclass(frozen=True)
class ProbeResult:
    rows: tuple[ProbeRow, ...] = ()
    title_ko: str = ""
    summary_ko: str = ""
    model: str = ""
    llm_called: bool = False  # 후보가 하나도 없으면 LLM을 호출하지 않는다
    error: str = ""  # 비어 있지 않으면 시험하지 못했다


def _outage_reason(kinds: set[LlmErrorKind]) -> str:
    """모든 모델이 실패한 이유 중 사용자가 고칠 수 있는 것을 먼저 알려 준다."""
    if LlmErrorKind.UNAUTHORIZED in kinds:
        return "OpenRouter가 키를 거부했습니다. 모델 화면에서 키를 다시 저장해 확인해 보세요"
    if LlmErrorKind.PAYMENT_REQUIRED in kinds:
        return "OpenRouter 잔액이 부족합니다"
    if LlmErrorKind.RATE_LIMITED in kinds:
        return "요청이 너무 많아 제한되었습니다. 잠시 뒤에 다시 시도하세요"
    return "모든 모델이 응답하지 않았습니다. 잠시 뒤에 다시 시도하세요"


class TopicProbe:
    def __init__(
        self,
        *,
        gateway: LlmGateway,
        topics: TopicRepository,
        clock: Clock,
        examples_count: Callable[[], int] = lambda: 0,
    ) -> None:
        self._examples_count = examples_count
        self._gateway = gateway
        self._topics = topics
        self._clock = clock
        self._last_call: datetime | None = None

    def run(self, title: str, body: str = "") -> ProbeResult:
        title, body = title.strip(), body.strip()
        if not title:
            return ProbeResult(error="제목을 입력하세요")
        if len(title) > MAX_TITLE_LENGTH:
            return ProbeResult(error=f"제목은 {MAX_TITLE_LENGTH}자까지")
        if len(body) > MAX_BODY_LENGTH:
            return ProbeResult(error=f"본문은 {MAX_BODY_LENGTH}자까지")
        topics = self._topics.list_all()
        if not topics:
            return ProbeResult(error="주제가 없습니다. 주제를 추가해 주세요")
        hits = {t.id: find_keywords(title, body, split_keywords(t.keywords)) for t in topics}
        candidates = [t for t in topics if is_candidate(t, title, body)]
        if not candidates:  # 키워드가 맞은 주제가 없으면 LLM에게 물을 것이 없다(호출 0회)
            rows = tuple(
                ProbeRow(t.name, False, False, hits[t.id], False, t.webhook_id) for t in topics
            )
            return ProbeResult(rows=rows)
        now = self._clock.now()
        if self._last_call is not None and now - self._last_call < MIN_INTERVAL:
            return ProbeResult(error="방금 시험했습니다. 잠시 뒤에 다시 시도하세요")

        self._last_call = now
        examples = load_examples(self._topics, candidates, self._examples_count())
        prompt = build_summary_prompt(title, summary_excerpt(body), candidates, examples)
        try:
            answer = self._gateway.complete(prompt)
        except LlmNotConfigured:
            return ProbeResult(error="OpenRouter 키가 설정되지 않았습니다")
        except BudgetBlocked:
            return ProbeResult(error="오늘 LLM 호출 한도에 도달해서 시험할 수 없습니다")
        except LlmOutage as outage:
            return ProbeResult(error=_outage_reason({kind for _, kind in outage.failures}))

        checked = validate_summary(
            answer.content, answer.finish_reason, valid_topic_ids={t.id for t in candidates}
        )
        if not checked.ok or checked.draft is None:
            return ProbeResult(
                error=f"모델의 응답을 사용할 수 없습니다({checked.reason})", model=answer.model
            )
        draft = checked.draft
        asked = {t.id for t in candidates}
        chosen = set(draft.topics)
        rows = tuple(
            ProbeRow(
                name=topic.name,
                asked=topic.id in asked,
                chosen=topic.id in chosen,
                keyword_hits=hits[topic.id],
                matched=topic.id in chosen,
                webhook_id=topic.webhook_id,
            )
            for topic in topics
        )
        return ProbeResult(
            rows=rows,
            title_ko=draft.title_ko,
            summary_ko=draft.summary_ko,
            model=answer.model,
            llm_called=True,
        )
