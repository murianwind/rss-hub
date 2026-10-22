"""작업 진행 상황: 지금 실행 중인 작업이 몇 개 중 몇 개를 마쳤는지(메모리에만 둔다).

서비스는 글이나 피드 하나를 시작할 때마다 report를 부르고, 상태 화면이 읽어서 "2/5건"처럼 보여 준다.
작업이 끝나면 실행기가 지운다. 서비스를 다시 시작하면 사라지는 것이 맞다(실행 중이던 작업도 없다).
"""

import threading


class JobProgress:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: dict[str, tuple[int, int]] = {}

    def report(self, job: str, done: int, total: int) -> None:
        with self._lock:
            self._values[job] = (done, total)

    def get(self, job: str) -> tuple[int, int] | None:
        with self._lock:
            return self._values.get(job)

    def clear(self, job: str) -> None:
        with self._lock:
            self._values.pop(job, None)
