"""요약 서비스: 수집된 글의 제목을 번역하고 요약해서 발송할 수 있는 상태(ready)로 만든다.

- 불량 응답은 채택하지 않고 재시도 횟수를 올린다. 3번 쌓이면 원문 발췌로 확정한다.
- 호출 자체의 실패(장애)와 예산 때문에 막힌 경우는 재시도 횟수를 올리지 않는다.
  장애가 대기 허용 시간을 넘기면 원문 발췌로 확정한다.
"""

import logging
from dataclasses import dataclass
from datetime import timedelta

from rss_hub.domain.budget import BudgetBlock
from rss_hub.domain.korean import is_korean
from rss_hub.domain.prompts import build_summary_prompt, summary_excerpt
from rss_hub.domain.summary import summary_order
from rss_hub.domain.text import fallback_excerpt, strip_html
from rss_hub.domain.validation import validate_summary
from rss_hub.services.clock import Clock
from rss_hub.services.llm_gateway import BudgetBlocked, LlmGateway, LlmNotConfigured, LlmOutage
from rss_hub.services.settings import SettingsService
from rss_hub.storage.articles import STATUS_COLLECTED, Article, ArticleRepository
from rss_hub.storage.topics import TopicRepository

logger = logging.getLogger(__name__)

MAX_RETRIES = 3


@dataclass(frozen=True)
class SummarizeReport:
    considered: int = 0
    ready: int = 0
    rejected: int = 0
    fallback: int = 0
    outage: bool = False
    blocked: BudgetBlock | None = None
    waiting_for_setup: bool = False


class SummarizeService:
    def __init__(
        self,
        *,
        articles: ArticleRepository,
        gateway: LlmGateway,
        settings: SettingsService,
        topics: TopicRepository,
        clock: Clock,
    ) -> None:
        self._topics = topics
        self._articles = articles
        self._gateway = gateway
        self._settings = settings
        self._clock = clock

    def pending(self, limit: int) -> list[Article]:
        """이번에 처리할 글: 처음 처리하는 글을 먼저, 같은 그룹에서는 오래된 글부터."""
        return summary_order(self._articles.list_by_status(STATUS_COLLECTED))[:limit]

    def run(self) -> SummarizeReport:
        if not all(item.ready for item in self._settings.setup_checklist()):
            return SummarizeReport(waiting_for_setup=True)  # 필요한 설정이 채워질 때까지 기다린다

        config = self._settings.snapshot()
        targets = self.pending(config.summarize_batch)
        wait_limit = timedelta(minutes=config.llm_wait_limit_minutes)
        now = self._clock.now()

        ready = rejected = fallback = 0
        outage = False
        blocked: BudgetBlock | None = None

        for article in targets:
            overdue = now - article.discovered_at >= wait_limit
            if outage:  # 장애 중에는 더 호출하지 않고, 오래 기다린 글만 원문 발췌로 확정한다
                if overdue:
                    self._finalize_fallback(article)
                    fallback += 1
                continue
            try:
                outcome = self._summarize(article)
            except BudgetBlocked as stop:
                blocked = stop.reason
                break
            except LlmNotConfigured:
                return SummarizeReport(considered=len(targets), waiting_for_setup=True)
            except LlmOutage:
                outage = True
                if overdue:
                    self._finalize_fallback(article)
                    fallback += 1
                continue
            except Exception:
                logger.exception("글 요약 중 예상하지 못한 오류: article_id=%s", article.id)
                outcome = "rejected" if self._register_failure(article) == "retry" else "fallback"

            if outcome == "ready":
                ready += 1
            elif outcome == "rejected":
                rejected += 1
            else:
                fallback += 1

        return SummarizeReport(
            considered=len(targets),
            ready=ready,
            rejected=rejected,
            fallback=fallback,
            outage=outage,
            blocked=blocked,
        )

    # ---------- 글 하나 ----------

    def _summarize(self, article: Article) -> str:
        plain = strip_html(article.content_html)
        topics = self._topics.list_enabled()
        prompt = build_summary_prompt(article.title, summary_excerpt(article.content_html), topics)
        answer = self._gateway.complete(prompt)

        result = validate_summary(
            answer.content, answer.finish_reason, valid_topic_ids={t.id for t in topics}
        )
        if result.draft is None:
            return "rejected" if self._register_failure(article) == "retry" else "fallback"

        title = article.title if is_korean(f"{article.title} {plain}") else result.draft.title_ko
        self._articles.mark_ready(
            article.id,
            title_ko=title,
            summary_ko=result.draft.summary_ko,
            topics=result.draft.topics,
            model=answer.model,
        )
        return "ready"

    def _register_failure(self, article: Article) -> str:
        """불량 응답이나 예외를 재시도 1회로 센다.

        3번째면 원문 발췌로 확정하고 "fallback"을 돌려준다.
        """
        if self._articles.bump_retry(article.id) >= MAX_RETRIES:
            self._finalize_fallback(article)
            return "fallback"
        return "retry"

    def _finalize_fallback(self, article: Article) -> None:
        self._articles.finalize_fallback(
            article.id,
            title_ko=article.title,
            summary_ko=fallback_excerpt(strip_html(article.content_html)),
        )
