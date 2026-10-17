"""가져오기 서비스: 파일을 올리면 미리보기만 만들고, 확정해야 구독 목록에 반영한다.

- 미리보기는 60분 동안만 보관한다. 만료되었거나 이미 쓴 토큰은 확정할 수 없다.
- 확정한 피드는 baseline_pending으로 등록한다. 첫 점검에서 지금 있는 글을 "이미 본 글"로만
  기록하므로, 기존 시스템이 이미 보낸 글이 다시 나가지 않는다.
- 미리보기와 확정 사이에 같은 피드가 생겼으면 오류가 아니라 중복으로 센다.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta

from rss_hub.domain.importing import (
    PRESETS,
    STATUS_NEW,
    Preview,
    build_preview,
    parse_import_file,
    preview_from_json,
    preview_to_json,
)
from rss_hub.services.clock import Clock
from rss_hub.storage.feeds import DEFAULT_EMOJI, DuplicateFeedError, FeedRepository
from rss_hub.storage.import_staging import ImportStagingRepository

PREVIEW_TTL = timedelta(minutes=60)


class PreviewExpired(Exception):
    message = "미리보기가 만료됨, 파일을 다시 올려 주세요"

    def __init__(self) -> None:
        super().__init__(self.message)


@dataclass(frozen=True)
class StoredPreview:
    token: str
    preview: Preview


@dataclass(frozen=True)
class ImportChoices:
    """확정할 때 사용자가 고른 것. 비어 있으면 기본값(카테고리 가져오기 켬, 제안된 프리셋 적용)."""

    import_categories: bool = True
    presets: Mapping[int, bool] = field(default_factory=dict)  # 항목 위치 -> 프리셋 적용 여부


@dataclass(frozen=True)
class ImportResult:
    created: int
    duplicate: int
    error: int
    categories_created: int


class ImportService:
    def __init__(
        self,
        *,
        feeds: FeedRepository,
        staging: ImportStagingRepository,
        clock: Clock,
    ) -> None:
        self._feeds = feeds
        self._staging = staging
        self._clock = clock

    def preview(self, filename: str, data: bytes) -> StoredPreview:
        """파일을 읽어서 미리보기를 만들고 보관한다. 구독 목록은 바꾸지 않는다."""
        entries = parse_import_file(filename, data)  # 파일이 잘못되면 ImportFileError
        self._staging.purge_expired()
        preview = build_preview(
            entries,
            existing_keys=self._feeds.existing_url_keys(),
            existing_categories=self._feeds.category_names(),
        )
        token = self._staging.save(preview_to_json(preview), ttl=PREVIEW_TTL)
        return StoredPreview(token=token, preview=preview)

    def load(self, token: str) -> Preview:
        payload = self._staging.load(token)
        if payload is None:
            raise PreviewExpired
        return preview_from_json(payload)

    def confirm(self, token: str, choices: ImportChoices | None = None) -> ImportResult:
        """미리보기의 신규 피드를 등록한다. 한 번 쓴 토큰은 다시 쓸 수 없다."""
        choices = choices or ImportChoices()
        preview = self.load(token)
        created = 0
        duplicate = preview.duplicate_count
        categories_created = 0

        for item in preview.items:
            if item.status != STATUS_NEW:
                continue
            preset = (
                PRESETS[item.preset]
                if item.preset and choices.presets.get(item.index, True)
                else None
            )
            category_id = None
            if choices.import_categories and item.category:
                category_id, was_created = self._feeds.get_or_create_category(item.category)
                categories_created += int(was_created)
            try:
                self._feeds.add(
                    item.url,
                    item.name,
                    html_url=item.html_url,
                    emoji=preset.emoji if preset else DEFAULT_EMOJI,
                    poll_priority=preset.poll_priority if preset else "normal",
                    max_entries=preset.max_entries if preset else None,
                    category_id=category_id,
                )
            except DuplicateFeedError:
                duplicate += 1
                continue
            created += 1

        self._staging.delete(token)
        return ImportResult(
            created=created,
            duplicate=duplicate,
            error=preview.error_count,
            categories_created=categories_created,
        )

    def cancel(self, token: str) -> None:
        self._staging.delete(token)
