"""공용 pytest 설정. 시나리오별 상태는 각 BDD 모듈의 ctx 픽스처가 만든다."""

import pytest

from tests.fakes.viewer_world import open_world


@pytest.fixture
def world(tmp_path):
    """실행 중인 앱과 기본 데이터(카테고리 둘, 사이트 둘)."""
    with open_world(tmp_path) as opened:
        yield opened


@pytest.fixture(autouse=True)
def _the_real_page_fetcher_never_touches_the_network(request, monkeypatch):
    """글을 열면 원문 페이지를 가져오려 하므로, 실제 수집기의 페이지 가져오기를 막는다.

    어댑터 시험은 이것을 실제 로컬 서버로 시험한다.
    """
    if "adapters" in request.path.parts:
        return
    from rss_hub.adapters.http_feed_fetcher import RequestsFeedFetcher
    from rss_hub.services.ports import FetchError

    def refuse(self, url):
        raise FetchError("NoNetworkInTests")

    monkeypatch.setattr(RequestsFeedFetcher, "fetch_page", refuse)
