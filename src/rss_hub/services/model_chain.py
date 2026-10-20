"""모델 체인 교체: 추천을 사용자가 승인하면 설정의 모델 체인을 바꾸고 시스템 웹훅으로 알린다."""

from collections.abc import Sequence
from dataclasses import dataclass

from rss_hub.services.alerts import AlertService
from rss_hub.services.settings import SettingsService
from rss_hub.storage.models import ModelRepository

MAX_CHAIN = 5


@dataclass(frozen=True)
class ApplyResult:
    ok: bool
    error: str = ""
    old: tuple[str, ...] = ()
    new: tuple[str, ...] = ()
    changed: bool = False


class ModelChainService:
    def __init__(
        self, *, settings: SettingsService, models: ModelRepository, alerts: AlertService
    ) -> None:
        self._settings = settings
        self._models = models
        self._alerts = alerts

    def apply(self, chain: Sequence[str]) -> ApplyResult:
        new = tuple(dict.fromkeys(m.strip() for m in chain if m.strip()))
        old = self._settings.snapshot().model_chain
        if not new:
            return ApplyResult(False, "바꿀 모델이 없습니다", old)
        if len(new) > MAX_CHAIN:
            return ApplyResult(False, f"체인은 {MAX_CHAIN}개까지입니다", old)
        if any("," in model for model in new):  # 설정은 쉼표로 이어 저장하므로 쪼개져 버린다
            return ApplyResult(False, "모델 이름에 쉼표가 있어 체인에 넣을 수 없습니다", old)
        known = {e.id for e in self._models.catalog()}
        if any(model not in known for model in new):
            return ApplyResult(False, "무료 목록에 없는 모델이 있습니다. 먼저 스캔하세요", old)
        if new == old:
            return ApplyResult(True, "", old, new, changed=False)
        result = self._settings.update({"model_chain": ",".join(new)})
        if result.errors:
            return ApplyResult(False, next(iter(result.errors.values())), old)
        self._alerts.notify(
            f"model_chain_changed:{','.join(new)}",
            "모델 체인이 바뀌었습니다.\n이전: " + ", ".join(old) + "\n새로: " + ", ".join(new),
        )
        return ApplyResult(True, "", old, new, changed=True)
