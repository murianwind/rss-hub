"""글 주소 가운데, 가져오는 쪽에서 본문이 있는 주소로 바꿔야 하는 것.

네이버 블로그의 글 주소(blog.naver.com/아이디/글번호)는 접속하는 쪽의 User-Agent에 따라
스크립트나 프레임으로 다른 주소로 보내는 껍데기를 돌려준다. 본문은 모바일 글 주소
(m.blog.naver.com/PostView.naver)에 그대로 있으므로 처음부터 그 주소를 가져온다.
새 사이트가 필요하면 아래 규칙 목록에 한 줄을 더한다.
"""

import re
from collections.abc import Callable
from urllib.parse import parse_qs, urlsplit

_NAVER_BLOG_POST = re.compile(
    r"^https?://(?:m\.)?blog\.naver\.com/(?P<blog>[A-Za-z0-9_-]+)/(?P<post>\d+)(?:[/?#]|$)"
)
_NAVER_HOSTS = ("blog.naver.com", "m.blog.naver.com")
NAVER_MOBILE_POST = "https://m.blog.naver.com/PostView.naver?blogId={blog}&logNo={post}"


def _naver_blog(link: str) -> str | None:
    found = _NAVER_BLOG_POST.match(link)
    if found:
        return NAVER_MOBILE_POST.format(blog=found["blog"], post=found["post"])
    parts = urlsplit(link)
    if parts.hostname in _NAVER_HOSTS and parts.path.rstrip("/") == "/PostView.naver":
        query = parse_qs(parts.query)
        blog, post = query.get("blogId", [""])[0], query.get("logNo", [""])[0]
        if re.fullmatch(r"[A-Za-z0-9_-]+", blog) and post.isdigit():
            return NAVER_MOBILE_POST.format(blog=blog, post=post)
    return None


_RULES: tuple[Callable[[str], str | None], ...] = (_naver_blog,)


def reading_url(link: str) -> str:
    """전문을 가져올 주소. 알려진 사이트면 본문이 있는 주소로, 아니면 글 주소 그대로."""
    for rule in _RULES:
        found = rule(link)
        if found is not None:
            return found
    return link
