"""features/*.feature의 시나리오를 ID(@SCH-01 등)로 골라 pytest 테스트로 연결한다.

한 feature 파일 안에 도메인 계층만으로 검증되는 시나리오와 서비스 계층이 필요한 시나리오가
섞여 있어서, 지금 단계에서 실행 가능한 시나리오만 ID로 골라 연결한다.
"""

import re
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any

from gherkin.parser import Parser
from gherkin.token_scanner import TokenScanner
from pytest_bdd import scenario

FEATURES_DIR = Path(__file__).resolve().parents[2] / "features"
_ID_TAG = re.compile(r"@[A-Z]{3}-\d{2}")


def scenario_names(feature_file: str) -> dict[str, str]:
    """시나리오 ID(예: "SCH-01") → 시나리오 이름."""
    text = (FEATURES_DIR / feature_file).read_text(encoding="utf-8")
    document = Parser().parse(TokenScanner(text))
    names: dict[str, str] = {}
    for child in document["feature"]["children"]:
        item = child.get("scenario")
        if not item:
            continue
        for tag in item["tags"]:
            if _ID_TAG.fullmatch(tag["name"]):
                names[tag["name"][1:]] = item["name"]
    return names


def bind(namespace: MutableMapping[str, Any], feature_file: str, ids: list[str]) -> None:
    """ids에 해당하는 시나리오를 namespace(테스트 모듈의 globals)에 테스트 함수로 등록한다."""
    names = scenario_names(feature_file)
    for scenario_id in ids:
        if scenario_id not in names:
            raise KeyError(f"{feature_file}에 {scenario_id} 시나리오가 없습니다")

        def _test() -> None:
            """시나리오 본문은 feature 파일의 단계가 실행한다."""

        _test.__name__ = f"test_{scenario_id.lower().replace('-', '_')}"
        namespace[_test.__name__] = scenario(feature_file, names[scenario_id])(_test)
