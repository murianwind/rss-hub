"""22_backup.feature: 백업 내려받기와 복원."""

import json
from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, then, when

from rss_hub.storage.feeds import STATUS_ACTIVE
from tests.bdd.binding import bind
from tests.keywords.backup import (
    SECRET_KEY,
    SECRET_URL,
    download_backup,
    edited,
    restore_backup,
)
from tests.keywords.page import text_of

bind(globals(), "22_backup.feature", [f"BAK-{n:02d}" for n in range(1, 11)])

MAX_BYTES = 100 * 1024 * 1024


@pytest.fixture
def ctx():
    return SimpleNamespace(articles={}, data=b"", response=None, webhook_id=None)


def feed_names(world):
    return {feed.name for feed in world.feeds.list_all()}


def feed_named(world, name):
    return next(f for f in world.feeds.list_all() if f.name == name)


@given('카테고리 "뉴스"에 든 피드 "뉴스 블로그"와 피드 "자유 블로그"가 있다')
def _feeds(world):
    assert feed_named(world, "뉴스 블로그").category_id == world.news
    assert feed_named(world, "자유 블로그")


@given('웹훅 "기본"과 OpenRouter 키가 설정되어 있다')
def _secrets(world, ctx):
    settings = world.parts.settings
    ctx.webhook_id = settings.add_webhook("기본", SECRET_URL)
    settings.set_openrouter_key(SECRET_KEY)


@given(parsers.parse('"뉴스 블로그"의 글 "{read}"을 읽었고 글 "{marked}"에 북마크했다'))
def _read_state(world, ctx, read, marked):
    ctx.articles[read] = world.article(world.f_news, title=read)
    ctx.articles[marked] = world.article(world.f_news, title=marked)
    world.articles.mark_read(ctx.articles[read])
    world.articles.set_bookmark(ctx.articles[marked], True)


@given(parsers.parse('피드 "{name}"에 글 "{title}"가 있다'))
def _article(world, ctx, name, title):
    ctx.articles[title] = world.article(feed_named(world, name).id, title=title)


@given(parsers.parse('피드 "{name}"의 웹훅을 "기본"으로 지정했다'))
def _assign_webhook(world, ctx, name):
    world.feeds.set_feed_webhook(feed_named(world, name).id, ctx.webhook_id)


@given("백업 파일을 내려받았다")
@when("백업 파일을 내려받는다")
def _download(world, ctx):
    ctx.response, ctx.data = download_backup(world)


@given(parsers.parse('그 뒤에 피드 "{gone}"를 지우고 북마크를 풀고 피드 "{added}"를 추가했다'))
def _change_everything(world, ctx, gone, added):
    world.feeds.delete(feed_named(world, gone).id)
    world.articles.set_bookmark(ctx.articles["북마크 글"], False)
    world.feeds.add("https://new.example.com/rss", added, status=STATUS_ACTIVE)


@given(parsers.parse('그 뒤에 피드 "{name}"를 추가했다'))
def _add_feed(world, name):
    world.feeds.add("https://new.example.com/rss", name, status=STATUS_ACTIVE)


@given(parsers.parse('그 뒤에 피드 "{name}"의 웹훅 지정을 풀었다'))
def _unassign(world, name):
    world.feeds.set_feed_webhook(feed_named(world, name).id, None)


@given(parsers.parse('그 뒤에 웹훅 "기본"을 지우고 웹훅 "{other}"을 추가했다'))
def _replace_webhook(world, ctx, other):
    world.parts.settings.delete_webhook(ctx.webhook_id)
    world.parts.settings.add_webhook(other, "https://discord.com/api/webhooks/888/OTHERTOKEN")


@when("백업 파일로 복원한다")
def _restore(world, ctx):
    ctx.response = restore_backup(world, ctx.data)


@when("확인 표시 없이 백업 파일로 복원한다")
def _restore_unconfirmed(world, ctx):
    ctx.response = restore_backup(world, ctx.data, confirm=False)


def _broken_file(kind, data):
    if kind == "JSON이 아닌 파일":
        return b"this is not json"
    if kind == "이 서비스의 백업이 아닌 JSON":
        return json.dumps({"hello": "world"}).encode()
    if kind == "더 새로운 버전의 백업":
        return edited(data, lambda d: d.update(schema_version=d["schema_version"] + 1))
    return edited(data, lambda d: d.pop("tables"))


BROKEN_FILES = (
    "JSON이 아닌 파일|이 서비스의 백업이 아닌 JSON|더 새로운 버전의 백업|항목이 빠진 백업"
)


