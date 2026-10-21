"""vulture(make deadcode)가 사용처를 찾지 못하지만 실제로는 쓰이는 이름.

vulture는 src/의 파이썬 코드만 읽는다. 아래 이름은 템플릿, 프레임워크, 시험이 읽는 것이라 그대로 둔다.
새 이름을 여기에 더할 때는 누가 읽는지 한 줄로 적는다.
"""

# Jinja 템플릿이 읽는다
_.new_count
keyword_hits
matched
llm_called
feed_count
today_count
feed_name
bookmarked
keep_unread
has_next
last_error
unlinked_webhooks  # backup_result.html
help  # SettingDef.help: _ui.html이 입력 칸 설명으로 보여 준다
plain  # 요약 보고서의 필드(시험이 단언한다)

# uvicorn이 "rss_hub.main:create_service_app --factory"로 불러온다
create_service_app

# 시험이 앱에서 설정 서비스를 꺼내 쓴다(app.state는 확장 지점이다)
_.settings_service

# 서비스 실행 결과(보고서)와 저장소 행 객체의 필드: 시험과 BDD 시나리오가 단언한다
archived
schedule_rebuilt
considered
waiting_for_base_url
waiting_for_setup
llm_model
read_at
attempts
sent_at
last_finished_at
last_skipped_at
first_seen_at
last_seen_at
finished_at
