"""주제 피드백 화면: 글 페이지와 주제 목록의 싫어요, 되돌리기, 주제로 버튼, 키워드 개선 제안.

- 싫어요는 그 주제 목록에서만 글을 뺀다. RSS와 카테고리 목록에는 그대로 남고, 되돌릴 수 있다.
- 주제로는 글을 그 주제에 넣는다. 이미 보낸 알림을 다시 보내지는 않는다
  (아직 보내지 않은 글은 주제 웹훅으로 간다).
- 키워드 개선 제안은 근거를 보여 주기만 하고, 사용자가 승인해야 주제의 키워드가 바뀐다.
"""

from fastapi import APIRouter, Request, Response
from fastapi.responses import PlainTextResponse, RedirectResponse

from rss_hub.domain.topics import TopicInputError, validate_topic_fields
from rss_hub.services.keyword_suggestions import KIND_ADD, KIND_REMOVE
from rss_hub.storage.articles import ArticleRepository
from rss_hub.storage.topics import TopicRepository
from rss_hub.web.ui import safe_path

ACTIONS = ("reject", "restore", "add")
WARNINGS = {
    "last": (
        "마지막 키워드는 지울 수 없습니다. 주제에는 키워드가 하나 이상 있어야 합니다. "
        "주제를 없애려면 주제 카드에서 삭제하세요."
    ),
    "missing": "그런 키워드가 없습니다",
}


def safe_next(value: object, default: str) -> str:
    """돌아갈 곳은 이 서비스의 읽기 화면 경로만 허용한다(다른 주소로 보내는 것을 막는다)."""
    return safe_path(value, default)


def build_feedback_router(*, topics: TopicRepository, articles: ArticleRepository) -> APIRouter:
    router = APIRouter()

    # ---------- 글 하나에 대한 버튼 ----------

    @router.post("/a/{article_id}/topics/{topic_id}/{action}")
    async def decide(request: Request, article_id: int, topic_id: int, action: str) -> Response:
        if action not in ACTIONS:
            return PlainTextResponse("알 수 없는 동작입니다", status_code=404)
        topic = topics.get(topic_id)
        if articles.get(article_id) is None or topic is None:
            return PlainTextResponse("글이나 주제를 찾을 수 없습니다", status_code=404)
        form = await request.form()
        if action == "reject":
            topics.reject(article_id, topic_id)
        elif action == "restore":
            topics.restore(article_id, topic_id)
        else:
            topics.add_manual(article_id, topic_id)
        return RedirectResponse(safe_next(form.get("next"), f"/a/{article_id}"), status_code=303)

    # ---------- 키워드 개선 제안(주제 카드 안에서 보여 준다) ----------

    @router.post("/topics/{topic_id}/keywords/{action}")
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
                return RedirectResponse("/topics?warn=missing", status_code=303)
            changed = [k for k in current if k != keyword]
            if not changed:
                return RedirectResponse("/topics?warn=last", status_code=303)
        try:
            fields = validate_topic_fields(topic.name, topic.description, ", ".join(changed))
        except TopicInputError:
            return RedirectResponse("/topics?warn=last", status_code=303)
        topics.update(topic.id, fields, webhook_id=topic.webhook_id)
        return RedirectResponse("/topics?saved=1", status_code=303)

    @router.post("/topics/{topic_id}/suggestions/dismiss")
    async def dismiss_suggestion(request: Request, topic_id: int) -> Response:
        """제안 하나를 지운다. 지운 제안은 같은 단어가 다시 제안되지 않는다."""
        form = await request.form()
        kind, keyword = str(form.get("kind", "")), str(form.get("keyword", "")).strip()
        if kind not in (KIND_ADD, KIND_REMOVE) or not keyword:
            return PlainTextResponse("알 수 없는 제안입니다", status_code=400)
        if not topics.dismiss_suggestion(topic_id, kind, keyword):
            return PlainTextResponse("주제를 찾을 수 없습니다", status_code=404)
        return RedirectResponse("/topics", status_code=303)

    return router
