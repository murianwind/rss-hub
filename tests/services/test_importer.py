import pytest

from rss_hub.domain.importing import ImportFileError
from rss_hub.services.importer import ImportChoices, ImportService, PreviewExpired
from rss_hub.services.settings import SettingsService
from rss_hub.storage.database import Database
from rss_hub.storage.feeds import STATUS_BASELINE, FeedRepository
from rss_hub.storage.import_staging import ImportStagingRepository
from tests.fakes.clock import FakeClock


class Env:
    def __init__(self, tmp_path):
        self.db = Database(tmp_path / "rss_hub.db")
        self.clock = FakeClock()
        self.settings = SettingsService(self.db, self.clock)
        self.feeds = FeedRepository(self.db, self.clock)
        self.staging = ImportStagingRepository(self.db, self.clock)
        self.service = ImportService(feeds=self.feeds, staging=self.staging, clock=self.clock)
        self.feeds.add("https://a.example.com/feed", "A")
        self.feeds.add("https://b.example.com/rss", "B")


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def items_to_opml(items):
    """[{name, url, html_url}] -> OPML 바이트"""
    body = "".join(
        f'<outline text="{i.get("name", "")}" xmlUrl="{i["url"]}" '
        f'htmlUrl="{i.get("html_url", "")}"/>'
        for i in items
    )
    return f'<?xml version="1.0"?><opml version="2.0"><body>{body}</body></opml>'.encode()


def feed_file(*urls, **named):
    entries = [{"name": url.split("//")[1].split(".")[0], "url": url} for url in urls]
    entries += [{"name": name, "url": url} for name, url in named.items()]
    return items_to_opml(entries)


def opml_file(body):
    return f'<?xml version="1.0"?><opml version="2.0"><body>{body}</body></opml>'.encode()


FIVE = feed_file(
    "https://a.example.com/feed",  # 이미 구독 중
    "https://n1.example.com/rss",
    "https://n2.example.com/rss",
    "https://n3.example.com/rss",
    "https://n4.example.com/rss",
)


# ---------- 미리보기 ----------


def test_a_preview_separates_new_from_duplicates_and_changes_nothing(env):
    before = env.feeds.list_all()
    stored = env.service.preview("feeds.opml", FIVE)
    assert (stored.preview.new_count, stored.preview.duplicate_count) == (4, 1)
    assert env.feeds.list_all() == before


def test_the_preview_can_be_loaded_again_with_its_token(env):
    stored = env.service.preview("feeds.opml", FIVE)
    assert env.service.load(stored.token) == stored.preview


def test_a_bad_file_is_rejected_and_nothing_is_stored(env):
    with pytest.raises(ImportFileError):
        env.service.preview("feeds.opml", b"{broken")
    assert env.staging.count() == 0 and len(env.feeds.list_all()) == 2


def test_old_previews_are_cleaned_up_when_a_new_one_is_made(env):
    old = env.service.preview("feeds.opml", FIVE)
    env.clock.advance(minutes=61)
    env.service.preview("feeds.opml", FIVE)
    assert env.staging.count() == 1
    with pytest.raises(PreviewExpired):
        env.service.load(old.token)


# ---------- 확정 ----------


def test_confirming_registers_only_the_new_feeds_as_baseline_pending(env):
    stored = env.service.preview("feeds.opml", FIVE)
    result = env.service.confirm(stored.token)
    assert (result.created, result.duplicate, result.error) == (4, 1, 0)
    added = [f for f in env.feeds.list_all() if f.url.startswith("https://n")]
    assert len(added) == 4 and {f.status for f in added} == {STATUS_BASELINE}
    assert len(env.feeds.list_all()) == 6


def test_the_result_counts_errors_too(env):
    data = items_to_opml(
        [
            {"name": "ok", "url": "https://ok.example.com/rss"},
            {"name": "dup", "url": "https://a.example.com/feed"},
            {"name": "bad", "url": "ftp://x.example.com/feed"},
            {"name": "internal", "url": "http://192.168.0.10/rss"},
        ]
    )
    result = env.service.confirm(env.service.preview("feeds.opml", data).token)
    assert (result.created, result.duplicate, result.error) == (1, 1, 2)
    assert all("192.168" not in f.url for f in env.feeds.list_all())


def test_the_name_and_site_address_are_kept(env):
    data = items_to_opml(
        [
            {
                "name": "스프링 개발 블로그",
                "url": "https://s.example.com/rss",
                "html_url": "https://s.example.com",
            }
        ]
    )
    env.service.confirm(env.service.preview("feeds.opml", data).token)
    feed = next(f for f in env.feeds.list_all() if f.url == "https://s.example.com/rss")
    assert (feed.name, feed.html_url) == ("스프링 개발 블로그", "https://s.example.com")


def test_a_token_can_only_be_used_once(env):
    stored = env.service.preview("feeds.opml", FIVE)
    env.service.confirm(stored.token)
    with pytest.raises(PreviewExpired):
        env.service.confirm(stored.token)
    assert len(env.feeds.list_all()) == 6


