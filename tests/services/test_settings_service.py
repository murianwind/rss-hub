import pytest

from rss_hub.domain.settings_rules import SettingError
from rss_hub.services.settings import SettingsService
from rss_hub.storage.database import Database
from tests.fakes.clock import FakeClock
from tests.keywords.store import raw_connection

WEBHOOK = "https://discord.com/api/webhooks/123/abcDEF"
OTHER_WEBHOOK = "https://discord.com/api/webhooks/456/ghiJKL"
KEY = "sk-or-test-1234567890"


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def service(tmp_path, clock):
    return SettingsService(Database(tmp_path / "rss_hub.db"), clock)


# ---------- 기본값과 읽기 ----------


def test_defaults_work_without_any_saved_setting(service):
    s = service.snapshot()
    assert s.base_url == ""
    assert s.timezone.key == "Asia/Seoul"
    assert s.collect_interval_minutes == 5
    assert (s.summarize_interval_seconds, s.deliver_interval_seconds) == (60, 60)
    assert s.slot_batch_size == 15
    assert s.default_max_entries == 50
    assert s.model_chain == (
        "nvidia/nemotron-3-super-120b-a12b:free",
        "nvidia/nemotron-3.5-super-vl:free",
    )
    assert (s.llm_daily_cap, s.llm_warn_percent, s.llm_rpm_cap) == (700, 80, 15)
    assert s.llm_reserve_calls == 20
    assert (s.llm_wait_limit_minutes, s.summarize_batch, s.alert_cooldown_hours) == (60, 5, 6)
    assert (s.webhook_default_id, s.webhook_system_id) == (None, None)


def test_saved_values_override_defaults_and_have_the_right_types(service):
    result = service.update(
        {
            "service_base_url": "https://rss.example.com/",
            "service_timezone": "UTC",
            "collect_interval_minutes": "10",
            "llm_daily_cap": "100",
            "model_chain": "a:free, b:free, a:free",
            "summarize_batch": "9",
        }
    )
    assert result.errors == {}
    s = service.snapshot()
    assert s.base_url == "https://rss.example.com"
    assert s.timezone.key == "UTC"
    assert s.collect_interval_minutes == 10
    assert s.llm_daily_cap == 100
    assert s.model_chain == ("a:free", "b:free")
    assert s.summarize_batch == 9


def test_a_change_is_visible_to_another_service_instance_without_restart(tmp_path, clock):
    first = SettingsService(Database(tmp_path / "rss_hub.db"), clock)
    second = SettingsService(Database(tmp_path / "rss_hub.db"), clock)
    first.update({"llm_daily_cap": "123"})
    assert second.snapshot().llm_daily_cap == 123


def test_raw_values_include_defaults_for_the_form(service):
    values = service.raw_values()
    assert values["collect_interval_minutes"] == "5"
    assert values["service_base_url"] == ""


# ---------- 검증과 원자성 ----------


def test_invalid_values_are_reported_per_field_with_the_domain_messages(service):
    result = service.update({"collect_interval_minutes": "7", "llm_warn_percent": "101"})
    assert result.errors == {
        "collect_interval_minutes": "60의 약수만 가능(1,2,3,4,5,6,10,12,15,20,30,60)",
        "llm_warn_percent": "1~100 사이",
    }
    assert result.changed == ()


def test_nothing_is_saved_when_any_field_is_invalid(service):
    result = service.update({"llm_daily_cap": "100", "collect_interval_minutes": "7"})
    assert "collect_interval_minutes" in result.errors
    assert service.snapshot().llm_daily_cap == 700


def test_unknown_setting_keys_are_rejected(service):
    result = service.update({"no_such_setting": "x"})
    assert result.errors == {"no_such_setting": "알 수 없는 설정"}


def test_unchanged_values_are_not_reported_as_changes(service):
    service.update({"llm_daily_cap": "100"})
    result = service.update({"llm_daily_cap": "100", "summarize_batch": "5"})
    assert result.changed == ()
    assert len(service.audit_log()) == 1


def test_empty_base_url_is_allowed_and_means_not_configured(service):
    service.update({"service_base_url": "https://rss.example.com"})
    assert service.update({"service_base_url": ""}).errors == {}
    assert service.snapshot().base_url == ""


# ---------- 변경 이력 ----------


def test_changes_are_recorded_with_time_and_a_readable_summary(service, clock):
    service.update({"service_base_url": "https://rss.example.com"})
    clock.advance(minutes=3)
    service.update({"service_base_url": "https://new.example.com"})
    entries = service.audit_log()
    assert [e.summary for e in entries] == [
        "서비스 주소 변경: https://rss.example.com → https://new.example.com",
        "서비스 주소 변경: (비어 있음) → https://rss.example.com",
    ]
    assert entries[0].changed_at > entries[1].changed_at


def test_audit_log_is_limited_and_newest_first(service, clock):
    for i in range(30):
        clock.advance(seconds=1)
        service.update({"llm_daily_cap": str(100 + i)})
    entries = service.audit_log(limit=5)
    assert len(entries) == 5
    assert entries[0].summary.endswith("→ 129")


# ---------- 비밀 값: OpenRouter 키 ----------


def test_openrouter_key_roundtrip_is_internal_only(service):
    assert service.has_openrouter_key() is False
    service.set_openrouter_key(f"  {KEY}  ")
    assert service.has_openrouter_key() is True
    assert service.get_openrouter_key() == KEY


def test_blank_openrouter_key_is_rejected_and_keeps_the_old_one(service):
    service.set_openrouter_key(KEY)
    with pytest.raises(SettingError):
        service.set_openrouter_key("   ")
    assert service.get_openrouter_key() == KEY


