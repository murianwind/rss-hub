"""글 화면의 전문 보기: 처음 열 때 가져오고, 실패하면 RSS 본문과 이유, 다시 가져오기."""

import pytest

from tests.fakes.discovery_fetcher import FakeDiscoveryFetcher
from tests.fakes.viewer_world import open_world
from tests.keywords.browser import post
from tests.keywords.page import body

LINK = "https://blog.example.com/post/1"
FULL = "원문 전체에만 있는 본문 문장입니다. " * 30
PAGE = (
    f"<html><body><nav>메뉴</nav><article><p>{FULL}</p></article>"
    "<footer>하단</footer></body></html>"
)


@pytest.fixture
def world(tmp_path):
    with open_world(tmp_path, fetcher=FakeDiscoveryFetcher()) as opened:
        yield opened


def test_opening_an_article_shows_the_full_text_from_the_original_page(world):
    world.fetcher.page(LINK, PAGE)
    article = world.article(link=LINK, content="<p>RSS에는 요약만 있다</p>")
    html = world.get(f"/a/{article}").text
    assert "원문 전체에만 있는 본문" in body(html) and "RSS에는 요약만" not in body(html)
    assert "메뉴" not in body(html) and "하단" not in body(html)
    assert "원문 페이지에서 가져온 전문입니다" not in html  # 안내 문구는 없다
    assert (
        "전문 다시 가져오기" in html.split('<div class="doc-scroll">')[0]
    )  # 제목 아래 고정 영역에 있다


def test_the_page_is_fetched_once_and_the_saved_text_is_used_afterwards(world):
    world.fetcher.page(LINK, PAGE)
    article = world.article(link=LINK)
    world.get(f"/a/{article}")
    world.get(f"/a/{article}")
    assert world.fetcher.page_calls == [LINK]
    assert world.articles.get(article).full_status == "ok"


def test_a_failed_fetch_shows_the_rss_text_with_the_reason_and_is_not_retried(world):
    world.fetcher.page_errors[LINK] = "ReadTimeout"
    article = world.article(link=LINK, content="<p>RSS 본문입니다</p>")
    html = world.get(f"/a/{article}").text
    assert "RSS 본문입니다" in body(html)
    assert (
        "원문 전문을 가져오지 못해 RSS 본문을 보여 줍니다" in html and "전문 다시 가져오기" in html
    )
    world.get(f"/a/{article}")
    assert world.fetcher.page_calls == [LINK]


def test_a_page_without_a_main_text_falls_back_with_a_clear_reason(world):
    world.fetcher.page(LINK, "<html><body><nav>메뉴만</nav></body></html>")
    article = world.article(link=LINK, content="<p>RSS 본문입니다</p>")
    html = world.get(f"/a/{article}").text
    assert "RSS 본문입니다" in body(html) and "본문을 찾지 못했습니다" in html


def test_an_article_without_a_usable_link_just_shows_the_rss_text_with_no_notice(world):
    article = world.article(link="", content="<p>링크 없는 글</p>")
    html = world.get(f"/a/{article}").text
    assert (
        "링크 없는 글" in body(html)
        and "가져오지 못해" not in html
        and "전문 다시 가져오기" not in html
    )
    assert world.fetcher.page_calls == []


@pytest.mark.parametrize(
    "link",
    ["http://127.0.0.1/x", "http://192.168.1.5/x", "http://localhost/x", "javascript:alert(1)"],
)
def test_a_private_or_unusable_link_is_never_requested(world, link):
    article = world.article(link=link)
    world.get(f"/a/{article}")
    assert world.fetcher.page_calls == []


def test_the_refetch_button_fetches_again_and_returns_with_a_toast(world):
    world.fetcher.page_errors[LINK] = "ReadTimeout"
    article = world.article(link=LINK)
    world.get(f"/a/{article}")
    del world.fetcher.page_errors[LINK]
    world.fetcher.page(LINK, PAGE)
    response = post(world, f"/a/{article}/fulltext", next=f"/a/{article}")
    assert (
        response.status_code == 303
        and response.headers["location"] == f"/a/{article}?toast=fulltext"
    )
    assert "원문 전체에만 있는 본문" in body(world.get(response.headers["location"]).text)
    assert "원문에서 전문을 다시 가져왔습니다." in world.get(response.headers["location"]).text


