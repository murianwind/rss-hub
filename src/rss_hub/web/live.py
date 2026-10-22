"""화면을 다시 불러오지 않고 사이드바를 갱신하는 데 쓰는 경로: 개수와 상태, 피드 강제 새로고침."""

from dataclasses import replace

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from rss_hub.domain.discovery import describe_fetch_failure
from rss_hub.services.collect import CollectService
from rss_hub.storage.feeds import FeedRepository
from rss_hub.storage.reader import ReaderRepository, Sidebar
from rss_hub.web.ui import ModelUsageView


def sidebar_state(side: Sidebar, model_usage: dict[str, int] | None = None) -> dict[str, object]:
    """사이드바의 모든 개수와 피드 상태(스크립트가 화면의 뱃지와 점을 고쳐 쓴다)."""
    return {
        "feeds": {
            str(f.id): {"state": f.state, "error": f.error, "unread": f.unread, "total": f.total}
            for f in side.feeds
        },
        "categories": {str(c.id): {"unread": c.unread, "total": c.total} for c in side.categories},
        "topics": {str(t.id): {"unread": t.unread, "total": t.total} for t in side.topics},
        "all_unread": side.all_unread,
        "bookmarks": side.bookmarks,
        "model_usage": model_usage,
    }


def build_live_router(
    *,
    reader: ReaderRepository,
    feeds: FeedRepository,
    collector: CollectService,
    model_usage: ModelUsageView,
) -> APIRouter:
    router = APIRouter()

    @router.get("/ui/state")
    def state() -> JSONResponse:
        return JSONResponse(sidebar_state(reader.sidebar(), model_usage()))

    @router.post("/ui/model-usage/refresh")
    def refresh_model_usage() -> JSONResponse:
        """서버에 오늘 호출 수를 바로 다시 묻는다(1분 동안 재사용하는 값을 건너뛴다)."""
        fresh = model_usage.refresh()
        if fresh is None:
            return JSONResponse({"error": "서버에서 값을 받지 못했습니다"}, status_code=502)
        return JSONResponse(fresh)

    @router.post("/feeds/{feed_id}/refresh")
    def refresh(feed_id: int) -> JSONResponse:
        """피드를 지금 바로 다시 읽는다. 저장된 검증값(etag)을 쓰지 않아서 새로 읽는다."""
        feed = feeds.get(feed_id)
        if feed is None:
            return JSONResponse({"ok": False, "error": "피드를 찾을 수 없음"}, status_code=404)
        report = collector.collect_feeds([replace(feed, etag=None, last_modified=None)])
        error = describe_fetch_failure(report.failed[0][1]) if report.failed else ""
        return JSONResponse(
            {
                "ok": not error,
                "error": error,
                "added": report.added,
                "baseline": report.baseline_recorded,
                "state": sidebar_state(reader.sidebar(), model_usage()),
            }
        )

    return router
