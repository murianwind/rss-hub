"""백업과 복원 키워드."""

import json

from tests.keywords.browser import BROWSER

SECRET_URL = "https://discord.com/api/webhooks/777/SECRETWEBHOOKTOKEN"
SECRET_KEY = "sk-or-v1-SECRETKEYVALUE"


def download_backup(world):
    """백업 파일을 내려받아 (응답, 내용 바이트)를 돌려준다."""
    response = world.get("/backup/export")
    assert response.status_code == 200
    return response, response.content


def restore_backup(world, data: bytes, *, confirm=True, name="backup.json"):
    """파일을 올려 복원한다."""
    form = {"confirm": "yes"} if confirm else {}
    return world.client.post(
        "/backup/restore", files={"file": (name, data)}, data=form, headers=BROWSER
    )


def edited(data: bytes, change):
    """백업 내용을 읽어 change(document)로 고친 뒤 다시 바이트로 돌려준다."""
    document = json.loads(data)
    change(document)
    return json.dumps(document).encode()
