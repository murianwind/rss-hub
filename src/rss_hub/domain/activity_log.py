"""작업 이력의 결과, 정렬, 이름. 유형은 오류 기록과 같은 이름(domain/error_log)을 쓴다."""

from rss_hub.domain.error_log import (
    KIND_COLLECT,
    KIND_DELIVER,
    KIND_FULLTEXT,
    KIND_LABELS,
    KIND_LLM,
    KIND_SUMMARIZE,
)

OUTCOME_OK = "ok"
OUTCOME_FAIL = "fail"
OUTCOME_LABELS = {OUTCOME_OK: "성공", OUTCOME_FAIL: "실패"}

# 작업 이력에 남기는 유형(작업 실행의 예외는 오류 기록에만 남는다)
ACTIVITY_KINDS = {
    kind: KIND_LABELS[kind]
    for kind in (KIND_COLLECT, KIND_FULLTEXT, KIND_SUMMARIZE, KIND_DELIVER, KIND_LLM)
}

SORT_RECENT = "recent"  # 일어난 때가 최근인 순
SORT_KIND = "kind"  # 유형별로 묶고 그 안에서는 최근순
SORT_FAIL = "fail"  # 실패를 먼저, 그 안에서는 최근순
SORT_LABELS = {SORT_RECENT: "최근순", SORT_KIND: "유형순", SORT_FAIL: "실패 먼저"}

MAX_LISTED = 300  # 화면에 보여 주는 최대 줄 수(복사도 이 범위)
MAX_FIELD = 300  # 대상과 메시지는 이 길이로 줄여 저장한다
MAX_DETAIL = 1000
