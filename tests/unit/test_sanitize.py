"""글 본문 정제: 외부 사이트가 준 HTML에서 읽기에 필요한 것만 남긴다."""

import re

import pytest

from rss_hub.domain.sanitize import sanitize_html

BASE = "https://blog.example.com/posts/1"


def clean(html, base=BASE):
    return sanitize_html(html, base)


def test_basic_formatting_is_kept():
    html = "<p>안녕 <strong>굵게</strong> <em>기울임</em><br>다음 줄</p><ul><li>하나</li></ul>"
    assert clean(html) == html.replace("<br>", "<br>")


def test_text_is_escaped_so_markup_like_text_stays_text():
    assert clean("<p>1 < 2 && 3 > 2</p>") == "<p>1 &lt; 2 &amp;&amp; 3 &gt; 2</p>"


def test_unclosed_and_misnested_tags_are_balanced():
    assert clean("<p>a<b>b<i>c</p>d") == "<p>a<b>b<i>c</i></b></p>d"
    assert clean("</p></div>text") == "text"


@pytest.mark.parametrize(
    "tag",
    [
        "script",
        "style",
        "iframe",
        "object",
        "noscript",
        "template",
        "svg",
        "math",
        "form",
        "textarea",
        "select",
        "title",
    ],
)
def test_dangerous_containers_are_removed_with_their_content(tag):
    assert (
        clean(f"<p>앞</p><{tag}>SECRET-PAYLOAD alert(1)</{tag}><p>뒤</p>") == "<p>앞</p><p>뒤</p>"
    )


def test_unknown_tags_are_unwrapped_but_their_text_stays():
    assert clean("<custom-box>보이는 글</custom-box>") == "보이는 글"


# ---------- 공격 사례 모음 ----------

XSS = [
    "<img src=x onerror=alert(1)>",
    '<img src="https://x.example.com/a.png" onerror="alert(1)" onload="alert(2)">',
    "<svg onload=alert(1)>",
    "<svg><script>alert(1)</script></svg>",
    '<a href="javascript:alert(1)">x</a>',
    '<a href="JaVaScRiPt:alert(1)">x</a>',
    '<a href=" javascript:alert(1)">x</a>',
    '<a href="java\tscript:alert(1)">x</a>',
    '<a href="java&#10;script:alert(1)">x</a>',
    '<a href="&#106;avascript:alert(1)">x</a>',
    '<a href="&#x6A;avascript&colon;alert(1)">x</a>',
    '<a href="\x01javascript:alert(1)">x</a>',
    '<a href="vbscript:msgbox(1)">x</a>',
    '<a href="data:text/html,<script>alert(1)</script>">x</a>',
    '<img src="javascript:alert(1)">',
    '<img src="data:image/svg+xml;base64,PHN2ZyBvbmxvYWQ9YWxlcnQoMSk+">',
    '<iframe src="https://evil.example.com"></iframe>',
    '<iframe srcdoc="<script>alert(1)</script>"></iframe>',
    '<object data="https://evil.example.com/x.swf"></object>',
    '<embed src="https://evil.example.com/x.swf">',
    '<form action="https://evil.example.com"><input name=a><button>x</button></form>',
    '<meta http-equiv="refresh" content="0;url=https://evil.example.com">',
    '<base href="https://evil.example.com/">',
    '<link rel="stylesheet" href="https://evil.example.com/x.css">',
    '<style>@import "https://evil.example.com/x.css"; body{display:none}</style>',
    '<p style="background:url(javascript:alert(1))">x</p>',
    '<p onclick="alert(1)" onmouseover="alert(2)">x</p>',
    '<div style="position:fixed;top:0;left:0;width:100%;height:100%">overlay</div>',
    "<scr<script>ipt>alert(1)</scr</script>ipt>",
    "<<script>alert(1)//<</script>",
    "<script\x00>alert(1)</script>",
    "<!--><script>alert(1)</script>-->",
    "<![CDATA[<script>alert(1)</script>]]>",
    '<noscript><p title="</noscript><img src=x onerror=alert(1)>">',
    '<math><mi//xlink:href="data:x,<script>alert(1)</script>">',
    "<details open ontoggle=alert(1)>x</details>",
    "<video><source onerror=alert(1)></video>",
    "<body onload=alert(1)>x</body>",
    '<a href="https://user:pass@evil.example.com/">x</a>',
    '<img src="https://user:pass@evil.example.com/a.png">',
    '<a href="javascript://evil.example.com/%0aalert(1)">x</a>',
    '<a href="JAVASCRIPT://evil.example.com/%0Aalert(document.cookie)">x</a>',
    '<a href="vbscript://evil.example.com/x">x</a>',
    '<a href="file://host/etc/passwd">x</a>',
    '<a href="ftp://evil.example.com/payload">x</a>',
    '<a href="gopher://evil.example.com/">x</a>',
    '<a href="about:blank">x</a>',
    '<a href="blob:https://evil.example.com/uuid">x</a>',
    '<img src="ftp://evil.example.com/a.png">',
    '<img src="javascript://evil.example.com/%0aalert(1)">',
]


