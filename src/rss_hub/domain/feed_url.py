"""피드 주소의 검증과 중복 판단용 정규화."""

from urllib.parse import urlsplit, urlunsplit

from rss_hub.domain.network import forbidden_host_reason

MAX_URL_LENGTH = 2048
ALLOWED_SCHEMES = ("http", "https")


class FeedUrlError(ValueError):
    """사용자에게 그대로 보여 줄 수 있는 오류 문구(message)를 가진 오류."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def validate_feed_url(url: str | None) -> str:
    """http/https 피드 주소인지 확인하고, 앞뒤 공백을 지운 주소를 돌려준다."""
    cleaned = (url or "").strip()
    if not cleaned:
        raise FeedUrlError("주소 없음")
    if len(cleaned) > MAX_URL_LENGTH:
        raise FeedUrlError("주소가 너무 김")
    try:
        parts = urlsplit(cleaned)
    except ValueError as error:
        raise FeedUrlError("주소 형식이 올바르지 않음") from error
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise FeedUrlError("http, https만 가능")
    if not parts.hostname:
        raise FeedUrlError("호스트 없음")
    try:
        parts.port  # noqa: B018 - 잘못된 포트(99999, abc)는 접근할 때 예외가 난다
    except ValueError as error:
        raise FeedUrlError("주소 형식이 올바르지 않음") from error
    reason = forbidden_host_reason(parts.hostname)
    if reason:
        raise FeedUrlError(reason)
    return cleaned


def feed_url_key(url: str) -> str:
    """같은 피드를 같은 값으로 만든다: 스킴과 호스트의 대소문자, 끝 슬래시, #조각을 무시한다.

    경로와 쿼리는 대소문자를 구분한다(서버가 구분할 수 있다).
    """
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    userinfo = f"{parts.username}@" if parts.username else ""
    port = f":{parts.port}" if parts.port else ""
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), f"{userinfo}{host}{port}", path, parts.query, ""))
