"""작업 이력을 남기는 도구. 서비스들이 한 일의 결과를 알릴 때 쓴다.

기록 때문에 본래 일이 실패하면 안 되므로 기록하다 생긴 오류는 삼키고 로그에만 남긴다.
"""

import logging

from rss_hub.domain.activity_log import OUTCOME_FAIL, OUTCOME_OK
from rss_hub.storage.activity_log import ActivityLogRepository

logger = logging.getLogger(__name__)


class ActivityRecorder:
    def __init__(self, repository: ActivityLogRepository | None) -> None:
        self._repository = repository

    def done(self, kind: str, source: str, message: str, detail: str = "") -> None:
        self._record(kind, OUTCOME_OK, source, message, detail)

    def failed(self, kind: str, source: str, message: str, detail: str = "") -> None:
        self._record(kind, OUTCOME_FAIL, source, message, detail)

    def _record(self, kind: str, outcome: str, source: str, message: str, detail: str) -> None:
        if self._repository is None:
            return
        try:
            self._repository.record(kind, outcome, source, message, detail)
        except Exception:
            logger.exception("작업 이력을 남기지 못했습니다: %s", kind)


NO_ACTIVITY = ActivityRecorder(None)  # 기록하지 않는 도구(시험이나 연결하지 않은 곳의 기본값)