@pytest.mark.security
@pytest.mark.parametrize("payload", XSS)
def test_no_attack_payload_survives_as_markup(payload):
    output = clean(f"<p>앞</p>{payload}<p>뒤</p>")
    lowered = output.lower()
    assert "<script" not in lowered and "<iframe" not in lowered and "<object" not in lowered
    assert "<embed" not in lowered and "<form" not in lowered and "<meta" not in lowered
    assert "<style" not in lowered and "<svg" not in lowered and "<base" not in lowered
    assert "<link" not in lowered and "<math" not in lowered and "<body" not in lowered
    assert not re.search(r"\son\w+\s*=", lowered), output
    assert "javascript:" not in lowered and "vbscript:" not in lowered and "data:" not in lowered
    assert "style=" not in lowered and "srcdoc" not in lowered and "@import" not in lowered
    assert "user:pass" not in lowered
    assert output.startswith(
        "<p>앞</p>"
    )  # 닫히지 않은 위험한 요소는 뒤의 내용까지 지운다(안전한 쪽)


@pytest.mark.security
def test_the_output_of_the_sanitizer_is_stable_when_sanitized_again():
    for payload in XSS:
        once = clean(payload)
        assert clean(once) == once


# ---------- 링크 ----------


def test_links_are_made_absolute_and_open_safely_in_a_new_tab():
    out = clean(
        '<a href="/about">소개</a> <a href="other.html">다른</a> <a href="https://x.example.com/p?a=1&amp;b=2">외부</a>'
    )
    assert (
        'href="https://blog.example.com/about"' in out
        and 'href="https://blog.example.com/posts/other.html"' in out
    )
    assert 'href="https://x.example.com/p?a=1&amp;b=2"' in out
    assert (
        out.count('rel="noopener noreferrer nofollow"') == 3 and out.count('target="_blank"') == 3
    )


def test_a_link_without_a_usable_address_keeps_its_text_only():
    assert (
        clean('<a name="top">제목</a><a href="">빈</a><a href="mailto:a@b.c">메일</a>')
        == "제목빈메일"
    )


def test_a_link_title_is_kept_and_escaped():
    assert 'title="a &quot;b&quot; &lt;c&gt;"' in clean(
        '<a href="https://x.example.com/" title=\'a "b" <c>\'>x</a>'
    )


# ---------- 이미지 ----------


def test_an_https_image_is_kept_with_safe_loading_attributes():
    out = clean(
        '<img src="/img/a.png" alt="그림" width="400" height="300" srcset="x 2x" class="big">'
    )
    assert (
        out == '<img src="https://blog.example.com/img/a.png" alt="그림" loading="lazy" '
        'decoding="async" referrerpolicy="no-referrer">'
    )


def test_only_https_images_are_kept_because_the_page_policy_allows_nothing_else():
    assert clean('<img src="http://x.example.com/a.png">') == ""
    assert clean('<img src="data:image/png;base64,AAAA">') == ""
    assert 'src="https://x.example.com/a.png"' in clean('<img src="https://x.example.com/a.png">')


@pytest.mark.parametrize(
    "attrs", ['width="1" height="1"', 'width="0"', 'height="2"', 'width="1px" height="1px"']
)
def test_tracking_pixels_are_dropped(attrs):
    assert clean(f'<img src="https://t.example.com/p.gif" {attrs}>') == ""


def test_an_image_without_a_source_is_dropped():
    assert clean('<img alt="설명만">') == ""


def test_a_properly_closed_dangerous_element_does_not_swallow_what_follows():
    assert clean("<p>앞</p><iframe>x</iframe><svg><path/></svg><p>뒤</p>") == "<p>앞</p><p>뒤</p>"


# ---------- 표, 제목 ----------


def test_tables_keep_their_structure_and_spans():
    out = clean(
        '<table><thead><tr><th colspan="2">제목</th></tr></thead>'
        '<tbody><tr><td rowspan="2">a</td><td>b</td></tr></tbody></table>'
    )
    assert 'colspan="2"' in out and 'rowspan="2"' in out and out.count("<tr>") == 2


