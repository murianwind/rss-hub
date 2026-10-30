"""발송 서비스: 요약이 끝난 글(ready)을 목적지마다 따로 Discord로 보내고 결과를 기록한다.

- 목적지는 피드, 카테고리, 기본 웹훅 순으로 정하고, OTT 글은 OTT 웹훅을 더한다.
- 목적지마다 결과를 따로 기록해서, 실패한 곳만 다시 보낸다.
  모두 보냈을 때만 글을 delivered로 바꾼다.
- 서비스 주소가 없으면 링크 없는 알림이 나가므로 발송을 보류한다.
- 웹훅 주소(토큰 포함)는 기록, 로그, 알림 문구에 넣지 않는다.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from rss_hub.domain.delivery import SendOutcome, classify_status, pause_after_send, retry_wait
from rss_hub.domain.error_log import KIND_DELIVER
from rss_hub.domain.message import article_url, build_message
from rss_hub.domain.routing import resolve_targets
from rss_hub.domain.topics import Topic, match_topic
from rss_hub.services.activity_log import NO_ACTIVITY, ActivityRecorder
from rss_hub.services.alerts import AlertService
from rss_hub.services.clock import Clock
from rss_hub.services.error_log import NO_ERRORS, ErrorRecorder
from rss_hub.services.ports import SendResult, WebhookSender
from rss_hub.services.settings import AppSettings, SettingsService
from rss_hub.storage.articles import STATUS_READY, Article, ArticleRepository
from rss_hub.storage.deliveries import (
    STATUS_PENDING,
    STATUS_SENT,
    Delivery,
    DeliveryRepository,
)
from rss_hub.storage.feeds import FeedRepository
from rss_hub.storage.topics import TopicRepository

logger = logging.getLogger(__name__)

MAX_ARTICLES_PER_RUN = 25
MAX_CONSECUTIVE_FAILURES = 3


@dataclass(frozen=True)
class DeliveryReport:
    considered: int = 0
    delivered: int = 0  # 모든 목적지로 보내서 완료한 글
    sent: int = 0  # 보낸 메시지
    failed: int = 0  # 이번에 보내지 못한 시도(다음 실행에서 다시 시도)
    permanent: int = 0  # 웹훅이 거부해서 더 시도하지 않는 목적지
    waiting_for_base_url: bool = False
    no_default_webhook: bool = False
    stopped_early: bool = False


@dataclass
class _Run:
    delivered: int = 0
    sent: int = 0
    failed: int = 0
    permanent: int = 0
    consecutive_failures: int = 0
    no_default_webhook: bool = False
    stopped_early: bool = False
    stop: bool = False


class DeliveryService:
    def __init__(
        self,
        *,
        articles: ArticleRepository,
        feeds: FeedRepository,
        deliveries: DeliveryRepository,
        settings: SettingsService,
        topics: TopicRepository,
        sender: WebhookSender,
        alerts: AlertService,
        clock: Clock,
        sleep: Callable[[float], None] = time.sleep,
        stop_requested: Callable[[], bool] = lambda: False,
        progress: Callable[[int, int], None] = lambda done, total: None,
        errors: ErrorRecorder = NO_ERRORS,
        activity: ActivityRecorder = NO_ACTIVITY,
    ) -> None:
        self._errors = errors
        self._activity = activity
        self._stop_requested = stop_requested
        self._progress = progress
        self._topics = topics
        self._articles = articles
        self._feeds = feeds
        self._deliveries = deliveries
        self._settings = settings
        self._sender = sender
        self._alerts = alerts
        self._clock = clock
        self._sleep = sleep

    def run(self) -> DeliveryReport:
        config = self._settings.snapshot()
        ready = self._articles.list_by_status(STATUS_READY)  # 발행 시각이 오래된 글부터
        if not config.base_url:
            return DeliveryReport(considered=len(ready), waiting_for_base_url=True)

        names = {w.id: w.name for w in self._settings.list_webhooks()}
        topics = self._topics.list_all()
        state = _Run()
        batch = ready[:MAX_ARTICLES_PER_RUN]
        for done, article in enumerate(batch):
            self._progress(done, len(batch))
            if state.stop:
                break
            if self._stop_requested():  # 서비스 종료 중: 지금 글까지 마치고 나머지는 ready로 남긴다
                state.stopped_early = True
                break
            try:
                self._deliver_article(article, topics, config, names, state)
            except Exception:
                logger.exception("글 발송 중 예상하지 못한 오류: article_id=%s", article.id)
        self._progress(len(batch), len(batch))
        return DeliveryReport(
            considered=len(ready),
            delivered=state.delivered,
            sent=state.sent,
            failed=state.failed,
            permanent=state.permanent,
            no_default_webhook=state.no_default_webhook,
            stopped_early=state.stopped_early,
        )

    # ---------- 글 하나 ----------

    def _deliver_article(
        self,
        article: Article,
        topics: list[Topic],
        config: AppSettings,
        names: dict[int, str],
        state: _Run,
    ) -> None:
        feed = self._feeds.get(article.feed_id)
        if feed is None:
            return
        flags = self._topics.flags_for(article.id)  # 사용자가 싫어요로 뺀 것과 "주제로" 넣은 것
        matches = {}
        for topic in topics:
            source, rejected = flags.get(topic.id, ("auto", False))
            if rejected:
                continue  # 싫어요로 뺀 주제로는 보내지 않는다
            hits = match_topic(topic, article.llm_topics, article.title, article.content_html)
            if hits is not None:
                matches[topic.id] = hits
            elif source == "manual":
                matches[topic.id] = ()  # 사용자가 직접 넣은 글은 키워드나 LLM과 상관없이 해당한다
        targets = resolve_targets(
            feed_webhook_id=feed.webhook_id,
            category_webhook_id=self._feeds.category_webhook_id(feed.category_id),
            default_webhook_id=config.webhook_default_id,
            topic_webhooks=[(t.id, t.webhook_id) for t in topics if t.id in matches],
        )
        if not targets:
            state.no_default_webhook = True
            state.stop = True
            self._alerts.notify(
                "delivery_no_webhook",
                "기본 웹훅 필요: 발송을 기다리는 글이 있지만 보낼 웹훅이 지정되어 있지 않습니다. "
                "설정 화면에서 기본 웹훅을 지정하세요.",
            )
            return
        self._topics.record_matches(article.id, matches)

        message = build_message(
            site=feed.name,
            emoji=feed.emoji,
            title=article.title_ko or article.title,
            summary=article.summary_ko or "",
            published=article.published_dt,
            link_url=article_url(config.base_url, article.id),
            tz=config.timezone,
        )
        for delivery in self._deliveries.ensure(article.id, targets):
            if delivery.status != STATUS_PENDING:
                continue  # 이미 보냈거나, 웹훅이 거부해서 더 시도하지 않는 목적지
            if not self._send_one(delivery, message, names, state):
                state.stop = True
                break

        wanted = {(t.webhook_id, t.purpose) for t in targets}
        current = [
            d
            for d in self._deliveries.for_article(article.id)
            if (d.webhook_id, d.purpose) in wanted
        ]
        if current and all(d.status == STATUS_SENT for d in current):
            self._articles.mark_delivered(article.id)
            state.delivered += 1

    # ---------- 목적지 하나 ----------

    def _send_one(
        self, delivery: Delivery, message: str, names: dict[int, str], state: _Run
    ) -> bool:
        """보낸다. 이번 실행을 계속해도 되면 True."""
        url = self._settings.get_webhook_url(delivery.webhook_id)
        if url is None:
            self._fail_permanently(delivery, "웹훅 주소를 찾을 수 없음", names, state)
            return True

        result = self._send(url, message)
        outcome = classify_status(result.status)
        if outcome is SendOutcome.RATE_LIMITED:
            self._deliveries.record_attempt_failure(delivery.id, "HTTP 429")
            self._note(delivery, names, "HTTP 429")
            self._sleep(retry_wait(result.retry_after))
            result = self._send(url, message)
            outcome = classify_status(result.status)
            if outcome is SendOutcome.RATE_LIMITED:
                self._deliveries.record_attempt_failure(delivery.id, "HTTP 429")
                self._note(delivery, names, "HTTP 429")
                state.failed += 1
                state.stopped_early = True  # 이번 실행에서는 더 시도하지 않는다
                return False

        if outcome is SendOutcome.SENT:
            self._deliveries.mark_sent(delivery.id, result.message_id)
            self._activity.done(
                KIND_DELIVER,
                names.get(delivery.webhook_id, f"#{delivery.webhook_id}"),
                "발송함",
                f"글 #{delivery.article_id}",
            )
            state.sent += 1
            state.consecutive_failures = 0
            pause = pause_after_send(result.rate_remaining, result.rate_reset_after)
            if pause:
                self._sleep(pause)  # 한도에 걸리기 전에 미리 기다린다
            return True

        reason = _reason(result)
        if outcome is SendOutcome.PERMANENT:
            self._fail_permanently(delivery, reason, names, state)
            return True

        self._deliveries.record_attempt_failure(delivery.id, reason)
        self._note(delivery, names, reason)
        state.failed += 1
        state.consecutive_failures += 1
        if state.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            state.stopped_early = True
            return False
        return True

    def _send(self, url: str, message: str) -> SendResult:
        try:
            return self._sender.send(url, message)
        except Exception as error:
            # 예외 문구에 주소가 들어 있을 수 있어서 종류 이름만 남긴다
            logger.warning("웹훅 전송 중 예외: %s", type(error).__name__)
            return SendResult(status=0, error=type(error).__name__)

    def _note(
        self, delivery: Delivery, names: dict[int, str], reason: str, *, permanent: bool = False
    ) -> None:
        source = names.get(delivery.webhook_id, f"#{delivery.webhook_id}")
        suffix = " (다시 시도하지 않음)" if permanent else ""
        message = f"발송하지 못함: {reason}{suffix}"
        self._errors.record(KIND_DELIVER, source, message, f"글 #{delivery.article_id}")
        self._activity.failed(KIND_DELIVER, source, message, f"글 #{delivery.article_id}")

    def _fail_permanently(
        self, delivery: Delivery, reason: str, names: dict[int, str], state: _Run
    ) -> None:
        self._deliveries.mark_permanent(delivery.id, reason)
        state.permanent += 1
        self._note(delivery, names, reason, permanent=True)
        name = names.get(delivery.webhook_id, f"#{delivery.webhook_id}")
        self._alerts.notify(
            f"delivery_permanent_{delivery.webhook_id}",
            f"웹훅 '{name}' 발송 실패({reason}): 웹훅이 삭제되었거나 거부하고 있습니다. "
            "설정 화면에서 웹훅을 확인하세요.",
        )


def _reason(result: SendResult) -> str:
    if result.status:
        return f"HTTP {result.status}"
    return result.error or "NetworkError"
