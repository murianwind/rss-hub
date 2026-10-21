"""모든 시나리오가 시험에 연결되어 있고, 시나리오 ID가 겹치지 않는지 확인한다."""

import importlib
import pkgutil
import re
from collections import Counter

import tests.bdd
from tests.bdd.binding import FEATURES_DIR

_ID_TAG = re.compile(r"(?m)^\s*@([A-Z]{3}-\d{2})\b")


def _scenario_ids():
    return [
        found
        for feature in sorted(FEATURES_DIR.glob("*.feature"))
        for found in _ID_TAG.findall(feature.read_text(encoding="utf-8"))
    ]


def _bound_test_names():
    names = set()
    for module_info in pkgutil.iter_modules(tests.bdd.__path__):
        if module_info.name.startswith("test_") and module_info.name != "test_traceability":
            module = importlib.import_module(f"tests.bdd.{module_info.name}")
            names.update(name for name in vars(module) if name.startswith("test_"))
    return names


def test_every_scenario_id_is_used_once():
    repeated = [i for i, count in Counter(_scenario_ids()).items() if count > 1]
    assert repeated == []


def test_every_scenario_is_bound_to_a_test():
    bound = _bound_test_names()
    unbound = [i for i in _scenario_ids() if f"test_{i.lower().replace('-', '_')}" not in bound]
    assert unbound == []
