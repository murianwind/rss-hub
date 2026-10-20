"""모델 벤치마크: 고정된 시험 글로 요약 품질을 재고, 점수로 모델 체인을 추천한다.

점수(100점): 성공률 50 + 한국어 제목 20 + 주제 판정 20 + 속도 10.
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

BENCH_TOPIC = Topic(1, "OTT", "OTT, 스트리밍 서비스와 영화, 드라마 소식", ("netflix",), None, True)


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
