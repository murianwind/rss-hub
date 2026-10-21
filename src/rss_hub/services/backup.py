"""백업 서비스: 내려받을 문서를 만들고, 올린 파일을 검사해서 복원한다."""

from collections.abc import Iterator

from rss_hub.domain.backup import BackupError, parse_backup
from rss_hub.domain.settings_rules import SettingError
from rss_hub.services.clock import Clock
from rss_hub.services.settings import ROLE_KEYS, SETTING_BY_KEY
from rss_hub.storage.backup import SCHEMA_VERSION, BackupRepository, RestoreResult
from rss_hub.storage.topics import SEEDED_KEY

# 백업에 넣고 복원하는 설정. 웹훅 역할(ROLE_KEYS)은 번호가 달라지므로 이름으로 따로 다룬다.
SETTING_KEYS = (*SETTING_BY_KEY, SEEDED_KEY)


class BackupService:
    def __init__(self, repository: BackupRepository, clock: Clock, app_version: str) -> None:
        self._repository = repository
        self._clock = clock
        self._version = app_version

    def export(self) -> tuple[str, Iterator[str]]:
        """(내려받을 파일 이름, JSON 조각)."""
        stamp = self._clock.now().strftime("%Y%m%d-%H%M%S")
        chunks = self._repository.export_chunks(
            setting_keys=SETTING_KEYS, role_keys=ROLE_KEYS, app_version=self._version
        )
        return f"rss-hub-backup-{stamp}.json", chunks

    def restore(self, raw: bytes) -> RestoreResult:
        """파일을 검사하고 현재 데이터를 그 내용으로 바꾼다. 올바르지 않으면 BackupError."""
        document = parse_backup(raw, max_schema_version=SCHEMA_VERSION)
        document["tables"]["settings"] = self._valid_settings(document["tables"]["settings"])
        return self._repository.restore(document, role_keys=ROLE_KEYS)

    @staticmethod
    def _valid_settings(rows: list[dict[str, object]]) -> list[dict[str, object]]:
        """아는 설정만 남기고, 값은 화면에서 저장할 때와 같은 규칙으로 검사한다."""
        kept = []
        for row in rows:
            key, value = row.get("key"), row.get("value")
            if key not in SETTING_KEYS or not isinstance(value, str):
                continue
            definition = SETTING_BY_KEY.get(key)
            if definition is not None:
                try:
                    value = definition.validate(value)
                except SettingError as error:
                    raise BackupError("백업 파일의 설정 값이 올바르지 않습니다") from error
            kept.append({**row, "value": value})
        return kept
