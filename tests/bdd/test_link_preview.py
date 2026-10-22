"""32_link_preview.feature: 미리보기 봇이 글 주소를 가져가도 읽음 처리하지 않는다."""

import re
from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, then, when

from rss_hub.web.ui import asset_version
from tests.bdd.binding import bind

bind(globals(), "32_link_preview.feature", [f"LNK-{n:02d}" for n in range(1, 5)])

DISCORD = "Mozilla/5.0 (compatible; Discordbot/2.0; +https://discordapp.com)"
SAFARI = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
)
CHROME = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)
REQUESTERS = {
    "Discord 미리보기 봇": {"user-agent": DISCORD},
    "Slack 미리보기 봇": {
        "user-agent": "Slackbot-LinkExpanding 1.0 (+https://api.slack.com/robots)"
    },
    "Facebook 미리보기 봇": {
        "user-agent": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)"
    },
    "Twitter 미리보기 봇": {"user-agent": "Twitterbot/1.0"},
    "검색 엔진 로봇": {
        "user-agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
    },
    "브라우저의 미리 가져오기(prefetch)": {"user-agent": CHROME, "sec-purpose": "prefetch"},
    "브라우저의 미리 그리기(prerender)": {
        "user-agent": CHROME,
        "sec-purpose": "prefetch;prerender",
    },
}
BROWSERS = {
    "아이폰 Safari": {"user-agent": SAFARI},
    "데스크톱 Chrome": {"user-agent": CHROME, "sec-fetch-dest": "document"},
    "사용자 정보가 없는 브라우저": {},
}


@pytest.fixture
def ctx():
    return SimpleNamespace(article=None, response=None, html="")


@given("읽지 않은 글이 있다")
def _unread(world, ctx):
    ctx.article = world.article(title="알림 글")
    assert world.articles.get(ctx.article).read_at is None


@when(parsers.parse("{who}가 글 주소를 가져간다"))
@when(parsers.parse("{who}이 글 주소를 가져간다"))
def _fetch_as_requester(world, ctx, who):
    ctx.response = world.client.get(f"/a/{ctx.article}", headers=REQUESTERS[who])


@when("Discord 미리보기 봇이 글 주소를 가져간다")
def _fetch_as_discord(world, ctx):
    ctx.response = world.client.get(f"/a/{ctx.article}", headers=REQUESTERS["Discord 미리보기 봇"])


@when(parsers.parse("{browser}로 글을 연다"))
def _open_as_browser(world, ctx, browser):
    ctx.response = world.client.get(f"/a/{ctx.article}", headers=BROWSERS[browser])


@then("글은 읽지 않음으로 남는다")
def _still_unread(world, ctx):
    assert world.articles.get(ctx.article).read_at is None


@then("원문 전문도 가져오지 않는다")
def _no_fulltext(world, ctx):
    assert world.articles.get(ctx.article).full_status is None


@then("글은 읽음이 된다")
def _read(world, ctx):
    assert world.articles.get(ctx.article).read_at is not None


@then("응답은 정상이고 글 제목이 들어 있다")
def _preview_ok(ctx):
    assert ctx.response.status_code == 200 and "알림 글" in ctx.response.text


@when("읽기 화면을 연다")
def _open_reader(world, ctx):
    ctx.html = world.get("/reader").text


@then("스크립트와 스타일의 주소에는 버전과 파일 내용에서 만든 값이 함께 붙는다")
def _versioned_urls(ctx):
    for name in ("app.css", "app.js"):
        found = re.search(rf"/static/{re.escape(name)}\?v=([^\"]+)", ctx.html)
        assert found and re.fullmatch(r"[\d.]+-[0-9a-f]{8}", found.group(1)), name


@then("파일 내용이 다르면 그 값도 다르다")
def _hash_changes(tmp_path):
    (tmp_path / "app.js").write_text("a")
    (tmp_path / "app.css").write_text("b")
    first = asset_version(tmp_path, "1.0")
    (tmp_path / "app.js").write_text("changed")
    assert asset_version(tmp_path, "1.0") != first and first.startswith("1.0-")
