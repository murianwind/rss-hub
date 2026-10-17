"""시스템 알림: 운영자가 알아야 하는 상황(호출 상한, 잔액 부족 등)을 시스템 웹훅으로 알린다.

같은 종류의 알림은 쿨다운(설정) 동안 반복하지 않는다.
보내지 못했으면 기록하지 않아서 다음 기회에 다시 시도한다.
"""

import logging
from datetime import UTC, timedelta

from rss_hub.services.clock import Clock
from rss_hub.services.ports import Notifier
from rss_hub.services.settings import SettingsService
from rss_hub.storage.alerts import AlertRepository

logger = logging.getLogger(__name__)


class AlertService:
    def __init__(
        self,
        *,
        alerts: AlertRepository,
        settings: SettingsService,
        notifier: Notifier,
        clock: Clock,
    ) -> None:
        self._alerts = alerts
        self._settings = settings
        self._notifier = notifier
        self._clock = clock

    def notify(self, kind: str, text: str, *, once_per_day: bool = False) -> bool:
        """알림을 보냈으면 True. 시스템 웹훅이 없거나, 쿨다운 중이거나, 전송에 실패하면 False."""
        config = self._settings.snapshot()
        webhook_id = config.webhook_system_id
        url = None if webhook_id is None else self._settings.get_webhook_url(webhook_id)
        if url is None:
            return False

        now = self._clock.now()
        last = self._alerts.last_sent(kind)
        if last is not None:
            if once_per_day:
                if last.astimezone(UTC).date() == now.astimezone(UTC).date():
                    return False
            elif now - last < timedelta(hours=config.alert_cooldown_hours):
                return False

        try:
            self._notifier.send(url, text)
        except Exception:
            # 웹훅 주소는 로그에 남기지 않는다
            logger.warning("시스템 알림 전송에 실패했습니다: kind=%s", kind, exc_info=False)
            return False
        self._alerts.record(kind, text)
        return True