def test_cancelling_saves_nothing_and_forgets_the_preview(env):
    stored = env.service.preview("feeds.opml", FIVE)
    env.service.cancel(stored.token)
    assert len(env.feeds.list_all()) == 2
    with pytest.raises(PreviewExpired):
        env.service.confirm(stored.token)


def test_cancelling_an_unknown_token_is_harmless(env):
    env.service.cancel("unknown")


@pytest.mark.parametrize(("minutes", "expired"), [(59, False), (60, True), (61, True)])
def test_the_preview_expires_after_sixty_minutes(env, minutes, expired):
    stored = env.service.preview("feeds.opml", FIVE)
    env.clock.advance(minutes=minutes)
    if expired:
        with pytest.raises(PreviewExpired) as info:
            env.service.confirm(stored.token)
        assert info.value.message == "미리보기가 만료됨, 파일을 다시 올려 주세요"
        assert len(env.feeds.list_all()) == 2
    else:
        assert env.service.confirm(stored.token).created == 4


def test_confirming_an_unknown_token_is_reported_as_expired(env):
    with pytest.raises(PreviewExpired):
        env.service.confirm("never-existed")


def test_uploading_the_same_file_again_finds_nothing_new(env):
    env.service.confirm(env.service.preview("feeds.opml", FIVE).token)
    again = env.service.preview("feeds.opml", FIVE)
    assert (again.preview.new_count, again.preview.duplicate_count) == (0, 5)


def test_a_feed_added_between_preview_and_confirm_is_counted_as_a_duplicate_not_an_error(env):
    stored = env.service.preview("feeds.opml", FIVE)
    env.feeds.add("https://n1.example.com/rss", "someone added it meanwhile")
    result = env.service.confirm(stored.token)
    assert (result.created, result.duplicate) == (3, 2)


# ---------- 카테고리 ----------

FOLDERS = opml_file(
    '<outline text="IT"><outline text="a1" xmlUrl="https://it1.example.com/rss"/>'
    '<outline text="a2" xmlUrl="https://it2.example.com/rss"/></outline>'
    '<outline text="뉴스"><outline text="n" xmlUrl="https://news.example.com/rss"/></outline>'
)


def test_folders_become_categories_and_feeds_join_their_own_folder(env):
    stored = env.service.preview("feeds.opml", FOLDERS)
    assert stored.preview.new_categories == ("IT", "뉴스")
    result = env.service.confirm(stored.token, ImportChoices(import_categories=True))
    assert result.categories_created == 2
    by_url = {f.url: f for f in env.feeds.list_all()}
    assert (
        by_url["https://it1.example.com/rss"].category_id
        == by_url["https://it2.example.com/rss"].category_id
    )
    assert (
        by_url["https://it1.example.com/rss"].category_id
        != by_url["https://news.example.com/rss"].category_id
    )
    assert env.feeds.category_names() == {"IT", "뉴스"}


def test_turning_categories_off_registers_feeds_without_categories(env):
    stored = env.service.preview("feeds.opml", FOLDERS)
    result = env.service.confirm(stored.token, ImportChoices(import_categories=False))
    assert result.created == 3 and result.categories_created == 0
    assert env.feeds.category_names() == set()
    assert all(f.category_id is None for f in env.feeds.list_all())


def test_an_existing_category_is_reused_not_created_again(env):
    existing_id, _ = env.feeds.get_or_create_category("IT")
    stored = env.service.preview("feeds.opml", FOLDERS)
    assert stored.preview.new_categories == ("뉴스",)
    result = env.service.confirm(stored.token)
    assert result.categories_created == 1
    it_feed = next(f for f in env.feeds.list_all() if f.url == "https://it1.example.com/rss")
    assert it_feed.category_id == existing_id


# ---------- 프리셋과 웹훅 ----------

GIZMODO_FILE = feed_file(Gizmodo="https://gizmodo.com/rss")


def test_a_suggested_preset_is_applied_by_default(env):
    stored = env.service.preview("feeds.opml", GIZMODO_FILE)
    assert stored.preview.items[0].preset == "gizmodo"
    env.service.confirm(stored.token)
    feed = next(f for f in env.feeds.list_all() if "gizmodo" in f.url)
    assert (feed.poll_priority, feed.max_entries, feed.emoji) == ("every_slot", 120, "🧪")


def test_the_awesome_blogs_preset_only_changes_the_priority(env):
    data = feed_file(Blogs="https://awesome-blogs.petabytes.org/feed.xml")
    env.service.confirm(env.service.preview("feeds.opml", data).token)
    feed = next(f for f in env.feeds.list_all() if "awesome-blogs" in f.url)
    assert (feed.poll_priority, feed.max_entries, feed.emoji) == ("every_slot", 50, "📢")


def test_removing_the_suggestion_registers_an_ordinary_feed(env):
    stored = env.service.preview("feeds.opml", GIZMODO_FILE)
    env.service.confirm(stored.token, ImportChoices(presets={0: False}))
    feed = next(f for f in env.feeds.list_all() if "gizmodo" in f.url)
    assert (feed.poll_priority, feed.max_entries, feed.emoji) == ("normal", None, "📢")
