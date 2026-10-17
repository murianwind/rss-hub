"""네트워크 관련 테스트 도우미."""


def allow_all(_ip: str) -> bool:
    """로컬 시험 서버에 연결해야 하는 테스트용: 어떤 주소도 막지 않는다."""
    return False
