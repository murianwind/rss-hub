"""설정 서비스: 일반 설정, 비밀 값(OpenRouter 키, 웹훅 주소), 변경 이력, 시작 점검표.

- 설정은 매번 저장소에서 읽는다. 그래서 값을 바꾸면 재시작 없이 다음 사용부터 반영된다.
- 비밀 값은 `secrets` 표에만 둔다. 화면용 값(스냅샷, 목록, 이력)에는 들어가지 않고,
  값이 필요한 내부 호출(`get_openrouter_key`, `get_webhook_url`)만 값을 돌려준다.
"""

import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo, available_timezones

from rss_hub.domain.settings_rules import (
    SettingError,
    normalize_base_url,
    normalize_model_chain,
    normalize_webhook_url,
    parse_collect_interval,
    parse_job_interval_seconds,
    parse_percent,
    parse_positive_int,
    validate_timezone,
    validate_webhook_name,
)
from rss_hub.services.clock import Clock
from rss_hub.storage.database import Database

DEFAULT_MODEL_CHAIN = "nvidia/nemotron-3-super-120b-a12b:free,nvidia/nemotron-3.5-super-vl:free"
EMPTY_LABEL = "(비어 있음)"
OPENROUTER_KEY = "openrouter_key"
ROLE_KEYS = {
    "default": "webhook_default_id",
    "system": "webhook_system_id",
}


@dataclass(frozen=True)
class SettingDef:
    key: str
    label: str
    default: str
    validate: Callable[[str], str]
    choices: tuple[tuple[str, str], ...] = ()  # (값, 이름). 있으면 선택 상자로 그린다
    help: str = ""  # 입력 칸 아래에 보여 주는 한 줄 설명
    show_when: tuple[str, str] | None = None  # (다른 설정 키, 값): 그 값일 때만 입력 칸을 보인다


def _bounded(maximum: int) -> Callable[[str], str]:
    return lambda raw: str(parse_positive_int(raw, maximum=maximum))


def _bounded_from_zero(maximum: int) -> Callable[[str], str]:
    return lambda raw: str(parse_positive_int(raw, minimum=0, maximum=maximum))


def _choice(options: tuple[tuple[str, str], ...]) -> Callable[[str], str]:
    allowed = {value for value, _ in options}

    def validate(raw: str) -> str:
        value = raw.strip()
        if value not in allowed:
            raise SettingError("목록에 있는 값 중에서 고르세요")
        return value

    return validate


_HIDDEN_ZONE_PREFIXES = ("Etc/", "posix/", "right/", "SystemV/", "US/", "Brazil/", "Canada/")
TIMEZONE_CHOICES = tuple(
    (zone, zone)
    for zone in sorted(available_timezones())
    if zone == "UTC" or ("/" in zone and not zone.startswith(_HIDDEN_ZONE_PREFIXES))
)  # 화면에서 고르는 목록. 서버는 그 밖의 IANA 이름도 받는다
ALERT_REPEAT_CHOICES = (("off", "끔"), ("on", "켬"))
THEME_CHOICES = (("system", "기기 설정 따르기"), ("light", "밝게"), ("dark", "어둡게"))
FONT_CHOICES = (("normal", "보통"), ("large", "크게"))
AUTO_READ_CHOICES = (("on", "켜기"), ("off", "끄기"))


def _base_url(raw: str) -> str:
    return normalize_base_url(raw) if raw.strip() else ""


