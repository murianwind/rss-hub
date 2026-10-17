"""호출 예산 판단: 하루 상한, 분당 상한, 서버가 알려 준 남은 호출 수."""

from enum import StrEnum


class BudgetBlock(StrEnum):
    DAILY_CAP = "daily_cap"  # 우리 서비스가 센 오늘 호출 수가 하루 상한에 도달
    SERVER_LOW = "server_low"  # 서버가 알려 준 남은 호출 수가 예비분 이하
    RATE = "rate"  # 최근 1분의 호출 수가 분당 상한에 도달


def check_budget(
    *,
    used_today: int,
    daily_cap: int,
    calls_last_minute: int,
    rpm_cap: int,
    server_remaining: int | None,
    reserve: int,
) -> BudgetBlock | None:
    """새 호출을 보내도 되는지. 막아야 하면 이유를, 보내도 되면 None을 돌려준다.

    서버가 알려 준 남은 호출 수는 같은 키를 쓰는 다른 프로그램의 호출까지 포함한다.
    값을 모르면(None) 우리 서비스의 기록만으로 판단한다.
    """
    if used_today >= daily_cap:
        return BudgetBlock.DAILY_CAP
    if server_remaining is not None and server_remaining <= reserve:
        return BudgetBlock.SERVER_LOW
    if calls_last_minute >= rpm_cap:
        return BudgetBlock.RATE
    return None


def warn_reached(*, used: int, cap: int, warn_percent: int) -> bool:
    """오늘 호출 수가 상한의 경고 비율에 도달했는지(정수로만 계산한다)."""
    return used * 100 >= cap * warn_percent
