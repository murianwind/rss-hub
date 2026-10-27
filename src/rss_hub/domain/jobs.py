"""작업이 실행될 시각을 정하는 규칙.

- 수집은 시각에 맞춘 슬롯(예: 5분마다 0, 5, 10분)에 실행한다. 서비스가 멈춰 있던 동안 지나간 슬롯은
  따라잡지 않고, 지금 속한 슬롯만 실행한다(따라잡으면 재시작 직후 점검이 한꺼번에 몰린다).
- 요약과 발송은 마지막 시작 시각으로부터 정해진 초가 지나면 실행한다.
"""

from datetime import datetime, timedelta

SLOT_GRACE_SECONDS = 60  # 슬롯이 시작되고 이 시간 안에만 실행한다


def latest_slot_start(local_now: datetime, interval_minutes: int) -> datetime:
    """지금 시각이 속한 슬롯의 시작(분을 주기의 배수로 내리고 초는 0으로)."""
    minute = local_now.minute - local_now.minute % interval_minutes
    return local_now.replace(minute=minute, second=0, microsecond=0)


def due_slot(
    local_now: datetime,
    last_slot: datetime | None,
    interval_minutes: int,
    grace_seconds: int = SLOT_GRACE_SECONDS,
) -> datetime | None:
    """지금 실행해야 하는 슬롯의 시작. 이미 실행했거나 시작한 지 오래되어 놓친 슬롯이면 None."""
    latest = latest_slot_start(local_now, interval_minutes)
    if last_slot is not None and latest <= last_slot:
        return None
    if (local_now - latest).total_seconds() >= grace_seconds:
        return None
    return latest


def interval_due(now: datetime, last_started: datetime | None, interval_seconds: int) -> bool:
    return last_started is None or (now - last_started).total_seconds() >= interval_seconds


def next_slot_start(
    local_now: datetime,
    last_slot: datetime | None,
    interval_minutes: int,
    grace_seconds: int = SLOT_GRACE_SECONDS,
) -> datetime:
    """다음에 실행될 슬롯의 시작. 지금 실행할 슬롯이 있으면 그 슬롯, 아니면 다음 슬롯."""
    if due_slot(local_now, last_slot, interval_minutes, grace_seconds) is not None:
        return latest_slot_start(local_now, interval_minutes)
    return latest_slot_start(local_now, interval_minutes) + timedelta(minutes=interval_minutes)


def next_interval_run(
    now: datetime, last_started: datetime | None, interval_seconds: int
) -> datetime:
    """다음에 실행될 시각. 이미 때가 되었거나 한 번도 실행하지 않았으면 지금."""
    if last_started is None:
        return now
    return max(now, last_started + timedelta(seconds=interval_seconds))
