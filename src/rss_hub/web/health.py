"""상태 확인에 쓰는 점검."""

import tempfile
from pathlib import Path


def data_dir_is_writable(path: Path) -> bool:
    """데이터 디렉터리에 임시 파일을 만들 수 있는지 확인한다(만든 파일은 바로 지운다).

    컨테이너의 볼륨 권한 문제(실행 사용자가 /data에 쓸 수 없음)를 가장 먼저 드러내는 점검이다.
    """
    try:
        with tempfile.TemporaryFile(dir=path):
            return True
    except OSError:
        return False
