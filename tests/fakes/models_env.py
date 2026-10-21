"""모델 스캔, 벤치마크, 체인 교체 시험 환경(LLM 시험 환경에 모델 저장소와 서비스를 더한 것)."""

from rss_hub.domain.benchmark import SAMPLES
from rss_hub.domain.models import FreeModel
from rss_hub.services.model_benchmark import BenchmarkService
from rss_hub.services.model_chain import ModelChainService
from rss_hub.services.model_scan import ModelScanService
from rss_hub.storage.models import ModelRepository
from tests.fakes.llm_client import reply
from tests.fakes.llm_env import LlmEnv


def free(model_id, **kwargs):
    return FreeModel(model_id, model_id, 32768, kwargs.get("json", True))


class Env(LlmEnv):
    def __init__(self, tmp_path, **kwargs):
        super().__init__(tmp_path, **kwargs)
        self.models = ModelRepository(self.db, self.clock)
        self.scanner = ModelScanService(
            client=self.client, models=self.models, settings=self.settings, alerts=self.alerts
        )
        self.chain = ModelChainService(
            settings=self.settings, models=self.models, alerts=self.alerts
        )
        self.ticks = 0.0
        self.monotonic_calls = 0
        self.sleeps_log: list[float] = []
        self.latency = 2.0

    def monotonic(self):
        """호출 하나가 latency초 걸린 것처럼 보이게 한다(시작과 끝, 두 번 불린다)."""
        self.monotonic_calls += 1
        if self.monotonic_calls % 2 == 0:
            self.ticks += self.latency
        return self.ticks

    def benchmark(self):
        return BenchmarkService(
            gateway=self.gateway,
            models=self.models,
            sleep=self.sleeps_log.append,
            monotonic=self.monotonic,
        )

    def perfect_answers(self, model, *, korean=True):
        """시험 글 6개에 대한 완벽한 답: OTT에 해당하는 글에만 주제 1."""
        title = "한국어 제목" if korean else "English title only"
        self.client.will(
            model,
            *[reply(title, "요약입니다.", topics=[1] if s.expects_topic else []) for s in SAMPLES],
        )
