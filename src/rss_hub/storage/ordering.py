"""사이드바의 순서(피드, 카테고리, 주제)를 저장한다. 드래그로 바꾼 순서가 여기에 남는다."""

from collections.abc import Sequence

from rss_hub.storage.database import Database

TABLES = {"feed": "feeds", "category": "categories", "topic": "topics"}
STEP = 10  # 사이에 끼워 넣을 여유


class OrderRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def set_order(self, kind: str, ids: Sequence[int]) -> bool:
        """보낸 순서대로 번호를 매긴다. 종류가 틀리거나 없는 번호, 중복이 있으면 바꾸지 않는다."""
        table = TABLES.get(kind)
        if table is None or not ids or len(set(ids)) != len(ids):
            return False
        marks = ",".join("?" for _ in ids)
        with self._db.connect() as conn:
            found = conn.execute(
                f"SELECT COUNT(*) AS n FROM {table} WHERE id IN ({marks})", list(ids)
            ).fetchone()["n"]
            if found != len(ids):
                return False
            for position, item in enumerate(ids, start=1):
                conn.execute(
                    f"UPDATE {table} SET sort_order = ? WHERE id = ?", (position * STEP, item)
                )
        return True
