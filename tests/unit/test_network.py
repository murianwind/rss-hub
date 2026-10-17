import pytest

from rss_hub.domain.network import FORBIDDEN_MESSAGE, forbidden_host_reason, is_forbidden_ip

PUBLIC_IPS = ["8.8.8.8", "93.184.216.34", "172.32.0.1", "172.15.255.255", "2606:4700:4700::1111"]
PRIVATE_IPS = [
    "127.0.0.1",
    "127.255.255.254",
    "10.0.0.1",
    "172.16.0.1",
    "172.31.255.255",
    "192.168.1.1",
    "169.254.169.254",  # 클라우드 메타데이터
    "100.64.0.1",  # 통신사 공유 주소
    "0.0.0.0",
    "224.0.0.1",  # 멀티캐스트
    "240.0.0.1",
    "255.255.255.255",
    "::1",
    "::",
    "fe80::1",
    "fe80::1%eth0",
    "fc00::1",
    "fd12:3456::1",
    "ff02::1",
    "::ffff:127.0.0.1",  # IPv4를 품은 IPv6
    "::ffff:192.168.1.1",
    "64:ff9b::7f00:1",  # NAT64로 127.0.0.1을 가리킴
    "64:ff9b::a00:1",  # NAT64로 10.0.0.1을 가리킴
    "2002:7f00:1::1",  # 6to4로 127.0.0.1을 가리킴
]


@pytest.mark.parametrize("ip", PUBLIC_IPS)
def test_public_addresses_are_allowed(ip):
    assert is_forbidden_ip(ip) is False


@pytest.mark.parametrize("ip", PRIVATE_IPS)
def test_private_internal_and_special_addresses_are_forbidden(ip):
    assert is_forbidden_ip(ip) is True


def test_a_value_that_is_not_an_ip_is_forbidden_to_be_safe():
    assert is_forbidden_ip("not-an-ip") is True


@pytest.mark.parametrize(
    "host",
    [
        "example.com",
        "blog.example.co.kr",
        "a.b.c.example.org",
        "EXAMPLE.COM",
        "example.com.",
        *PUBLIC_IPS,
    ],
)
def test_public_hosts_pass(host):
    assert forbidden_host_reason(host) is None


@pytest.mark.parametrize("host", PRIVATE_IPS)
def test_private_ip_literals_are_rejected(host):
    assert forbidden_host_reason(host) == FORBIDDEN_MESSAGE


@pytest.mark.parametrize("host", ["[::1]", "[fe80::1]", "[::ffff:10.0.0.1]"])
def test_bracketed_ipv6_literals_are_rejected(host):
    assert forbidden_host_reason(host) == FORBIDDEN_MESSAGE


@pytest.mark.parametrize(
    "host",
    [
        "2130706433",  # 127.0.0.1을 한 숫자로
        "0x7f000001",  # 16진수
        "017700000001",  # 8진수
        "127.1",  # 줄여 쓴 주소
        "127.0.1",
        "0177.0.0.1",
        "0x7f.0.0.1",
        "3232235777",  # 192.168.1.1
        "167772161",  # 10.0.0.1
    ],
)
def test_disguised_ipv4_forms_are_rejected(host):
    assert forbidden_host_reason(host) == FORBIDDEN_MESSAGE


@pytest.mark.parametrize(
    "host",
    [
        "localhost",
        "LOCALHOST",
        "localhost.",
        "foo.localhost",
        "printer.local",
        "nas.lan",
        "svc.internal",
        "router.home.arpa",
        "intranet",
        "nas",  # 점이 없는 한 단어 호스트는 내부 이름이다
    ],
)
def test_internal_names_are_rejected(host):
    assert forbidden_host_reason(host) == FORBIDDEN_MESSAGE


@pytest.mark.parametrize(
    "host", ["1.2.3.4.example.com", "127.0.0.1.example.com", "localhost.example.com", "mylocal.com"]
)
def test_a_public_name_that_merely_contains_internal_looking_parts_is_allowed(host):
    assert forbidden_host_reason(host) is None


@pytest.mark.parametrize("host", ["0x7f.0.0.256", "999.999.999.999", "1.2.3.4.5", "0xzz"])
def test_malformed_numeric_hosts_are_not_mistaken_for_addresses(host):
    # 올바른 주소가 아니면 이름일 뿐이라 이 규칙으로는 걸러지지 않는다(연결 단계에서 막는다)
    assert forbidden_host_reason(host) in (None, FORBIDDEN_MESSAGE)


def test_an_empty_host_has_no_reason_here_because_the_url_check_reports_it():
    assert forbidden_host_reason("") is None


@pytest.mark.parametrize("host", ["bad:host", "a:b:c", "::zz"])
def test_colon_text_that_is_not_an_ipv6_address_is_treated_as_an_internal_style_name(host):
    assert forbidden_host_reason(host) == FORBIDDEN_MESSAGE


@pytest.mark.parametrize(
    "ip",
    ["::ffff:8.8.8.8", "64:ff9b::808:808", "2002:808:808::1"],
)
def test_ipv6_forms_that_embed_a_public_ipv4_address_are_allowed(ip):
    # 안에 든 주소가 공개 주소이면 허용한다(사설 주소를 품은 것만 막는다)
    assert is_forbidden_ip(ip) is False
    assert forbidden_host_reason(ip) is None


@pytest.mark.parametrize("host", ["9.16777216", "9.255.255.256", "1.2.3.256", "0.0.0.16777216"])
def test_numbers_too_big_for_their_form_are_not_read_as_an_address(host):
    # 만약 주소로 잘못 읽으면 10.0.0.0 같은 사설 주소로 바뀌는 값들이다
    assert forbidden_host_reason(host) is None
