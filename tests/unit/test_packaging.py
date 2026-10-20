"""설치된 패키지에도 화면 파일(템플릿, 정적 파일)이 들어가는지 확인한다.

소스 폴더에서 돌리는 시험은 이 문제를 못 잡는다(파일이 항상 있다). Docker 이미지처럼
`pip install .`로 설치하면 package-data에 없는 파일은 빠져서 서비스가 시작되지 못한다.
"""

import tomllib
from fnmatch import fnmatch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "src" / "rss_hub"
DATA_DIRS = ("web/templates", "web/static")


def declared_patterns() -> list[str]:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return config["tool"]["setuptools"]["package-data"]["rss_hub"]


def data_files() -> list[str]:
    found = []
    for folder in DATA_DIRS:
        found += [
            path.relative_to(PACKAGE).as_posix()
            for path in (PACKAGE / folder).rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        ]
    return found


def test_every_template_and_static_file_is_declared_as_package_data():
    patterns = declared_patterns()
    missing = [f for f in data_files() if not any(fnmatch(f, pattern) for pattern in patterns)]
    assert missing == [], f"설치 패키지에 빠지는 파일: {missing}"


def test_the_data_folders_are_not_empty():
    folders = {Path(f).parts[1] for f in data_files()}
    assert folders == {"templates", "static"}
    assert {"web/static/app.css", "web/static/app.js"} <= set(data_files())
