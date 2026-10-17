"""Discord 웹훅 응답 해석과 속도 조절."""

from enum import StrEnum

MAX_RATE_LIMIT_WAIT = 30.0
DEFAULT_RATE_LIMIT_WAIT = 5.0
MAX_BUCKET_WAIT = 10.0
BUCKET_MARGIN = 0.1


class SendOutcome(StrEnum):
    SENT = "sent"
    RATE_LIMITED = "rate_limited"  # 429: 기다렸다가 한 번 다시 시도
    PERMANENT = "permanent"  # 웹훅이 삭제되었거나 거부함: 다시 보내도 소용없다
    TRANSIENT = "transient"  # 서버 오류, 네트워크 실패: 다음 실행에서 다시 보낸다


def classify_status(status: int) -> SendOutcome:
    """응답 상태 코드로 다음에 할 일을 정한다(0은 연결 실패나 시간 초과)."""
    if 200 <= status < 300:
        return SendOutcome.SENT
    if status == 429:
        return SendOutcome.RATE_LIMITED
    if 400 <= status < 500 and status != 408:
        return SendOutcome.PERMANENT
    return SendOutcome.TRANSIENT


def pause_after_send(remaining: int | None, reset_after: float | None) -> float:
    """보낸 직후 남은 횟수가 0이면, 429를 받기 전에 한도가 다시 채워질 때까지 기다린다."""
    if remaining is None or reset_after is None or remaining > 0:
        return 0.0
    return min(reset_after + BUCKET_MARGIN, MAX_BUCKET_WAIT)


def retry_wait(retry_after: float | None) -> float:
    """429에서 기다릴 시간(최대 30초). 알려 주지 않으면 5초."""
    if not retry_after:
        return DEFAULT_RATE_LIMIT_WAIT
    return min(retry_after, MAX_RATE_LIMIT_WAIT)
