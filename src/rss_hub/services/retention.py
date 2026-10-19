"""글 보관 기간 정리: 보관 기간이 지난 글을 지운다(0이면 계속 보관)."""

from datetime import timedelta

from rss_hub.services.clock import Clock
from rss_hub.services.settings import SettingsService
from rss_hub.storage.articles import ArticleRepository


class RetentionService:
    def __init__(
        self, *, articles: ArticleRepository, settings: SettingsService, clock: Clock
    ) -> None:
        self._articles = articles
        self._settings = settings
        self._clock = clock

    def run(self) -> int:
        """지운 글 수. 보관 기간 설정은 실행할 때마다 읽는다."""
        days = self._settings.snapshot().article_retention_days
        if days == 0:
            return 0
        return self._articles.delete_older_than(self._clock.now() - timedelta(days=days))
