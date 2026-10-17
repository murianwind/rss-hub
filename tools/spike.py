#!/usr/bin/env python3
"""설계의 가정을 실제 서비스로 확인하는 시험(스파이크) 스크립트.

표준 라이브러리만 쓴다(설치할 것이 없다). 키와 웹훅 주소는 실행 중에 직접 입력하며,
화면에도 파일에도 남기지 않는다. 결과 보고서에서는 입력한 비밀 값을 한 번 더 걸러 낸다.

사용법
  python tools/spike.py key               # 키 정보만 확인(호출 한도를 쓰지 않는다)
  python tools/spike.py openrouter        # S1: OpenRouter 호출 방식 확인
  python tools/spike.py discord           # S2: Discord 웹훅 동작 확인
  python tools/spike.py discord-deleted   # S2 후반: 삭제한 웹훅으로 보냈을 때의 응답 확인

자세한 안내는 tools/SPIKE.md를 본다.
"""

from __future__ import annotations

import argparse
import getpass
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
CURRENT_MODELS = (
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
)
VARIANTS = {
    "A": "기존 방식(기존 프롬프트, max_tokens 350)",
    "B": "JSON 요청(새 프롬프트, max_tokens 700)",
    "C": "B + 추론 끄기(reasoning.effort=none)",
    "D": "C + JSON 강제(response_format=json_object, require_parameters)",
}
# 요약에 쓸 수 없는 종류(안전 분류기, 임베딩 등)의 이름 조각
NOT_FOR_SUMMARY = ("safety", "guard", "embed", "rerank", "moderation")
CAPABILITY_FLAGS = ("reasoning", "include_reasoning", "response_format", "structured_outputs")
HEADER_KEYWORDS = ("ratelimit", "retry-after")
MASK = "[비밀 값]"

LEGACY_PROMPT = """Translate the title to Korean, then summarize the article in Korean in 2-3 sentences. Also judge whether this article is primarily about OTT/streaming content (movies, dramas, TV shows, streaming service reviews, OTT platform news).

Output format (strictly follow):
TITLE: <Korean translated title>
SUMMARY: <2-3 sentence Korean summary>
OTT: <yes or no>

Rules:
- Output ONLY the TITLE, SUMMARY, and OTT lines above. No other text.
- Do NOT use Chinese characters (한자). Use pure Korean or English terms only.
- No HTML tags.
- OTT must be exactly "yes" or "no".

Title: <<TITLE>>
Content: <<CONTENT>>"""

JSON_PROMPT = """Translate the title to Korean and summarize the article in Korean in 2-3 sentences. Also judge whether the article is primarily about OTT/streaming content (movies, dramas, TV shows, streaming service news).

Respond with ONLY one JSON object and nothing else, in exactly this shape:
{"title_ko": "<Korean translated title>", "summary_ko": "<2-3 sentence Korean summary>", "is_ott": true or false}

Rules:
- No markdown code fences, no explanations, no reasoning text.
- Do NOT use Chinese characters. Use pure Korean or English terms only.
- No HTML tags.

Title: <<TITLE>>
Content: <<CONTENT>>"""

ARTICLES = (
    {
        "name": "영문 기술 글",
        "title": "Apple unveils new phone with a bigger battery",
        "content": (
            "Apple on Tuesday introduced its newest phone, which the company says lasts about two "
            "hours longer than last year's model. The device has a larger battery, a slimmer frame "
            "and a new chip designed to reduce power use during video playback. Reviewers who tested "
            "an early unit said web browsing and streaming held up well, but demanding games drained "
            "the battery noticeably faster. The phone goes on sale next month in 30 countries, with "
            "prices starting at the same level as the previous generation."
        ),
    },
    {
        "name": "한국어 글",
        "title": "스프링 부트 4 마이그레이션 후기",
        "content": (
            "지난주에 사내 서비스 세 개를 스프링 부트 4로 올렸습니다. 가장 먼저 부딪힌 문제는 "
            "설정 속성 이름이 바뀐 것이었고, 두 번째는 일부 라이브러리가 아직 새 버전을 지원하지 "
            "않는 점이었습니다. 테스트를 먼저 정리한 뒤 한 서비스씩 옮겼더니 전체 작업은 이틀 "
            "정도 걸렸습니다. 빌드 시간은 눈에 띄게 줄었지만 메모리 사용량은 조금 늘었습니다."
        ),
    },
)

LEAK_PHRASES = ("We need to translate", "Korean summary")
HANJA = re.compile(r"[\u4E00-\u9FFF]")
FENCE = re.compile(r"^```[a-zA-Z0-9]*\s*\n?(.*?)\n?```$", re.DOTALL)
DISCORD_HOSTS = ("discord.com", "discordapp.com")
DISCORD_PATH = re.compile(r"^/api(?:/v\d+)?/webhooks/\d+/[A-Za-z0-9._-]+$")


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


@dataclass
class Response:
    status: int
    headers: dict[str, str]
    body: bytes
    elapsed: float
    error: str = ""

    def json(self) -> Any:
        try:
            return json.loads(self.body.decode("utf-8", "replace"))
        except ValueError:
            return None

    def rate_headers(self) -> dict[str, str]:
        return {k: v for k, v in self.headers.items() if any(w in k for w in HEADER_KEYWORDS)}


