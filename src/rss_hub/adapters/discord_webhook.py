"""Discord 웹훅으로 메시지를 보내는 어댑터.

- 글 제목이나 요약에 들어 있는 @everyone 같은 멘션이 실제 알림이 되지 않게
  allowed_mentions를 비운다.
- 웹훅 주소(토큰 포함)는 오류 문구, 로그에 남기지 않는다. 실패는 오류 종류 이름만 돌려준다.
- 설정 화면은 이미 Discord 주소만 받지만, 보내기 직전에 한 번 더 확인한다(임의 주소로의 요청 방지).
"""

import re
from typing import Any
from urllib.parse import urlsplit

import requests

from rss_hub.domain.text import truncate_with_ellipsis
from rss_hub.services.ports import SendResult, WebhookSender

DISCORD_HOSTS = ("discord.com", "discordapp.com")
DEFAULT_TIMEOUT = (5.0, 15.0)
NOTIFICATION_LIMIT = 1900
_PATH = re.compile(r"^/api(?:/v\d+)?/webhooks/\d+/[A-Za-z0-9._-]+$")


class NotificationFailed(Exception):
    """시스템 알림을 보내지 못했다. 메시지에 주소를 넣지 않는다."""


def check_webhook_address(
    url: str, allowed_hosts: tuple[str, ...] = DISCORD_HOSTS, require_https: bool = True
) -> str:
    """보내도 되는 주소인지. 안 되면 이유를, 되면 빈 문자열을 돌려준다."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if require_https and parts.scheme != "https":
        return "https 주소가 아님"
    if not any(host == allowed or host.endswith("." + allowed) for allowed in allowed_hosts):
        return "허용하지 않는 주소"
    if not _PATH.match(parts.path):
        return "웹훅 주소 형식이 아님"
    return ""


def _float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


class RequestsWebhookSender:
    def __init__(
        self,
        *,
        timeout: tuple[float, float] = DEFAULT_TIMEOUT,
        allowed_hosts: tuple[str, ...] = DISCORD_HOSTS,
        require_https: bool = True,
    ) -> None:
        self._timeout = timeout
        self._allowed_hosts = allowed_hosts
        self._require_https = require_https

    def send(self, webhook_url: str, content: str) -> SendResult:
        if check_webhook_address(webhook_url, self._allowed_hosts, self._require_https):
            return SendResult(status=400, error="InvalidWebhookAddress")  # 보내지 않는다
        try:
            response = requests.post(
                f"{webhook_url}?wait=true",
                json={"content": content, "allowed_mentions": {"parse": []}},
                timeout=self._timeout,
            )
        except requests.exceptions.RequestException as error:
            return SendResult(status=0, error=type(error).__name__)

        try:
            body = response.json()
        except ValueError:
            body = None
        body = body if isinstance(body, dict) else {}
        message_id = body.get("id")
        retry_after = _float(response.headers.get("Retry-After"))
        if retry_after is None:
            retry_after = _float(body.get("retry_after"))
        return SendResult(
            status=response.status_code,
            retry_after=retry_after,
            rate_remaining=_int(response.headers.get("X-RateLimit-Remaining")),
            rate_reset_after=_float(response.headers.get("X-RateLimit-Reset-After")),
            message_id=None if message_id is None else str(message_id),
        )


class DiscordNotifier:
    """시스템 알림(호출 상한 도달, 잔액 부족 등)을 시스템 웹훅으로 보낸다."""

    def __init__(self, sender: WebhookSender) -> None:
        self._sender = sender

    def send(self, webhook_url: str, text: str) -> None:
        result = self._sender.send(webhook_url, truncate_with_ellipsis(text, NOTIFICATION_LIMIT))
        if not 200 <= result.status < 300:
            reason = f"HTTP {result.status}" if result.status else result.error
            raise NotificationFailed(f"Discord로 알림을 보내지 못했습니다({reason})")
