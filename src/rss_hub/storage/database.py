"""SQLite 연결. 요청마다 새 연결을 열고, 성공하면 커밋하고 실패하면 변경을 버린다."""

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from rss_hub.storage.migrations import apply_migrations

BUSY_TIMEOUT_SECONDS = 5.0


class Database:
    """객체를 만드는 것만으로는 디스크를 건드리지 않는다.

    처음 연결할 때 파일을 만들고 마이그레이션한다.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._ready = False
        self._lock = threading.Lock()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self._ensure_ready()
        conn = self._open()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()  # 커밋하지 않고 닫으면 SQLite가 변경을 버린다(오류 시 되돌리기)

    def _open(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, timeout=BUSY_TIMEOUT_SECONDS)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _ensure_ready(self) -> None:
        if self._ready:
            return
        with self._lock:
            if self._ready:
                return
            conn = self._open()
            try:
                conn.execute("PRAGMA journal_mode = WAL")
                apply_migrations(conn)
                conn.commit()
            finally:
                conn.close()
            self._ready = True