def http(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    payload: Any = None,
    timeout: float = 90.0,
) -> Response:
    """HTTP 요청 하나. 어떤 실패든 예외 대신 Response로 돌려준다(오류 문구에는 주소를 넣지 않는다)."""
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request_headers = {"User-Agent": "rss-hub-spike/1.0"}
    if data is not None:
        request_headers["Content-Type"] = "application/json"
    request_headers.update(headers or {})
    request = urllib.request.Request(url, data=data, headers=request_headers, method=method)
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            body = reply.read()
            return Response(
                reply.status,
                {k.lower(): v for k, v in reply.headers.items()},
                body,
                time.monotonic() - started,
            )
    except urllib.error.HTTPError as error:
        body = error.read()
        return Response(
            error.code,
            {k.lower(): v for k, v in error.headers.items()},
            body,
            time.monotonic() - started,
        )
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        reason = getattr(error, "reason", error)
        return Response(0, {}, b"", time.monotonic() - started, f"{type(error).__name__}: {reason}")


def short(text: str, limit: int = 160) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def retry_after_seconds(response: Response, fallback: float = 5.0) -> float:
    candidates: list[Any] = [response.headers.get("retry-after")]
    body = response.json()
    if isinstance(body, dict):
        candidates.append(body.get("retry_after"))
    for value in candidates:
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return fallback


# ---------------------------------------------------------------------------
# 응답 검증 (tests/unit/test_validation.py와 같은 규칙)
# ---------------------------------------------------------------------------


def validate_json_summary(raw: str, finish_reason: str | None) -> str:
    """새 방식(JSON) 응답을 검사한다. 통과하면 "ok", 아니면 실패 이유를 돌려준다."""
    if finish_reason == "length":
        return "잘림(length)"
    text = raw.strip()
    fenced = FENCE.match(text)
    if fenced:
        text = fenced.group(1).strip()
    try:
        data = json.loads(text)
    except ValueError:
        return "JSON 아님"
    if not isinstance(data, dict):
        return "JSON 아님"
    title, summary = data.get("title_ko"), data.get("summary_ko")
    if not isinstance(title, str) or not isinstance(summary, str):
        return "필드 누락"
    title, summary = title.strip(), summary.strip()
    if not title or not summary:
        return "빈 제목/요약"
    for part in (title, summary):
        if "TITLE:" in part or "SUMMARY:" in part:
            return "형식 표지 잔류"
        if any(phrase in part for phrase in LEAK_PHRASES):
            return "추론 과정 누출"
        if HANJA.search(part):
            return "한자 혼입"
    return "ok"


def validate_legacy_summary(raw: str, finish_reason: str | None) -> str:
    """기존 방식(TITLE/SUMMARY/OTT 줄) 응답을 기존 코드와 같은 기준으로 검사한다."""
    if finish_reason == "length":
        return "잘림(length)"
    title = summary = None
    for line in raw.splitlines():
        if line.startswith("TITLE:"):
            title = line[len("TITLE:") :].strip()
        elif line.startswith("SUMMARY:"):
            summary = line[len("SUMMARY:") :].strip()
    if not title or not summary:
        return "형식 어긋남"
    if any(phrase in summary for phrase in LEAK_PHRASES):
        return "추론 과정 누출"
    if HANJA.search(summary) or HANJA.search(title):
        return "한자 혼입"
    return "ok"


# ---------------------------------------------------------------------------
# S1: OpenRouter
# ---------------------------------------------------------------------------


@dataclass
class CallResult:
    model: str
    variant: str
    article: str
    status: int
    elapsed: float
    verdict: str
    finish_reason: str = ""
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    reasoning_tokens: int | None = None
    content_chars: int = 0
    reasoning_field: bool = False
    provider: str = ""
    error: str = ""
    retried_429: bool = False
    rate_headers: dict[str, str] = field(default_factory=dict)
    sample: str = ""


def auth_headers(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}", "X-Title": "RSS Hub spike"}


def fetch_key_info(base_url: str, key: str) -> dict[str, Any]:
    """키 정보에서 비밀이 아닌 항목만 골라낸다(label에는 키의 일부가 들어 있을 수 있어 제외한다)."""
    response = http("GET", f"{base_url}/key", headers=auth_headers(key), timeout=30)
    body = response.json()
    info: dict[str, Any] = {"status": response.status}
    if response.error:
        info["error"] = response.error
    data = body.get("data") if isinstance(body, dict) else None
    if isinstance(data, dict):
        for name in (
            "is_free_tier",
            "usage",
            "usage_daily",
            "usage_weekly",
            "usage_monthly",
            "limit",
            "limit_remaining",
            "limit_reset",
            "rate_limit",
            "free_model_daily_requests",
            "effective_budget",
            "budgets",
            "allowed_data_regions",
            "expires_at",
            "include_byok_in_limit",
        ):
            if name in data:
                info[name] = data[name]
        # 식별자(계정, 조직, 작업공간 번호)와 label은 값을 보고서에 넣지 않는다. 항목 이름만 남긴다
        info["값을 보지 않은 항목"] = sorted(set(data) - set(info) - {"label", "name", "hash"})
    elif response.status >= 400:
        info["error"] = short(response.body.decode("utf-8", "replace"))
    return info