SETTING_DEFS: tuple[SettingDef, ...] = (
    SettingDef(
        "service_base_url",
        "서비스 주소",
        "",
        _base_url,
        help="Discord 알림 속 링크가 열리는 주소. 밖에서도 열려면 외부 주소(도메인)를 넣으세요",
    ),
    SettingDef(
        "service_timezone",
        "서비스 시간대",
        "Asia/Seoul",
        validate_timezone,
        choices=TIMEZONE_CHOICES,
        help="알림 시각과 날짜를 계산하는 시간대(예: Asia/Seoul)",
    ),
    SettingDef(
        "collect_interval_minutes",
        "수집 주기(분)",
        "5",
        lambda r: str(parse_collect_interval(r)),
        help="피드를 나눠 점검하는 간격(분). 60의 약수만 가능",
    ),
    SettingDef(
        "summarize_interval_seconds",
        "요약 주기(초)",
        "60",
        lambda r: str(parse_job_interval_seconds(r)),
        help="새 글을 요약하러 가는 간격(10~3600초)",
    ),
    SettingDef(
        "deliver_interval_seconds",
        "발송 주기(초)",
        "60",
        lambda r: str(parse_job_interval_seconds(r)),
        help="요약된 글을 Discord로 보내러 가는 간격(10~3600초)",
    ),
    SettingDef(
        "slot_batch_size",
        "슬롯 기본 배치 크기",
        "15",
        _bounded(1000),
        help="한 번에 점검하는 피드 수의 기본값(1~1000)",
    ),
    SettingDef(
        "default_max_entries",
        "피드 기본 최대 검사 항목",
        "50",
        _bounded(500),
        help="피드마다 한 번에 읽는 글 수의 기본값(1~500)",
    ),
    SettingDef(
        "baseline_archive_count",
        "첫 점검 때 보관할 최근 글 수",
        "5",
        _bounded_from_zero(20),
        help="새 피드의 첫 점검 때 읽기 화면에만 남길 최근 글 수(0~20)",
    ),
    SettingDef(
        "topic_feedback_examples",
        "요약 요청에 넣을 확인 예시 수",
        "0",
        _bounded_from_zero(5),
        help="요약 요청에 참고로 넣을 확인된 예시 수(주제별, 0~5). 0이면 안 넣음",
    ),
    SettingDef(
        "ui_theme",
        "화면 테마",
        "system",
        _choice(THEME_CHOICES),
        THEME_CHOICES,
        help="화면 밝기. 기기 설정을 따르거나 밝게, 어둡게로 고정",
    ),
    SettingDef(
        "ui_font_size",
        "글자 크기",
        "normal",
        _choice(FONT_CHOICES),
        FONT_CHOICES,
        help="읽기 화면의 글자 크기",
    ),
    SettingDef(
        "ui_auto_read",
        "스크롤하면 자동으로 읽음 처리",
        "on",
        _choice(AUTO_READ_CHOICES),
        AUTO_READ_CHOICES,
        help="글 목록에서 스크롤로 지나간 글을 읽음으로 표시",
    ),
    SettingDef(
        "article_retention_days",
        "글 보관 기간(일)",
        "90",
        _bounded_from_zero(3650),
        help="이 기간이 지난 글을 지움(0~3650일, 0이면 계속 보관). 북마크는 남김",
    ),
    SettingDef(
        "model_chain",
        "모델 체인",
        DEFAULT_MODEL_CHAIN,
        lambda r: ",".join(normalize_model_chain(r)),
        help="요약에 쓸 모델을 쉼표로 구분. 앞에서부터 시도하고 실패하면 다음으로",
    ),
    SettingDef(
        "llm_daily_cap",
        "LLM 하루 상한",
        "700",
        _bounded(100_000),
        help="하루에 부를 최대 LLM 호출 수. 넘으면 다음 날까지 요약을 멈춤",
    ),
    SettingDef(
        "llm_warn_percent",
        "LLM 경고 비율(%)",
        "80",
        lambda r: str(parse_percent(r)),
        help="하루 상한의 이 비율(1~100%)에 닿으면 시스템 알림을 보냄",
    ),
    SettingDef(
        "llm_rpm_cap",
        "LLM 분당 상한",
        "15",
        _bounded(1000),
        help="1분에 부를 최대 호출 수(OpenRouter 무료 한도에 맞춤)",
    ),
    SettingDef(
        "llm_reserve_calls",
        "서버 남은 호출 예비분",
        "20",
        lambda r: str(parse_positive_int(r, minimum=0, maximum=1000)),
        help="서버가 알려 준 남은 호출 수가 이 값 이하이면 요약을 멈춤",
    ),
    SettingDef(
        "llm_wait_limit_minutes",
        "장애 대기 허용(분)",
        "60",
        _bounded(1440),
        help="모델 장애가 이 시간(분) 넘게 이어지면 원문 발췌로 대신 보냄",
    ),
    SettingDef(
        "summarize_batch",
        "요약 묶음(글 수)",
        "5",
        _bounded(50),
        help="요약 잡이 한 번에 처리하는 글 수(1~50)",
    ),
    SettingDef(
        "alert_repeat",
        "같은 알림 반복 보내기",
        "off",
        _choice(ALERT_REPEAT_CHOICES),
        ALERT_REPEAT_CHOICES,
        help="끄면 같은 종류의 시스템 알림은 한 번 보내고 24시간 안에는 다시 보내지 않음",
    ),
    SettingDef(
        "alert_cooldown_hours",
        "반복 간격(시간)",
        "6",
        _bounded(168),
        help="같은 알림을 다시 보내기까지 기다리는 시간(1~168)",
        show_when=("alert_repeat", "on"),
    ),
)
SETTING_BY_KEY = {d.key: d for d in SETTING_DEFS}


