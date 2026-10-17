import sqlite3
import threading

import pytest

from rss_hub.storage.database import Database
from rss_hub.storage.migrations import MIGRATIONS

EXPECTED_TABLES = {
    "settings",
    "secrets",
    "settings_audit",
    "webhooks",
    "categories",
    "feeds",
    "feed_stats",
    "seen_guids",
    "articles",
    "llm_usage",
    "alert_log",
    "deliveries",
    "import_staging",
    "topics",
    "article_topics",
    "job_runs",
}


def table_names(conn):
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {row["name"] for row in rows}


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "rss_hub.db")


def test_first_connection_creates_the_file_and_all_tables(db, tmp_path):
    assert not (tmp_path / "rss_hub.db").exists()
    with db.connect() as conn:
        assert table_names(conn) >= EXPECTED_TABLES
    assert (tmp_path / "rss_hub.db").exists()


def test_creating_the_database_object_does_not_touch_the_disk(tmp_path):
    Database(tmp_path / "later.db")
    assert list(tmp_path.iterdir()) == []


def test_schema_version_matches_the_number_of_migrations(db):
    with db.connect() as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)


def test_migrations_are_idempotent_across_instances(tmp_path):
    path = tmp_path / "rss_hub.db"
    with Database(path).connect() as conn:
        conn.execute("INSERT INTO settings(key, value, updated_at) VALUES('k', 'v', 't')")
    with Database(path).connect() as conn:
        assert conn.execute("SELECT value FROM settings WHERE key='k'").fetchone()["value"] == "v"
        assert conn.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)


def test_connection_uses_wal_and_foreign_keys(db):
    with db.connect() as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_changes_are_committed_on_success(db):
    with db.connect() as conn:
        conn.execute("INSERT INTO settings(key, value, updated_at) VALUES('a', '1', 't')")
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM settings").fetchone()[0] == 1


def test_changes_are_rolled_back_on_error(db):
    with pytest.raises(RuntimeError), db.connect() as conn:
        conn.execute("INSERT INTO settings(key, value, updated_at) VALUES('a', '1', 't')")
        raise RuntimeError("중간에 실패")
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM settings").fetchone()[0] == 0


def test_rows_are_accessible_by_column_name(db):
    with db.connect() as conn:
        conn.execute("INSERT INTO settings(key, value, updated_at) VALUES('a', '1', 't')")
        row = conn.execute("SELECT * FROM settings").fetchone()
        assert isinstance(row, sqlite3.Row)
        assert row["key"] == "a"


def test_concurrent_first_use_migrates_only_once(tmp_path):
    database = Database(tmp_path / "rss_hub.db")
    errors: list[BaseException] = []

    def use() -> None:
        try:
            with database.connect() as conn:
                conn.execute("SELECT 1 FROM settings")
        except BaseException as error:
            errors.append(error)

    threads = [threading.Thread(target=use) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
