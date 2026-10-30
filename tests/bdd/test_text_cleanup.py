"""35_text_cleanup.feature: 제목과 본문의 문자 참조와 전각 글자 다듬기."""

import json
import re
from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, then, when

from rss_hub.domain.page_feed import extract_page_items
from rss_hub.domain.sanitize import sanitize_html
from rss_hub.domain.text import strip_html
from rss_hub.domain.validation import validate_summary
from rss_hub.storage.migrations import apply_migrations
from tests.bdd.binding import bind
from tests.fakes.collect_env import CollectEnv
from tests.fakes.entries import entry
from tests.fakes.page_html import BASE, listing

bind(globals(), "35_text_cleanup.feature", [f"TXT-{n:02d}" for n in range(1, 7)])


@pytest.fixture
def env(tmp_path):
    return CollectEnv(tmp_path)


@pytest.fixture
def ctx():
    return SimpleNamespace(feed=None, html="", text="", draft=None, listing=None, db=None)


@given(parsers.parse('피드가 제목 "{title}"인 글을 보낸다'))
def _feed_with_title(env, ctx, title):
    ctx.feed, url = env.add_feed()
    env.fetcher.serve(url, [{**entry(), "title": title}])


@when("수집한다")
def _collect(env, ctx):
    env.collect(ctx.feed)


@then(parsers.parse('저장된 글의 제목은 "{title}"이다'))
def _stored_title(env, title):
    assert [a.title for a in env.collected()] == [title]


@given(parsers.parse('본문에 "&amp;middot;"가 보통 글과 코드 안에 있는 글이 있다'))
def _double_encoded_body(ctx):
    ctx.html = "<p>A&amp;middot;B</p><pre><code>x &amp;middot; y</code></pre>"


@when("본문을 정제한다")
def _sanitize(ctx):
    ctx.text = sanitize_html(ctx.html)


@then(parsers.parse('보통 글에서는 가운뎃점이 되고 코드 안에서는 "&middot;" 글자 그대로 보인다'))
def _body_result(ctx):
    assert "<p>A·B</p>" in ctx.text
    assert "<code>x &amp;middot; y</code>" in ctx.text  # 화면에는 &middot;가 글자로 보인다


@given(parsers.parse('본문이 "{html}"인 글이 있다'))
def _body(ctx, html):
    ctx.html = html


@when("본문에서 텍스트를 뽑는다")
def _plain(ctx):
    ctx.text = strip_html(ctx.html)


@then(parsers.parse('텍스트는 "{text}"이다'))
def _plain_is(ctx, text):
    assert ctx.text == text


@given(parsers.parse('모델이 제목 "{title}"와 요약 "{summary}"을 돌려준다'))
@given(parsers.parse('모델이 제목 "{title}"와 요약 "{summary}"를 돌려준다'))
def _model_answer(ctx, title, summary):
    ctx.text = json.dumps({"title_ko": title, "summary_ko": summary, "topics": []})


@when("응답을 검증한다")
def _validate(ctx):
    ctx.draft = validate_summary(ctx.text, "stop").draft


@then(parsers.parse('제목은 "{title}"이고 요약은 "{summary}"이다'))
def _draft_is(ctx, title, summary):
    assert (ctx.draft.title_ko, ctx.draft.summary_ko) == (title, summary)


@given(parsers.parse('제목이 "{title}"인 글 목록 페이지가 있다'))
def _page(ctx, title):
    items = [
        (f"post-{n}", f"소식&amp;middot;{n}번 목록에 나오는 글의 제목입니다", None)
        for n in range(1, 6)
    ]
    ctx.html = listing(items, title=title)


@when("페이지에서 글 목록을 읽는다")
def _read_page(ctx):
    ctx.listing = extract_page_items(ctx.html, f"{BASE}/news")


@then(parsers.parse('구독 이름은 "{name}"이고 글 제목에도 문자 참조가 남지 않는다'))
def _page_result(ctx, name):
    assert ctx.listing.title == name
    assert ctx.listing.items and all("&" not in item.title for item in ctx.listing.items)
    assert all("·" in item.title for item in ctx.listing.items)


@given("문자 참조가 그대로 저장된 글 제목과 사이트 이름이 있는 데이터베이스가 있다")
def _old_db(env, ctx):
    feed, url = env.add_feed()
    env.fetcher.serve(url, [entry()])
    env.collect(feed)
    ctx.feed = feed
    ctx.article = env.collected()[0].id
    ctx.db = env.db
    with env.db.connect() as conn:
        conn.execute("UPDATE feeds SET name = '뉴스&amp;middot;블로그' WHERE id = ?", (feed,))
        conn.execute(
            "UPDATE articles SET title = ?, title_ko = ? WHERE id = ?",
            ("제목&middot;하나", "제목&amp;middot;둘", ctx.article),
        )
        conn.execute("DROP TABLE error_log")  # 19번 이후의 마이그레이션이 다시 만든다
        conn.execute("DROP TABLE activity_log")
        conn.execute("PRAGMA user_version = 18")


@when("데이터베이스를 최신으로 올린다")
def _migrate(ctx):
    with ctx.db.connect() as conn:
        apply_migrations(conn)


@then("글 제목, 한국어 제목, 사이트 이름이 모두 다듬어져 있다")
def _migrated(ctx):
    with ctx.db.connect() as conn:
        article = conn.execute(
            "SELECT title, title_ko FROM articles WHERE id = ?", (ctx.article,)
        ).fetchone()
        name = conn.execute("SELECT name FROM feeds WHERE id = ?", (ctx.feed,)).fetchone()[0]
    assert (article["title"], article["title_ko"], name) == ("제목·하나", "제목·둘", "뉴스·블로그")
    assert not re.search(r"&\w+;", f"{article['title']}{article['title_ko']}{name}")
