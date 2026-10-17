"""09_settings.feature 중 입력 검증 시나리오(SET-08~12)를 도메인 규칙으로 검증한다.

저장소, 화면, 비밀 값 처리가 필요한 나머지 설정 시나리오는 서비스 계층 구현 뒤에 연결한다.
"""

from dataclasses import dataclass

import pytest
from pytest_bdd import parsers, then, when

from rss_hub.domain.settings_rules import (
    SettingError,
    normalize_base_url,
    normalize_model_chain,
    normalize_webhook_url,
    parse_collect_interval,
    parse_job_interval_seconds,
    validate_timezone,
)
from tests.bdd.binding import bind

bind(globals(), "09_settings.feature", [f"SET-{n:02d}" for n in range(8, 13)])


@dataclass
class Outcome:
    ok: bool
    value: str = ""
    message: str = ""


@pytest.fixture
def outcome():
    return {}


def _run(store, func, raw, render=str):
    try:
        store["result"] = Outcome(ok=True, value=render(func(raw)))
    except SettingError as error:
        store["result"] = Outcome(ok=False, message=error.message)


INTERVAL_FUNCS = {
    "수집 주기(분)": parse_collect_interval,
    "요약 주기(초)": parse_job_interval_seconds,
    "발송 주기(초)": parse_job_interval_seconds,
}


@when(parsers.re(r'서비스 주소를 "(?P<raw>.*)"으로 저장한다'))
def _base_url(outcome, raw):
    _run(outcome, normalize_base_url, raw)


@when(parsers.re(r'웹훅 주소를 "(?P<raw>.*)"로 저장한다'))
def _webhook(outcome, raw):
    _run(outcome, normalize_webhook_url, raw)


@when(
    parsers.re(
        r'(?P<setting>수집 주기\(분\)|요약 주기\(초\)|발송 주기\(초\))을 "(?P<raw>.*)"로 저장한다'
    )
)
def _interval(outcome, setting, raw):
    _run(outcome, INTERVAL_FUNCS[setting], raw)


@when(parsers.re(r'서비스 시간대를 "(?P<raw>.*)"으로 저장한다'))
def _timezone(outcome, raw):
    _run(outcome, validate_timezone, raw)


@when(parsers.re(r'모델 체인을 "(?P<raw>.*)"으로 저장한다'))
def _model_chain(outcome, raw):
    _run(outcome, normalize_model_chain, raw, render=", ".join)


@then(parsers.parse("결과: {text}"))
def _expect(outcome, text):
    result = outcome["result"]
    if text == "저장된다":
        assert result.ok, result.message
    elif text.startswith("저장되고 값은 "):
        expected = text.removeprefix("저장되고 값은 ").removesuffix(" 하나")
        assert result.ok, result.message
        assert result.value == expected
    elif text.startswith("저장되고 순서는 "):
        assert result.ok, result.message
        assert result.value == text.removeprefix("저장되고 순서는 ")
    elif text.startswith('오류 "') and text.endswith('"'):
        assert not result.ok
        assert result.message == text[len('오류 "') : -1]
    else:
        pytest.fail(f"해석할 수 없는 기대 결과: {text}")
