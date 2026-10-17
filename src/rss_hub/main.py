"""서비스 시작점. 웹 서버와 함께 수집, 요약, 발송 잡을 돌린다.

uvicorn rss_hub.main:create_service_app --factory
"""

from fastapi import FastAPI

from rss_hub.runtime import build_runner
from rss_hub.web.app import create_app


def create_service_app() -> FastAPI:
    return create_app(runner_factory=build_runner)
