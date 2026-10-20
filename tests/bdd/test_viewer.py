"""12_viewer.feature: 사이드바, 글 목록, 글 페이지, 보관 글과 정리."""

import html as html_module
import re
from datetime import timedelta
from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, then, when

from rss_hub.services.collect import CollectService
from rss_hub.services.retention import RetentionService
from rss_hub.storage.articles import NewArticle
from rss_hub.storage.feeds import STATUS_BASELINE
from tests.bdd.binding import bind
from tests.fakes.entries import today
from tests.fakes.feed_fetcher import FakeFeedFetcher
from tests.fakes.viewer_world import BASE, World, groups
from tests.fakes.web_parts import start_app

bind(globals(), "12_viewer.feature", [f"VWR-{n:02d}" for n in range(1, 15)])


@pytest.fixture
def world(tmp_path):
    parts, client = start_app(tmp_path)
    with client:
        yield World(parts)


@pytest.fixture
def ctx():
    return SimpleNamespace(
        response=None, ids={}, guids={}, last=None, items=[], fetcher=None, feed=None
    )


def feed_id(world, name):
    return {"뉴스 블로그": world.f_news, "자유 블로그": world.f_free}[name]


TITLE_LINK = (
    r'<a class="title" href="/a/\d+(?:\?[^"]*)?">'
    r'(?:<span class="dot"[^>]*></span>)?(.*?)</a>'
)


def listed_titles(response):
    return [html_module.unescape(t) for t in re.findall(TITLE_LINK, response.text)]


def sidebar_html(response):
    return response.text.split('<nav aria-label="구독 목록">')[1].split("</nav>")[0]


# ---------- 배경 ----------


@given('사이트 "뉴스 블로그"(카테고리 "뉴스")와 "자유 블로그"(카테고리 없음)가 등록되어 있다')
def _sites(world):
    names = {f.name: f.category_id for f in world.feeds.list_all()}
    assert names == {"뉴스 블로그": world.news, "자유 블로그": None}


@given('주제 "OTT"가 있다')
def _topic(world):
    assert [t.name for t in world.topics.list_all()] == ["OTT"]


# ---------- 글 만들기 ----------


TWO_TIMED = (
    r'사이트 "(?P<feed>[^"]+)"에 글 "(?P<a>[^"]+)"\(10시 00분\)과 '
    r'"(?P<b>[^"]+)"\(10시 30분\)이 있다'
)


@given(parsers.re(TWO_TIMED))
def _two_timed(world, ctx, feed, a, b):
    ctx.ids[a] = world.article(feed_id(world, feed), 0, title=a)
    ctx.ids[b] = world.article(feed_id(world, feed), 30, title=b)


@given(parsers.re(r'사이트 "(?P<feed>[^"]+)"에 글 "(?P<title>[^"]+)"이 있다'))
def _one(world, ctx, feed, title):
    ctx.ids[title] = world.article(feed_id(world, feed), 0, title=title)
    ctx.last = ctx.ids[title]


@given(parsers.re(r'사이트 "(?P<feed>[^"]+)"에 글 (?P<count>\d+)개가 있다'))
def _many(world, feed, count):
    for number in range(int(count)):
        world.article(feed_id(world, feed), number, title=f"글 {number:02d}")


TOPIC_ARTICLE = (
    r'사이트 "(?P<feed>[^"]+)"에 주제 "(?P<topic>[^"]+)"로 분류된 글 "(?P<title>[^"]+)"이 있고 '
    r"아직 알림을 보내지 않았다"
)


@given(parsers.re(TOPIC_ARTICLE))
def _topic_article(world, ctx, feed, topic, title):
    ctx.ids[title] = world.article(feed_id(world, feed), 0, title=title)
    topic_id = next(t.id for t in world.topics.list_all() if t.name == topic)
    world.topics.record_matches(ctx.ids[title], {topic_id: ()})


TRANSLATED = (
    r'사이트 "(?P<feed>[^"]+)"에 원래 제목 "(?P<orig>[^"]+)", 번역 제목 "(?P<ko>[^"]+)", '
    r'요약 "(?P<summary>[^"]+)"인 글이 있다'
)


@given(parsers.re(TRANSLATED))
def _translated(world, ctx, feed, orig, ko, summary):
    ctx.last = world.article(feed_id(world, feed), 0, title=orig, ko=ko, summary=summary)
    ctx.orig = orig


@given(parsers.re(r'그 글은 주제 "(?P<topic>[^"]+)"에 키워드 "(?P<keyword>[^"]+)"로 해당했다'))
def _matched(world, ctx, topic, keyword):
    topic_id = next(t.id for t in world.topics.list_all() if t.name == topic)
    world.topics.record_matches(ctx.last, {topic_id: (keyword,)})


@given(parsers.re(r'사이트 "(?P<feed>[^"]+)"에 원문 주소가 "(?P<link>[^"]*)"인 글이 있다'))
def _with_link(world, ctx, feed, link):
    ctx.last = world.article(feed_id(world, feed), 0, link=link)


