import pytest

from rss_hub.domain.page_urls import reading_url

MOBILE = "https://m.blog.naver.com/PostView.naver?blogId=skim209&logNo=224358894904"


@pytest.mark.parametrize(
    "link",
    [
        "https://blog.naver.com/skim209/224358894904",
        "https://blog.naver.com/skim209/224358894904?fromRss=true&trackingCode=rss",
        "http://blog.naver.com/skim209/224358894904/",
        "https://m.blog.naver.com/skim209/224358894904",
        "https://blog.naver.com/PostView.naver?blogId=skim209&logNo=224358894904&redirect=Dlog",
        "https://m.blog.naver.com/PostView.naver?blogId=skim209&logNo=224358894904",
    ],
)
def test_naver_blog_posts_are_read_from_the_mobile_post_address(link):
    assert reading_url(link) == MOBILE


@pytest.mark.parametrize(
    "link",
    [
        "https://example.com/post/1",
        "https://blog.naver.com/skim209",  # 글 번호가 없는 블로그 주소
        "https://blog.naver.com/PostView.naver?blogId=skim209",  # 글 번호가 없다
        "https://blog.naver.com/PostView.naver?blogId=a/b&logNo=1",  # 아이디 모양이 아니다
        "https://evilblog.naver.com.example.org/skim209/1",
        "https://cafe.naver.com/skim209/1",
    ],
)
def test_other_addresses_are_left_alone(link):
    assert reading_url(link) == link
