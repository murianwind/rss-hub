"""웹 화면 시험의 공통 설정."""

import pytest


@pytest.fixture(autouse=True)
def _the_real_page_fetcher_never_touches_the_network(monkeypatch):
    """화면 시험은 원문 페이지를 실제로 가져오지 않는다(글을 열면 전문을 가져오려 하므로)."""
    from rss_hub.adapters.http_feed_fetcher import RequestsFeedFetcher
    from rss_hub.services.ports import FetchError

    def refuse(self, url):
        raise FetchError("NoNetworkInTests")

    monkeypatch.setattr(RequestsFeedFetcher, "fetch_page", refuse)
