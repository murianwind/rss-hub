"""피드 항목(entry) 만들기. 시각은 서비스 시간대(Asia/Seoul)의 2026-10-16을 기준으로 한다."""

from typing import Any

_counter = {"n": 0}


def entry(
    *,
    published: str | None = "2026-10-16T10:00:00+09:00",
    guid: str | None = None,
    title: str = "제목",
    **extra: Any,
) -> dict[str, Any]:
    _counter["n"] += 1
    n = _counter["n"]
    data: dict[str, Any] = {
        "id": guid or f"https://example.com/post/{n}",
        "title": f"{title} {n}",
        "link": f"https://example.com/post/{n}",
        "summary": f"<p>본문 {n}</p>",
    }
    if published is not None:
        data["published"] = published
    data.update(extra)
    return data


def today(count: int, *, hour: int = 10) -> list[dict[str, Any]]:
    return [entry(published=f"2026-10-16T{hour:02d}:{i % 60:02d}:00+09:00") for i in range(count)]


def yesterday(count: int) -> list[dict[str, Any]]:
    return [entry(published=f"2026-10-15T10:{i % 60:02d}:00+09:00") for i in range(count)]
