"""주제 피드백 화면(M5): 글 페이지와 주제 목록의 싫어요, 되돌리기, 주제로 버튼, 키워드 개선 제안.

- 싫어요는 그 주제 목록에서만 글을 뺀다. RSS와 카테고리 목록에는 그대로 남고, 되돌릴 수 있다.
- 주제로는 글을 그 주제에 넣는다. 이미 보낸 알림을 다시 보내지는 않는다
  (아직 보내지 않은 글은 주제 웹훅으로 간다).
- 키워드 개선 제안은 근거를 보여 주기만 하고, 사용자가 승인해야 주제의 키워드가 바뀐다.
"""

import re

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from rss_hub.domain.topic_suggestions import suggest_additions, suggest_removals
from rss_hub.domain.topics import Topic, TopicInputError, validate_topic_fields
from rss_hub.storage.articles import ArticleRepository
from rss_hub.storage.topics import TopicRepository

_SAFE_NEXT = re.compile(
    r"^/(?:reader(?:/(?:feed|category|topic)/\d+)?|a/\d+|topics/\d+/suggestions)(?:\?page=\d+)?$"
)
ACTIONS = ("reject", "restore", "add")
LAST_KEYWORD_MESSAGE = (
    "마지막 키워드는 지울 수 없습니다. 키워드가 하나도 없으면 모든 글을 LLM에게 묻게 됩니다. "
    "정말 비우려면 주제 화면에서 직접 고치세요."
)


def safe_next(value: object, default: str) -> str:
    """돌아갈 곳은 이 서비스의 읽기 화면 경로만 허용한다(다른 주소로 보내는 것을 막는다)."""
    text = str(value or "")
    return text if _SAFE_NEXT.fullmatch(text) else default


def build_feedback_router(
    *, topics: TopicRepository, articles: ArticleRepository, templates: Jinja2Templates
) -> APIRouter:
    router = APIRouter()

    # ---------- 글 하나에 대한 버튼 ----------

    @router.post("/a/{article_id}/topics/{topic_id}/{action}")
    async def decide(request: Request, article_id: int, topic_id: int, action: str) -> Response:
        if action not in ACTIONS:
            return PlainTextResponse("알 수 없는 동작입니다", status_code=404)
        topic = topics.get(topic_id)
        if articles.get(article_id) is None or topic is None:
            return PlainTextResponse("글이나 주제를 찾을 수 없습니다", status_code=404)
        if action == "add" and not topic.enabled:
            return PlainTextResponse("꺼진 주제에는 넣을 수 없습니다", status_code=400)
        form = await request.form()
        if action == "reject":
            topics.reject(article_id, topic_id)
        elif action == "restore":
            topics.restore(article_id, topic_id)
        else:
            topics.add_manual(article_id, topic_id)
        return RedirectResponse(safe_next(form.get("next"), f"/a/{article_id}"), status_code=303)

    # ---------- 키워드 개선 제안 ----------

    def suggestions_page(
        request: Request, topic: Topic, *, error: str = "", notice: str = "", status_code: int = 200
    ) -> HTMLResponse:
        samples = topics.feedback_samples(topic.id)
        manual = [s for s in samples if s.source == "manual" and not s.rejected]
        rejected = [s for s in samples if s.rejected]
        context = {
            "topic": topic,
            "manual": manual,
            "rejected": rejected,
            "additions": suggest_additions(
                [s.title for s in manual], [s.title for s in rejected], topic.keywords
            ),
            "removals": suggest_removals(topics.keyword_outcomes(topic.id)),
            "error": error,
            "notice": notice,
        }
        return templates.TemplateResponse(
            request, "topic_suggestions.html", context, status_code=status_code
        )

    @router.get("/topics/{topic_id}/suggestions", response_class=HTMLResponse)
    def suggestions(request: Request, topic_id: int, saved: str = "") -> Response:
        topic = topics.get(topic_id)
        if topic is None:
            return PlainTextResponse("주제를 찾을 수 없습니다", status_code=404)
        return suggestions_page(request, topic, notice="키워드를 바꿨습니다." if saved else "")

    @router.post("/topics/{topic_id}/keywords/{action}", response_class=HTMLResponse)
    async def change_keyword(request: Request, topic_id: int, action: str) -> Response:
        topic = topics.get(topic_id)
        if topic is None or action not in ("add", "remove"):
            return PlainTextResponse("주제를 찾을 수 없습니다", status_code=404)
        form = await request.form()
        keyword = str(form.get("keyword", "")).strip()
        current = list(topic.keywords)
        if action == "add":
            changed = (
                [*current, keyword]
                if keyword and keyword.lower() not in map(str.lower, current)
                else current
            )
        else:
            if keyword not in current:
                return suggestions_page(
                    request, topic, error="그런 키워드가 없습니다", status_code=400
                )
            changed = [k for k in current if k != keyword]
            if not changed:
                return suggestions_page(request, topic, error=LAST_KEYWORD_MESSAGE, status_code=400)
        try:
            fields = validate_topic_fields(topic.name, topic.description, ", ".join(changed))
        except TopicInputError as error:
            return suggestions_page(request, topic, error=error.message, status_code=400)
        topics.update(topic.id, fields, webhook_id=topic.webhook_id, enabled=topic.enabled)
        return RedirectResponse(f"/topics/{topic.id}/suggestions?saved=1", status_code=303)

    return router
