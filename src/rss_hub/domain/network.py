"""서버가 요청을 보내면 안 되는 주소(사설망, 내부, 루프백, 특수 주소) 판별.

인증 없이 열려 있는 서비스에서 서버가 사용자가 준 주소로 요청을 보내면, 공격자가 서버를 시켜
집 안의 다른 장치나 클라우드 메타데이터 주소(169.254.169.254)에 요청하게 만들 수 있다(SSRF).
그래서 사설망 주소는 어떤 경우에도 허용하지 않는다(사용자 결정, 설계 §11).

- 주소를 쓴 모양을 보는 검사(`forbidden_host_reason`)는 가져오기 단계에서 쓴다.
- 실제로 연결된 상대 IP를 보는 검사(`is_forbidden_ip`)는 연결 시점에 쓴다.
  이름이 공개 주소처럼 보여도 사설망으로 풀리거나 리다이렉트로 사설망에 닿는 경우를 막는다.
"""

import ipaddress

FORBIDDEN_MESSAGE = "사설망·내부 주소는 허용하지 않음"
INTERNAL_SUFFIXES = (
    ".localhost",
    ".local",
    ".internal",
    ".lan",
    ".home.arpa",
    ".intranet",
    ".corp",
    ".home",
)
_NAT64 = ipaddress.ip_network("64:ff9b::/96")


def _embedded_ipv4(addr: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    """IPv4를 품은 IPv6(IPv4 매핑, 6to4, NAT64)에서 안에 든 IPv4 주소를 꺼낸다."""
    if addr.ipv4_mapped is not None:
        return addr.ipv4_mapped
    if addr.sixtofour is not None:
        return addr.sixtofour
    if addr in _NAT64:
        return ipaddress.IPv4Address(int(addr) & 0xFFFFFFFF)
    return None


def _forbidden(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(addr, ipaddress.IPv6Address):
        embedded = _embedded_ipv4(addr)
        if embedded is not None:
            return _forbidden(embedded)
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
        or not addr.is_global
    )


def is_forbidden_ip(ip: str) -> bool:
    """연결된 상대의 IP가 사설망, 내부, 특수 주소인지. 읽을 수 없으면 안전하게 금지로 본다."""
    try:
        addr = ipaddress.ip_address(ip.split("%")[0].strip().strip("[]"))
    except ValueError:
        return True
    return _forbidden(addr)


def _loose_ipv4(host: str) -> str | None:
    """운영체제가 IPv4로 읽는 변형 표기(2130706433, 0x7f000001, 127.1 등)를 점 표기로 바꾼다."""
    parts = host.split(".")
    if not 1 <= len(parts) <= 4:
        return None
    values: list[int] = []
    for part in parts:
        if part.lower().startswith("0x"):
            digits, base, allowed = part[2:], 16, "0123456789abcdef"
        elif len(part) > 1 and part.startswith("0"):
            digits, base, allowed = part[1:], 8, "01234567"
        else:
            digits, base, allowed = part, 10, "0123456789"
        if not digits or any(c not in allowed for c in digits.lower()):
            return None
        values.append(int(digits, base))
    *head, last = values
    if any(v > 255 for v in head) or last >= 256 ** (4 - len(head)):
        return None
    number = 0
    for value in head:
        number = number * 256 + value
    number = number * 256 ** (4 - len(head)) + last
    return str(ipaddress.IPv4Address(number))


def _literal_ip(host: str) -> str | None:
    """호스트가 IP 주소를 직접 쓴 것이면 그 주소를, 이름이면 None."""
    if ":" in host:
        try:
            return str(ipaddress.ip_address(host.split("%")[0]))
        except ValueError:
            return None
    return _loose_ipv4(host)


def forbidden_host_reason(host: str) -> str | None:
    """주소의 호스트 부분이 사설망, 내부 주소로 보이면 이유를, 아니면 None을 돌려준다.

    이름이 공개 주소처럼 보여도 실제로는 사설망으로 풀리는 경우는 여기서 알 수 없다.
    그 경우는 연결 단계에서 막는다.
    """
    name = host.strip().strip("[]").lower().rstrip(".")
    if not name:
        return None
    literal = _literal_ip(name)
    if literal is not None:
        return FORBIDDEN_MESSAGE if is_forbidden_ip(literal) else None
    if name == "localhost" or name.endswith(INTERNAL_SUFFIXES) or "." not in name:
        return FORBIDDEN_MESSAGE
    return None
