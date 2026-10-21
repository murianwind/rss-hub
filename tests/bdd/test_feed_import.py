"""07_feed_import.feature 전체: 미리보기, 확정, 중복, 잘못된 파일, 보안, 프리셋, 사설망 차단."""

import socket
from datetime import timedelta
from types import SimpleNamespace
from xml.sax.saxutils import quoteattr

import pytest
from pytest_bdd import given, parsers, then, when

from rss_hub.adapters.http_feed_fetcher import RequestsFeedFetcher
from rss_hub.domain.importing import MAX_UPLOAD_BYTES, PRESETS, ImportFileError
from rss_hub.services.collect import CollectService
from rss_hub.services.importer import PREVIEW_TTL, ImportChoices, PreviewExpired
from rss_hub.storage.feeds import STATUS_ACTIVE, STATUS_BASELINE
from tests.bdd.binding import bind
from tests.fakes.entries import entry, today
from tests.fakes.http_server import FakeServer
from tests.fakes.import_env import ImportEnv

IMPORT_SCENARIOS = [1, *range(4, 22)]  # IMP-02, 03은 JSON 전용이라 없앴다
bind(globals(), "07_feed_import.feature", [f"IMP-{n:02d}" for n in IMPORT_SCENARIOS])


@pytest.fixture
def env(tmp_path):
    return ImportEnv(tmp_path)


@pytest.fixture
def ctx():
    state = SimpleNamespace(
        filename="feeds.opml",
        data=b"",
        stored=None,
        error=None,
        result=None,
        token=None,
        servers=[],
        attack_server=None,
        extra={},
    )
    yield state
    for server in state.servers:
        server.stop()


def opml_file(body):
    return f'<?xml version="1.0"?><opml version="2.0"><body>{body}</body></opml>'.encode()


def outline(url, text="", title=""):
    return f'<outline text="{text}" title="{title}" xmlUrl="{url}"/>'


def opml_items(items):
    """문자열(주소) 또는 {name, url, html_url} 목록을 OPML 바이트로."""
    body = ""
    for item in items:
        if isinstance(item, str):
            item = {"name": "", "url": item}
        body += (
            f"<outline text={quoteattr(item.get('name', ''))} xmlUrl={quoteattr(item['url'])} "
            f"htmlUrl={quoteattr(item.get('html_url', ''))}/>"
        )
    return opml_file(body)


def upload(env, ctx):
    try:
        ctx.stored = env.importer.preview(ctx.filename, ctx.data)
        ctx.error = None
    except ImportFileError as error:
        ctx.stored, ctx.error = None, error.message


def confirm(env, ctx, choices=None):
    try:
        ctx.result = env.importer.confirm(ctx.stored.token, choices)
        ctx.error = None
    except PreviewExpired as error:
        ctx.result, ctx.error = None, error.message


def imported_feeds(env):
    return [
        f
        for f in env.feeds.list_all()
        if f.url not in ("https://a.example.com/feed", "https://b.example.com/rss")
    ]


# ---------- 배경 ----------


@given(
    '구독 목록에 주소 "https://a.example.com/feed"와 "https://b.example.com/rss" 피드가 이미 있다'
)
def _existing(env):
    assert env.feed_count() == 2


# ---------- 파일 만들기 ----------


@given('OPML 파일에 피드 5개가 있고 그중 1개는 이미 구독 중인 "https://a.example.com/feed"이다')
def _opml_five(ctx):
    urls = ["https://a.example.com/feed"] + [f"https://n{i}.example.com/rss" for i in range(1, 5)]
    ctx.filename, ctx.data = "subscriptions.opml", opml_file("".join(outline(u) for u in urls))


@given(
    parsers.re(
        r'OPML의 피드 항목에 text가 "(?P<text>.*)", title이 "(?P<title>.*)"로 있고 주소는 "(?P<url>.*)"이다'
    )
)
def _opml_names(ctx, text, title, url):
    ctx.filename, ctx.data = "feeds.opml", opml_file(outline(url, text, title))


@given('OPML에 "IT" 폴더 아래 피드 2개와 "뉴스" 폴더 아래 피드 1개가 있다')
def _opml_two_folders(ctx):
    body = (
        f'<outline text="IT">{outline("https://it1.example.com/rss", "a1")}{outline("https://it2.example.com/rss", "a2")}</outline>'
        f'<outline text="뉴스">{outline("https://news.example.com/rss", "n")}</outline>'
    )
    ctx.filename, ctx.data = "feeds.opml", opml_file(body)