def test_openrouter_key_can_be_deleted_explicitly(service):
    service.set_openrouter_key(KEY)
    service.delete_openrouter_key()
    assert service.has_openrouter_key() is False
    assert service.get_openrouter_key() is None


def test_secret_values_never_appear_in_the_audit_log_or_settings_snapshot(service):
    service.set_openrouter_key(KEY)
    service.add_webhook("dev", WEBHOOK)
    text = " ".join(e.summary for e in service.audit_log()) + repr(service.snapshot())
    assert KEY not in text
    assert "abcDEF" not in text
    assert "OpenRouter 키 변경됨" in text


def test_secret_values_are_not_stored_in_the_plain_settings_table(service, tmp_path):

    service.set_openrouter_key(KEY)
    service.add_webhook("dev", WEBHOOK)
    with raw_connection(tmp_path / "rss_hub.db") as conn:
        plain = " ".join(str(v) for row in conn.execute("SELECT * FROM settings") for v in row)
        audit = " ".join(
            str(v) for row in conn.execute("SELECT * FROM settings_audit") for v in row
        )
        assert KEY not in plain + audit
        assert "abcDEF" not in plain + audit


# ---------- 웹훅 ----------


def test_adding_a_webhook_lists_only_its_name(service):
    webhook_id = service.add_webhook(" dev ", WEBHOOK)
    infos = service.list_webhooks()
    assert [(w.id, w.name) for w in infos] == [(webhook_id, "dev")]
    assert not hasattr(infos[0], "url")
    assert service.get_webhook_url(webhook_id) == WEBHOOK


def test_webhook_url_is_normalized_and_validated(service):
    wid = service.add_webhook("dev", WEBHOOK + "?wait=true")
    assert service.get_webhook_url(wid) == WEBHOOK
    with pytest.raises(SettingError) as info:
        service.add_webhook("evil", "https://evil.example.com/api/webhooks/1/a")
    assert info.value.message == "Discord 웹훅 주소가 아님"


def test_webhook_names_must_be_unique(service):
    service.add_webhook("dev", WEBHOOK)
    with pytest.raises(SettingError) as info:
        service.add_webhook("dev", OTHER_WEBHOOK)
    assert info.value.message == "같은 이름의 웹훅이 이미 있음"


def test_webhook_roles_are_saved_and_exposed_through_the_snapshot(service):
    a = service.add_webhook("rss", WEBHOOK)
    b = service.add_webhook("system", OTHER_WEBHOOK)
    service.set_webhook_roles(default_id=a, system_id=b)
    s = service.snapshot()
    assert (s.webhook_default_id, s.webhook_system_id) == (a, b)


def test_roles_must_point_to_existing_webhooks(service):
    with pytest.raises(SettingError) as info:
        service.set_webhook_roles(default_id=999, system_id=None)
    assert info.value.message == "없는 웹훅임"


def test_deleting_a_webhook_clears_the_roles_that_used_it(service):
    dev = service.add_webhook("dev", WEBHOOK)
    service.set_webhook_roles(default_id=None, system_id=dev)
    service.delete_webhook(dev)
    assert service.list_webhooks() == []
    assert service.snapshot().webhook_system_id is None
    assert service.get_webhook_url(dev) is None


def test_deleting_an_unknown_webhook_is_harmless(service):
    service.delete_webhook(999)


def test_webhook_events_are_audited_without_the_address(service):
    wid = service.add_webhook("dev", WEBHOOK)
    service.delete_webhook(wid)
    summaries = [e.summary for e in service.audit_log()]
    assert "웹훅 'dev' 삭제됨" in summaries
    assert "웹훅 'dev' 추가됨" in summaries


# ---------- 시작 점검표 ----------


def test_setup_checklist_lists_what_is_missing(service):
    items = {i.key: i.ready for i in service.setup_checklist()}
    assert items == {"openrouter_key": False, "default_webhook": False, "service_base_url": False}


def test_setup_checklist_turns_ready_as_settings_are_filled(service):
    service.set_openrouter_key(KEY)
    wid = service.add_webhook("rss", WEBHOOK)
    service.set_webhook_roles(default_id=wid, system_id=None)
    service.update({"service_base_url": "https://rss.example.com"})
    assert all(i.ready for i in service.setup_checklist())
    assert [i.label for i in service.setup_checklist()] == [
        "OpenRouter 키",
        "기본 웹훅",
        "서비스 주소",
    ]


def test_deleting_a_missing_openrouter_key_changes_nothing(service):
    service.delete_openrouter_key()
    assert service.audit_log() == []


def test_saving_the_same_roles_again_adds_no_audit_entry(service):
    wid = service.add_webhook("rss", WEBHOOK)
    service.set_webhook_roles(default_id=wid, system_id=None)
    before = len(service.audit_log())
    service.set_webhook_roles(default_id=wid, system_id=None)
    assert len(service.audit_log()) == before


def test_reserve_calls_may_be_zero_but_not_negative_or_huge(service):
    assert service.update({"llm_reserve_calls": "0"}).errors == {}
    assert service.snapshot().llm_reserve_calls == 0
    assert service.update({"llm_reserve_calls": "-1"}).errors == {
        "llm_reserve_calls": "0~1000 사이"
    }
    assert service.update({"llm_reserve_calls": "abc"}).errors == {
        "llm_reserve_calls": "숫자만 입력할 수 있음"
    }
    assert service.update({"llm_reserve_calls": "1001"}).errors == {
        "llm_reserve_calls": "0~1000 사이"
    }
