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

    def add(link="https://a.example.com/post/1", title="제목"):
        new = NewArticle(
            feed, f"g-{link}", title, link, "<p>RSS 요약</p>", "", clock.now(), "2026-10-16"
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


def test_the_heading_that_repeats_the_article_title_is_left_out_of_the_stored_text(env):
    articles, service, pages, add = env
    title = "Build a Board That Challenges Your Thinking"
    pages.pages["https://a.example.com/post/1"] = (
        f"<article><h1>{title}</h1><p>{PARAGRAPH}</p>"
        "<h2>전혀 다른 소제목</h2><p>뒷 문단</p></article>"
    )
    article_id = add(title=title)
    service.ensure(articles.get(article_id))
    stored = articles.get(article_id).full_html
    assert title not in stored and "전혀 다른 소제목" in stored


# ---------- RSS 본문이 더 완전하면 잘린 원문 페이지로 덮어쓰지 않는다(HBR 유료 벽) ----------

RSS_FULL = "<p>" + "RSS가 이미 전문을 담고 있는 긴 본문 문장입니다. " * 40 + "</p>"
PAGE_TRUNCATED = (
    "<html><body><article><p>"
    + "RSS가 이미 전문을 담고 있는 긴 본문 문장입니다. " * 20
    + "</p></article></body></html>"
)


def add_with_content(articles, feed, content, link="https://a.example.com/post/9"):
    new = NewArticle(feed, f"g-{link}", "제목", link, content, "", FakeClock().now(), "2026-10-16")
    return articles.add(new)


@pytest.fixture
def env2(tmp_path):
    db, clock = Database(tmp_path / "rss_hub.db"), FakeClock()
    feeds, articles = FeedRepository(db, clock), ArticleRepository(db, clock)
    feed = feeds.add("https://a.example.com/rss", "A")
    pages = FakePages()
    return articles, FullTextService(articles=articles, pages=pages), pages, feed


def test_a_page_shorter_than_the_rss_body_does_not_replace_it(env2):
    articles, service, pages, feed = env2
    pages.pages["https://a.example.com/post/9"] = PAGE_TRUNCATED
    article_id = add_with_content(articles, feed, RSS_FULL)
    result = service.ensure(articles.get(article_id))
    assert (
        result.state == "failed"
        and result.html is None
        and "RSS 본문보다 짧습니다" in result.reason
    )
    saved = articles.get(article_id)
    assert saved.full_status == "failed" and saved.full_html is None
    assert (
        len(pages.calls) == 1
        and service.ensure(articles.get(article_id)).state == "failed"
        and len(pages.calls) == 1
    )


def test_a_page_longer_than_the_rss_summary_is_used(env2):
    articles, service, pages, feed = env2
    pages.pages["https://a.example.com/post/9"] = PAGE
    article_id = add_with_content(articles, feed, "<p>짧은 RSS 요약입니다.</p>")
    assert service.ensure(articles.get(article_id)).state == "ok"


def test_a_short_rss_body_never_blocks_the_page_even_if_the_page_is_not_longer(env2):
    articles, service, pages, feed = env2
    pages.pages["https://a.example.com/post/9"] = (
        "<article><p>" + "비슷한 길이의 본문 문장입니다. " * 15 + "</p></article>"
    )
    article_id = add_with_content(
        articles, feed, "<p>" + "비슷한 길이의 본문 문장입니다. " * 15 + "</p>"
    )  # RSS도 300자 미만이 아님
    result = service.ensure(articles.get(article_id))
    assert result.state == "ok"  # 길이가 비슷하면(80% 이상) 원문 페이지를 쓴다


def test_the_force_refetch_applies_the_same_comparison(env2):
    articles, service, pages, feed = env2
    pages.pages["https://a.example.com/post/9"] = PAGE_TRUNCATED
    article_id = add_with_content(articles, feed, RSS_FULL)
    service.ensure(articles.get(article_id))
    assert service.ensure(articles.get(article_id), force=True).state == "failed"


def test_a_short_rss_body_does_not_count_as_a_full_text_even_when_the_page_is_shorter_than_it(env2):
    articles, service, pages, feed = env2
    pages.pages["https://a.example.com/post/9"] = (
        "<article><p>" + "짧은 원문 문장입니다. " * 20 + "</p></article>"
    )
    article_id = add_with_content(
        articles, feed, "<p>" + "요약 문장입니다. " * 30 + "</p>"
    )  # 300자 미만이고 원문보다 길다
    assert service.ensure(articles.get(article_id)).state == "ok"


def test_a_rss_summary_under_the_limit_is_never_compared_with_the_page_length(env2):
    articles, service, pages, feed = env2
    page_text = "가" * 210  # 본문 판정(200자) 이상이지만 RSS(290자)의 80%(232자)보다 짧다
    pages.pages["https://a.example.com/post/9"] = f"<article><p>{page_text}</p></article>"
    article_id = add_with_content(
        articles, feed, f"<p>{'나' * 290}</p>"
    )  # 300자 미만이라 비교하지 않는다
    assert service.ensure(articles.get(article_id)).state == "ok"
    limit = add_with_content(
        articles, feed, f"<p>{'다' * 300}</p>", link="https://a.example.com/post/10"
    )
    pages.pages["https://a.example.com/post/10"] = f"<article><p>{page_text}</p></article>"
    assert (
        service.ensure(articles.get(limit)).state == "failed"
    )  # 300자 이상이면 비교한다(210 < 240)