@given('OPML에 "IT" 폴더 아래 피드 2개가 있다')
def _opml_one_folder(ctx):
    body = f'<outline text="IT">{outline("https://it1.example.com/rss", "a1")}{outline("https://it2.example.com/rss", "a2")}</outline>'
    ctx.filename, ctx.data = "feeds.opml", opml_file(body)


@given(parsers.parse('파일에 "{first}"와 "{second}" 두 항목이 있다'))
def _two_items(ctx, first, second):
    ctx.filename, ctx.data = "feeds.opml", opml_items([first, second])


@given(parsers.re(r'파일에 정상 피드 2개와 주소가 "(?P<url>.*)"인 항목 1개가 있다'))
def _two_good_one_bad(ctx, url):
    items = [
        {"name": "ok1", "url": "https://ok1.example.com/rss"},
        {"name": "ok2", "url": "https://ok2.example.com/rss"},
    ]
    items.append({"name": "bad", "url": url})
    ctx.filename, ctx.data = "feeds.opml", opml_items(items)


ONE_FEED = opml_items(["https://a.example.com/rss"])
PROBLEM_FILES = {
    "XML이 아닌 .opml": ("feeds.opml", b"just text, not xml"),
    "지원하지 않는 확장자(.txt, .json)": ("feeds.json", ONE_FEED),
    "비어 있는": ("feeds.opml", b""),
    "5MB를 넘는": ("feeds.opml", ONE_FEED + b" " * MAX_UPLOAD_BYTES),
    "피드가 2000개를 넘는": (
        "feeds.opml",
        opml_items([f"https://f{i}.example.com/rss" for i in range(2001)]),
    ),
}


@given(
    parsers.re(
        r"(?P<problem>XML이 아닌 \.opml|지원하지 않는 확장자\(\.txt, \.json\)|비어 있는|5MB를 넘는|피드가 2000개를 넘는) 파일이 있다"
    )
)
def _problem_file(ctx, problem):
    ctx.filename, ctx.data = PROBLEM_FILES[problem]


@given(parsers.parse('UTF-8 BOM이 붙은 OPML 파일에 이름이 "{name}"인 피드가 있다'))
def _bom_opml(ctx, name):
    ctx.filename = "feeds.opml"
    ctx.data = (
        opml_items([{"name": name, "url": "https://s.example.com/rss"}])
        .decode()
        .encode("utf-8-sig")
    )


@given(parsers.re(r"(?P<attack>.+)이 들어 있는 OPML 파일이 있다"))
def _attack_file(ctx, attack):
    target = "file:///etc/passwd"
    if "http://" in attack:
        ctx.attack_server = FakeServer(lambda *_: (200, {}, b"EXTERNAL-RESPONSE"))
        ctx.attack_server.start()
        ctx.servers.append(ctx.attack_server)
        target = ctx.attack_server.url("/x")
    if "billion" in attack:
        head = (
            '<!DOCTYPE opml [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">'
            '<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;"><!ENTITY d "&c;&c;&c;&c;&c;&c;&c;&c;&c;&c;">]>'
        )
        text = "&d;"
    else:
        head = f'<!DOCTYPE opml [<!ENTITY xxe SYSTEM "{target}">]>'
        text = "&xxe;"
    ctx.filename = "feeds.opml"
    ctx.data = f'<?xml version="1.0"?>{head}<opml><body><outline text="{text}" xmlUrl="https://a.example.com/x"/></body></opml>'.encode()


@given(parsers.re(r'피드의 (?P<where>이름|피드 주소|사이트 주소)에 "(?P<marker>.*)"가 들어 있다'))
def _preset_marker(ctx, where, marker):
    item = {"name": "일반 피드", "url": "https://plain.example.com/rss", "html_url": ""}
    if where == "이름":
        item["name"] = marker
    elif where == "피드 주소":
        item["url"] = (
            f"https://{marker}/feed" if "." in marker else f"https://{marker}.example.org/feed"
        )
    else:
        item["html_url"] = f"https://{marker}.example.com"
    ctx.filename, ctx.data = "feeds.opml", opml_items([item])


