"""수집 서비스: 이번 슬롯의 피드를 점검해서 오늘 발행된 새 글을 저장한다.

- 오늘 발행된 글만 모은다("오늘"은 설정의 서비스 시간대 기준).
- 이미 본 글(발송했거나 대기열에 있는 글)은 날짜와 상관없이 다시 모으지 않는다.
- 새로 등록한 피드의 첫 점검은 지금 있는 글을 "이미 본 글"로만 기록한다(알림 폭주 방지).
- 피드 하나가 실패해도 같은 슬롯의 나머지 피드는 계속 점검한다.
"""

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time

from rss_hub.domain.activity import measure_activity
from rss_hub.domain.dates import parse_entry_datetime
from rss_hub.domain.entries import extract_article_fields
from rss_hub.domain.guid import select_guid
from rss_hub.domain.schedule import (
    FeedRef,
    Schedule,
    build_schedule,
    schedule_fingerprint,
    slot_for,
)
from rss_hub.services.clock import Clock
from rss_hub.services.page_source import PageFeedSource
from rss_hub.services.ports import FeedFetcher, FetchError
from rss_hub.services.settings import AppSettings, SettingsService
from rss_hub.storage.articles import (
    PUBLISHED_DATE,
    PUBLISHED_EXACT,
    PUBLISHED_UNKNOWN,
    SEEN_BASELINE,
    SEEN_STALE,
    ArticleRepository,
    NewArticle,
)
from rss_hub.storage.feeds import KIND_PAGE, STATUS_BASELINE, Feed, FeedRepository

logger = logging.getLogger(__name__)

MAX_ENRICH_PER_RUN = 10  # 웹페이지 구독에서 한 번에 본문을 가져오는 새 글의 최대 수


@dataclass(frozen=True)
class CollectReport:
    checked: int
    added: int
    baseline_recorded: int
    failed: tuple[tuple[int, str], ...]
    archived: int = 0
    slot: int | None = None
    schedule_rebuilt: bool = False