@given(parsers.re(r'사이트 "(?P<feed>[^"]+)"에 본문이 "(?P<body>.*)"인 글이 있다'))
def _with_body(world, ctx, feed, body):
    ctx.last = world.article(feed_id(world, feed), 0, title="12345", content=body)


@given(
    '사이트 "자유 블로그"에 본문에 https 이미지, http 이미지, 1픽셀 이미지가 하나씩 있는 글이 있다'
)
def _with_images(world, ctx):
    content = (
        '<p>글</p><img src="https://img.example.com/ok.png" alt="정상">'
        '<img src="http://img.example.com/plain-http.png" alt="http">'
        '<img src="https://t.example.com/pixel.gif" width="1" height="1" alt="추적">'
    )
    ctx.last = world.article(world.f_free, 0, content=content)


# ---------- 열기 ----------


@when("읽기 화면을 연다")
def _open_reader(world, ctx):
    ctx.response = world.get("/reader")


@when("2쪽을 연다")
def _open_page_two(world, ctx):
    ctx.response = world.get("/reader?page=2")


@when("그 글을 연다")
def _open_article(world, ctx):
    ctx.response = world.get(f"/a/{ctx.last}")


@when(parsers.re(r'사이드바에서 (?P<kind>사이트|카테고리|주제) "(?P<name>[^"]+)"를 고른다'))
def _choose(world, ctx, kind, name):
    ctx.response = world.get("/reader")
    path = {"사이트": "/reader/feed/", "카테고리": "/reader/category/", "주제": "/reader/topic/"}[
        kind
    ]
    label = re.escape(f"# {name}" if kind == "주제" else name)
    hrefs = re.findall(
        rf'<a class="nav-item" href="({path}\d+)"[^>]*><span class="sb-text">{label}</span>',
        sidebar_html(ctx.response),
    )
    assert hrefs, f"{kind} {name} 링크가 없다"
    ctx.response = world.get(hrefs[0])


@when("없는 카테고리 목록을 연다")
def _open_missing_category(world, ctx):
    ctx.response = world.get("/reader/category/9999")


@when("없는 글을 연다")
def _open_missing_article(world, ctx):
    ctx.response = world.get("/a/999999")


# ---------- 사이드바 ----------


@then('사이드바에는 "RSS", "카테고리", "주제", "환경 설정" 구역이 이 순서로 있다')
def _four_sections(ctx):
    assert list(groups(ctx.response.text)) == ["RSS", "카테고리", "주제", "환경 설정"]


@then('RSS 아래에는 등록된 사이트 전체("뉴스 블로그", "자유 블로그")가 있다')
def _rss_has_all(ctx):
    rss = groups(ctx.response.text)["RSS"]
    assert "뉴스 블로그" in rss and "자유 블로그" in rss


@then('카테고리 "뉴스" 아래에는 사이트 "뉴스 블로그"가 있고 "자유 블로그"는 없다')
def _category_nests(ctx):
    category = groups(ctx.response.text)["카테고리"]
    news = category.split('<details class="tree"')[1:]
    section = next(part for part in news if ">뉴스</span>" in part.split("</summary>")[0])
    assert "뉴스 블로그" in section and "자유 블로그" not in category


@then('주제 아래에는 사이트 없이 주제 "OTT"만 있다')
def _topics_only(ctx):
    topic = groups(ctx.response.text)["주제"]
    assert "OTT" in topic and "/reader/feed/" not in topic and "블로그" not in topic
    assert len(re.findall(r'<a class="nav-item" href="/reader/topic/\d+"', topic)) == 1


@then("사이드바는 한 곳에만 있고 메뉴 버튼으로 서랍처럼 열 수 있다")
def _drawer(ctx):
    text = ctx.response.text
    assert text.count('<nav aria-label="구독 목록">') == 1 and 'class="sidebar"' in text
    assert 'data-action="open-drawer"' in text and 'class="backdrop"' in text


# ---------- 목록 ----------


@then(
    parsers.re(
        r'글 목록은 "(?P<first>[^"]+)", "(?P<second>[^"]+)" 순서이고 "(?P<absent>[^"]+)"은 없다'
    )
)
def _ordered(ctx, first, second, absent):
    assert (
        listed_titles(ctx.response) == [first, second]
        and absent not in ctx.response.text.split('<div class="scroll">')[1]
    )


@then(parsers.re(r'(?:글 )?목록에는 "(?P<title>[^"]+)"만 있다'))
def _only(ctx, title):
    assert listed_titles(ctx.response) == [title]


@then('글 30개가 나오고 "다음" 링크가 있다')
def _thirty(ctx):
    assert len(listed_titles(ctx.response)) == 30 and "다음 →" in ctx.response.text


@then('글 5개가 나오고 "이전" 링크가 있다')
def _five(ctx):
    assert len(listed_titles(ctx.response)) == 5 and "← 이전" in ctx.response.text


@then("404로 답하고 사이드바가 그대로 있다")
def _not_found(ctx):
    assert ctx.response.status_code == 404 and 'class="sidebar"' in ctx.response.text


