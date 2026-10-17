import pytest

from rss_hub.domain.budget import BudgetBlock, check_budget, warn_reached


def check(**overrides):
    values = {
        "used_today": 0,
        "daily_cap": 700,
        "calls_last_minute": 0,
        "rpm_cap": 15,
        "server_remaining": None,
        "reserve": 20,
    }
    values.update(overrides)
    return check_budget(**values)


def test_nothing_is_blocked_when_every_limit_has_room():
    assert check(used_today=699, calls_last_minute=14, server_remaining=500) is None


@pytest.mark.parametrize(
    ("used", "expected"), [(699, None), (700, BudgetBlock.DAILY_CAP), (701, BudgetBlock.DAILY_CAP)]
)
def test_daily_cap(used, expected):
    assert check(used_today=used) is expected


@pytest.mark.parametrize(
    ("calls", "expected"), [(14, None), (15, BudgetBlock.RATE), (16, BudgetBlock.RATE)]
)
def test_per_minute_cap(calls, expected):
    assert check(calls_last_minute=calls) is expected


@pytest.mark.parametrize(
    ("remaining", "expected"),
    [(None, None), (21, None), (20, BudgetBlock.SERVER_LOW), (0, BudgetBlock.SERVER_LOW)],
)
def test_server_reported_remaining_keeps_a_reserve(remaining, expected):
    assert check(server_remaining=remaining) is expected


def test_a_zero_reserve_allows_calls_until_the_server_says_zero():
    assert check(server_remaining=1, reserve=0) is None
    assert check(server_remaining=0, reserve=0) is BudgetBlock.SERVER_LOW


def test_unknown_server_value_never_blocks():
    assert check(server_remaining=None, reserve=1000) is None


def test_when_several_limits_are_hit_the_daily_cap_is_reported_first_then_server_then_rate():
    assert check(used_today=700, server_remaining=0, calls_last_minute=99) is BudgetBlock.DAILY_CAP
    assert check(server_remaining=0, calls_last_minute=99) is BudgetBlock.SERVER_LOW
    assert check(calls_last_minute=99) is BudgetBlock.RATE


@pytest.mark.parametrize(
    ("used", "cap", "percent", "expected"),
    [
        (559, 700, 80, False),
        (560, 700, 80, True),
        (561, 700, 80, True),
        (1, 3, 50, False),  # 1.5 미만
        (2, 3, 50, True),
        (700, 700, 100, True),
        (699, 700, 100, False),
    ],
)
def test_warning_threshold(used, cap, percent, expected):
    assert warn_reached(used=used, cap=cap, warn_percent=percent) is expected