class CollectService:
    def __init__(
        self,
        *,
        feeds: FeedRepository,
        articles: ArticleRepository,
        fetcher: FeedFetcher,
        settings: SettingsService,
        clock: Clock,
        pages: PageFeedSource | None = None,
    ) -> None:
        self._pages = pages
        self._feeds = feeds
        self._articles = articles
        self._fetcher = fetcher
        self._settings = settings
        self._clock = clock
        self._schedule_cache: tuple[str, Schedule] | None = None

    def run_slot(self) -> CollectReport:
        """지금 시각의 슬롯에 배정된 피드를 점검한다. 스케줄은 입력이 같으면 재사용한다."""
        config = self._settings.snapshot()
        local = self._clock.now().astimezone(config.timezone)
        feeds = self._feeds.list_all()
        refs = [FeedRef(str(f.id), f.poll_priority) for f in feeds]

        fingerprint = schedule_fingerprint(
            refs,
            config.collect_interval_minutes,
            local.date().isoformat(),
            local.strftime("%Y-%m-%dT%H"),
            config.slot_batch_size,
        )
        rebuilt = self._schedule_cache is None or self._schedule_cache[0] != fingerprint
        if rebuilt or self._schedule_cache is None:
            schedule = build_schedule(
                refs,
                self._feeds.activity_by_key(),
                config.collect_interval_minutes,
                config.slot_batch_size,
            )
            self._schedule_cache = (fingerprint, schedule)
        else:
            schedule = self._schedule_cache[1]

        slot = slot_for(local.minute, config.collect_interval_minutes)
        by_key = {str(f.id): f for f in feeds}
        batch = [by_key[key] for key in schedule.batches[slot]]
        report = self.collect_feeds(batch)
        return replace(report, slot=slot, schedule_rebuilt=rebuilt)

    def collect_feeds(self, feeds: Sequence[Feed]) -> CollectReport:
        """주어진 피드를 점검한다. 한 피드의 실패는 기록만 하고 나머지를 계속한다."""
        config = self._settings.snapshot()
        now = self._clock.now()
        local = now.astimezone(config.timezone)
        added = 0
        baseline = 0
        failed: list[tuple[int, str]] = []

        for feed in feeds:
            try:
                new_articles, recorded = self._check(feed, config, local)
            except FetchError as error:
                self._feeds.record_failure(feed.id, error.reason)
                failed.append((feed.id, error.reason))
            except Exception as error:  # 한 피드의 예상 못한 오류가 슬롯 전체를 막지 않게 한다
                logger.exception("피드 점검 중 예상하지 못한 오류: feed_id=%s", feed.id)
                self._feeds.record_failure(feed.id, type(error).__name__)
                failed.append((feed.id, type(error).__name__))
            else:
                added += new_articles
                baseline += recorded
        return CollectReport(
            checked=len(feeds), added=added, baseline_recorded=baseline, failed=tuple(failed)
        )

    def _check(self, feed: Feed, config: AppSettings, local: datetime) -> tuple[int, int]:
        """피드 하나를 점검하고 (새로 저장한 글 수, 기준선으로 기록한 글 수)를 돌려준다."""
        if feed.kind == KIND_PAGE:  # 웹페이지 구독: 목록 페이지에서 글을 뽑는다
            if self._pages is None:
                raise FetchError("PageSourceUnavailable")
            result = self._pages.fetch(feed.url)
        else:
            result = self._fetcher.fetch(feed.url, etag=feed.etag, last_modified=feed.last_modified)
        if result.status == 304:  # 변경 없음: 내용을 해석하지 않는다
            self._feeds.record_success(
                feed.id, etag=feed.etag, last_modified=feed.last_modified, activate=False
            )
            return 0, 0

        limit = feed.max_entries or config.default_max_entries
        today = local.date()
        examined = [
            (entry, parse_entry_datetime(entry, config.timezone))
            for entry in result.entries[:limit]
        ]
        self._feeds.save_stats(
            feed.id, measure_activity((moment for _, moment in examined), local, today)
        )

        added = 0
        recorded = 0
        if feed.status == STATUS_BASELINE:
            recorded = self._articles.mark_seen(
                (select_guid(entry) for entry, _ in examined), SEEN_BASELINE
            )
            self._archive_recent(feed, examined, config.baseline_archive_count, local)
        else:
            added = self._store_todays_articles(feed, examined, today, local)
        self._feeds.record_success(
            feed.id, etag=result.etag, last_modified=result.last_modified, activate=True
        )
        return added, recorded

    def _archive_recent(
        self,
        feed: Feed,
        examined: Sequence[tuple[object, datetime | None]],
        count: int,
        local: datetime,
    ) -> None:
        """첫 점검 때 가장 최근 글 count개를 뷰어용으로 보관한다. 알림도 요약도 하지 않는다."""
        oldest = datetime.min.replace(tzinfo=local.tzinfo)
        newest = sorted(examined, key=lambda item: item[1] or oldest, reverse=True)
        for entry, moment in newest[:count]:
            fields = extract_article_fields(entry)  # type: ignore[arg-type]
            published, kind = moment or local, _kind_of(entry, moment)
            content = fields.content_html
            if feed.kind == KIND_PAGE and kind == PUBLISHED_UNKNOWN and self._pages is not None:
                details = self._pages.read_article_details(fields.link, local.tzinfo or UTC)
                content = content or details.content
                if details.published is not None:
                    published, kind = _noon(details.published, local), PUBLISHED_DATE
            self._articles.add_archived(
                NewArticle(
                    feed_id=feed.id,
                    guid=select_guid(entry),  # type: ignore[arg-type]
                    title=fields.title,
                    link=fields.link,
                    content_html=content,
                    published_raw=fields.published_raw,
                    published_dt=published,
                    published_date=published.date().isoformat(),
                    published_kind=kind,
                )
            )

    def _store_todays_articles(
        self,
        feed: Feed,
        examined: Sequence[tuple[object, datetime | None]],
        today: date,
        local: datetime,
    ) -> int:
        added = 0
        enriched = 0
        for entry, moment in examined:
            if moment is None or moment.date() != today:
                continue
            fields = extract_article_fields(entry)  # type: ignore[arg-type]
            guid = select_guid(entry)  # type: ignore[arg-type]
            content = fields.content_html
            published, kind = moment, _kind_of(entry, moment)
            if (
                feed.kind == KIND_PAGE
                and (not content or kind == PUBLISHED_UNKNOWN)
                and self._pages is not None
                and enriched < MAX_ENRICH_PER_RUN
                and not self._articles.is_seen(guid)
            ):
                details = self._pages.read_article_details(fields.link, local.tzinfo or UTC)
                enriched += 1
                content = content or details.content  # 요약은 본문이 있어야 잘 나온다
                if kind == PUBLISHED_UNKNOWN and details.published is not None:
                    if details.published != today:  # 오래된 글이 오늘 글로 알림 가지 않게 한다
                        self._articles.mark_seen([guid], SEEN_STALE)
                        continue
                    published, kind = _noon(details.published, local), PUBLISHED_DATE
            article = NewArticle(
                feed_id=feed.id,
                guid=guid,
                title=fields.title,
                link=fields.link,
                content_html=content,
                published_raw=fields.published_raw,
                published_dt=published,
                published_date=published.date().isoformat(),
                published_kind=kind,
            )
            if self._articles.add(article) is not None:
                added += 1
        return added


def _kind_of(entry: object, moment: datetime | None) -> str:
    """항목의 발행일을 얼마나 아는지. 웹페이지 구독 항목은 수집원이 적어 둔다."""
    if moment is None:
        return PUBLISHED_UNKNOWN
    written = entry.get("published_kind") if isinstance(entry, Mapping) else None
    return written if isinstance(written, str) else PUBLISHED_EXACT


def _noon(day: date, local: datetime) -> datetime:
    """날짜만 아는 값은 그날 낮 12시로 저장한다(하루 중 어느 때든 같은 날이다)."""
    return datetime.combine(day, time(12), tzinfo=local.tzinfo)
