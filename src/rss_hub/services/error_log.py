"""오류 기록을 남기는 도구. 서비스들이 실패를 알릴 때 쓴다.

기록 때문에 본래 일이 실패하면 안 되므로 기록하다 생긴 오류는 삼키고 로그에만 남긴다.
"""

import logging

from rss_hub.storage.error_log import ErrorLogRepository

logger = logging.getLogger(__name__)


class ErrorRecorder:
    def __init__(self, repository: ErrorLogRepository | None) -> None:
        self._repository = repository

    def record(self, kind: str, source: str, message: str, detail: str = "") -> None:
        if self._repository is None:
            return
        try:
            self._repository.record(kind, source, message, detail)
        except Exception:
            logger.exception("오류 기록을 남기지 못했습니다: %s", kind)


NO_ERRORS = ErrorRecorder(None)  # 기록하지 않는 도구(시험이나 연결하지 않은 곳의 기본값)