def free_text_models(base_url: str, key: str) -> tuple[list[dict[str, Any]], str]:
    response = http("GET", f"{base_url}/models", headers=auth_headers(key), timeout=60)
    body = response.json()
    if response.status != 200 or not isinstance(body, dict):
        return [], f"모델 목록 조회 실패(HTTP {response.status}) {response.error}".strip()
    models = []
    for item in body.get("data", []):
        pricing = item.get("pricing") or {}
        modalities = (item.get("architecture") or {}).get("output_modalities") or ["text"]
        if (
            str(pricing.get("prompt")) == "0"
            and str(pricing.get("completion")) == "0"
            and set(modalities) == {"text"}  # 음악, 이미지 같은 다른 출력이 있는 모델은 제외
            and not any(word in str(item.get("id")) for word in NOT_FOR_SUMMARY)
        ):
            models.append(item)
    models.sort(key=lambda m: m.get("created") or 0, reverse=True)
    return models, ""


def capabilities(model: dict[str, Any]) -> list[str]:
    supported = set(model.get("supported_parameters") or [])
    return [flag for flag in CAPABILITY_FLAGS if flag in supported]


def plan_models(free: list[dict[str, Any]], requested: list[str], max_models: int) -> list[str]:
    """시험할 모델: 직접 지정한 것, 없으면 지금 쓰는 모델 + 응답 형식 지정을 지원하는 최신 무료 모델."""
    if requested:
        return requested[:max_models]
    free_ids = [m["id"] for m in free]
    chosen = [m for m in CURRENT_MODELS if m in free_ids]
    for model in free:
        if len(chosen) >= max_models:
            break
        wants = {"response_format", "structured_outputs"} & set(
            model.get("supported_parameters") or []
        )
        if model["id"] not in chosen and wants:
            chosen.append(model["id"])
    return chosen[:max_models]


def hint_for(status: int, error: str) -> str:
    """실패한 호출의 흔한 원인을 쉬운 말로 알려 준다."""
    text = error.lower()
    if status == 0:
        slow = "timed out" in text or "timeout" in text
        return "응답이 너무 느려서 시간이 초과됐습니다" if slow else "인터넷 연결을 확인하세요"
    if status == 401:
        return "키가 올바르지 않습니다. 키를 다시 복사해서 입력해 보세요"
    if status == 402:
        return "OpenRouter 계정의 잔액이 부족하거나 음수입니다(무료 모델도 막힙니다)"
    if status == 403:
        return "이 키로는 사용할 수 없습니다(권한 또는 지역 제한)"
    if status == 404 and ("policy" in text or "privacy" in text):
        return (
            "개인정보(데이터 정책) 설정 때문에 이 무료 모델을 쓸 수 없습니다. "
            "https://openrouter.ai/settings/privacy 에서 무료 모델과 관련된 항목을 허용했는지 확인하세요"
        )
    if status == 404:
        return "이 모델 또는 요청 옵션을 지원하는 제공자가 없습니다"
    if status in (408, 504):
        return "응답이 너무 느려서 시간이 초과됐습니다"
    if status == 429:
        return "호출 한도 초과이거나 제공자가 붐빕니다(분당 20회, 하루 50회 또는 1000회)"
    if status >= 500:
        return "제공자 서버 오류입니다. 잠시 뒤 다시 해 보세요"
    return ""


def preflight(base_url: str, key: str, model: str, timeout: float) -> CallResult:
    """본 시험 전에 짧은 호출 한 번으로 키, 잔액, 모델 사용 가능 여부를 확인한다."""
    payload = {
        "model": model,
        "max_tokens": 20,
        "messages": [{"role": "user", "content": "Reply with the single word: ok"}],
    }
    url = f"{base_url}/chat/completions"
    response = http("POST", url, headers=auth_headers(key), payload=payload, timeout=timeout)
    retried = False
    if (
        response.status == 429
    ):  # 무료 모델의 일시적인 한도 초과는 흔하다. 한 번만 기다렸다가 다시 시도한다
        retried = True
        time.sleep(min(retry_after_seconds(response), 10.0))
        response = http("POST", url, headers=auth_headers(key), payload=payload, timeout=timeout)
    result = CallResult(
        model,
        "P",
        "사전 확인",
        response.status,
        response.elapsed,
        verdict="ok" if response.status == 200 else "요청 실패",
        retried_429=retried,
        rate_headers=response.rate_headers(),
    )
    if response.status != 200:
        result.error = error_message(response)
    return result


def build_payload(model: str, variant: str, article: dict[str, str]) -> dict[str, Any]:
    template = LEGACY_PROMPT if variant == "A" else JSON_PROMPT
    prompt = template.replace("<<TITLE>>", article["title"]).replace(
        "<<CONTENT>>", article["content"]
    )
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 350 if variant == "A" else 700,
    }
    if variant in ("C", "D"):
        payload["reasoning"] = {"effort": "none"}
    if variant == "D":
        payload["response_format"] = {"type": "json_object"}
        payload["provider"] = {"require_parameters": True}
    return payload


