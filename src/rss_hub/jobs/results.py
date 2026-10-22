"""작업 보고서를 사람이 읽는 한 줄 결과로 바꾼다(상태 화면의 "결과:"에 보인다)."""

from rss_hub.services.collect import CollectReport
from rss_hub.services.deliver import DeliveryReport
from rss_hub.services.model_scan import ScanReport
from rss_hub.services.summarize import SummarizeReport


def _summarize(report: SummarizeReport) -> str:
    if report.waiting_for_setup:
        return "필요한 설정이 비어 있어 기다립니다"
    if report.blocked is not None:
        return "호출 한도에 막혀 멈췄습니다"
    if report.outage:
        return "모델이 응답하지 않아 멈췄습니다"
    if report.plain:
        return f"키 없이 원문 제목으로 {report.plain}건 확정"
    parts = [
        text
        for count, text in (
            (report.ready, f"요약 {report.ready}건"),
            (report.fallback, f"원문 발췌로 확정 {report.fallback}건"),
            (report.rejected, f"다시 시도할 글 {report.rejected}건"),
        )
        if count
    ]
    return " · ".join(parts) or "요약할 글이 없었습니다"


def _deliver(report: DeliveryReport) -> str:
    if report.waiting_for_base_url:
        return "서비스 주소가 없어 보내지 않았습니다"
    if report.no_default_webhook:
        return "기본 웹훅이 없어 보내지 않았습니다"
    if not report.considered:
        return "보낼 글이 없었습니다"
    text = f"글 {report.delivered}건 발송(메시지 {report.sent}개)"
    if report.failed or report.permanent:
        text += f" · 실패 {report.failed + report.permanent}"
    return text


def _collect(report: CollectReport) -> str:
    if not report.checked:
        return "이번에는 점검할 피드가 없었습니다"
    text = f"피드 {report.checked}개 점검 · 새 글 {report.added}개"
    if report.failed:
        text += f" · 실패 {len(report.failed)}개"
    return text


def _scan(report: ScanReport) -> str:
    return f"무료 모델 {len(report.models)}개 확인" if report.ok else f"확인 실패: {report.error}"


def describe_result(job: str, result: object) -> str:
    """작업이 돌려준 보고서의 한 줄 요약. 알 수 없는 모양이면 빈 글자."""
    if isinstance(result, SummarizeReport):
        return _summarize(result)
    if isinstance(result, DeliveryReport):
        return _deliver(result)
    if isinstance(result, CollectReport):
        return _collect(result)
    if isinstance(result, ScanReport):
        return _scan(result)
    if job == "retention" and isinstance(result, int):
        return f"오래된 글 {result}개 삭제" if result else "지울 글이 없었습니다"
    return ""