# ---------- 글 페이지 ----------


@then(parsers.re(r'제목 "(?P<ko>[^"]+)"와 원래 제목, 요약 "(?P<summary>[^"]+)"가 보인다'))
def _titles_and_summary(ctx, ko, summary):
    text = ctx.response.text
    assert f"<h1>{ko}</h1>" in text and ctx.orig in text and summary in text


@then(parsers.re(r'주제 "(?P<topic>[^"]+)"와 키워드 "(?P<keyword>[^"]+)"가 보인다'))
def _topic_and_keyword(ctx, topic, keyword):
    assert topic in ctx.response.text and f'title="{keyword}"' in ctx.response.text


@then("원문 보기 버튼이 있다")
def _has_button(ctx):
    assert "원문 보기" in ctx.response.text


@then("원문 보기 버튼은 있고 새 탭에서 안전하게 열린다")
def _button_safe(world, ctx):
    anchor = re.search(r'<a class="button"[^>]*>원문 보기.*?</a>', ctx.response.text, re.S).group(0)
    assert f'href="/a/{ctx.last}/original"' in anchor and 'target="_blank"' in anchor
    assert 'rel="noopener noreferrer"' in anchor


@then("원문 보기 버튼은 없다")
def _no_button(ctx):
    assert "원문 보기" not in ctx.response.text


def article_body(ctx):
    return ctx.response.text.split('class="article-body"')[1]


@then(parsers.re(r'본문에 "(?P<ok>[^"]+)"은 보이고 "(?P<bad>.+)"는 없다'))
def _body_safe(ctx, ok, bad):
    body = article_body(ctx)
    assert ok in body and bad.lower() not in body.lower()


@then("본문에는 https 이미지만 있다")
def _only_https_image(ctx):
    sources = re.findall(r'<img src="([^"]+)"', article_body(ctx))
    assert sources == ["https://img.example.com/ok.png"]


@then("이미지는 referrer 없이 늦게 불러오도록 표시된다")
def _image_attributes(ctx):
    image = re.search(r"<img [^>]*>", article_body(ctx)).group(0)
    assert 'referrerpolicy="no-referrer"' in image and 'loading="lazy"' in image


@then(parsers.re(r'본문 영역의 언어 표시는 "(?P<lang>[^"]+)"이다'))
def _language(ctx, lang):
    area = re.search(r'<div class="article-body"([^>]*)>', ctx.response.text).group(1)
    assert ('lang="' + lang + '"' in area) if lang != "없음" else ("lang=" not in area)


# ---------- 보관 글 ----------


@given("방금 가져온 피드에 글 30개가 있다")
def _imported_feed(world, ctx):
    ctx.fetcher = FakeFeedFetcher()
    ctx.feed = world.feeds.add(
        "https://new.example.com/rss", "새로 가져온 피드", status=STATUS_BASELINE
    )
    ctx.entries = today(30)
    ctx.fetcher.serve("https://new.example.com/rss", ctx.entries)
    ctx.service = CollectService(
        feeds=world.feeds,
        articles=world.articles,
        fetcher=ctx.fetcher,
        settings=world.parts.settings,
        clock=world.parts.clock,
    )


@when("이 피드를 처음 점검한다")
def _first_check(world, ctx):
    ctx.report = ctx.service.collect_feeds([world.feeds.get(ctx.feed)])
    ctx.response = world.get("/reader")


@then("뷰어에는 가장 최근 글 5개가 보인다")
def _five_newest(ctx):
    newest = sorted(ctx.entries, key=lambda e: e["published"], reverse=True)[:5]
    assert listed_titles(ctx.response) == [e["title"] for e in newest]


@then("보관 글은 요약하거나 발송하지 않는다")
def _not_summarized(world):
    assert set(world.articles.count_by_status()) == {"archived"}
    assert (
        world.articles.list_by_status("collected") == []
        and world.articles.list_by_status("ready") == []
    )


@then("다음 점검에서도 그 글들이 다시 수집되지 않는다")
def _not_collected_again(world, ctx):
    report = ctx.service.collect_feeds([world.feeds.get(ctx.feed)])
    assert report.added == 0 and world.articles.list_by_status("collected") == []


# ---------- 정리 ----------


@given("100일이 지났다")
def _hundred_days(world):
    world.parts.clock.advance(days=100)


@when("보관 기간 정리를 실행한다")
def _retention(world, ctx):
    RetentionService(
        articles=world.articles, settings=world.parts.settings, clock=world.parts.clock
    ).run()
    ctx.response = world.get("/reader")


@then(parsers.re(r'"(?P<title>[^"]+)"은 다시 수집되지 않는다'))
def _not_collected(world, ctx, title):
    guid = f"g{ctx.ids[title]}"
    article = NewArticle(
        world.f_free, guid, title, "https://x/1", "c", "", BASE + timedelta(days=1), "2026-10-17"
    )
    assert world.articles.add(article) is None