def parse_reply(response: Response) -> dict[str, Any]:
    """채팅 응답에서 필요한 값만 뽑는다."""
    body = response.json()
    out: dict[str, Any] = {
        "content": "",
        "finish": "",
        "usage": {},
        "reasoning": False,
        "provider": "",
    }
    if not isinstance(body, dict):
        return out
    choices = body.get("choices") or []
    if choices and isinstance(choices[0], dict):
        message = choices[0].get("message") or {}
        out["content"] = message.get("content") or ""
        out["finish"] = choices[0].get("finish_reason") or ""
        out["reasoning"] = bool(message.get("reasoning") or message.get("reasoning_details"))
    out["usage"] = body.get("usage") or {}
    out["provider"] = str(body.get("provider") or "")
    return out


def error_message(response: Response) -> str:
    if response.error:
        return response.error
    body = response.json()
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        err = body["error"]
        return short(f"{err.get('code', '')} {err.get('message', '')}")
    return short(response.body.decode("utf-8", "replace"))


def call_model(
    base_url: str, key: str, model: str, variant: str, article: dict[str, str], *, timeout: float
) -> CallResult:
    payload = build_payload(model, variant, article)
    response = http(
        "POST",
        f"{base_url}/chat/completions",
        headers=auth_headers(key),
        payload=payload,
        timeout=timeout,
    )
    retried = False
    if response.status == 429:  # 한 번만 기다렸다가 다시 시도한다
        retried = True
        time.sleep(min(retry_after_seconds(response), 30.0))
        response = http(
            "POST",
            f"{base_url}/chat/completions",
            headers=auth_headers(key),
            payload=payload,
            timeout=timeout,
        )

    result = CallResult(
        model,
        variant,
        article["name"],
        response.status,
        response.elapsed,
        verdict="",
        retried_429=retried,
        rate_headers=response.rate_headers(),
    )
    if response.status != 200:
        result.verdict = "요청 실패"
        result.error = error_message(response)
        return result

    reply = parse_reply(response)
    usage = reply["usage"]
    details = usage.get("completion_tokens_details") or {}
    result.finish_reason = reply["finish"]
    result.prompt_tokens = usage.get("prompt_tokens")
    result.completion_tokens = usage.get("completion_tokens")
    result.reasoning_tokens = details.get("reasoning_tokens")
    result.content_chars = len(reply["content"])
    result.reasoning_field = reply["reasoning"]
    result.provider = reply["provider"]
    result.sample = short(reply["content"], 140)
    check = validate_legacy_summary if variant == "A" else validate_json_summary
    result.verdict = check(reply["content"], reply["finish"])
    return result


# ---------------------------------------------------------------------------
# 보고서
# ---------------------------------------------------------------------------


def percent(count: int, total: int) -> str:
    return f"{count}/{total}" if total else "-"


def summarize(results: list[CallResult], models: list[str], variants: list[str]) -> list[str]:
    lines = ["모델 / 방식별 통과 수 (통과 / 시도), 평균 지연(초), 평균 추론 토큰"]
    for model in models:
        lines.append(f"  {model}")
        for variant in variants:
            rows = [r for r in results if r.model == model and r.variant == variant]
            if not rows:
                continue
            ok = sum(1 for r in rows if r.verdict == "ok")
            latency = sum(r.elapsed for r in rows) / len(rows)
            reasoning = [r.reasoning_tokens for r in rows if r.reasoning_tokens is not None]
            reasoning_text = f"{sum(reasoning) / len(reasoning):.0f}" if reasoning else "보고 안 됨"
            lines.append(
                f"    {variant}  {percent(ok, len(rows)):>5}   {latency:5.1f}초   추론 {reasoning_text}"
            )
    return lines


def observations(results: list[CallResult], models: list[str]) -> list[str]:
    notes: list[str] = []
    for model in models:
        mine = [r for r in results if r.model == model]
        by_variant = {v: [r for r in mine if r.variant == v] for v in VARIANTS}
        rate = {
            v: sum(1 for r in rows if r.verdict == "ok") / len(rows)
            for v, rows in by_variant.items()
            if rows
        }
        if not rate:
            continue
        best = max(rate, key=lambda v: (rate[v], -sum(r.elapsed for r in by_variant[v])))
        notes.append(
            f"{model}: 통과율이 가장 높은 방식은 {best}({rate[best]:.0%}). "
            + ", ".join(f"{v} {rate[v]:.0%}" for v in sorted(rate))
        )
        for variant in ("C", "D"):
            failed = [r for r in by_variant.get(variant, []) if r.status != 200]
            if failed and len(failed) == len(by_variant[variant]):
                notes.append(f"  - {variant} 요청은 모두 거부됨: {failed[0].error}")
        left_over = [r for r in by_variant.get("C", []) if (r.reasoning_tokens or 0) > 0]
        if left_over:
            notes.append(
                f"  - 추론 끄기(C) 뒤에도 추론 토큰이 쓰였다: 평균 "
                f"{sum(r.reasoning_tokens or 0 for r in left_over) / len(left_over):.0f}토큰"
            )
        truncated = [r for r in mine if r.verdict.startswith("잘림")]
        if truncated:
            notes.append(
                f"  - 응답이 잘린 횟수: {len(truncated)} ({', '.join(sorted({r.variant for r in truncated}))} 방식)"
            )
    return notes