@given("미리보기에서 Gizmodo 피드에 프리셋이 제안되어 있다")
def _gizmodo_suggested(env, ctx):
    ctx.filename, ctx.data = (
        "feeds.opml",
        opml_items([{"name": "Gizmodo", "url": "https://gizmodo.com/rss"}]),
    )
    upload(env, ctx)
    assert ctx.stored.preview.items[0].preset == "gizmodo"


# ---------- 올리기 ----------


@when(parsers.re(r"(?:OPML)? ?파일을 올린다"))
@when("같은 파일을 다시 올린다")
def _upload(env, ctx):
    upload(env, ctx)


@when("OPML 파일을 올리고 카테고리 가져오기를 끄고 확정한다")
def _upload_and_confirm_without_categories(env, ctx):
    upload(env, ctx)
    confirm(env, ctx, ImportChoices(import_categories=False))


# ---------- 미리보기 확인 ----------


@then(parsers.parse("미리보기에 신규 {new:d}개와 중복 {dup:d}개가 표시된다"))
def _new_and_dup(ctx, new, dup):
    assert (ctx.stored.preview.new_count, ctx.stored.preview.duplicate_count) == (new, dup)


@then(parsers.parse("미리보기에 신규 {new:d}개와 오류 {err:d}개가 표시된다"))
def _new_and_error(ctx, new, err):
    assert (ctx.stored.preview.new_count, ctx.stored.preview.error_count) == (new, err)


@then(parsers.parse("미리보기에 신규 {new:d}개가 표시된다"))
def _new_only(ctx, new):
    assert ctx.stored.preview.new_count == new


@then("이 시점에는 구독 목록이 바뀌지 않는다")
@then("구독 목록은 바뀌지 않는다")
def _unchanged(env):
    assert env.feed_count() == 2


@then("이름, 주소, 사이트 주소가 그대로 표시된다")
def _shown_as_is(ctx):
    shown = [(i.name, i.url, i.html_url) for i in ctx.stored.preview.items]
    assert shown == [(f["name"], f["url"], f["html_url"]) for f in ctx.extra["legacy"]]


@then(parsers.parse('첫 번째 피드의 이름은 "{name}"이다'))
@then(parsers.parse('미리보기의 피드 이름은 "{name}"이다'))
@then(parsers.parse('미리보기의 이름은 "{name}"이다'))
def _first_name(ctx, name):
    assert ctx.stored.preview.items[0].name == name


@then(parsers.parse('오류 항목에 이유 "{reason}"이 표시된다'))
def _error_reason(ctx, reason):
    errors = [i for i in ctx.stored.preview.items if i.status == "error"]
    assert [e.reason for e in errors] == [reason]


@then(parsers.parse('오류 메시지 "{message}"가 표시된다'))
def _error_message(ctx, message):
    assert ctx.error == message


@then(parsers.parse('미리보기에 새 카테고리 "{first}"와 "{second}"가 제안된다'))
def _categories_suggested(ctx, first, second):
    assert ctx.stored.preview.new_categories == (first, second)


# ---------- 카테고리 ----------


@when("카테고리 가져오기를 켜고 확정한다")
def _confirm_with_categories(env, ctx):
    confirm(env, ctx, ImportChoices(import_categories=True))


@then(parsers.parse('카테고리 "{first}"와 "{second}"가 만들어진다'))
def _categories_created(env, first, second):
    assert env.feeds.category_names() == {first, second}


@then("각 피드는 자기 폴더의 카테고리에 속한다")
def _feeds_in_folders(env):
    names = {}
    with env.db.connect() as conn:
        for row in conn.execute("SELECT id, name FROM categories"):
            names[row["id"]] = row["name"]
    by_url = {f.url: names.get(f.category_id) for f in imported_feeds(env)}
    assert by_url == {
        "https://it1.example.com/rss": "IT",
        "https://it2.example.com/rss": "IT",
        "https://news.example.com/rss": "뉴스",
    }


@then("피드 2개가 등록된다")
def _two_registered(env):
    assert len(imported_feeds(env)) == 2


@then("카테고리는 만들어지지 않는다")
def _no_categories(env):
    assert env.feeds.category_names() == set()


# ---------- 위험한 파일 ----------


@then("파일은 거부된다")
def _rejected(ctx):
    assert ctx.stored is None and ctx.error


