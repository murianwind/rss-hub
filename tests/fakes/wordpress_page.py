"""워드프레스 글 견본: 제목, 문장 부호 없는 목록, 주소 줄과 피드의 자동 문구가 든 RSS 본문."""

# ruff: noqa: E501  (HTML 견본은 한 줄이 읽기 쉽다)

WP_BODY = (
    '<div class="wp-block-group"><div class="wp-block-group__inner-container">'
    '<figure class="wp-block-image"><img src="https://jv.example.com/a.webp" alt="로봇"/></figure>'
    '<p class="wp-block-paragraph">최근 1년간 다양한 생성형 AI를 이용하면서 느낀 점은<br>'
    "AI의 진정한 가치는 단순한 생성이 아닌<br><strong>생성+편집+제어</strong>에서 만들어진다는 것입니다.</p>"
    '<p class="wp-block-paragraph">즉, AI가 만들어낸 1차적 생성물을<br>사용자가 수정하고 편집해서<br>'
    "원하는 방향으로 조정할 수 있을 때<br>더 큰 가치가 만들어지게 됩니다.</p>"
    "<h2>[프롬프트]</h2><ul>"
    "<li>로봇 SVG 파일을 받았다. 보이냐?</li>"
    "<li>파일을 열어서 로봇이 어떤 구조로 되어 있는지 분석해 줘</li>"
    "<li>로봇을 분리해서 부품별 이름과 관절 회전 중심을 설정한 애니메이션용 SVG 파일을 만들어 줘.</li>"
    "<li>이 로봇이 다양한 행동을 하는 애니메이션을 만들어줘.</li>"
    "<li>AWS에 배포하고 URL 알려줘</li></ul>"
    '<h2>[웹에서 보기]</h2><p><a href="https://jv.example.org/2D/Robot/">https://jv.example.org/2D/Robot/</a></p>'
    '<p class="wp-block-paragraph">비전공자도 생성은 할 수 있지만<br>전공자는 편집+제어를 할 수 있기 때문에<br>'
    "전공자의 생성형 AI 활용이 더 큰 가치를 만들어 낼 수 있습니다.</p>"
    "<h2>[1줄 요약]</h2><p><strong>생성형 AI의 진정한 가치는<br>생성 이후에 만들어진다.</strong></p>"
    "</div></div>"
)
WP_FOOTER = (
    '<p>The post <a href="https://jv.example.com/blog/p/1">생성형 AI의 가치는 생성 이후에 만들어진다</a> '
    'appeared first on <a href="https://jv.example.com/blog">Jinho&#039;s AI Studio</a>.</p>'
)
