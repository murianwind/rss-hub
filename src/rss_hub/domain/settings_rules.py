"""설정 값 검증. 오류 문구(message)는 화면에 그대로 보여 주므로 입력 값을 되돌려 주지 않는다."""

import re
from collections.abc import Sequence
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

COLLECT_INTERVAL_CHOICES = tuple(d for d in range(1, 61) if 60 % d == 0)
JOB_INTERVAL_SECONDS_RANGE = (10, 3600)
MAX_WEBHOOK_NAME_LENGTH = 40

_WEBHOOK_HOSTS = ("discord.com", "discordapp.com")
_WEBHOOK_PATH = re.compile(r"^/api(?:/v\d+)?/webhooks/\d+/[A-Za-z0-9._-]+$")


class SettingError(ValueError):
    """화면에 그대로 보여 줄 수 있는 오류 문구(message)를 가진 오류."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def normalize_base_url(raw: str) -> str:
    """서비스 주소: http/https만 받고, 끝 슬래시와 쿼리, #조각을 지운다. 하위 경로는 유지한다."""
    try:
        parts = urlsplit(raw.strip())
    except ValueError as error:
        raise SettingError("http:// 또는 https://로 시작해야 함") from error
    if parts.scheme.lower() not in ("http", "https"):
        raise SettingError("http:// 또는 https://로 시작해야 함")
    if not parts.hostname:
        raise SettingError("주소에 호스트가 필요함")
    host = parts.hostname.lower()
    netloc = f"{host}:{parts.port}" if parts.port else host
    return urlunsplit((parts.scheme.lower(), netloc, parts.path.rstrip("/"), "", ""))


def normalize_webhook_url(raw: str) -> str:
    """Discord 웹훅 주소만 받는다. 인증 없는 화면에서 임의 주소로 요청이 나가는 것을 막는다."""
    not_discord = SettingError("Discord 웹훅 주소가 아님")
    try:
        parts = urlsplit(raw.strip())
        port = parts.port
    except ValueError as error:
        raise not_discord from error
    if parts.scheme.lower() == "http":
        raise SettingError("https만 가능")
    host = (parts.hostname or "").lower()
    host_ok = any(host == allowed or host.endswith(f".{allowed}") for allowed in _WEBHOOK_HOSTS)
    if (
        parts.scheme.lower() != "https"
        or not host_ok
        or port not in (None, 443)
        or parts.username
        or parts.password
        or not _WEBHOOK_PATH.match(parts.path)
    ):
        raise not_discord
    return urlunsplit(("https", host, parts.path, "", ""))


def _parse_int(raw: str) -> int:
    try:
        return int(raw.strip())
    except ValueError as error:
        raise SettingError("숫자만 입력할 수 있음") from error


def parse_collect_interval(raw: str) -> int:
    """수집 주기(분): 60의 약수."""
    minutes = _parse_int(raw)
    if minutes not in COLLECT_INTERVAL_CHOICES:
        choices = ",".join(str(c) for c in COLLECT_INTERVAL_CHOICES)
        raise SettingError(f"60의 약수만 가능({choices})")
    return minutes


def parse_job_interval_seconds(raw: str) -> int:
    """요약, 발송 주기(초): 10~3600."""
    seconds = _parse_int(raw)
    low, high = JOB_INTERVAL_SECONDS_RANGE
    if not low <= seconds <= high:
        raise SettingError(f"{low}~{high}초 사이")
    return seconds


def parse_positive_int(raw: str, *, minimum: int = 1, maximum: int | None = None) -> int:
    """minimum 이상(maximum이 있으면 그 이하)의 정수."""
    value = _parse_int(raw)
    if maximum is None:
        if value < minimum:
            raise SettingError(f"{minimum} 이상이어야 함")
    elif not minimum <= value <= maximum:
        raise SettingError(f"{minimum}~{maximum} 사이")
    return value


def parse_percent(raw: str) -> int:
    """1~100 사이의 퍼센트 값."""
    return parse_positive_int(raw, minimum=1, maximum=100)


def validate_webhook_name(raw: str) -> str:
    """웹훅 이름: 앞뒤 공백을 지우고, 비어 있지 않으며 40자 이하."""
    name = raw.strip()
    if not name:
        raise SettingError("이름이 필요함")
    if len(name) > MAX_WEBHOOK_NAME_LENGTH:
        raise SettingError(f"이름은 {MAX_WEBHOOK_NAME_LENGTH}자까지")
    return name


def validate_timezone(name: str) -> str:
    """IANA 시간대 이름(예: Asia/Seoul)만 받는다."""
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError) as error:
        raise SettingError("IANA 시간대 이름이 아님") from error
    return name


def normalize_model_chain(raw: str | Sequence[str]) -> tuple[str, ...]:
    """모델 체인: 쉼표로 나누거나 목록으로 받아 공백과 중복을 정리하고, 순서는 유지한다."""
    items = raw.split(",") if isinstance(raw, str) else list(raw)
    models = tuple(dict.fromkeys(item.strip() for item in items if item.strip()))
    if not models:
        raise SettingError("모델이 하나 이상 필요")
    return models
