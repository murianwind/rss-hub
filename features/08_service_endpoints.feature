@service
Feature: 서비스 상태와 임시 글 링크
  M1에는 글 뷰어가 없다. Discord 메시지의 서비스 링크는 임시로 원문으로 이동시키고(M4에서 뷰어로 교체),
  컨테이너 상태 확인과 운영 점검에 필요한 최소 엔드포인트만 둔다.
  설정과 피드 가져오기 화면은 09_settings, 07_feed_import에서 다룬다.
  (SVC-08, SVC-09는 환경 변수 방식이 사라지면서 09_settings의 SET-01, SET-02 등으로 옮겼다)

  # ---------- 상태 확인 ----------

  @SVC-01
  Scenario: 스케줄러가 정상이면 /healthz는 200으로 답한다
    Given 마지막 수집이 3분 전에 성공했다
    When "/healthz"를 요청한다
    Then 상태 코드는 200이다
    And 본문에 마지막 수집, 요약, 발송 시각과 "ok"가 있다

  @SVC-02
  Scenario: 수집이 오래 멈춰 있으면 /healthz는 503으로 답한다
    # Docker 헬스체크가 이 값을 보고 컨테이너를 비정상으로 표시한다
    Given 마지막 수집이 16분 전이다
    When "/healthz"를 요청한다
    Then 상태 코드는 503이다
    And 본문의 상태는 "stale"이다

  @SVC-03
  Scenario: /status는 대기 글 수, 오늘 호출 수, 최근 실패 피드를 보여 준다
    Given 대기 글 4개, 오늘 LLM 호출 120회, 실패 피드 2개가 있다
    When "/status"를 요청한다
    Then 본문에 이 숫자들이 있다

  @SVC-04
  Scenario: 상태 응답에는 비밀 값이 들어 있지 않다
    When "/healthz"와 "/status"를 요청한다
    Then 웹훅 주소, API 키, 환경 변수 원본 값은 어디에도 없다

  # ---------- 임시 글 링크 ----------

  @SVC-05
  Scenario: /a/{id}/original은 글의 원문 주소로 이동시킨다(글 페이지는 /a/{id}, 뷰어 시나리오 참고)
    Given 글 123의 원문 주소는 "https://example.com/original"이다
    When "/a/123/original"을 요청한다
    Then 상태 코드는 302이다
    And 이동 주소는 "https://example.com/original"이다

  @SVC-06
  Scenario: 없는 글이면 404로 답한다
    When "/a/999999/original"를 요청한다
    Then 상태 코드는 404이다

  @SVC-07
  Scenario Outline: 원문 주소가 http, https가 아니면 이동시키지 않는다
    Given 글 124의 원문 주소는 "<link>"이다
    When "/a/124/original"를 요청한다
    Then 상태 코드는 404이다

    Examples:
      | link                      |
      | javascript:alert(1)       |
      | file:///etc/passwd        |
      | data:text/html,hello      |

  # ---------- 시작과 종료 ----------

  @SVC-10
  Scenario: 종료 신호를 받으면 진행 중인 발송을 끝내고 멈춘다
    Given 발송 작업이 한창 진행 중이다
    When 서비스가 종료 신호를 받는다
    Then 이미 Discord로 나간 글은 발송 완료로 기록된다
    And 아직 보내지 않은 글은 "ready"로 남는다
