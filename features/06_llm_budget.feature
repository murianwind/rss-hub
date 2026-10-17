@llm
Feature: LLM 호출 예산과 모델 체인
  OpenRouter 무료 모델은 요청 수로 제한된다(분당 20회, 하루 50회 또는 1,000회).
  운영 호출이 하루 한도를 다 쓰지 않도록 가드를 두고, 모델이 막히면 다음 모델로 넘어간다.

  Background:
    # 아래 값은 모두 설정(UI)에서 바꿀 수 있고, 적힌 값은 기본값이다
    Given 모델 체인은 "model-a", "model-b" 순서이다
    And 하루 운영 호출 상한은 700회이고 경고 비율은 80%이다
    And 분당 호출 상한은 15회이다

  # 하루의 경계: OpenRouter가 일일 사용량을 UTC 기준으로 집계하는 것으로 보인다(공식 문서의
  # usage_daily는 "current UTC day"). 구현 첫 스파이크에서 실제 응답으로 확인한다. (docs/01 §13)

  @BUD-01 @legacy-parity @legacy:rss_llm.summarize_item
  Scenario: 모델 체인 순서대로 시도하고 처음 성공한 응답을 쓴다
    Given "model-a"가 오류로 실패하고 "model-b"가 성공한다
    When LLM에 요청한다
    Then "model-a"를 먼저 호출한 뒤 "model-b"를 호출한다
    And 응답과 함께 "model-b" 사용 기록이 반환된다

  @BUD-02 @legacy-parity @legacy:rss_llm.summarize_item
  Scenario: 한도 초과(429)는 Retry-After만큼(최대 30초) 기다려 같은 모델에 한 번 더 시도한다
    Given "model-a"가 429와 Retry-After 40초로 답하고, 기다린 뒤 다시 시도하면 성공한다
    When LLM에 요청한다
    Then 대기 시간은 30초로 제한된다
    And "model-a"로 한 번 더 요청한다
    And "model-b"는 호출하지 않는다

  @BUD-03 @legacy-parity @legacy:rss_llm.summarize_item
  Scenario: 재시도에도 실패하면 다음 모델로 넘어간다
    Given "model-a"가 두 번 연속 429로 답한다
    When LLM에 요청한다
    Then "model-b"를 호출한다

  @BUD-04 @new
  Scenario: 체인의 모든 모델이 응답하지 못하면 "장애" 신호를 올린다
    Given "model-a"와 "model-b"가 모두 실패한다
    When LLM에 요청한다
    Then 호출자는 "장애"를 받는다
    And 잘못된 응답이 아니라 호출 자체의 실패로 구분된다

  # ---------- 호출 수 기록과 가드 ----------

  @BUD-05 @new
  Scenario: 호출 한 번마다 모델, 성공 여부, 날짜별 횟수를 기록한다
    Given 모델 체인에는 "model-a"만 있다
    When LLM에 3번 요청해서 2번 성공하고 1번 실패한다
    Then 오늘 호출 수는 3이다
    And 모델별 성공과 실패가 따로 기록된다

  @BUD-06 @new
  Scenario: 실패한 호출도 한도를 쓴 것으로 센다
    # 실패 요청도 하루 한도에 포함될 수 있다는 보고가 있어 보수적으로 센다 (공식 문서로 미확인)
    Given 모델 체인에는 "model-a"만 있다
    And 오늘 호출 수는 10이다
    When 호출이 429로 실패하고 기다린 뒤 다시 시도한 호출은 성공한다
    Then 오늘 호출 수는 12이다

  @BUD-07 @new
  Scenario: 상한의 80%에 도달하면 시스템 알림을 하루에 한 번만 보낸다
    Given 오늘 호출 수는 559이다
    When 호출이 1번 더 일어난다
    Then 시스템 웹훅으로 "호출 80% 도달" 알림이 1번 간다
    When 호출이 5번 더 일어난다
    Then 같은 알림은 다시 가지 않는다

  @BUD-08 @new
  Scenario: 상한에 도달하면 새 호출을 멈추고 글은 대기시킨다
    Given 오늘 호출 수는 700이다
    And 요약 대상 글이 있다
    When 요약 작업을 실행한다
    Then LLM 호출은 일어나지 않는다
    And 글의 재시도 횟수는 늘지 않는다
    And 시스템 웹훅으로 "호출 상한 도달" 알림이 1번 간다

  @BUD-09 @new
  Scenario: 날짜가 바뀌면 호출 수를 0부터 다시 센다
    Given 오늘 호출 수는 700이고 상한에 도달해 있다
    When UTC 날짜가 바뀐다
    Then 오늘 호출 수는 0이다
    And 요약 작업은 다시 호출할 수 있다

  @BUD-10 @new
  Scenario: 1분 안에 보내는 호출은 분당 상한을 넘지 않는다
    Given 요약 대상 글이 30개 있고 모두 즉시 응답한다
    When 1분 동안 요약 작업을 반복 실행한다
    Then 그 1분 동안의 LLM 호출은 15번 이하이다

  # ---------- 오류와 비밀 ----------

  @BUD-11 @new
  Scenario: 잔액이 음수라서 402로 답하면 시스템 알림을 보내고 장애로 취급한다
    Given 모든 모델이 402로 답한다
    When LLM에 요청한다
    Then 호출자는 "장애"를 받는다
    And 시스템 웹훅으로 "잔액 확인 필요" 알림이 1번 간다

  @BUD-12 @new
  Scenario: 같은 종류의 시스템 알림은 쿨다운 동안 반복하지 않는다
    Given "호출 상한 도달" 알림을 방금 보냈다
    When 같은 상황이 계속 감지된다
    Then 쿨다운이 끝나기 전에는 같은 알림을 다시 보내지 않는다

  @BUD-13 @new
  Scenario: 모델 체인은 코드가 아닌 설정 데이터에서 읽는다
    Given 설정의 모델 체인을 "model-c"로 바꾼다
    When LLM에 요청한다
    Then "model-c"를 호출하고 "model-a"는 호출하지 않는다

  @BUD-14 @new
  Scenario: 상한 설정을 바꾸면 재시작 없이 바로 적용된다
    Given 오늘 호출 수는 700이고 상한에 도달해 있다
    When 하루 운영 호출 상한을 800으로 바꾼다
    Then 요약 작업은 다시 호출할 수 있다

  # ---------- 서버가 알려 주는 남은 호출 수 ----------
  # OpenRouter 키 정보(/api/v1/key)의 free_model_daily_requests는 이 키의 하루 무료 호출 한도와 사용량을 알려 준다.
  # 같은 키를 쓰는 다른 프로그램(기존 크론 등)이 쓴 호출도 포함되므로, 우리 서비스가 센 값만으로는 모자란다.
  # 이 조회는 채팅 호출이 아니라서 호출 한도를 쓰지 않는다.

  @BUD-15 @new
  Scenario: 서버가 알려 준 남은 호출 수가 예비분 이하이면 새 호출을 멈춘다
    Given 서버가 알려 준 오늘 사용량은 985, 한도는 1000이다
    And 예비 호출 수는 20이다
    And 우리 서비스가 센 오늘 호출 수는 10이다
    And 요약 대상 글이 있다
    When 요약 작업을 실행한다
    Then LLM 호출은 일어나지 않는다
    And 글의 재시도 횟수는 늘지 않는다
    And 시스템 웹훅으로 "서버 한도 임박" 알림이 1번 간다

  @BUD-16 @new
  Scenario: 서버가 알려 주는 값을 가져오지 못하면 우리 서비스의 기록만으로 판단한다
    Given 서버의 키 정보 조회가 실패한다
    And 우리 서비스가 센 오늘 호출 수는 10이다
    And 요약 대상 글이 있다
    When 요약 작업을 실행한다
    Then LLM 호출은 정상적으로 일어난다

  @BUD-17 @new
  Scenario: 서버가 알려 준 값은 5분 동안 다시 조회하지 않고 쓴다
    Given 서버가 알려 준 오늘 사용량은 100, 한도는 1000이다
    And 요약 대상 글이 있다
    # 각 실행 직전에 새 글이 하나씩 수집된다
    When 요약 작업을 실행하고 4분 뒤에 다시 실행한다
    Then 서버 키 정보 조회는 1번이다
    When 6분이 더 지난 뒤 요약 작업을 실행한다
    Then 서버 키 정보 조회는 2번이다
    And 키 정보 조회는 우리 서비스의 호출 수에 포함되지 않는다