def render_openrouter_report(
    *,
    key_before: dict[str, Any],
    key_after: dict[str, Any] | None,
    free: list[dict[str, Any]],
    models: list[str],
    variants: list[str],
    results: list[CallResult],
    list_error: str,
    pre: list[CallResult] | None = None,
    skipped: dict[str, str] | None = None,
    interrupted: bool = False,
) -> str:
    now = datetime.now(timezone.utc)
    out = ["# S1 OpenRouter 시험 보고서", f"실행 시각(UTC): {now:%Y-%m-%d %H:%M:%S}", ""]
    out += ["## 키 정보 (실행 전)"] + [f"- {k}: {v}" for k, v in key_before.items()]
    if key_after is not None:
        changed = {k: v for k, v in key_after.items() if key_before.get(k) != v}
        out += ["## 키 정보 (실행 후, 달라진 항목)"] + (
            [f"- {k}: {v}" for k, v in changed.items()] or ["- 달라진 항목 없음"]
        )
    out += ["", f"## 무료 모델 {len(free)}개" + (f" ({list_error})" if list_error else "")]
    for model in free[:40]:
        caps = ",".join(capabilities(model)) or "-"
        expiry = f" 만료 {model['expiration_date']}" if model.get("expiration_date") else ""
        out.append(f"- {model['id']}  문맥 {model.get('context_length')}  [{caps}]{expiry}")
    if pre:
        out += ["", "## 사전 확인(모델마다 짧은 호출 1번, 응답한 모델만 본 시험에 사용)"]
        for item in pre:
            state = "응답함" if item.status == 200 else "제외"
            out.append(f"- {item.model}: HTTP {item.status}, {item.elapsed:.1f}초 → {state}")
            if item.status != 200:
                out.append(f"    오류: {item.error}")
                out.append(f"    원인 추정: {hint_for(item.status, item.error) or '알 수 없음'}")
    if interrupted:
        out += ["", "※ 시험을 중간에 멈췄습니다. 아래는 그때까지의 결과입니다."]
    for model, reason in (skipped or {}).items():
        out += ["", f"※ {model}: {reason}"]
    out += [
        "",
        "## 호출 시험",
        f"시험한 모델: {', '.join(models) or '(없음)'}",
        "방식: " + "; ".join(f"{v}={VARIANTS[v]}" for v in variants),
        "",
    ]
    out += summarize(results, models, variants)
    out += ["", "## 호출별 결과"]
    for r in results:
        tokens = (
            f"프롬프트 {r.prompt_tokens} / 출력 {r.completion_tokens} / 추론 {r.reasoning_tokens}"
        )
        head = (
            f"- {r.model} {r.variant} [{r.article}] HTTP {r.status} {r.elapsed:.1f}초 → {r.verdict}"
        )
        out.append(head)
        if r.status == 200:
            out.append(
                f"    종료 {r.finish_reason or '-'}, {tokens}, 응답 {r.content_chars}자, "
                f"추론 필드 {'있음' if r.reasoning_field else '없음'}, 제공자 {r.provider or '-'}"
            )
            if r.verdict != "ok":
                out.append(f"    응답 일부: {r.sample}")
        else:
            out.append(f"    오류: {r.error}")
            guess = hint_for(r.status, r.error)
            if guess:
                out.append(f"    원인 추정: {guess}")
        if r.retried_429:
            out.append("    429를 받아 한 번 기다린 뒤 다시 시도함")
        if r.rate_headers:
            out.append(f"    한도 관련 헤더: {r.rate_headers}")
    out += ["", "## 자동 관찰"] + (observations(results, models) or ["- (호출 결과 없음)"])
    out += [
        "",
        "## 아직 확인하지 못한 것",
        "- 실패한 요청이 하루 한도에 포함되는지, 하루 한도의 기준 시각(UTC 여부)은 이 시험으로 알 수 없습니다.",
        "- is_free_tier의 의미는 위 키 정보와 본인의 결제 이력(10달러 이상 구매 여부)을 맞춰서 해석합니다.",
    ]
    return "\n".join(out) + "\n"


def mask_secrets(text: str, secrets: list[str]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, MASK)
    return text


FAIL_FAST_COUNT = 3


def check_models(
    base_url: str, key: str, candidates: list[str], args: argparse.Namespace
) -> tuple[list[str], list[CallResult], bool]:
    """후보 모델마다 짧은 호출을 보내서 응답하는 모델만 고른다.

    돌려주는 값: (응답한 모델, 사전 확인 결과 전체, 키/잔액 문제로 시험을 계속할 수 없는지)
    """
    healthy: list[str] = []
    checked: list[CallResult] = []
    for model in candidates:
        if len(healthy) >= args.max_models or len(checked) >= args.max_preflight:
            break
        print(f"    {model} …", end=" ", flush=True)
        result = preflight(base_url, key, model, args.preflight_timeout)
        checked.append(result)
        if result.status == 200:
            healthy.append(model)
            print(f"응답함({result.elapsed:.1f}초)")
            continue
        print(f"제외 — HTTP {result.status}, {result.elapsed:.0f}초: {short(result.error, 100)}")
        print(f"        → {hint_for(result.status, result.error) or '알 수 없는 오류'}")
        if result.status in (401, 402):
            return healthy, checked, True
    return healthy, checked, False


