"""뷰어 시험용 세계: 카테고리 둘, 사이트 둘, 글을 쉽게 만드는 도우미."""

import re
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from rss_hub.storage.articles import ArticleRepository, NewArticle
from rss_hub.storage.feeds import FeedRepository
from rss_hub.storage.topics import TopicRepository
from tests.fakes.web_parts import start_app
from tests.keywords.store import create_category

BASE = datetime(2026, 10, 16, 1, 0, tzinfo=UTC)  # 한국 시각 10:00


class World:
    def __init__(self, parts):
        self.parts = parts
        self.client = parts.client
        self.feeds = FeedRepository(parts.db, parts.clock)
        self.articles = ArticleRepository(parts.db, parts.clock)
        self.topics = TopicRepository(parts.db, parts.clock)
        self.news = create_category(self.feeds, "뉴스")
        self.tech = create_category(self.feeds, "기술")
        self.f_news = self.feeds.add(
            "https://n.example.com/rss", "뉴스 블로그", category_id=self.news
        )
        self.f_free = self.feeds.add("https://f.example.com/rss", "자유 블로그")
        self.n = 0

    def article(
        self,
        feed=None,
        minutes=0,
        *,
        title=None,
        content="<p>본문입니다</p>",
        ko=None,
        summary=None,
        link=None,
        status="collected",
        published_kind="exact",
    ):
        self.n += 1
        article_id = self.articles.add(
            NewArticle(
                feed or self.f_free,
                f"g{self.n}",
                title or f"Title {self.n}",
                link if link is not None else f"https://x.example.com/{self.n}",
                content,
                "",
                BASE + timedelta(minutes=minutes),
                "2026-10-16",
                published_kind,
            )
        )
        if ko or summary:
            self.articles.mark_ready(
                article_id,
                title_ko=ko or "번역",
                summary_ko=summary or "요약",
                topics=[],
                model="m",
            )
        if status == "archived":
            with self.parts.db.connect() as conn:
                conn.execute("UPDATE articles SET status = 'archived' WHERE id = ?", (article_id,))
        return article_id

    def get(self, path):
        return self.client.get(path)


SECTION_NAMES = {"rss": "RSS", "categories": "카테고리", "topics": "주제", "settings": "설정"}


def groups(html):
    """사이드바의 구역(RSS, 카테고리, 주제, 설정)을 이름으로 나눈다."""
    nav = html.split('<nav aria-label="구독 목록">')[1].split("</nav>")[0]
    parts = re.split(r'<details class="sec" id="sec-', nav)[1:]
    return {SECTION_NAMES[part.split('"', 1)[0]]: part for part in parts}


@contextmanager
def open_world(tmp_path, *, fetcher=None):
    """실행 중인 앱과 World. fetcher를 주면 피드 수집기로 쓰고 world.fetcher로도 꺼내 쓴다."""
    parts, client = start_app(tmp_path, feed_fetcher=fetcher)
    with client:
        world = World(parts)
        world.fetcher = fetcher
        yield world
