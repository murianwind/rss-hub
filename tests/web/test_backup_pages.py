import json

from tests.keywords.backup import download_backup, restore_backup
from tests.keywords.browser import BROWSER, CROSS_SITE
from tests.keywords.page import text_of


def test_the_download_is_a_json_attachment_that_is_never_cached(world):
    response, data = download_backup(world)
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["content-disposition"].startswith(
        'attachment; filename="rss-hub-backup-'
    )
    assert response.headers["cache-control"] == "no-store"
    assert json.loads(data)["format"] == "rss-hub-backup"


def test_restoring_without_choosing_a_file_is_reported(world):
    response = world.client.post("/backup/restore", data={"confirm": "yes"}, headers=BROWSER)
    assert response.status_code == 400 and "파일을 선택" in text_of(response)


def test_a_file_that_turns_out_larger_than_declared_is_refused_while_reading(world, monkeypatch):
    monkeypatch.setattr("rss_hub.web.backup.MAX_BACKUP_BYTES", 10)
    response = restore_backup(world, b"x" * 100)
    assert response.status_code == 413


def test_a_cross_site_restore_is_rejected_before_anything_changes(world):
    _, data = download_backup(world)
    response = world.client.post(
        "/backup/restore",
        files={"file": ("backup.json", data)},
        data={"confirm": "yes"},
        headers=CROSS_SITE,
    )
    assert response.status_code == 403


def test_the_result_never_echoes_the_file_content(world):
    response = restore_backup(world, b'{"secret-looking": "sk-or-v1-LEAKME"}')
    assert response.status_code == 400 and "LEAKME" not in response.text
