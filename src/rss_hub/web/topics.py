"""주제 알림 화면: 주제 목록, 추가, 수정, 삭제."""

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from rss_hub.domain.topics import TopicInputError, validate_topic_fields
from rss_hub.services.settings import SettingsService
from rss_hub.services.topic_probe import ProbeResult, TopicProbe
from rss_hub.storage.topics import TopicRepository
from rss_hub.web.forms import id_or_none
from rss_hub.web.ui import done, done_after_delete


def _counts(topics: TopicRepository, topic_id: int) -> tuple[int, int]:
    samples = topics.feedback_samples(topic_id)
    return (
        sum(1 for s in samples if s.source == "manual" and not s.rejected),
        sum(1 for s in samples if s.rejected),
    )


def build_topic_router(
    topics: TopicRepository,
    settings: SettingsService,
    templates: Jinja2Templates,
    probe: TopicProbe,
) -> APIRouter:
    router = APIRouter()

    def page(
        request: Request,
        *,
        error: str = "",
        notice: str = "",
        status_code: int = 200,
        probe_result: ProbeResult | None = None,
        probe_input: tuple[str, str] = ("", ""),
    ) -> HTMLResponse:
        context = {
            "probe": probe_result,
            "probe_title": probe_input[0],
            "probe_body": probe_input[1],
            "webhook_names": {w.id: w.name for w in settings.list_webhooks()},
            "topics": topics.list_all(),
            "feedback_counts": {t.id: _counts(topics, t.id) for t in topics.list_all()},
            "webhooks": settings.list_webhooks(),
            "error": error,
            "notice": notice,
        }
        return templates.TemplateResponse(request, "topics.html", context, status_code=status_code)

    @router.get("/topics", response_class=HTMLResponse)
    def topic_page(request: Request, saved: str = "", deleted: str = "") -> HTMLResponse:
        notice = "저장했습니다." if saved else "삭제했습니다." if deleted else ""
        return page(request, notice=notice)

    @router.post("/topics/probe", response_class=HTMLResponse)
    async def probe_topics(request: Request) -> Response:
        form = await request.form()
        title, body = str(form.get("title", "")), str(form.get("body", ""))
        return page(request, probe_result=probe.run(title, body), probe_input=(title, body))

    @router.post("/topics/add", response_class=HTMLResponse)
    async def add_topic(request: Request) -> Response:
        form = await request.form()
        try:
            fields = validate_topic_fields(
                str(form.get("name", "")),
                str(form.get("description", "")),
                str(form.get("keywords", "")),
            )
            topics.add(
                fields,
                webhook_id=id_or_none(form.get("webhook_id")),
                enabled=form.get("enabled") == "yes",
            )
        except TopicInputError as error:
            return page(request, error=error.message, status_code=400)
        return done(form, "/topics?saved=1", "saved")

    @router.post("/topics/{topic_id}/update", response_class=HTMLResponse)
    async def update_topic(request: Request, topic_id: int) -> Response:
        form = await request.form()
        try:
            fields = validate_topic_fields(
                str(form.get("name", "")),
                str(form.get("description", "")),
                str(form.get("keywords", "")),
            )
            found = topics.update(
                topic_id,
                fields,
                webhook_id=id_or_none(form.get("webhook_id")),
                enabled=form.get("enabled") == "yes",
            )
        except TopicInputError as error:
            return page(request, error=error.message, status_code=400)
        if not found:
            return page(request, error="주제를 찾을 수 없음", status_code=404)
        return done(form, "/topics?saved=1", "saved")

    @router.post("/topics/{topic_id}/delete", response_class=HTMLResponse)
    async def delete_topic(request: Request, topic_id: int) -> Response:
        form = await request.form()
        if form.get("confirm") != "yes":
            return page(request, error="삭제 확인이 필요합니다", status_code=400)
        if not topics.delete(topic_id):
            return page(request, error="주제를 찾을 수 없음", status_code=404)
        return done_after_delete(form, "/topics?deleted=1", "deleted", "topic", topic_id)

    return router
