"""글 하나의 제목 번역과 요약을 사용자가 다시 요청한다.

수집 파이프라인(SummarizeService)과 달리 글의 상태, 재시도 횟수, 주제, 발송 여부는 건드리지 않고
제목 번역과 요약만 바꾼다. 실패하면 이전 값을 그대로 둔다.
"""

from dataclasses import dataclass

from rss_hub.domain.korean import is_korean
from rss_hub.domain.prompts import build_summary_prompt, summary_excerpt
from rss_hub.domain.validation import validate_summary
from rss_hub.services.llm_gateway import BudgetBlocked, LlmGateway, LlmNotConfigured, LlmOutage
from rss_hub.services.summary_check import summary_rejection
from rss_hub.storage.articles import Article, ArticleRepository

OK = "ok"
KOREAN = "korean"  # 이미 한국어 글이라 번역하지 않았다
NOT_CONFIGURED = "not_configured"  # OpenRouter 키가 없다
BLOCKED = "blocked"  # 호출 예산 때문에 보내지 않았다
OUTAGE = "outage"  # 모든 모델이 응답하지 못했다
REJECTED = "rejected"  # 응답을 쓸 수 없었다


def needs_translation(article: Article) -> bool:
    """원문이 한국어가 아닌 글(제목과 본문으로 판단)."""
    return not is_korean(f"{article.title} {article.content_html}")


def offers_retranslation(article: Article) -> bool:
    """글 화면에 다시 요청 버튼을 보일 글: 원문이 한국어가 아니고 제목이나 요약이 한국어가 아니다.

    제목과 요약이 모두 한국어면(번역이 된 글) 보이지 않는다.
    요약이 영어 발췌이거나 비어 있으면 보인다."""
    translated = is_korean(article.title_ko) and is_korean(article.summary_ko)
    return needs_translation(article) and not translated


@dataclass(frozen=True)
class Retranslation:
    state: str


class RetranslateService:
    def __init__(self, *, articles: ArticleRepository, gateway: LlmGateway) -> None:
        self._articles = articles
        self._gateway = gateway

    def run(self, article: Article) -> Retranslation:
        if not needs_translation(article):
            return Retranslation(KOREAN)
        body = article.full_html if article.full_status == "ok" and article.full_html else None
        prompt = build_summary_prompt(article.title, summary_excerpt(body or article.content_html))
        try:
            answer = self._gateway.complete(prompt, summary_rejection())
        except LlmNotConfigured:
            return Retranslation(NOT_CONFIGURED)
        except BudgetBlocked:
            return Retranslation(BLOCKED)
        except LlmOutage:
            return Retranslation(OUTAGE)
        draft = validate_summary(answer.content, answer.finish_reason).draft
        if draft is None:
            return Retranslation(REJECTED)
        self._articles.save_translation(
            article.id, title_ko=draft.title_ko, summary_ko=draft.summary_ko, model=answer.model
        )
        return Retranslation(OK)
