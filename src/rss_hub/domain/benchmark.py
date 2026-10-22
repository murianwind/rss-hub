"""모델 벤치마크: 고정된 시험 글로 요약 품질을 재고, 점수로 모델 체인을 추천한다.

점수(100점): 성공률 50 + 한국어 제목 20 + 주제 판정 20 + 속도 10.
한도 초과나 일시 장애로만 실패한 모델은 품질을 잴 수 없으므로 "측정 못 함"으로 구분한다.
- 성공률: 응답이 요약 응답 검증을 통과한 비율.
- 한국어 제목: 통과한 응답 중 번역 제목이 한국어인 비율.
- 주제 판정: 통과한 응답 중 주제 확인이 기대와 같은 비율.
- 속도: 성공한 호출의 중앙값이 5초 이하면 만점, 30초 이상이면 0점, 그 사이는 직선.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from statistics import median

from rss_hub.domain.topics import Topic

SPEED_FULL_MS = 5_000
SPEED_ZERO_MS = 30_000
MIN_OK_RATE = 0.8  # 추천 대상이 되려면 성공률이 이 이상이어야 한다
CHAIN_SIZE = 3
WEIGHTS = (50.0, 20.0, 20.0, 10.0)

BENCH_TOPIC = Topic(1, "OTT", "OTT, 스트리밍 서비스와 영화, 드라마 소식", ("netflix",), None)


@dataclass(frozen=True)
class BenchSample:
    title: str
    content: str
    expects_topic: bool  # BENCH_TOPIC(OTT)에 해당해야 하는 글인가


SAMPLES: tuple[BenchSample, ...] = (
    BenchSample(
        "Netflix announces a new original drama series for next spring",
        "Netflix said on Tuesday that a new original drama series will premiere next spring. "
        "The series follows three siblings who inherit a failing hotel, and the streaming service "
        "has ordered two seasons. Filming begins this summer in Vancouver, and the cast includes "
        "several actors from earlier hit shows on the platform.",
        True,
    ),
    BenchSample(
        "Apple unveils the iPhone 18 with a bigger battery and a faster chip",
        "Apple introduced the iPhone 18 on Wednesday with a larger battery, a faster processor, "
        "and an improved camera system. The company said the phone lasts about two hours longer "
        "than last year's model, and preorders start Friday in more than forty countries.",
        False,
    ),
    BenchSample(
        "넷플릭스, 새 오리지널 드라마 시리즈 공개 일정 발표",
        "넷플릭스가 새 오리지널 드라마 시리즈의 공개 일정을 발표했다. 이 작품은 폐업 위기의 호텔을 "
        "물려받은 세 남매의 이야기를 그리며, 전 세계 190여 개국에서 동시에 공개된다. 제작사는 "
        "다음 달 첫 예고편을 내놓을 예정이라고 밝혔다.",
        True,
    ),
    BenchSample(
        "스프링 부트 4 마이그레이션 후기와 주의할 점",
        "스프링 부트 3에서 4로 올리면서 겪은 문제를 정리했다. 의존성 충돌, 설정 속성 이름 변경, "
        "테스트 슬라이스 변경이 가장 큰 걸림돌이었다. 단계별로 올리는 방법과 자동 변환 도구의 "
        "한계도 함께 적었다.",
        False,
    ),
    BenchSample(
        "Disney+ raises prices again and adds a cheaper ad-supported plan",
        "Disney+ will raise its subscription prices next month while expanding a cheaper plan that "
        "includes advertising. The streaming service said the change helps fund new movies and "
        "series, and that existing subscribers can keep their current plan for one more billing "
        "cycle before the new prices apply.",
        True,
    ),
    BenchSample(
        "Central bank holds interest rates steady as inflation cools",
        "The central bank left its benchmark interest rate unchanged on Thursday, saying inflation "
        "has cooled but remains above its target. Officials signaled that cuts could begin later "
        "this year if the trend continues, and markets reacted calmly to the announcement.",
        False,
    ),
)


@dataclass(frozen=True)
class CallResult:
    ok: bool  # 요약 응답 검증을 통과했다
    korean_ok: bool
    topic_ok: bool
    latency_ms: int | None
    error: str = ""


@dataclass(frozen=True)
class ModelScore:
    model: str
    calls: int
    ok: int
    korean: int  # 통과한 응답 중 한국어 제목 수
    topic: int  # 통과한 응답 중 주제 판정이 기대와 같은 수
    p50_ms: int | None
    score: float
    errors: tuple[str, ...]


@dataclass(frozen=True)
class Recommendation:
    chain: tuple[str, ...]
    changed: bool
    reason: str


def speed_points(p50_ms: int | None) -> float:
    if p50_ms is None:
        return 0.0
    if p50_ms <= SPEED_FULL_MS:
        return WEIGHTS[3]
    if p50_ms >= SPEED_ZERO_MS:
        return 0.0
    return WEIGHTS[3] * (SPEED_ZERO_MS - p50_ms) / (SPEED_ZERO_MS - SPEED_FULL_MS)


def score_model(model: str, results: Sequence[CallResult]) -> ModelScore:
    calls = len(results)
    passed = [r for r in results if r.ok]
    ok, korean = len(passed), sum(r.korean_ok for r in passed)
    topic = sum(r.topic_ok for r in passed)
    latencies = [r.latency_ms for r in passed if r.latency_ms is not None]
    p50 = int(median(latencies)) if latencies else None
    total = 0.0
    if calls:
        total += WEIGHTS[0] * ok / calls
        if ok:
            total += WEIGHTS[1] * korean / ok + WEIGHTS[2] * topic / ok
        total += speed_points(p50)
    errors = tuple(r.error for r in results if not r.ok and r.error)
    return ModelScore(model, calls, ok, korean, topic, p50, round(total, 1), errors)


def recommend(
    scores: Sequence[ModelScore],
    current_chain: Sequence[str],
    *,
    size: int = CHAIN_SIZE,
    min_ok_rate: float = MIN_OK_RATE,
) -> Recommendation:
    eligible = [s for s in scores if s.calls and s.ok / s.calls >= min_ok_rate]
    if not eligible:
        return Recommendation((), False, f"성공률 {int(min_ok_rate * 100)}% 이상인 모델이 없습니다")
    eligible.sort(key=lambda s: (-s.score, s.p50_ms if s.p50_ms is not None else 10**9, s.model))
    chain = tuple(s.model for s in eligible[:size])
    if chain == tuple(current_chain):
        return Recommendation(chain, False, "현재 체인이 이미 가장 좋습니다")
    best = eligible[0]
    return Recommendation(
        chain, True, f"가장 점수가 높은 모델은 {best.model}({best.score}점)입니다"
    )


# ---------- 결과를 사람이 읽을 수 있게 풀기 ----------


@dataclass(frozen=True)
class ErrorInfo:
    label: str
    explanation: str
    transient: bool = False  # 모델 품질과 무관한 실패(다시 시험하면 달라질 수 있다)


_TRANSIENT_NOTE = "모델 품질과는 무관하니 잠시 뒤 다시 시험하세요."
ERRORS: dict[str, ErrorInfo] = {
    "rate_limited": ErrorInfo(
        "요청 한도 초과",
        f"모델 공급자가 요청이 몰려 거절했습니다(429). {_TRANSIENT_NOTE}",
        True,
    ),
    "unavailable": ErrorInfo(
        "일시 장애", f"모델 서버 오류나 시간 초과입니다(5xx). {_TRANSIENT_NOTE}", True
    ),
    "payment": ErrorInfo("잔액 부족", "OpenRouter 잔액이 부족합니다(402)."),
    "unauthorized": ErrorInfo(
        "키 거부", "OpenRouter가 키를 거부했습니다. 모델 화면에서 키를 확인하세요."
    ),
    "policy": ErrorInfo(
        "개인정보 설정",
        "OpenRouter 개인정보 설정에서 무료 모델 사용(데이터 정책)을 허용해야 합니다.",
    ),
    "unsupported": ErrorInfo(
        "지원하지 않는 옵션", "이 모델이나 공급자가 JSON 응답 같은 요청 옵션을 지원하지 않습니다."
    ),
    "other": ErrorInfo("알 수 없는 오류", "원인을 알 수 없는 호출 오류입니다."),
    "not_json": ErrorInfo("응답이 JSON이 아님", "요청한 JSON 형식이 아닌 글로 답했습니다."),
    "missing_field": ErrorInfo("필수 항목 누락", "JSON에 제목, 요약 같은 필수 항목이 빠졌습니다."),
    "empty_title": ErrorInfo("제목이 비어 있음", "번역 제목을 비워서 답했습니다."),
    "empty_summary": ErrorInfo("요약이 비어 있음", "요약을 비워서 답했습니다."),
    "hanja": ErrorInfo("한자 섞임", "한국어 요약에 한자가 섞여 나왔습니다."),
    "reasoning_leak": ErrorInfo("생각 과정 노출", "답에 모델의 생각 과정이 섞여 나왔습니다."),
    "format_marker": ErrorInfo("형식 표시 섞임", "답에 마크다운 같은 형식 표시가 섞여 나왔습니다."),
    "truncated": ErrorInfo("응답이 잘림", "글자 수 한도에 걸려 답이 중간에 끊겼습니다."),
}
UNKNOWN_ERROR = ErrorInfo("응답이 올바르지 않음", "요약 응답 검사를 통과하지 못했습니다.")


def describe_error(code: str) -> ErrorInfo:
    return ERRORS.get(code, UNKNOWN_ERROR)


@dataclass(frozen=True)
class FailureLine:
    label: str
    count: int
    explanation: str


@dataclass(frozen=True)
class ScoreExplanation:
    measured: bool
    headline: str  # "종합 78점" 또는 "측정 못 함"
    parts: tuple[str, ...]  # "성공 5/6(83%)", "한국어 제목 5/5", ...
    failures: tuple[FailureLine, ...]


def is_unmeasured(score: ModelScore) -> bool:
    """통과한 호출이 하나도 없고 실패가 모두 품질과 무관한 것이면 품질을 잰 것이 아니다."""
    return (
        score.ok == 0
        and bool(score.errors)
        and all(describe_error(code).transient for code in score.errors)
    )


def _seconds(milliseconds: int) -> str:
    return f"{milliseconds / 1000:.1f}".removesuffix(".0")


def explain_score(score: ModelScore) -> ScoreExplanation:
    percent = round(100 * score.ok / score.calls) if score.calls else 0
    parts = [f"성공 {score.ok}/{score.calls}({percent}%)"]
    if score.ok:
        parts += [f"한국어 제목 {score.korean}/{score.ok}", f"주제 판정 {score.topic}/{score.ok}"]
    if score.p50_ms is not None:
        parts.append(f"응답 {_seconds(score.p50_ms)}초")
    counts: dict[str, int] = {}
    for code in score.errors:
        counts[code] = counts.get(code, 0) + 1
    failures = tuple(
        FailureLine(describe_error(code).label, count, describe_error(code).explanation)
        for code, count in sorted(counts.items(), key=lambda item: -item[1])
    )
    measured = not is_unmeasured(score)
    headline = f"종합 {score.score:g}점" if measured else "측정 못 함"
    return ScoreExplanation(measured, headline, tuple(parts), failures)


def format_tokens(count: int) -> str:
    """문맥 길이(토큰 수)를 짧게: 262144 → 262K."""
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}".removesuffix(".0") + "M"
    return f"{round(count / 1000)}K" if count >= 1000 else str(count)
