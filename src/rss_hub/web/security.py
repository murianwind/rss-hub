"""인증이 없는 관리 화면을 지키는 최소 장치.

- 다른 사이트가 사용자의 브라우저를 이용해 설정을 바꾸는 요청(CSRF)을 거부한다.
- 모든 응답에 캐시 금지와 보안 헤더를 붙인다.
"""

from collections.abc import Mapping
from urllib.parse import urlsplit

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

SECURITY_HEADERS: dict[str, str] = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
        "base-uri 'none'; frame-ancestors 'none'"
    ),
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


def request_is_same_origin(headers: Mapping[str, str]) -> bool:
    """상태를 바꾸는 요청이 우리 화면에서 왔는지 판단한다(헤더 이름은 소문자).

    브라우저는 다른 사이트에서 보내는 요청에 Origin과 Sec-Fetch-Site를 붙이고, 페이지의 스크립트가
    이 헤더를 바꿀 수 없다. 이 헤더가 없는 요청(curl 등)은 브라우저를 통한 CSRF 경로가 아니다.
    """
    site = headers.get("sec-fetch-site")
    if site is not None and site not in ("same-origin", "none"):
        return False

    origin = headers.get("origin")
    if origin is None:
        return True

    allowed = {headers.get("host", "").lower()}
    forwarded = headers.get("x-forwarded-host")
    if forwarded:  # 리버스 프록시(NPM)가 넘긴 공개 주소. 첫 값만 쓴다
        allowed.add(forwarded.split(",")[0].strip().lower())
    allowed.discard("")

    netloc = urlsplit(origin).netloc.lower()
    return bool(netloc) and netloc in allowed