def test_headings_are_shifted_below_the_page_title():
    assert (
        clean("<h1>a</h1><h2>b</h2><h3>c</h3><h6>d</h6>")
        == "<h3>a</h3><h3>b</h3><h4>c</h4><h6>d</h6>"
    )


def test_code_blocks_keep_their_text():
    assert (
        clean("<pre><code>if a < b: print('x')</code></pre>")
        == "<pre><code>if a &lt; b: print(&#x27;x&#x27;)</code></pre>"
    )


# ---------- 한계 ----------


def test_extreme_nesting_does_not_crash_or_explode():
    out = clean("<div>" * 5000 + "깊다" + "</div>" * 5000)
    assert "깊다" in out and out.count("<div>") <= 100


def test_a_huge_input_is_cut_instead_of_processed_forever():
    out = clean("<p>가나다</p>" * 200_000)
    assert 0 < len(out) < 1_200_000


def test_empty_and_whitespace_inputs_give_an_empty_result():
    assert clean("") == "" and clean("   \n ") == ""


def test_without_a_base_address_relative_links_are_dropped():
    assert clean('<a href="/x">상대</a><img src="/a.png">', base="") == "상대"


def test_entities_in_text_are_decoded_once_and_escaped_again():
    assert clean("<p>Tom &amp; Jerry &lt;3 &#x1F600;</p>") == "<p>Tom &amp; Jerry &lt;3 😀</p>"


# ---------- 경계 ----------


@pytest.mark.parametrize(
    "href", ["http://[not-an-address/", "https://[::1", "http://a.example.com:99999/x"]
)
def test_an_address_that_cannot_be_parsed_is_dropped_without_raising(href):
    assert clean(f'<a href="{href}">글자</a>') == "글자"


def test_a_very_long_address_is_dropped():
    assert clean('<a href="https://x.example.com/' + "a" * 3000 + '">글자</a>') == "글자"


def test_a_closing_tag_closes_everything_opened_after_its_match():
    assert clean("<div><p><span>a</div>b") == "<div><p><span>a</span></p></div>b"


def test_a_numbered_list_keeps_a_sane_start_value_only():
    assert clean('<ol start="5"><li>a</li></ol>') == '<ol start="5"><li>a</li></ol>'
    assert clean('<ol start="-3"><li>a</li></ol>') == "<ol><li>a</li></ol>"
    assert clean('<ol start="99999"><li>a</li></ol>') == "<ol><li>a</li></ol>"


def test_a_parser_failure_returns_the_safe_part_built_so_far(monkeypatch):
    from rss_hub.domain import sanitize

    def explode(self, data):
        self.handle_data("앞부분")
        raise RuntimeError("parser failure")

    monkeypatch.setattr(sanitize._Cleaner, "feed", explode)
    assert sanitize_html("<p>무엇이든</p>", BASE) == "앞부분"


def test_unclosed_elements_are_closed_at_the_end_of_the_input():
    assert clean("<ul><li>하나<li>둘") == "<ul><li>하나<li>둘</li></li></ul>"


# ---------- 위험한 요소 안쪽, 주소 형식, 제어 문자 ----------


@pytest.mark.security
@pytest.mark.parametrize(
    "href",
    [
        "ftp://x.example.com/f",
        "file://host/etc/passwd",
        "gopher://x.example.com/",
        "javascript://x.example.com/%0aalert(1)",
        "vbscript://x.example.com/",
    ],
)
def test_only_http_and_https_links_are_followed_even_when_the_address_has_a_host(href):
    assert clean(f'<a href="{href}">글자</a>') == "글자"
    assert clean(f'<img src="{href}">') == ""


def test_tags_inside_a_removed_container_vanish_with_it():
    html = '<svg><a href="https://x.example.com/">링크</a><img src="https://x.example.com/a.png"><b>굵게</b></svg>'
    assert clean(f"<p>앞</p>{html}<p>뒤</p>") == "<p>앞</p><p>뒤</p>"
    assert clean('<iframe><p>안쪽</p><a href="https://x.example.com/">x</a></iframe>') == ""


@pytest.mark.security
@pytest.mark.parametrize(
    "html",
    [
        '<a href="https://x.example.com/a\x01b\x7fc">글자</a>',
        '<img src="https://x.example.com/a\x00b.png">',
        '<a href="  https://x.example.com/a b  ">글자</a>',
    ],
)
def test_control_characters_and_spaces_never_end_up_in_an_address(html):
    out = clean(html)
    address = re.search(r'(?:href|src)="([^"]*)"', out)
    assert address and not re.search(r"[\x00-\x20\x7f]", address.group(1))
