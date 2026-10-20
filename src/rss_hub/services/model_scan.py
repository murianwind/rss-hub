"""무료 모델 스캔: 지금 쓸 수 있는 무료 텍스트 모델 목록을 가져와 저장하고, 변동을 알린다.

- 호출 한도를 쓰지 않는다(모델 목록 조회일 뿐 채팅 호출이 아니다).
- 지금 쓰는 모델 체인의 모델이 무료 목록에서 사라졌으면 시스템 웹훅으로 알린다(하루에 한 번).
- 목록이 비어 있으면 서비스 쪽 문제로 보고 저장하지 않는다
  (체인의 모델이 전부 사라진 것으로 오해하지 않도록).
"""

from dataclasses import dataclass, field

from rss_hub.domain.models import FreeModel
from rss_hub.services.alerts import AlertService
from rss_hub.services.ports import LlmClient
from rss_hub.services.settings import SettingsService
from rss_hub.storage.models import ModelRepository, ScanDiff

ALERT_CHAIN_GONE = "model_chain_gone"


@dataclass(frozen=True)
class ScanReport:
    ok: bool
    models: tuple[FreeModel, ...] = ()
    diff: ScanDiff = field(default_factory=lambda: ScanDiff((), (), ()))
    chain_missing: tuple[str, ...] = ()
    first_scan: bool = False
    error: str = ""


class ModelScanService:
    def __init__(
        self,
        *,
        client: LlmClient,
        models: ModelRepository,
        settings: SettingsService,
        alerts: AlertService,
    ) -> None:
        self._client = client
        self._models = models
        self._settings = settings
        self._alerts = alerts

    def scan(self) -> ScanReport:
        found = self._client.list_free_models()
        if found is None:
            return ScanReport(ok=False, error="모델 목록을 가져오지 못했습니다")
        if not found:
            return ScanReport(
                ok=False, error="모델 목록이 비어 있습니다. 잠시 뒤에 다시 시도하세요"
            )
        first = not self._models.catalog(include_gone=True)
        diff = self._models.save_scan(found)
        available = {m.id for m in found}
        missing = tuple(m for m in self._settings.snapshot().model_chain if m not in available)
        if missing:
            self._alerts.notify(
                ALERT_CHAIN_GONE,
                "모델 체인의 모델이 무료 목록에서 사라졌습니다: " + ", ".join(missing),
                once_per_day=True,
            )
        return ScanReport(
            ok=True, models=tuple(found), diff=diff, chain_missing=missing, first_scan=first
        )