def run_openrouter(args: argparse.Namespace, key: str, *, input_fn=input) -> str:
    base_url = args.base_url.rstrip("/")
    print("1/5 키 정보를 확인합니다…")
    key_before = fetch_key_info(base_url, key)
    if key_before.get("status") in (401, 403):
        print(f"    키 정보 조회가 거부됐습니다(HTTP {key_before['status']}). 키를 확인하세요.")
    print("2/5 무료 모델 목록을 가져옵니다…")
    free, list_error = free_text_models(base_url, key)
    requested = [m.strip() for m in (args.models or "").split(",") if m.strip()]
    candidates = plan_models(free, requested, max(args.max_models, args.max_preflight))
    variants = [v for v in args.variants.split(",") if v in VARIANTS]

    print(
        f"3/5 사전 확인: 후보 모델에 짧은 호출을 1번씩 보내서 응답하는 모델만 고릅니다"
        f"(한 번에 최대 {args.preflight_timeout:.0f}초 기다립니다)…"
    )
    models, pre, fatal = check_models(base_url, key, candidates, args)

    def stop_report(message: str) -> str:
        print(f"    {message}")
        report = render_openrouter_report(
            key_before=key_before,
            key_after=None,
            free=free,
            models=models,
            variants=variants,
            results=[],
            list_error=list_error,
            pre=pre,
        )
        return mask_secrets(report, [key])

    if fatal:
        return stop_report("이 문제를 해결하기 전에는 시험을 계속할 수 없어서 멈춥니다.")
    if not models:
        return stop_report(
            "응답하는 모델이 없어서 멈춥니다. 위 원인을 확인하거나 나중에 다시 해 보세요."
        )

    calls = len(models) * len(variants) * len(ARTICLES)
    print(
        f"4/5 시험 계획: 모델 {len(models)}개 × 방식 {len(variants)}개 × 글 {len(ARTICLES)}개"
        f" = 호출 최대 {calls}회"
    )
    for model in models:
        print(f"    - {model}")
    print("    (무료 모델의 하루 호출 한도를 이만큼까지 씁니다.")
    print(f"     같은 이유로 {FAIL_FAST_COUNT}번 연속 실패하면 그 모델은 건너뜁니다.)")
    print("    (Ctrl+C로 멈추면 지금까지의 결과로 보고서를 만듭니다.)")
    if calls and not args.yes and input_fn("계속할까요? [y/N] ").strip().lower() != "y":
        print("취소했습니다.")
        return ""

    results: list[CallResult] = []
    skipped: dict[str, str] = {}
    interrupted = False
    done = 0
    try:
        for model in models:
            streak_status, streak = None, 0
            for variant in variants:
                for article in ARTICLES:
                    done += 1
                    if model in skipped:
                        continue
                    result = call_model(
                        base_url, key, model, variant, article, timeout=args.timeout
                    )
                    results.append(result)
                    line = f"    [{done}/{calls}] {model} {variant} {article['name']}: {result.verdict}"
                    if result.status != 200:
                        line += f" (HTTP {result.status}, {result.elapsed:.0f}초) {short(result.error, 90)}"
                    print(line)
                    if result.status == 200:
                        streak_status, streak = None, 0
                    else:
                        streak = streak + 1 if streak_status == result.status else 1
                        streak_status = result.status
                        if streak == 1:
                            guess = hint_for(result.status, result.error)
                            if guess:
                                print(f"        → {guess}")
                        if streak >= FAIL_FAST_COUNT:
                            skipped[model] = (
                                f"같은 이유(HTTP {result.status})로 {FAIL_FAST_COUNT}번 연속 실패해서 "
                                "나머지 호출을 건너뛰었습니다"
                            )
                            print("        → 같은 이유로 연속 실패해서 이 모델은 건너뜁니다.")
                    time.sleep(args.delay)  # 분당 20회 한도를 넘지 않게 간격을 둔다
    except KeyboardInterrupt:
        interrupted = True
        print("\n중단했습니다. 지금까지의 결과로 보고서를 만듭니다.")
    print("5/5 보고서를 만듭니다…")
    key_after = fetch_key_info(base_url, key) if results else None
    report = render_openrouter_report(
        key_before=key_before,
        key_after=key_after,
        free=free,
        models=models,
        variants=variants,
        results=results,
        list_error=list_error,
        pre=pre,
        skipped=skipped,
        interrupted=interrupted,
    )
    return mask_secrets(report, [key])


def run_key(args: argparse.Namespace, key: str) -> str:
    """키 정보만 조회한다. 채팅 호출이 없어서 무료 모델의 하루 호출 한도를 쓰지 않는다."""
    info = fetch_key_info(args.base_url.rstrip("/"), key)
    now = datetime.now(timezone.utc)
    out = ["# OpenRouter 키 정보", f"조회 시각(UTC): {now:%Y-%m-%d %H:%M:%S}", ""]
    out += [f"- {name}: {value}" for name, value in info.items()]
    return mask_secrets("\n".join(out) + "\n", [key])


