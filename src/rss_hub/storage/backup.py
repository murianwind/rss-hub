"""백업 내보내기와 복원. 표 전체를 한 번에 읽고, 복원은 한 트랜잭션으로 바꾼다.

비밀 값(secrets 표)과 웹훅 주소는 읽지도 쓰지도 않는다. 웹훅은 이름으로만 다룬다.
"""

import json
import sqlite3
from collections.abc import Collection, Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from rss_hub.domain.backup import (
    FORMAT,
    ROLES,
    TABLE_ORDER,
    VERSION,
    WEBHOOK_COLUMN,
    WEBHOOK_TABLES,
    BackupError,
)
from rss_hub.services.clock import Clock
from rss_hub.storage.database import Database
from rss_hub.storage.migrations import MIGRATIONS
from rss_hub.storage.timestamps import to_iso

SCHEMA_VERSION = len(MIGRATIONS)
COUNTED_TABLES = ("feeds", "categories", "topics", "articles")


@dataclass(frozen=True)
class RestoreResult:
    counts: Mapping[str, int]  # 피드, 카테고리, 주제, 글의 수
    unlinked_webhooks: tuple[str, ...]  # 같은 이름의 웹훅이 없어서 지정을 해제한 웹훅 이름


def _dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


class BackupRepository:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    def export_chunks(
        self, *, setting_keys: Collection[str], role_keys: Mapping[str, str], app_version: str
    ) -> Iterator[str]:
        """JSON 문서를 조각으로 낸다(큰 글 표도 한 번에 메모리에 올리지 않는다)."""
        with self._db.connect() as conn:
            conn.execute("BEGIN")  # 표마다 읽는 시점이 달라지지 않게 한 시점의 내용으로 읽는다
            webhooks = [
                {"id": r["id"], "name": r["name"]}
                for r in conn.execute("SELECT id, name FROM webhooks ORDER BY id")
            ]
            names = {w["id"]: w["name"] for w in webhooks}
            roles = {role: self._role_name(conn, role_keys[role], names) for role in ROLES}
            head = {
                "format": FORMAT,
                "version": VERSION,
                "schema_version": SCHEMA_VERSION,
                "exported_at": to_iso(self._clock.now()),
                "app_version": app_version,
                "webhooks": webhooks,
                "roles": roles,
            }
            yield _dumps(head)[:-1] + ',"tables":{'
            for position, table in enumerate(TABLE_ORDER):
                yield ("," if position else "") + _dumps(table) + ":["
                yield from self._rows(conn, table, setting_keys)
                yield "]"
            yield "}}"

    @staticmethod
    def _role_name(conn: sqlite3.Connection, key: str, names: Mapping[int, str]) -> str | None:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        value = None if row is None else str(row["value"])
        return names.get(int(value)) if value is not None and value.isdecimal() else None

    @staticmethod
    def _rows(conn: sqlite3.Connection, table: str, setting_keys: Collection[str]) -> Iterator[str]:
        if table == "settings":
            marks = ",".join("?" for _ in setting_keys)
            cursor = conn.execute(
                f"SELECT * FROM settings WHERE key IN ({marks}) ORDER BY key", list(setting_keys)
            )
        else:
            cursor = conn.execute(f"SELECT * FROM {table} ORDER BY rowid")
        for position, row in enumerate(cursor):
            yield ("," if position else "") + _dumps(dict(row))

    def restore(
        self,
        document: Mapping[str, Any],
        *,
        role_keys: Mapping[str, str],
    ) -> RestoreResult:
        """현재 데이터를 문서의 내용으로 바꾼다. 하나라도 실패하면 아무것도 바꾸지 않는다."""
        tables: Mapping[str, list[dict[str, Any]]] = document["tables"]
        in_file = {w["id"]: w["name"] for w in document["webhooks"]}
        try:
            with self._db.connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                current = {
                    r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM webhooks")
                }
                unlinked: set[str] = set()

                def webhook(old_id: object) -> int | None:
                    name = in_file.get(old_id) if isinstance(old_id, int) else None
                    if name is None:
                        return None
                    if name not in current:
                        unlinked.add(name)
                    return current.get(name)

                for table in reversed(TABLE_ORDER):
                    conn.execute(f"DELETE FROM {table}")
                for table in TABLE_ORDER:
                    self._insert(conn, table, tables[table], webhook)
                for role in ROLES:
                    name = document["roles"].get(role)
                    if name is None:
                        continue
                    if name in current:
                        conn.execute(
                            "INSERT INTO settings(key, value, updated_at) VALUES(?, ?, ?)",
                            (role_keys[role], str(current[name]), to_iso(self._clock.now())),
                        )
                    else:
                        unlinked.add(name)
        except sqlite3.Error as error:
            raise BackupError("백업 내용이 이 서비스의 데이터와 맞지 않습니다") from error
        return RestoreResult(
            counts={table: len(tables[table]) for table in COUNTED_TABLES},
            unlinked_webhooks=tuple(sorted(unlinked)),
        )

    @staticmethod
    def _insert(
        conn: sqlite3.Connection,
        table: str,
        rows: list[dict[str, Any]],
        webhook: Any,
    ) -> None:
        known = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        for row in rows:
            if not row or not set(row) <= known:
                raise BackupError("백업 파일에 이 버전에 없는 항목이 있습니다")
            values = dict(row)
            if table in WEBHOOK_TABLES and WEBHOOK_COLUMN in values:
                values[WEBHOOK_COLUMN] = webhook(values[WEBHOOK_COLUMN])
                if table == "deliveries" and values[WEBHOOK_COLUMN] is None:
                    continue  # 보낼 곳이 없어진 발송 기록은 건너뛴다(글의 상태는 그대로다)
            columns = ", ".join(values)
            marks = ", ".join("?" for _ in values)
            conn.execute(f"INSERT INTO {table}({columns}) VALUES({marks})", list(values.values()))
