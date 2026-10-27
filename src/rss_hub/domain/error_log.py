"""서버 오류 기록의 유형과 이름. 상태 화면이 유형별로 모아 보여 준다."""

KIND_COLLECT = "collect"
KIND_FULLTEXT = "fulltext"
KIND_SUMMARIZE = "summarize"
KIND_DELIVER = "deliver"
KIND_LLM = "llm"
KIND_JOB = "job"

KIND_LABELS = {
    KIND_COLLECT: "피드 수집",
    KIND_FULLTEXT: "전문 가져오기",
    KIND_SUMMARIZE: "요약",
    KIND_DELIVER: "발송",
    KIND_LLM: "LLM 호출",
    KIND_JOB: "작업 실행",
}

SORT_RECENT = "recent"  # 마지막으로 일어난 때가 최근인 순
SORT_KIND = "kind"  # 유형별로 묶고 그 안에서는 최근순
SORT_COUNT = "count"  # 많이 일어난 순
SORT_LABELS = {SORT_RECENT: "최근순", SORT_KIND: "유형순", SORT_COUNT: "많이 발생한 순"}
MAX_LISTED = 300  # 화면에 보여 주는 최대 줄 수(복사도 이 범위)
MAX_FIELD = 300  # 대상과 메시지는 이 길이로 줄여 저장한다
MAX_DETAIL = 1000
