"""백업 파일의 모양과 검사. 입출력 없이 파일 내용(JSON)만 본다.

파일 하나에 구독, 카테고리, 주제, 글, 읽음과 북마크, 설정이 들어간다. 웹훅 주소와 OpenRouter 키는
넣지 않는다. 웹훅은 이름만 적고, 어느 항목이 어느 웹훅을 쓰는지는 이름으로 이어 붙인다.
"""

import json
from typing import Any

FORMAT = "rss-hub-backup"
VERSION = 1
MAX_BACKUP_BYTES = 100 * 1024 * 1024  # 올릴 수 있는 파일의 최대 크기

# 복원할 표와 넣는 순서(앞의 표를 가리키는 표가 뒤에 온다). 지울 때는 반대로 지운다.
TABLE_ORDER = (
    "categories",
    "topics",
    "feeds",
    "feed_stats",
    "articles",
    "article_topics",
    "deliveries",
    "seen_guids",
    "settings",
)
WEBHOOK_COLUMN = "webhook_id"
WEBHOOK_TABLES = ("categories", "topics", "feeds", "deliveries")
ROLES = ("default", "system")


class BackupError(Exception):
    """화면에 그대로 보여 줄 수 있는 이유(message)를 가진 오류. 파일 내용은 담지 않는다."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _is_scalar(value: object) -> bool:
    return value is None or isinstance(value, str | int | float)


def parse_backup(raw: bytes, *, max_schema_version: int) -> dict[str, Any]:
    """파일 내용을 읽고 모양을 확인한다. 올바르지 않으면 BackupError."""
    try:
        document = json.loads(raw)
    except (ValueError, RecursionError) as error:
        raise BackupError("JSON 파일이 아닙니다") from error
    if not isinstance(document, dict) or document.get("format") != FORMAT:
        raise BackupError("이 서비스의 백업 파일이 아닙니다")
    if document.get("version") != VERSION:
        raise BackupError("지원하지 않는 백업 형식입니다")
    schema = document.get("schema_version")
    if not isinstance(schema, int) or isinstance(schema, bool) or schema < 1:
        raise BackupError("백업 파일의 버전을 읽을 수 없습니다")
    if schema > max_schema_version:
        raise BackupError("더 새로운 버전에서 만든 백업이라 이 버전에서는 복원할 수 없습니다")
    _check_webhooks(document)
    _check_tables(document)
    return document


def _check_webhooks(document: dict[str, Any]) -> None:
    webhooks, roles = document.get("webhooks"), document.get("roles")
    names_ok = isinstance(webhooks, list) and all(
        isinstance(w, dict) and isinstance(w.get("id"), int) and isinstance(w.get("name"), str)
        for w in webhooks
    )
    roles_ok = isinstance(roles, dict) and all(
        key in ROLES and (value is None or isinstance(value, str)) for key, value in roles.items()
    )
    if not names_ok or not roles_ok:
        raise BackupError("백업 파일의 웹훅 항목이 올바르지 않습니다")


def _check_tables(document: dict[str, Any]) -> None:
    tables = document.get("tables")
    if not isinstance(tables, dict) or set(tables) != set(TABLE_ORDER):
        raise BackupError("백업 파일에 빠졌거나 모르는 항목이 있습니다")
    for rows in tables.values():
        if not isinstance(rows, list):
            raise BackupError("백업 파일의 항목이 올바르지 않습니다")
        for row in rows:
            if not isinstance(row, dict) or not all(_is_scalar(v) for v in row.values()):
                raise BackupError("백업 파일의 항목이 올바르지 않습니다")
