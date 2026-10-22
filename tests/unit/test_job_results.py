"""작업 결과 한 줄: 보고서에 없는 모양과 드문 분기."""

from rss_hub.jobs.progress import JobProgress
from rss_hub.jobs.results import describe_result
from rss_hub.services.llm_gateway import BudgetBlock
from rss_hub.services.summarize import SummarizeReport


def test_an_unknown_result_has_no_line():
    assert describe_result("summarize", object()) == ""
    assert describe_result("collect", 5) == ""  # 정수는 정리 작업의 결과일 때만 뜻이 있다


def test_a_collect_run_with_nothing_to_check_says_so():
    from rss_hub.services.collect import CollectReport

    report = CollectReport(checked=0, added=0, baseline_recorded=0, failed=())
    assert describe_result("collect", report) == "이번에는 점검할 피드가 없었습니다"


def test_a_blocked_or_retrying_summary_is_described():
    assert "호출 한도" in describe_result(
        "summarize", SummarizeReport(blocked=next(iter(BudgetBlock)))
    )
    assert describe_result("summarize", SummarizeReport(considered=1, rejected=1)) == (
        "다시 시도할 글 1건"
    )


def test_a_delivery_with_failures_counts_them():
    from rss_hub.services.deliver import DeliveryReport

    report = DeliveryReport(considered=2, delivered=1, sent=1, failed=1, permanent=1)
    assert describe_result("deliver", report) == "글 1건 발송(메시지 1개) · 실패 2"


def test_progress_is_kept_per_job_and_cleared():
    progress = JobProgress()
    assert progress.get("summarize") is None
    progress.report("summarize", 1, 4)
    progress.report("deliver", 0, 2)
    assert progress.get("summarize") == (1, 4) and progress.get("deliver") == (0, 2)
    progress.clear("summarize")
    progress.clear("summarize")  # 두 번 지워도 같다
    assert progress.get("summarize") is None and progress.get("deliver") == (0, 2)