@dataclass(frozen=True)
class AppSettings:
    """다른 서비스가 쓰는 형태의 설정(타입이 있는 값). 비밀 값은 들어 있지 않다."""

    base_url: str
    timezone: ZoneInfo
    collect_interval_minutes: int
    summarize_interval_seconds: int
    deliver_interval_seconds: int
    slot_batch_size: int
    default_max_entries: int
    baseline_archive_count: int
    ui_theme: str
    ui_font_size: str
    ui_auto_read: str
    topic_feedback_examples: int
    article_retention_days: int
    model_chain: tuple[str, ...]
    llm_daily_cap: int
    llm_warn_percent: int
    llm_rpm_cap: int
    llm_reserve_calls: int
    llm_wait_limit_minutes: int
    summarize_batch: int
    alert_repeat: bool
    alert_cooldown_hours: int
    webhook_default_id: int | None
    webhook_system_id: int | None


@dataclass(frozen=True)
class UpdateResult:
    errors: dict[str, str]
    changed: tuple[str, ...]


@dataclass(frozen=True)
class WebhookInfo:
    """화면용 웹훅 정보. 주소는 들어 있지 않다."""

    id: int
    name: str


@dataclass(frozen=True)
class AuditEntry:
    changed_at: datetime
    summary: str


@dataclass(frozen=True)
class SetupItem:
    key: str
    label: str
    ready: bool
    required: bool = True  # False이면 비어 있어도 서비스가 동작한다(기능만 줄어든다)