@when(parsers.re(rf"(?P<kind>{BROKEN_FILES})로 복원한다"))
def _restore_broken(world, ctx, kind):
    ctx.response = restore_backup(world, _broken_file(kind, ctx.data))


@when("글 하나가 없는 피드를 가리키도록 고친 백업 파일로 복원한다")
def _restore_dangling(world, ctx):
    def dangle(document):
        document["tables"]["articles"][0]["feed_id"] = 99999

    ctx.response = restore_backup(world, edited(ctx.data, dangle))


@when("허용 크기를 넘는 파일로 복원한다")
def _restore_huge(world, ctx):
    ctx.response = world.client.post(
        "/backup/restore",
        content=b"x",
        headers={
            "origin": "null",
            "sec-fetch-site": "same-origin",
            "content-type": "multipart/form-data; boundary=x",
            "content-length": str(MAX_BYTES + 10_000_000),
        },
    )


@when("백업·복원 화면을 연다")
def _backup_page(world, ctx):
    ctx.response = world.get("/backup")


@then("파일에 웹훅 주소와 OpenRouter 키는 없다")
def _no_secrets(ctx):
    text = ctx.data.decode()
    for secret in (SECRET_URL, "SECRETWEBHOOKTOKEN", SECRET_KEY, "SECRETKEYVALUE"):
        assert secret not in text


@then("웹훅은 이름만 들어 있다")
def _names_only(ctx):
    assert [w["name"] for w in json.loads(ctx.data)["webhooks"]] == ["기본"]
    assert set(json.loads(ctx.data)["webhooks"][0]) == {"id", "name"}


@then("파일에 피드 2개, 카테고리 2개, 글 2개가 있다")
def _counts(ctx):
    tables = json.loads(ctx.data)["tables"]
    assert (len(tables["feeds"]), len(tables["categories"]), len(tables["articles"])) == (2, 2, 2)


@then('글 "읽은 글"은 읽음이고 글 "북마크 글"은 북마크로 기록되어 있다')
def _recorded_state(ctx):
    by_title = {a["title"]: a for a in json.loads(ctx.data)["tables"]["articles"]}
    assert by_title["읽은 글"]["read_at"] and not by_title["읽은 글"]["bookmarked_at"]
    assert by_title["북마크 글"]["bookmarked_at"]


@then('피드는 "뉴스 블로그"와 "자유 블로그"이고 "새 피드"는 없다')
def _feeds_restored(world, ctx):
    assert ctx.response.status_code == 200
    assert feed_names(world) == {"뉴스 블로그", "자유 블로그"}


@then('글 "읽은 글"은 읽음이고 글 "북마크 글"은 북마크 상태다')
def _state_restored(world, ctx):
    read = world.articles.get(ctx.articles["읽은 글"])
    marked = world.articles.get(ctx.articles["북마크 글"])
    assert read.read_at is not None and read.bookmarked_at is None
    assert marked.bookmarked_at is not None


@then("복원 결과 화면에 되돌린 피드와 글의 수가 보인다")
def _result_counts(ctx):
    text = text_of(ctx.response)
    assert "복원했습니다" in text and "피드 2개" in text and "글 2개" in text


@then(parsers.parse('피드 "{name}"의 웹훅은 "기본"이다'))
def _webhook_is_default(world, ctx, name):
    assert feed_named(world, name).webhook_id == ctx.webhook_id


@then('웹훅 "기본"의 주소와 OpenRouter 키는 바뀌지 않았다')
def _secrets_unchanged(world, ctx):
    settings = world.parts.settings
    assert settings.get_webhook_url(ctx.webhook_id) == SECRET_URL
    assert settings.has_openrouter_key()


@then(parsers.parse('피드 "{name}"의 웹훅은 지정되어 있지 않다'))
def _webhook_unset(world, name):
    assert feed_named(world, name).webhook_id is None


@then('복원 결과 화면은 다시 지정해야 하는 웹훅 "기본"을 알려 준다')
def _unlinked_notice(ctx):
    text = text_of(ctx.response)
    assert "다시 지정" in text and "기본" in text


@then("복원은 거부되고 이유가 보인다")
def _rejected(ctx):
    assert ctx.response.status_code == 400
    assert "복원하지 않았습니다" in text_of(ctx.response)


@then(parsers.parse('피드 "{name}"는 그대로 있다'))
def _still_there(world, name):
    assert name in feed_names(world)


@then("복원은 413으로 거부된다")
def _too_large(ctx):
    assert ctx.response.status_code == 413


@then("내려받기 링크와 파일 올리기 양식이 있다")
def _backup_screen(ctx):
    html = ctx.response.text
    assert 'href="/backup/export"' in html
    assert 'action="/backup/restore"' in html and 'type="file"' in html