# ---------------------------------------------------------------------------
# S2: Discord
# ---------------------------------------------------------------------------


def check_discord_url(url: str, *, skip_host_check: bool = False) -> str:
    """Discord 웹훅 주소인지 확인한다. 아니면 이유를 문자열로 돌려주고, 맞으면 빈 문자열."""
    parts = urllib.parse.urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if skip_host_check:
        return ""
    if parts.scheme != "https":
        return "https 주소여야 합니다"
    if not any(host == h or host.endswith("." + h) for h in DISCORD_HOSTS):
        return "Discord 주소가 아닙니다"
    if not DISCORD_PATH.match(parts.path):
        return "웹훅 주소 형식이 아닙니다"
    return ""


@dataclass
class Step:
    name: str
    status: int
    note: str = ""
    headers: dict[str, str] = field(default_factory=dict)


def webhook_post(url: str, content: str, *, wait: bool) -> Response:
    target = url + ("?wait=true" if wait else "")
    return http(
        "POST", target, payload={"content": content, "allowed_mentions": {"parse": []}}, timeout=30
    )


def body_summary(response: Response) -> str:
    body = response.json()
    if isinstance(body, dict):
        parts = []
        for name in ("code", "message", "retry_after", "global"):
            if name in body:
                parts.append(f"{name}={short(str(body[name]), 80)}")
        return ", ".join(parts)
    return response.error or short(response.body.decode("utf-8", "replace"), 80)


def run_discord(args: argparse.Namespace, url: str) -> str:
    problem = check_discord_url(url, skip_host_check=args.skip_host_check)
    if problem:
        print(f"웹훅 주소 확인 실패: {problem}")
        return ""
    steps: list[Step] = []
    created: list[str] = []
    sample = (
        "📢 **[RSS Hub 시험] 새 글 알림** `14:32`\n**새 아이폰 배터리 수명이 늘었다**\n"
        "배터리가 커지고 영상 재생 전력 소모가 줄었다.\n🔗 [글 읽기](https://rss.example.com/a/123)"
    )

    print("1/6 메시지 보내기(응답 받기)…")
    reply = webhook_post(url, sample, wait=True)
    body = reply.json()
    message_id = str(body.get("id")) if isinstance(body, dict) and body.get("id") else ""
    if message_id:
        created.append(message_id)
    keys = sorted(body) if isinstance(body, dict) else []
    steps.append(
        Step(
            "메시지 보내기(?wait=true)",
            reply.status,
            f"응답 항목: {', '.join(keys)}",
            reply.rate_headers(),
        )
    )
    time.sleep(args.delay)

    print("2/6 메시지 보내기(응답 안 받기)…")
    reply = webhook_post(url, "[RSS Hub 시험] 응답 없이 보내기", wait=False)
    steps.append(Step("메시지 보내기(?wait 없음)", reply.status, f"본문 {len(reply.body)}바이트"))
    time.sleep(args.delay)

    print("3/6 길이 한도 확인…")
    for length in (1900, 2000, 2001):
        reply = webhook_post(url, "가" * length, wait=True)
        body = reply.json()
        if isinstance(body, dict) and body.get("id"):
            created.append(str(body["id"]))
        steps.append(
            Step(
                f"{length}자 메시지",
                reply.status,
                "" if reply.status < 300 else body_summary(reply),
            )
        )
        time.sleep(args.delay)

    print("4/6 연속 발송으로 한도(429) 확인…")
    first_429: Response | None = None
    statuses: list[int] = []
    for index in range(args.burst):
        reply = webhook_post(url, f"[RSS Hub 시험] 연속 발송 {index + 1}/{args.burst}", wait=True)
        statuses.append(reply.status)
        body = reply.json()
        if isinstance(body, dict) and body.get("id"):
            created.append(str(body["id"]))
        if reply.status == 429:
            first_429 = first_429 or reply
            time.sleep(min(retry_after_seconds(reply, 1.0), 10.0))
    steps.append(
        Step(
            f"연속 {args.burst}회 발송",
            429 if first_429 else 200,
            f"상태 코드 순서: {statuses}",
            first_429.rate_headers() if first_429 else {},
        )
    )
    if first_429 is not None:
        steps.append(Step("429 응답 내용", 429, body_summary(first_429), first_429.rate_headers()))

    print("5/6 보낸 메시지 삭제…")
    deleted = 0
    delete_statuses: list[int] = []
    for message in created:
        reply = http("DELETE", f"{url}/messages/{message}", timeout=30)
        delete_statuses.append(reply.status)
        deleted += 1 if reply.status in (200, 204) else 0
        if reply.status == 429:
            time.sleep(min(retry_after_seconds(reply, 1.0), 10.0))
        time.sleep(min(0.3, args.delay))
    steps.append(
        Step(
            "메시지 삭제",
            delete_statuses[0] if delete_statuses else 0,
            f"{deleted}/{len(created)}개 삭제됨, 상태 코드: {sorted(set(delete_statuses))}",
        )
    )

    print("6/6 보고서를 만듭니다…")
    return mask_secrets(render_discord_report(steps), [url, url.rsplit("/", 1)[-1]])