@then("서버 파일 내용이나 외부 요청 결과가 화면과 로그 어디에도 나타나지 않는다")
def _nothing_leaked(ctx, caplog):
    shown = f"{ctx.error} {caplog.text}"
    assert "root:" not in shown and "passwd" not in shown and "EXTERNAL-RESPONSE" not in shown
    if ctx.attack_server is not None:
        assert ctx.attack_server.requests == []  # 외부 주소로 요청을 보내지 않았다


@then("서버는 계속 정상 응답한다")
def _server_still_works(env):
    stored = env.importer.preview("ok.opml", opml_items(["https://still-ok.example.com/rss"]))
    assert stored.preview.new_count == 1


# ---------- 확정과 취소 ----------


@given("미리보기에 신규 4개, 중복 1개, 오류 1개가 있다")
def _preview_with_all(env, ctx):
    items = [
        {"name": "dup", "url": "https://a.example.com/feed"},
        {"name": "bad", "url": "ftp://x.example.com/f"},
    ]
    items += [{"name": f"n{i}", "url": f"https://n{i}.example.com/rss"} for i in range(1, 5)]
    ctx.filename, ctx.data = "feeds.opml", opml_items(items)
    upload(env, ctx)


@given("미리보기에 신규 4개가 있다")
def _preview_with_four(env, ctx):
    ctx.filename, ctx.data = (
        "feeds.opml",
        opml_items([f"https://n{i}.example.com/rss" for i in range(1, 5)]),
    )
    upload(env, ctx)


@when("확정한다")
def _confirm(env, ctx):
    confirm(env, ctx)


@when("취소한다")
def _cancel(env, ctx):
    env.importer.cancel(ctx.stored.token)


@then('피드 4개가 상태 "baseline_pending"으로 등록된다')
def _four_baseline(env):
    added = imported_feeds(env)
    assert len(added) == 4 and {f.status for f in added} == {STATUS_BASELINE}


@then("결과에 신규 4개, 중복 1개, 오류 1개가 표시된다")
def _result_counts(ctx):
    assert (ctx.result.created, ctx.result.duplicate, ctx.result.error) == (4, 1, 1)


@given("미리보기를 만든 지 61분이 지났다")
def _sixty_one_minutes(env, ctx):
    ctx.filename, ctx.data = (
        "feeds.opml",
        opml_items([f"https://n{i}.example.com/rss" for i in range(1, 5)]),
    )
    upload(env, ctx)
    env.clock.advance(minutes=61)


@given("미리보기 보관 시간은 60분이다")
def _ttl(env):
    assert timedelta(minutes=60) == PREVIEW_TTL


@given("같은 파일을 이미 확정까지 가져왔다")
def _already_imported(env, ctx):
    ctx.filename, ctx.data = (
        "feeds.opml",
        opml_items([f"https://same{i}.example.com/rss" for i in range(1, 4)]),
    )
    upload(env, ctx)
    confirm(env, ctx)
    assert ctx.result.created == 3


# ---------- 프리셋 ----------


@then(parsers.re(r'이 피드에 프리셋 "(?P<label>.+)"이 제안된다'))
def _preset_label(ctx, label):
    preset = ctx.stored.preview.items[0].preset
    assert preset is not None and PRESETS[preset].label == label


@when("프리셋을 그대로 두고 확정한다")
def _confirm_with_preset(env, ctx):
    confirm(env, ctx)


@when("프리셋을 해제하고 확정한다")
def _confirm_without_preset(env, ctx):
    confirm(env, ctx, ImportChoices(presets={0: False}))


def the_feed(env):
    feeds = imported_feeds(env)
    assert len(feeds) == 1
    return feeds[0]


@then(parsers.parse('이 피드의 폴링 우선순위는 "{priority}"이다'))
def _priority(env, priority):
    assert the_feed(env).poll_priority == priority


@then(parsers.parse("이 피드의 최대 검사 항목 수는 {limit:d}이다"))
def _max_entries(env, limit):
    assert the_feed(env).max_entries == limit


@then("이 피드의 최대 검사 항목 수는 기본값이다")
def _default_max_entries(env):
    assert the_feed(env).max_entries is None


@then(parsers.parse('이 피드의 머리말 이모지는 "{emoji}"이다'))
def _emoji(env, emoji):
    assert the_feed(env).emoji == emoji


# ---------- IMP-18: 방금 가져온 피드의 현재 글은 다시 보내지 않는다 ----------


