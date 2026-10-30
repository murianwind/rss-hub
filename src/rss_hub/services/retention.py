"""보관 기간 정리: 보관 기간이 지난 글(0이면 계속 보관)과 오류 기록, 작업 이력을 지운다."""

from datetime import UTC, timedelta

from rss_hub.services.clock import Clock
from rss_hub.services.settings import SettingsService
from rss_hub.storage.activity_log import ActivityLogRepository
from rss_hub.storage.articles import ArticleRepository
from rss_hub.storage.error_log import ErrorLogRepository


class RetentionService:
    def __init__(
        self,
        *,
        articles: ArticleRepository,
        settings: SettingsService,
        clock: Clock,
        error_log: ErrorLogRepository | None = None,
        activity: ActivityLogRepository | None = None,
    ) -> None:
        self._articles = articles
        self._settings = settings
        self._clock = clock
        self._error_log = error_log
        self._activity = activity

    def run(self) -> int:
        """지운 글 수. 보관 기간 설정은 실행할 때마다 읽는다. 오래된 오류 기록도 함께 지운다."""
        config = self._settings.snapshot()
        now = self._clock.now()
        cutoff = (now - timedelta(days=config.error_log_retention_days)).astimezone(UTC).date()
        if self._error_log is not None:
            self._error_log.delete_before(cutoff)
        if self._activity is not None:
            self._activity.delete_before(cutoff)
        if config.article_retention_days == 0:
            return 0
        return self._articles.delete_older_than(now - timedelta(days=config.article_retention_days))
