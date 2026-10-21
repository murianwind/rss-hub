import json

import pytest

from rss_hub.domain.backup import BackupError
from rss_hub.services.backup import BackupService
from rss_hub.storage.backup import BackupRepository
from tests.fakes.delivery_env import DeliveryEnv, webhook_url
from tests.keywords.store import create_category


@pytest.fixture
def env(tmp_path):
    return DeliveryEnv(tmp_path)


@pytest.fixture
def service(env):
    return BackupService(BackupRepository(env.db, env.clock), env.clock, "test")


def exported(service) -> bytes:
    _, chunks = service.export()
    return "".join(chunks).encode()


def test_the_file_name_carries_the_export_time(service):
    name, chunks = service.export()
    list(chunks)
    assert name == "rss-hub-backup-20261016-050000.json"


def test_the_exported_file_has_no_webhook_urls_keys_or_secret_tables(env, service):
    env.settings.set_openrouter_key("sk-or-v1-SECRETKEYVALUE")
    text = exported(service).decode()
    assert "SECRET" not in text and "discord.com" not in text
    assert '"secrets"' not in text and '"settings_audit"' not in text


def test_roles_are_written_by_webhook_name(env, service):
    document = json.loads(exported(service))
    assert document["roles"] == {"default": "rss", "system": "시스템"}
    assert all(row["key"] != "webhook_default_id" for row in document["tables"]["settings"])


def test_restoring_an_export_brings_back_everything_including_topic_matches_and_deliveries(
    env, service
):
    category = create_category(env.feeds, "뉴스", webhook_id=env.webhooks["dev"])
    feed = env.add_feed("Second", category=category)
    article_id = env.add_ready_article(feed_id=feed, title="Netflix news", topics=("OTT",))
    env.service.run()
    env.articles.mark_read(article_id)
    before = (
        env.statuses(article_id),
        [t.name for t in env.topics.list_all()],
        [(f.name, f.category_id) for f in env.feeds.list_all()],
        env.articles.get(article_id),
    )
    data = exported(service)

    env.feeds.delete(feed)
    env.settings.update({"service_base_url": "https://changed.example.com"})
    env.topics.delete(env.topic_id("OTT"))

    result = service.restore(data)

    after = (
        env.statuses(article_id),
        [t.name for t in env.topics.list_all()],
        [(f.name, f.category_id) for f in env.feeds.list_all()],
        env.articles.get(article_id),
    )
    assert after == before
    assert env.settings.snapshot().base_url == "https://rss.example.com"
    assert result.counts["articles"] == 1 and result.unlinked_webhooks == ()


def test_webhook_references_follow_the_name_to_the_new_webhook_id(env, service):
    env.feeds.set_feed_webhook(env.feed_id, env.webhooks["dev"])
    data = exported(service)
    env.settings.delete_webhook(env.webhooks["dev"])
    new_id = env.settings.add_webhook("dev", webhook_url("dev"))
    service.restore(data)
    assert env.feeds.get(env.feed_id).webhook_id == new_id


def test_a_missing_webhook_is_unlinked_everywhere_and_reported_once(env, service):
    env.feeds.set_feed_webhook(env.feed_id, env.webhooks["dev"])
    env.add_topic("개발", ["cve"], webhook="dev")
    data = exported(service)
    env.settings.delete_webhook(env.webhooks["dev"])
    result = service.restore(data)
    assert env.feeds.get(env.feed_id).webhook_id is None
    assert next(t for t in env.topics.list_all() if t.name == "개발").webhook_id is None
    assert result.unlinked_webhooks == ("dev",)


def test_a_missing_default_role_webhook_leaves_the_role_empty_and_is_reported(env, service):
    data = exported(service)
    env.settings.delete_webhook(env.webhooks["rss"])
    result = service.restore(data)
    assert env.settings.snapshot().webhook_default_id is None
    assert "rss" in result.unlinked_webhooks


def test_secrets_and_webhook_urls_of_this_installation_survive_a_restore(env, service):
    env.settings.set_openrouter_key("sk-or-v1-abcdefghijkl")
    data = exported(service)
    service.restore(data)
    assert env.settings.has_openrouter_key()
    assert env.settings.get_webhook_url(env.webhooks["rss"]) == webhook_url("rss")


def test_the_seeded_flag_is_restored_so_deleted_default_topics_do_not_come_back(env, service):
    env.topics.ensure_defaults()
    env.topics.delete(env.topic_id("OTT"))
    data = exported(service)
    service.restore(data)
    assert env.topics.ensure_defaults() is False


def edited(data, change):
    document = json.loads(data)
    change(document)
    return json.dumps(document).encode()


def with_setting(document, key, value):
    rows = document["tables"]["settings"]
    rows[:] = [row for row in rows if row["key"] != key]
    rows.append({"key": key, "value": value, "updated_at": "x"})


def test_an_invalid_setting_value_refuses_the_whole_restore(env, service):
    env.add_ready_article()
    env.settings.update({"collect_interval_minutes": "10"})
    data = exported(service)
    with pytest.raises(BackupError):
        service.restore(edited(data, lambda d: with_setting(d, "collect_interval_minutes", "7")))
    assert env.settings.snapshot().collect_interval_minutes == 10
    assert len(env.articles.list_by_status("ready")) == 1  # 데이터는 그대로


def test_unknown_settings_in_the_file_are_ignored(env, service):
    data = exported(service)

    service.restore(edited(data, lambda d: with_setting(d, "evil", "1")))
    assert "evil" not in env.settings.raw_values()


def test_a_column_this_version_does_not_have_refuses_the_restore(env, service):
    env.add_ready_article()
    data = exported(service)

    def add_column(document):
        document["tables"]["articles"][0]["no_such_column"] = 1

    with pytest.raises(BackupError):
        service.restore(edited(data, add_column))
    assert len(env.articles.list_by_status("ready")) == 1


def test_an_older_schema_file_restores_with_the_defaults_of_the_missing_columns(env, service):
    article_id = env.add_ready_article()
    data = exported(service)

    def drop_newer_columns(document):
        document["schema_version"] = 10
        for row in document["tables"]["articles"]:
            for column in ("keep_unread", "full_html", "full_status", "full_error"):
                row.pop(column, None)

    service.restore(edited(data, drop_newer_columns))
    assert env.articles.get(article_id).full_status is None


def test_delivery_records_for_a_missing_webhook_are_skipped_not_fatal(env, service):
    article_id = env.add_ready_article(title="Netflix news", topics=("OTT",))
    env.service.run()
    assert "ott:topic:OTT" in env.statuses(article_id)
    data = exported(service)
    env.settings.delete_webhook(env.webhooks["ott"])
    result = service.restore(data)
    assert "ott" in result.unlinked_webhooks
    assert env.statuses(article_id) == {"rss:primary": "sent"}