@given("방금 가져온 피드에 오늘 발행된 글 30개가 있다")
def _imported_feed_with_entries(env, ctx):
    ctx.filename, ctx.data = (
        "feeds.opml",
        opml_items([{"name": "새 피드", "url": "https://imported.example.com/rss"}]),
    )
    upload(env, ctx)
    confirm(env, ctx)
    ctx.extra["items"] = today(30)
    env.fetcher.serve("https://imported.example.com/rss", ctx.extra["items"])


@when("이 피드를 처음 점검한다")
def _first_check(env, ctx):
    ctx.extra["feed_id"] = the_feed(env).id
    assert the_feed(env).status == STATUS_BASELINE
    env.collect(ctx.extra["feed_id"])


@then('30개 글은 "이미 본 글"로 기록된다')
def _thirty_seen(env, ctx):
    assert all(env.articles.is_seen(e["id"]) for e in ctx.extra["items"])


@then("Discord로 나가는 메시지는 없다")
def _nothing_to_send(env):
    # 요약하거나 발송할 글은 만들어지지 않았다(뷰어에서만 보이는 보관 글은 있을 수 있다)
    assert set(env.articles.count_by_status()) <= {"archived"}


@when("그 뒤에 새 글이 올라와서 다음 점검을 한다")
def _second_check(env, ctx):
    ctx.extra["fresh"] = entry(published="2026-10-16T13:00:00+09:00")
    env.fetcher.serve("https://imported.example.com/rss", [ctx.extra["fresh"], *ctx.extra["items"]])
    env.collect(ctx.extra["feed_id"])


@then("새 글만 수집된다")
def _only_fresh(env, ctx):
    assert [a.guid for a in env.articles.list_by_status("collected")] == [ctx.extra["fresh"]["id"]]
    assert the_feed(env).status == STATUS_ACTIVE


# ---------- IMP-20, 21: 사설망으로 연결되는 경우 ----------


def start_server(ctx, host="127.0.0.1", handler=None):
    server = FakeServer(handler or (lambda *_: (200, {}, b"<rss/>")), host)
    server.start()
    ctx.servers.append(server)
    return server


def real_collector(env):
    return CollectService(
        feeds=env.feeds,
        articles=env.articles,
        fetcher=RequestsFeedFetcher(timeout=(1.0, 1.0)),
        settings=env.settings,
        clock=env.clock,
    )


@given("주소가 공개 이름이지만 사설망 주소로 풀리는 피드가 있다")
def _public_name_private_address(env, ctx, monkeypatch):
    server = start_server(ctx)
    ctx.extra["private_server"] = server
    real = socket.getaddrinfo
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, *a, **k: real("127.0.0.1" if host == "feeds.example.com" else host, *a, **k),
    )
    port = server.url("").rsplit(":", 1)[1]
    ctx.extra["feed_id"] = env.feeds.add(
        f"http://feeds.example.com:{port}/feed", "공개 이름", status=STATUS_ACTIVE
    )
    env.service = real_collector(env)


@given("공개 주소의 피드가 사설망 주소로 리다이렉트한다")
def _redirect_to_private(env, ctx):
    private = start_server(ctx, "127.0.0.2")
    public = start_server(ctx, handler=lambda *_: (302, {"Location": private.url("/feed")}, b""))
    ctx.extra["private_server"] = private
    ctx.extra["feed_id"] = env.feeds.add(public.url("/feed"), "리다이렉트", status=STATUS_ACTIVE)
    env.service = CollectService(
        feeds=env.feeds,
        articles=env.articles,
        fetcher=RequestsFeedFetcher(
            timeout=(1.0, 1.0), forbid_address=lambda ip: ip == "127.0.0.2"
        ),
        settings=env.settings,
        clock=env.clock,
    )


@when("이 피드를 점검한다")
def _check_feed(env, ctx):
    ctx.extra["report"] = env.collect(ctx.extra["feed_id"])


@then(parsers.parse('점검은 "{reason}"로 실패로 기록된다'))
def _failed_with(env, ctx, reason):
    assert ctx.extra["report"].failed == ((ctx.extra["feed_id"], reason),)
    assert env.feeds.get(ctx.extra["feed_id"]).last_error == reason


@then("사설망 서버는 아무 요청도 받지 않는다")
def _private_server_untouched(ctx):
    assert ctx.extra["private_server"].requests == []
