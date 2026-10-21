import json

import pytest

from rss_hub.domain.backup import FORMAT, TABLE_ORDER, VERSION, BackupError, parse_backup


def document(**changes):
    base = {
        "format": FORMAT,
        "version": VERSION,
        "schema_version": 3,
        "webhooks": [{"id": 1, "name": "기본"}],
        "roles": {"default": "기본", "system": None},
        "tables": {name: [] for name in TABLE_ORDER},
    }
    base.update(changes)
    return json.dumps(base).encode()


def parse(raw, schema=3):
    return parse_backup(raw, max_schema_version=schema)


def test_a_valid_document_is_returned_as_it_is():
    assert parse(document())["webhooks"] == [{"id": 1, "name": "기본"}]


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"not json",
        b"[]",
        b'{"hello": 1}',
        document(format="other"),
        document(version=2),
        document(schema_version=0),
        document(schema_version="3"),
        document(schema_version=True),
        document(schema_version=4),  # 이 서비스보다 새로운 버전
        document(webhooks=[{"id": "1", "name": "기본"}]),
        document(webhooks="기본"),
        document(roles={"default": 1}),
        document(roles={"other": "기본"}),
        document(tables=[]),
        document(tables={name: [] for name in TABLE_ORDER[:-1]}),
        document(tables={**{name: [] for name in TABLE_ORDER}, "secrets": []}),
        document(tables={**{name: [] for name in TABLE_ORDER}, "feeds": {}}),
        document(tables={**{name: [] for name in TABLE_ORDER}, "feeds": ["x"]}),
        document(tables={**{name: [] for name in TABLE_ORDER}, "feeds": [{"name": ["a"]}]}),
    ],
)
def test_anything_else_is_refused_with_a_fixed_message(raw):
    with pytest.raises(BackupError) as caught:
        parse(raw)
    assert caught.value.message


def test_deeply_nested_json_is_refused_instead_of_crashing():
    with pytest.raises(BackupError):
        parse(b"[" * 100_000)
