"""웹페이지 구독 시험용 HTML 견본: 글 목록 페이지(메뉴, 푸터, 쪽 번호, 태그 같은 군더더기 포함)."""

# ruff: noqa: E501  (HTML 견본은 한 줄이 읽기 쉽다)

BASE = "https://blog.example.com"


def listing(items, *, section="/news", base=BASE, extra="", title="예제 블로그 - 소식"):
    """items: (슬러그, 제목, 날짜 또는 None) 목록. 날짜는 앵커 글자 앞에 붙는다(comscore 모양)."""
    cards = "".join(
        f'<article class="card"><a href="{section}/{slug}">{(date + " ") if date else ""}{text}</a></article>'
        for slug, text, date in items
    )
    return (
        f"<html><head><title>{title}</title></head><body>"
        f'<nav><a href="{section}">소식</a><a href="/about">소개</a><a href="{section}/menu-link">메뉴</a></nav>'
        f"<main><h1>소식</h1>{cards}{extra}"
        f'<ul class="pager"><li><a href="{section}?page=2">2</a></li><li><a href="{section}/page/3">3</a></li></ul>'
        f'<p>태그: <a href="{section}/tag/ai">AI</a> <a href="{section}/category/news">뉴스</a></p>'
        f'<p><a href="https://other.example.org{section}/elsewhere">다른 사이트 글</a></p></main>'
        f'<footer><a href="{section}/footer-link">푸터</a></footer></body></html>'
    )


def sample_items(count, *, dated=False):
    return [
        (
            f"post-{n}",
            f"새 소식 {n}번: 목록에 나오는 글의 제목입니다",
            "2026-10-16" if dated else None,
        )
        for n in range(1, count + 1)
    ]


def article_html(n):
    paragraphs = "".join(
        f"<p>{n}번 글의 {k}번째 본문 문단입니다. 요약에 쓸 충분히 긴 문장이고 서로 겹치지 않습니다.</p>"
        for k in range(1, 7)
    )
    return f"<html><body><article>{paragraphs}</article></body></html>"


COMSCORE_LIKE = """<html><head><title>Blog - Comscore, Inc.</title></head><body>
<nav><a href="/Insights/Blog">Blog</a><a href="/ger/Insights/Blog">Deutsch</a></nav>
<div><a href="/Insights/Blog/The-Slow-Death-of-Age-and-Gender" title="Blog: The Slow Death of Age and Gender"></a>
<a href="/Insights/Blog/The-Slow-Death-of-Age-and-Gender" title="Read more: The Slow Death of Age and Gender">Read more</a></div>
<div><a href="/Insights/Blog/Summer-Signals" title="Summer Signals: Reading Guide to the Season That Was">Blog Summer Signals: Reading Guide to the Season That Was</a></div>
<a href="/Insights/Blog/Front-Door" title="Blog: The New Front Door to Financial Decision Making">29 jul 2026 The New Front Door to Financial Decision Making:...</a>
<ul><li><a href="/Insights/Blog?page=2">2</a></li></ul><footer><a href="/Insights/Blog/Footer">Footer</a></footer></body></html>"""


def dated_article_html(n, *, head="", body_top=""):
    """발행일 정보를 head(메타, JSON-LD)나 본문 위쪽에 넣은 글 페이지."""
    paragraphs = "".join(
        f"<p>{n}번 글의 {k}번째 본문 문단입니다. 요약에 쓸 충분히 긴 문장이고 서로 겹치지 않습니다.</p>"
        for k in range(1, 7)
    )
    return f"<html><head>{head}</head><body><article>{body_top}{paragraphs}</article></body></html>"


PUBLISHED_PAGES = {
    "메타 태그 article:published_time": dict(
        head='<meta property="article:published_time" content="2026-09-28T09:00:00+09:00">'
    ),
    "time 태그의 datetime": dict(body_top='<p><time datetime="2026-09-28">Sep 28</time></p>'),
    "JSON-LD의 datePublished": dict(
        head='<script type="application/ld+json">{"@type":"Article","datePublished":"2026-09-28T01:00:00+09:00"}</script>'
    ),
    "본문 위쪽의 September 28, 2026": dict(body_top="<p>By Kim</p><p>September 28, 2026</p>"),
    "본문 위쪽의 2026년 9월 28일 게시": dict(body_top="<p>게시일: 2026년 9월 28일</p>"),
}
