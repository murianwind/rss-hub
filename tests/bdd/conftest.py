"""BDD 공용 단계.

수집 시나리오의 배경(Background)은 서비스의 기본값과 테스트 환경(2026-10-16 14:00, Asia/Seoul)이
이미 같아서 별도 준비가 필요 없다. 환경이 이 값과 다르면 환경을 만드는 쪽(CollectEnv)이 실패한다.
"""

import pytest
from pytest_bdd import given


@given('오늘은 "2026-10-16"이다')
def _today_is_fixed():
    """CollectEnv의 가짜 시계가 2026-10-16 14:00(Asia/Seoul)로 시작한다."""


@given("피드당 최대 검사 항목 수 기본값은 50이다")
def _default_max_entries():
    """설정의 기본값(default_max_entries)이 50이다."""


@given('서비스 시간대는 "Asia/Seoul"이다')
def _service_timezone():
    """설정의 기본값(service_timezone)이 Asia/Seoul이다."""


@given("수집 주기는 5분이다")
def _default_interval():
    """설정의 기본값(collect_interval_minutes)이 5이다."""


@given("한 슬롯의 기본 배치 크기는 15이다")
def _default_batch_size():
    """설정의 기본값(slot_batch_size)이 15이다."""


@pytest.fixture(autouse=True)
def _the_real_page_fetcher_never_touches_the_network(monkeypatch):
    """화면 시험은 원문 페이지를 실제로 가져오지 않는다(글을 열면 전문을 가져오려 하므로)."""
    from rss_hub.adapters.http_feed_fetcher import RequestsFeedFetcher
    from rss_hub.services.ports import FetchError

    def refuse(self, url):
        raise FetchError("NoNetworkInTests")

    monkeypatch.setattr(RequestsFeedFetcher, "fetch_page", refuse)
