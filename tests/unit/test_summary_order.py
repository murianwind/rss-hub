from dataclasses import dataclass
from datetime import UTC, datetime

from rss_hub.domain.summary import summary_order


@dataclass(frozen=True)
class Item:
    name: str
    retry_count: int
    published_dt: datetime


def at(hour, minute=0):
    return datetime(2026, 10, 16, hour, minute, tzinfo=UTC)


def names(items):
    return [i.name for i in summary_order(items)]


def test_first_time_articles_come_before_retries_and_each_group_is_oldest_first():
    a = Item("A", 0, at(10, 0))
    b = Item("B", 0, at(10, 30))
    c = Item("C", 1, at(9, 0))
    assert names([c, b, a]) == ["A", "B", "C"]


def test_all_retries_are_one_group_ordered_by_age():
    older = Item("older", 2, at(8))
    newer = Item("newer", 1, at(9))
    assert names([newer, older]) == ["older", "newer"]


def test_order_is_stable_for_equal_keys():
    first = Item("first", 0, at(10))
    second = Item("second", 0, at(10))
    assert names([first, second]) == ["first", "second"]


def test_empty_input():
    assert summary_order([]) == []
