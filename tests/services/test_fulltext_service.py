"""글의 전문 가져오기: 처음 한 번만 가져오고, 실패도 기록하고, 다시 가져오기는 명시적으로만."""

from dataclasses import dataclass, field

import pytest

from rss_hub.services.fulltext import FullTextService
from rss_hub.services.ports import FetchError, PageResult
from rss_hub.storage.articles import ArticleRepository, NewArticle
from rss_hub.storage.database import Database
from rss_hub.storage.feeds import FeedRepository
from tests.fakes.clock import FakeClock

PARAGRAPH = "원문에만 있는 본문 문장입니다. " * 30
PAGE = (
    f"<html><body><nav>메뉴</nav><article><p>{PARAGRAPH}</p></article>"
    "<footer>하단</footer></body></html>"
)


@dataclass
class FakePages:
    pages: dict[str, str] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    final: dict[str, str] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def fetch_page(self, url: str) -> PageResult:
        self.calls.append(url)
        if url in self.errors:
            raise FetchError(self.errors[url])
        return PageResult(self.pages[url], self.final.get(url, url))


@pytest.fixture
def env(tmp_path):
    db, clock = Database(tmp_path / "rss_hub.db"), FakeClock()
    feeds, articles = FeedRepository(db, clock), ArticleRepository(db, clock)
    feed = feeds.add("https://a.example.com/rss", "A")
    pages = FakePages()

    def add(link="https://a.example.com/post/1"):
        new = NewArticle(
            feed, f"g-{link}", "제목", link, "<p>RSS 요약</p>", "", clock.now(), "2026-10-16"
        )
        return articles.add(new)

    return articles, FullTextService(articles=articles, pages=pages), pages, add


def test_the_first_open_fetches_the_page_and_saves_the_main_text(env):
    articles, service, pages, add = env
    pages.pages["https://a.example.com/post/1"] = PAGE
    article = articles.get(add())
    result = service.ensure(article)
    assert (
        result.state == "ok" and "원문에만 있는 본문" in result.html and "메뉴" not in result.html
    )
    saved = articles.get(article.id)
    assert saved.full_status == "ok" and saved.full_html == result.html and saved.full_error is None


def test_the_second_open_uses_the_saved_text_and_does_not_fetch_again(env):
    articles, service, pages, add = env
    pages.pages["https://a.example.com/post/1"] = PAGE
    article_id = add()
    service.ensure(articles.get(article_id))
    again = service.ensure(articles.get(article_id))
    assert again.state == "ok" and len(pages.calls) == 1


def test_a_failure_is_recorded_and_not_retried_on_every_open(env):
    articles, service, pages, add = env
    pages.errors["https://a.example.com/post/1"] = "ReadTimeout"
    article_id = add()
    first = service.ensure(articles.get(article_id))
    second = service.ensure(articles.get(article_id))
    assert first.state == second.state == "failed" and first.html is None and first.reason
    assert len(pages.calls) == 1
    saved = articles.get(article_id)
    assert (saved.full_status, saved.full_error) == ("failed", "ReadTimeout")


def test_force_fetches_again_and_a_later_success_replaces_the_failure(env):
    articles, service, pages, add = env
    pages.errors["https://a.example.com/post/1"] = "ReadTimeout"
    article_id = add()
    service.ensure(articles.get(article_id))
    del pages.errors["https://a.example.com/post/1"]
    pages.pages["https://a.example.com/post/1"] = PAGE
    again = service.ensure(articles.get(article_id), force=True)
    assert again.state == "ok" and len(pages.calls) == 2
    saved = articles.get(article_id)
    assert (saved.full_status, saved.full_error) == ("ok", None)


def test_a_page_without_a_main_text_is_a_recorded_failure_with_a_clear_reason(env):
    articles, service, pages, add = env
    pages.pages["https://a.example.com/post/1"] = "<html><body><nav>메뉴만</nav></body></html>"
    result = service.ensure(articles.get(add()))
    assert result.state == "failed" and "본문을 찾지 못했습니다" in result.reason


@pytest.mark.parametrize(
    "link",
    [
        "",
        "javascript:alert(1)",
        "ftp://a.example.com/x",
        "http://127.0.0.1/x",
        "http://192.168.0.5/x",
        "http://localhost/x",
        "file:///etc/passwd",
    ],
)
def test_an_unusable_or_private_link_is_skipped_without_any_request_or_record(env, link):
    articles, service, pages, add = env
    article_id = add(link)
    result = service.ensure(articles.get(article_id))
    assert result.state == "skipped" and result.html is None and pages.calls == []
    assert articles.get(article_id).full_status is None  # 기록하지 않는다


def test_relative_links_are_resolved_against_the_final_address_after_redirects(env):
    articles, service, pages, add = env
    pages.pages["https://a.example.com/post/1"] = PAGE.replace(
        "</article>", "<a href='/more'>더</a></article>"
    )
    pages.final["https://a.example.com/post/1"] = "https://cdn.example.com/moved/post"
    assert 'href="https://cdn.example.com/more"' in service.ensure(articles.get(add())).html


def test_the_page_text_is_sanitized_before_it_is_stored(env):
    articles, service, pages, add = env
    evil = PAGE.replace("<p>", "<p onclick='x()'><script>alert(1)</script>", 1)
    pages.pages["https://a.example.com/post/1"] = evil
    article_id = add()
    service.ensure(articles.get(article_id))
    stored = articles.get(article_id).full_html
    assert "onclick" not in stored and "<script" not in stored and "alert(1)" not in stored


def test_the_stored_text_is_capped(env):
    from rss_hub.storage.articles import MAX_FULL_TEXT_CHARS

    articles, service, pages, add = env
    pages.pages["https://a.example.com/post/1"] = (
        f"<article><p>{'가' * (MAX_FULL_TEXT_CHARS + 5000)}</p></article>"
    )
    article_id = add()
    service.ensure(articles.get(article_id))
    assert len(articles.get(article_id).full_html) <= MAX_FULL_TEXT_CHARS


def test_saving_for_a_missing_article_changes_nothing(env):
    articles, _, _, _ = env
    assert articles.save_full_text(999, "<p>x</p>") is False
    assert articles.save_full_text_failure(999, "x") is False


def test_a_long_failure_reason_is_shortened(env):
    articles, _, _, add = env
    article_id = add()
    articles.save_full_text_failure(article_id, "x" * 500)
    assert len(articles.get(article_id).full_error) == 100
