"""설정은 모두 화면(DB)에서 한다. 소스 어디에서도 환경 변수를 읽지 않는다."""

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "rss_hub"
FORBIDDEN = re.compile(r"os\.environ|os\.getenv|\bgetenv\(|\benviron\[|from os import .*environ")


def test_no_source_file_reads_environment_variables():
    offenders = [
        str(path.relative_to(SRC))
        for path in SRC.rglob("*.py")
        if FORBIDDEN.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []
