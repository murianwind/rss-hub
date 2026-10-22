"""설정 항목을 화면별로 묶는 규칙. 항목의 라벨과 설명은 services.settings의 SettingDef에 있다."""

from rss_hub.services.settings import SETTING_BY_KEY, SettingDef

# (그룹 이름, 설정 키). 한 화면에 여러 그룹이 들어가면 그룹 이름을 소제목으로 보여 준다
SETTING_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("일반", ("service_base_url", "service_timezone")),
    (
        "주기",
        ("collect_interval_minutes", "summarize_interval_seconds", "deliver_interval_seconds"),
    ),
    (
        "수집과 보관",
        (
            "slot_batch_size",
            "default_max_entries",
            "baseline_archive_count",
            "article_retention_days",
        ),
    ),
    (
        "호출 한도",
        (
            "llm_daily_cap",
            "llm_warn_percent",
            "llm_rpm_cap",
            "llm_reserve_calls",
            "llm_wait_limit_minutes",
            "summarize_batch",
            "topic_feedback_examples",
        ),
    ),
    ("알림", ("alert_repeat", "alert_cooldown_hours")),
    ("화면", ("ui_theme", "ui_font_size", "ui_auto_read")),
)
GROUP_KEYS = dict(SETTING_GROUPS)

# 설정 화면의 아코디언: (id, 제목, 들어가는 그룹). 위에서 아래로 쓰는 순서다
SETTINGS_ACCORDIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("general", "서비스 주소와 시간대", ("일반",)),
    ("collect", "수집과 보관", ("주기", "수집과 보관")),
    ("display", "화면: 테마, 글자 크기, 읽음 처리", ("화면",)),
)


def keys_of(*groups: str) -> frozenset[str]:
    return frozenset(key for group in groups for key in GROUP_KEYS[group])


def sections(*groups: str, titled: bool = False) -> list[tuple[str, list[SettingDef]]]:
    """화면에 그릴 (소제목, 설정 정의 목록). titled가 False이면 소제목을 비운다."""
    return [
        (group if titled else "", [SETTING_BY_KEY[key] for key in GROUP_KEYS[group]])
        for group in groups
    ]