def render_discord_report(steps: list[Step]) -> str:
    now = datetime.now(timezone.utc)
    out = ["# S2 Discord 웹훅 시험 보고서", f"실행 시각(UTC): {now:%Y-%m-%d %H:%M:%S}", ""]
    for step in steps:
        out.append(f"- {step.name}: HTTP {step.status}" + (f" — {step.note}" if step.note else ""))
        if step.headers:
            out.append(f"    한도 관련 헤더: {step.headers}")
    out += [
        "",
        "## 직접 확인할 것",
        "- 시험 채널에서 첫 메시지의 모양(굵은 글씨, 링크 글자)이 의도대로 보이는지",
        "- 이 시험이 보낸 메시지가 채널에 남아 있지 않은지(삭제 결과가 위에 있습니다)",
    ]
    return "\n".join(out) + "\n"


def run_discord_deleted(args: argparse.Namespace, url: str) -> str:
    problem = check_discord_url(url, skip_host_check=args.skip_host_check)
    if problem:
        print(f"웹훅 주소 확인 실패: {problem}")
        return ""
    reply = webhook_post(url, "[RSS Hub 시험] 삭제한 웹훅으로 보내기", wait=True)
    steps = [Step("삭제된 웹훅으로 보내기", reply.status, body_summary(reply))]
    return mask_secrets(render_discord_report(steps), [url, url.rsplit("/", 1)[-1]])


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    key_cmd = sub.add_parser("key", help="키 정보만 확인(호출 한도를 쓰지 않는다)")
    key_cmd.add_argument("--base-url", default=DEFAULT_BASE_URL, help=argparse.SUPPRESS)

    openrouter = sub.add_parser("openrouter", help="S1: OpenRouter 호출 방식 확인")
    openrouter.add_argument(
        "--models", default="", help="시험할 모델(쉼표로 구분). 없으면 자동으로 고른다"
    )
    openrouter.add_argument("--max-models", type=int, default=4, help="시험할 모델 수(기본 4)")
    openrouter.add_argument("--variants", default="A,B,C,D", help="시험할 방식(기본 A,B,C,D)")
    openrouter.add_argument(
        "--preflight-timeout",
        type=float,
        default=30.0,
        help="사전 확인 호출당 제한 시간(초, 기본 30)",
    )
    openrouter.add_argument(
        "--max-preflight", type=int, default=6, help="사전 확인으로 시험해 볼 후보 모델 수(기본 6)"
    )
    openrouter.add_argument("--delay", type=float, default=4.0, help="호출 사이 간격(초, 기본 4)")
    openrouter.add_argument(
        "--timeout", type=float, default=60.0, help="호출당 제한 시간(초, 기본 60)"
    )
    openrouter.add_argument("--base-url", default=DEFAULT_BASE_URL, help=argparse.SUPPRESS)
    openrouter.add_argument("--yes", action="store_true", help="계속할지 묻지 않는다")

    for name, help_text in (
        ("discord", "S2: Discord 웹훅 동작 확인"),
        ("discord-deleted", "S2 후반: 삭제한 웹훅으로 보냈을 때의 응답"),
    ):
        sub_parser = sub.add_parser(name, help=help_text)
        sub_parser.add_argument("--delay", type=float, default=1.5, help="호출 사이 간격(초)")
        sub_parser.add_argument("--burst", type=int, default=8, help="연속 발송 횟수(기본 8)")
        sub_parser.add_argument("--skip-host-check", action="store_true", help=argparse.SUPPRESS)

    for p in sub.choices.values():
        p.add_argument("--out", default="", help="보고서 저장 경로(기본: spike-report-<종류>.txt)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args(sys.argv[1:] if argv is None else argv)

    if args.command == "key":
        key = getpass.getpass(
            "OpenRouter 키를 입력하세요(입력해도 화면에 보이지 않습니다): "
        ).strip()
        if not key:
            print("키가 비어 있습니다.")
            return 1
        report, default_name = run_key(args, key), "spike-report-key.txt"
    elif args.command == "openrouter":
        key = getpass.getpass(
            "OpenRouter 키를 입력하세요(입력해도 화면에 보이지 않습니다): "
        ).strip()
        if not key:
            print("키가 비어 있습니다.")
            return 1
        report, default_name = run_openrouter(args, key), "spike-report-openrouter.txt"
    else:
        url = getpass.getpass(
            "시험용 Discord 웹훅 주소를 입력하세요(화면에 보이지 않습니다): "
        ).strip()
        runner = run_discord if args.command == "discord" else run_discord_deleted
        report, default_name = runner(args, url), f"spike-report-{args.command}.txt"

    if not report:
        return 1
    path = Path(args.out or default_name)
    path.write_text(report, encoding="utf-8")
    print()
    print(report)
    print(f"보고서를 저장했습니다: {path}")
    print("이 보고서에는 키와 웹훅 주소가 들어 있지 않습니다. 내용을 그대로 붙여넣어 주세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
