"""스키마 마이그레이션. 번호는 목록의 순서이고, SQLite의 user_version에 적용된 개수를 기록한다.

이미 적용된 항목은 고치지 않는다. 스키마를 바꾸려면 목록 끝에 새 항목을 추가한다.
"""

import sqlite3

MIGRATIONS: tuple[str, ...] = (
    # 1: 설정, 비밀 값, 변경 이력, 웹훅
    """
    CREATE TABLE settings (
        key        TEXT PRIMARY KEY,
        value      TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE secrets (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    CREATE TABLE settings_audit (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        key        TEXT NOT NULL,
        changed_at TEXT NOT NULL,
        summary    TEXT NOT NULL
    );
    CREATE TABLE webhooks (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        name       TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL
    );
    """,
    # 2: 카테고리, 피드, 피드 통계, 본 글 기록, 글
    """
    CREATE TABLE categories (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        name       TEXT NOT NULL UNIQUE,
        webhook_id INTEGER REFERENCES webhooks(id) ON DELETE SET NULL
    );
    CREATE TABLE feeds (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        url           TEXT NOT NULL,
        url_key       TEXT NOT NULL UNIQUE,
        name          TEXT NOT NULL,
        html_url      TEXT NOT NULL DEFAULT '',
        category_id   INTEGER REFERENCES categories(id) ON DELETE SET NULL,
        webhook_id    INTEGER REFERENCES webhooks(id) ON DELETE SET NULL,
        emoji         TEXT NOT NULL DEFAULT '📢',
        poll_priority TEXT NOT NULL DEFAULT 'normal',
        ott_check     INTEGER NOT NULL DEFAULT 1,
        max_entries   INTEGER,
        status        TEXT NOT NULL DEFAULT 'baseline_pending',
        fail_count    INTEGER NOT NULL DEFAULT 0,
        last_error    TEXT,
        etag          TEXT,
        last_modified TEXT,
        last_checked_at TEXT,
        created_at    TEXT NOT NULL
    );
    CREATE TABLE feed_stats (
        feed_id           INTEGER PRIMARY KEY REFERENCES feeds(id) ON DELETE CASCADE,
        recent_count_7d   INTEGER NOT NULL,
        target_date_count INTEGER NOT NULL,
        last_published_dt TEXT,
        updated_at        TEXT NOT NULL
    );
    CREATE TABLE seen_guids (
        guid          TEXT PRIMARY KEY,
        reason        TEXT NOT NULL,
        first_seen_at TEXT NOT NULL
    );
    CREATE TABLE articles (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        feed_id       INTEGER NOT NULL REFERENCES feeds(id) ON DELETE CASCADE,
        guid          TEXT NOT NULL UNIQUE,
        title         TEXT NOT NULL,
        link          TEXT NOT NULL,
        content_html  TEXT NOT NULL,
        published_raw TEXT NOT NULL,
        published_dt  TEXT NOT NULL,
        published_date TEXT NOT NULL,
        discovered_at TEXT NOT NULL,
        status        TEXT NOT NULL DEFAULT 'collected',
        title_ko      TEXT,
        summary_ko    TEXT,
        is_ott        INTEGER,
        llm_model     TEXT,
        retry_count   INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX articles_by_status ON articles(status, published_dt);
    """,
    # 3: LLM 호출 기록, 시스템 알림 기록
    """
    CREATE TABLE llm_usage (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        called_at         TEXT NOT NULL,
        day               TEXT NOT NULL,
        model             TEXT NOT NULL,
        outcome           TEXT NOT NULL,
        status            INTEGER NOT NULL,
        prompt_tokens     INTEGER,
        completion_tokens INTEGER,
        reasoning_tokens  INTEGER
    );
    CREATE INDEX llm_usage_by_day ON llm_usage(day);
    CREATE INDEX llm_usage_by_time ON llm_usage(called_at);
    CREATE TABLE alert_log (
        id      INTEGER PRIMARY KEY AUTOINCREMENT,
        kind    TEXT NOT NULL,
        sent_at TEXT NOT NULL,
        text    TEXT NOT NULL
    );
    CREATE INDEX alert_log_by_kind ON alert_log(kind, sent_at);
    """,
    # 4: 발송 기록(글 하나를 목적지마다 따로 기록한다)
    """
    CREATE TABLE deliveries (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
        webhook_id INTEGER NOT NULL REFERENCES webhooks(id) ON DELETE CASCADE,
        purpose    TEXT NOT NULL,
        status     TEXT NOT NULL DEFAULT 'pending',
        attempts   INTEGER NOT NULL DEFAULT 0,
        last_error TEXT,
        message_id TEXT,
        sent_at    TEXT,
        created_at TEXT NOT NULL,
        UNIQUE(article_id, webhook_id, purpose)
    );
    CREATE INDEX deliveries_by_status ON deliveries(status);
    """,
    # 5: 가져오기 미리보기 임시 보관(확정하기 전까지 구독 목록은 바뀌지 않는다)
    """
    CREATE TABLE import_staging (
        token      TEXT PRIMARY KEY,
        payload    TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL
    );
    CREATE INDEX import_staging_by_expiry ON import_staging(expires_at);
    """,
    # 6: 주제 알림. 글에는 LLM이 고른 주제 번호를 기록한다.
    # feeds.webhook_id, feeds.ott_check, articles.is_ott 열은 더 이상 쓰지 않는다
    # (SQLite는 외래 키가 걸린 열을 지울 수 없어서 남겨 둔다).
    """
    ALTER TABLE articles ADD COLUMN llm_topics TEXT;
    CREATE TABLE topics (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT NOT NULL,
        name_key    TEXT NOT NULL UNIQUE,
        description TEXT NOT NULL DEFAULT '',
        keywords    TEXT NOT NULL DEFAULT '[]',
        webhook_id  INTEGER REFERENCES webhooks(id) ON DELETE SET NULL,
        enabled     INTEGER NOT NULL DEFAULT 1,
        created_at  TEXT NOT NULL
    );
    CREATE TABLE article_topics (
        article_id       INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
        topic_id         INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
        matched_keywords TEXT NOT NULL DEFAULT '[]',
        PRIMARY KEY (article_id, topic_id)
    );
    """,
    # 7: 잡 실행 기록(작업마다 한 줄). /healthz와 /status가 읽고,
    # 재시작해도 지나간 슬롯을 따라잡지 않는 기준이 된다
    """
    CREATE TABLE job_runs (
        job              TEXT PRIMARY KEY,
        last_started_at  TEXT,
        last_finished_at TEXT,
        last_ok_at       TEXT,
        last_status      TEXT,
        last_error       TEXT,
        last_slot        TEXT,
        skipped_count    INTEGER NOT NULL DEFAULT 0,
        last_skipped_at  TEXT
    );
    """,
    # 8: 사용자가 정한 주제 소속(M5). source는 auto(요약이 판정) 또는 manual("주제로"),
    # rejected는 "싫어요"로 그 주제 목록에서 뺐다는 표시(되돌릴 수 있다)
    """
    ALTER TABLE article_topics ADD COLUMN source TEXT NOT NULL DEFAULT 'auto';
    ALTER TABLE article_topics ADD COLUMN rejected INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE article_topics ADD COLUMN decided_at TEXT;
    """,
    # 9: 무료 모델 목록(스캔), 벤치마크 실행과 점수(M3)
    """
    CREATE TABLE model_catalog (
        id             TEXT PRIMARY KEY,
        name           TEXT NOT NULL,
        context_length INTEGER NOT NULL,
        supports_json  INTEGER NOT NULL,
        first_seen_at  TEXT NOT NULL,
        last_seen_at   TEXT NOT NULL,
        gone           INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE benchmark_runs (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        status      TEXT NOT NULL,
        started_at  TEXT NOT NULL,
        finished_at TEXT,
        total       INTEGER NOT NULL,
        done        INTEGER NOT NULL DEFAULT 0,
        note        TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE benchmark_scores (
        run_id INTEGER NOT NULL REFERENCES benchmark_runs(id) ON DELETE CASCADE,
        model  TEXT NOT NULL,
        calls  INTEGER NOT NULL,
        ok     INTEGER NOT NULL,
        korean INTEGER NOT NULL,
        topic  INTEGER NOT NULL,
        p50_ms INTEGER,
        score  REAL NOT NULL,
        errors TEXT NOT NULL DEFAULT '[]',
        PRIMARY KEY (run_id, model)
    );
    """,
)


def apply_migrations(conn: sqlite3.Connection) -> None:
    """아직 적용하지 않은 마이그레이션만 순서대로 적용한다."""
    applied = int(conn.execute("PRAGMA user_version").fetchone()[0])
    for number, script in enumerate(MIGRATIONS[applied:], start=applied + 1):
        conn.executescript(script)
        conn.execute(f"PRAGMA user_version = {number}")
