"""설치된 패키지 버전. 설치되지 않은 개발 환경에서는 "dev"."""

from importlib.metadata import PackageNotFoundError, version


def get_version() -> str:
    try:
        return version("rss-hub")
    except PackageNotFoundError:
        return "dev"