def test_a_failed_refetch_says_so(world):
    world.fetcher.page_errors[LINK] = "ReadTimeout"
    article = world.article(link=LINK)
    response = post(world, f"/a/{article}/fulltext", next=f"/a/{article}")
    assert response.headers["location"] == f"/a/{article}?toast=fulltext_failed"


def test_refetching_a_missing_article_gives_404(world):
    assert post(world, "/a/999/fulltext").status_code == 404


@pytest.mark.security
def test_the_refetch_return_address_is_checked(world):
    world.fetcher.page(LINK, PAGE)
    article = world.article(link=LINK)
    response = post(world, f"/a/{article}/fulltext", next="https://evil.example.com/")
    assert response.headers["location"].startswith(f"/a/{article}")


@pytest.mark.security
def test_other_sites_cannot_trigger_a_fetch(world):
    article = world.article(link=LINK)
    cross = {"origin": "https://evil.example.com", "sec-fetch-site": "cross-site"}
    assert world.client.post(f"/a/{article}/fulltext", headers=cross).status_code == 403
    assert (
        world.fetcher.page_calls == []
        and world.client.get(f"/a/{article}/fulltext").status_code == 405
    )


@pytest.mark.security
def test_a_hostile_original_page_cannot_run_anything_in_the_reader(world):
    evil = PAGE.replace(
        "<p>", "<p onclick='x()'><script>window.__pwned=1</script><img src=x onerror='alert(1)'>", 1
    )
    evil = evil.replace(
        "</article>",
        "<a href='javascript:alert(1)'>클릭</a><iframe src='https://evil.example.com'></iframe></article>",
    )
    world.fetcher.page(LINK, evil)
    article = world.article(link=LINK)
    text = body(world.get(f"/a/{article}").text)
    for danger in ("<script", "onclick", "onerror", "javascript:", "<iframe", "__pwned"):
        assert danger not in text
    assert "원문 전체에만 있는 본문" in text


def test_the_page_language_is_detected_from_the_full_text(world):
    english = "This is the full article text of the original page. " * 30
    world.fetcher.page(LINK, f"<html><body><article><p>{english}</p></article></body></html>")
    article = world.article(link=LINK, title="제목", content="<p>한국어 요약</p>")
    assert 'lang="en"' in world.get(f"/a/{article}").text


def test_opening_a_list_never_fetches_pages(world):
    world.article(link=LINK)
    world.get("/reader")
    assert world.fetcher.page_calls == []


def test_a_youtube_embed_in_the_full_text_is_a_video_link_that_opens_in_a_new_window(world):
    embed = "<iframe src='https://www.youtube.com/embed/dQw4w9WgXcQ'></iframe>"
    world.fetcher.page(LINK, PAGE.replace("</article>", f"{embed}</article>"))
    article = world.article(link=LINK)
    text = body(world.get(f"/a/{article}").text)
    link = next(a for a in text.split("<a ") if "영상 보기" in a)
    assert 'href="https://www.youtube.com/watch?v=dQw4w9WgXcQ"' in link
    assert 'target="_blank"' in link and "<iframe" not in text
    rel = link.split('rel="')[1].split('"')[0].split()
    assert "noopener" in rel and "noreferrer" in rel  # 새 창에서 이 페이지에 접근하지 못한다


def test_the_rss_fallback_body_does_not_get_video_links(world):
    world.fetcher.page_errors[LINK] = "ReadTimeout"
    content = "<p>RSS 본문</p><iframe src='https://www.youtube.com/embed/dQw4w9WgXcQ'></iframe>"
    article = world.article(link=LINK, content=content)
    text = body(world.get(f"/a/{article}").text)
    assert "RSS 본문" in text and "영상 보기" not in text and "<iframe" not in text