class SettingsService:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    # ---------- 일반 설정 ----------

    def raw_values(self) -> dict[str, str]:
        """폼에 채울 값(저장된 값, 없으면 기본값)."""
        with self._db.connect() as conn:
            stored = self._stored(conn)
        return {d.key: stored.get(d.key, d.default) for d in SETTING_DEFS}

    def snapshot(self) -> AppSettings:
        with self._db.connect() as conn:
            stored = self._stored(conn)
        v = {d.key: stored.get(d.key, d.default) for d in SETTING_DEFS}
        return AppSettings(
            base_url=v["service_base_url"],
            timezone=ZoneInfo(v["service_timezone"]),
            collect_interval_minutes=int(v["collect_interval_minutes"]),
            summarize_interval_seconds=int(v["summarize_interval_seconds"]),
            deliver_interval_seconds=int(v["deliver_interval_seconds"]),
            slot_batch_size=int(v["slot_batch_size"]),
            default_max_entries=int(v["default_max_entries"]),
            baseline_archive_count=int(v["baseline_archive_count"]),
            ui_theme=v["ui_theme"],
            ui_font_size=v["ui_font_size"],
            ui_auto_read=v["ui_auto_read"],
            topic_feedback_examples=int(v["topic_feedback_examples"]),
            article_retention_days=int(v["article_retention_days"]),
            model_chain=tuple(v["model_chain"].split(",")),
            llm_daily_cap=int(v["llm_daily_cap"]),
            llm_warn_percent=int(v["llm_warn_percent"]),
            llm_rpm_cap=int(v["llm_rpm_cap"]),
            llm_reserve_calls=int(v["llm_reserve_calls"]),
            llm_wait_limit_minutes=int(v["llm_wait_limit_minutes"]),
            summarize_batch=int(v["summarize_batch"]),
            alert_repeat=v["alert_repeat"] == "on",
            alert_cooldown_hours=int(v["alert_cooldown_hours"]),
            webhook_default_id=_to_id(stored.get(ROLE_KEYS["default"], "")),
            webhook_system_id=_to_id(stored.get(ROLE_KEYS["system"], "")),
        )

    def update(self, values: Mapping[str, str]) -> UpdateResult:
        """모든 값을 먼저 검증하고, 하나라도 틀리면 아무것도 저장하지 않는다."""
        errors: dict[str, str] = {}
        normalized: dict[str, str] = {}
        for key, raw in values.items():
            definition = SETTING_BY_KEY.get(key)
            if definition is None:
                errors[key] = "알 수 없는 설정"
                continue
            try:
                normalized[key] = definition.validate(raw)
            except SettingError as error:
                errors[key] = error.message
        if errors:
            return UpdateResult(errors=errors, changed=())

        now = self._clock.now().isoformat()
        changed: list[str] = []
        with self._db.connect() as conn:
            stored = self._stored(conn)
            for key, new in normalized.items():
                definition = SETTING_BY_KEY[key]
                old = stored.get(key, definition.default)
                if old == new:
                    continue
                self._write_setting(conn, key, new, now)
                summary = f"{definition.label} 변경: {old or EMPTY_LABEL} → {new or EMPTY_LABEL}"
                self._audit(conn, key, now, summary)
                changed.append(key)
        return UpdateResult(errors={}, changed=tuple(changed))

    # ---------- OpenRouter 키 ----------

    def has_openrouter_key(self) -> bool:
        return self.get_openrouter_key() is not None

    def get_openrouter_key(self) -> str | None:
        """내부 호출 전용. 화면과 이력에는 절대 쓰지 않는다."""
        with self._db.connect() as conn:
            return self._secret(conn, OPENROUTER_KEY)

    def set_openrouter_key(self, value: str) -> None:
        key = value.strip()
        if not key:
            raise SettingError("값이 비어 있음")
        now = self._clock.now().isoformat()
        with self._db.connect() as conn:
            self._write_secret(conn, OPENROUTER_KEY, key)
            self._audit(conn, OPENROUTER_KEY, now, "OpenRouter 키 변경됨")

    def delete_openrouter_key(self) -> None:
        now = self._clock.now().isoformat()
        with self._db.connect() as conn:
            if self._secret(conn, OPENROUTER_KEY) is None:
                return
            conn.execute("DELETE FROM secrets WHERE key = ?", (OPENROUTER_KEY,))
            self._audit(conn, OPENROUTER_KEY, now, "OpenRouter 키 삭제됨")

    # ---------- 웹훅 ----------

    def add_webhook(self, name: str, url: str) -> int:
        clean_name = validate_webhook_name(name)
        clean_url = normalize_webhook_url(url)
        now = self._clock.now().isoformat()
        try:
            with self._db.connect() as conn:
                cursor = conn.execute(
                    "INSERT INTO webhooks(name, created_at) VALUES(?, ?)", (clean_name, now)
                )
                webhook_id = int(cursor.lastrowid or 0)
                self._write_secret(conn, _webhook_secret_key(webhook_id), clean_url)
                self._audit(conn, "webhooks", now, f"웹훅 '{clean_name}' 추가됨")
        except sqlite3.IntegrityError as error:
            raise SettingError("같은 이름의 웹훅이 이미 있음") from error
        return webhook_id

    def list_webhooks(self) -> list[WebhookInfo]:
        with self._db.connect() as conn:
            rows = conn.execute("SELECT id, name FROM webhooks ORDER BY id").fetchall()
        return [WebhookInfo(id=row["id"], name=row["name"]) for row in rows]

    def get_webhook_url(self, webhook_id: int) -> str | None:
        """내부 호출 전용. 화면과 이력에는 절대 쓰지 않는다."""
        with self._db.connect() as conn:
            return self._secret(conn, _webhook_secret_key(webhook_id))

    def delete_webhook(self, webhook_id: int) -> None:
        """웹훅을 지우고, 그 웹훅을 역할(기본, 시스템)로 지정한 곳은 비운다."""
        now = self._clock.now().isoformat()
        with self._db.connect() as conn:
            row = conn.execute("SELECT name FROM webhooks WHERE id = ?", (webhook_id,)).fetchone()
            if row is None:
                return
            conn.execute("DELETE FROM secrets WHERE key = ?", (_webhook_secret_key(webhook_id),))
            conn.execute("DELETE FROM webhooks WHERE id = ?", (webhook_id,))
            for role_key in ROLE_KEYS.values():
                conn.execute(
                    "UPDATE settings SET value = '', updated_at = ? WHERE key = ? AND value = ?",
                    (now, role_key, str(webhook_id)),
                )
            self._audit(conn, "webhooks", now, f"웹훅 '{row['name']}' 삭제됨")

    def set_webhook_roles(self, *, default_id: int | None, system_id: int | None) -> None:
        wanted = {"default": default_id, "system": system_id}
        now = self._clock.now().isoformat()
        with self._db.connect() as conn:
            existing = {row["id"] for row in conn.execute("SELECT id FROM webhooks")}
            if any(i is not None and i not in existing for i in wanted.values()):
                raise SettingError("없는 웹훅임")
            stored = self._stored(conn)
            changed = False
            for role, webhook_id in wanted.items():
                new = "" if webhook_id is None else str(webhook_id)
                key = ROLE_KEYS[role]
                if stored.get(key, "") != new:
                    self._write_setting(conn, key, new, now)
                    changed = True
            if changed:
                self._audit(conn, "webhook_roles", now, "웹훅 역할 변경")

    # ---------- 점검표와 이력 ----------

    def setup_checklist(self) -> list[SetupItem]:
        """처음 쓸 때 채워야 하는 설정이 채워졌는지."""
        snapshot = self.snapshot()
        webhook_ids = {w.id for w in self.list_webhooks()}
        return [
            SetupItem("openrouter_key", "OpenRouter 키", self.has_openrouter_key(), required=False),
            SetupItem("default_webhook", "기본 웹훅", snapshot.webhook_default_id in webhook_ids),
            SetupItem("service_base_url", "서비스 주소", bool(snapshot.base_url)),
        ]

    def audit_log(self, limit: int = 20) -> list[AuditEntry]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT changed_at, summary FROM settings_audit ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            AuditEntry(changed_at=datetime.fromisoformat(r["changed_at"]), summary=r["summary"])
            for r in rows
        ]

    # ---------- 내부 ----------

    @staticmethod
    def _stored(conn: sqlite3.Connection) -> dict[str, str]:
        return {row["key"]: row["value"] for row in conn.execute("SELECT key, value FROM settings")}

    @staticmethod
    def _write_setting(conn: sqlite3.Connection, key: str, value: str, now: str) -> None:
        conn.execute(
            "INSERT INTO settings(key, value, updated_at) VALUES(?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE "
            "SET value = excluded.value, updated_at = excluded.updated_at",
            (key, value, now),
        )

    @staticmethod
    def _secret(conn: sqlite3.Connection, key: str) -> str | None:
        row = conn.execute("SELECT value FROM secrets WHERE key = ?", (key,)).fetchone()
        return None if row is None else str(row["value"])

    @staticmethod
    def _write_secret(conn: sqlite3.Connection, key: str, value: str) -> None:
        conn.execute(
            "INSERT INTO secrets(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    @staticmethod
    def _audit(conn: sqlite3.Connection, key: str, now: str, summary: str) -> None:
        conn.execute(
            "INSERT INTO settings_audit(key, changed_at, summary) VALUES(?, ?, ?)",
            (key, now, summary),
        )


def _webhook_secret_key(webhook_id: int) -> str:
    return f"webhook:{webhook_id}"


def _to_id(value: str) -> int | None:
    return int(value) if value else None
