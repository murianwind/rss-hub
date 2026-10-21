"""화면 HTML에서 부분을 찾는 키워드."""

import html as html_module
import re


def card(html, title):
    """제목이 든 목록 카드 하나."""
    cards = html.split('<article class="card')[1:]
    return next(c for c in cards if title in c.split("</article>")[0])


def row(html, name):
    """이름이 든 피드 관리 화면의 피드 줄(문자 참조를 풀어서)."""
    rows = html.split('<li class="feed-row">')[1:]
    return html_module.unescape(next(r for r in rows if name in r.split("</li>")[0]))


def text_of(response):
    """응답에서 태그를 뺀 글자(공백은 하나로)."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", response.text))


def body(html):
    """글 페이지의 본문 영역."""
    return html.split('class="article-body"')[1].split('<div class="doc-foot">')[0]


def rss_section(html):
    return html.split('id="sec-rss"')[1].split("</details>")[0]


def category_section(html):
    return html.split('id="sec-categories"')[1].split('id="sec-topics"')[0]


def feed_ids(section):
    """사이드바 구역에 있는 피드 id를 나온 순서대로."""
    return [int(n) for n in re.findall(r'data-drag-kind="feed" data-drag-id="(\d+)"', section)]


def heading_link(html):
    """제목 줄의 사이트 링크: (주소, rel) 또는 None."""
    found = re.search(
        r'<h1><a class="site-link" href="([^"]+)" target="_blank" rel="([^"]+)"', html
    )
    return None if found is None else (found.group(1), found.group(2))
