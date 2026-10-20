@m5
Feature: 주제 피드백(M5): 싫어요, 주제로, 키워드 개선 제안

  주제 분류가 틀렸을 때 글 페이지의 버튼으로 바로잡을 수 있어야 한다. 싫어요는 그 주제 목록에서만 글을 빼고
  원래 목록에는 그대로 남긴다. 주제로는 글을 그 주제에 넣는다. 누른 기록은 키워드 개선 제안의 근거가 되고,
  제안은 사용자가 승인해야 반영된다. LLM을 학습시키는 것이 아니라, 판정을 즉시 바로잡고 키워드와 요청의
  예시를 고치는 방식이다.

  Background:
    Given 사이트 "자유 블로그"와 주제 "OTT"(키워드 "netflix"), 주제 "게임"(키워드 "steam")이 있다

  # ---------- 싫어요와 주제로 ----------

  @FBK-01 @new
  Scenario: 싫어요는 그 주제 목록에서만 글을 빼고 다른 목록에는 남긴다
    Given 주제 "OTT"로 분류된 글 "Netflix stock falls"가 있다
    When 그 글에 주제 "OTT"의 싫어요를 누른다
    Then 주제 "OTT" 목록에는 그 글이 없다
    And 전체 목록과 사이트 "자유 블로그" 목록에는 그 글이 그대로 있다

  @FBK-02 @new
  Scenario: 싫어요는 되돌릴 수 있다
    Given 주제 "OTT"로 분류된 글 "Netflix stock falls"가 있다
    And 그 글에 주제 "OTT"의 싫어요를 눌렀다
    When 그 글에 주제 "OTT"의 되돌리기를 누른다
    Then 주제 "OTT" 목록에 그 글이 다시 있다

  @FBK-03 @new
  Scenario: 주제로는 키워드와 LLM 판정과 상관없이 글을 그 주제에 넣는다
    Given 어느 주제에도 속하지 않은 글 "Stream night"가 있다
    When 그 글에 주제 "OTT"의 주제로를 누른다
    Then 주제 "OTT" 목록에 그 글이 있다
    And 글 페이지에는 주제 "OTT"의 싫어요 버튼이 보인다

  @FBK-04 @new
  Scenario Outline: 아직 알림을 보내지 않은 글은 사용자의 선택대로 주제 웹훅으로 간다
    Given 아직 보내지 않은 글 "<title>"이 있다(요약 단계에서 주제 "OTT"로 판정됨 <judged>)
    And 사용자가 그 글에 주제 "OTT"의 <action>를 눌렀다
    When 발송 작업이 실행된다
    Then 기본 웹훅으로는 나가고 주제 "OTT" 웹훅으로는 <topic_result>

    Examples:
      | title           | judged | action  | topic_result |
      | Netflix movie   | 예     | 싫어요   | 나가지 않는다  |
      | Netflix movie   | 예     | (안 누름) | 나간다       |
      | Totally unrelated | 아니오 | 주제로   | 나간다       |
      | Totally unrelated | 아니오 | (안 누름) | 나가지 않는다 |

  @FBK-05 @new
  Scenario: 이미 보낸 글에 주제로를 눌러도 알림을 다시 보내지 않는다
    Given 이미 기본 웹훅으로 보낸 글 "Totally unrelated"가 있다
    When 그 글에 주제 "OTT"의 주제로를 누른다
    And 발송 작업이 실행된다
    Then 주제 "OTT" 웹훅으로는 아무것도 나가지 않는다
    And 주제 "OTT" 목록에는 그 글이 있다

  @FBK-06 @new
  Scenario: 자동 판정이 다시 기록되어도 사용자의 선택은 유지된다
    Given 주제 "OTT"로 분류된 글 "Netflix stock falls"가 있다
    And 그 글에 주제 "OTT"의 싫어요를 눌렀다
    When 요약 단계가 같은 글을 주제 "OTT"로 다시 판정해 기록한다
    Then 주제 "OTT" 목록에는 그 글이 없다

  # ---------- 키워드 개선 제안 ----------

  @FBK-07 @new
  Scenario: 주제로를 여러 번 누른 글들의 공통 단어를 키워드로 더하자고 제안한다
    Given 어느 주제에도 속하지 않은 글 "Squid Game trailer"가 있다
    And 어느 주제에도 속하지 않은 글 "Squid Game cast"가 있다
    And 두 글에 주제 "OTT"의 주제로를 눌렀다
    When 주제 "OTT"의 키워드 개선 제안을 연다
    Then "squid"를 키워드에 추가하자는 제안이 근거 글과 함께 보인다

  @FBK-08 @new
  Scenario: 싫어요가 쌓인 키워드는 빼도록 제안한다
    Given 키워드 "netflix"로 주제 "OTT"에 들어온 글 2개에 싫어요를 눌렀다
    When 주제 "OTT"의 키워드 개선 제안을 연다
    Then "netflix"를 키워드에서 빼자는 제안이 "2개를 싫어요로 뺌"이라는 근거와 함께 보인다

  @FBK-09 @new
  Scenario: 제안은 승인해야 반영되고, 마지막 키워드는 지울 수 없다
    When 주제 "OTT"의 제안에서 "squid"를 키워드에 추가한다
    Then 주제 "OTT"의 키워드는 "netflix", "squid"이다
    When 주제 "OTT"의 제안에서 "squid"를 키워드에서 뺀다
    And 주제 "OTT"의 제안에서 "netflix"를 키워드에서 뺀다
    Then 마지막 키워드는 지울 수 없다는 안내가 보이고 키워드는 "netflix" 하나로 남는다

  # ---------- 요청의 예시 ----------

  @FBK-10 @new
  Scenario Outline: 사용자가 확인한 예시는 설정한 개수만큼 후보 주제에만 요청에 들어간다
    Given 주제 "OTT"에 직접 넣은 글 3개와 싫어요로 뺀 글 3개가 있다
    And 요약 요청에 넣을 예시 수 설정은 <count>이다
    And 제목에 "Netflix"가 있는 영문 글이 수집되어 있다
    When 요약 작업을 실행한다
    Then 요청에는 "직접 넣은 글" 예시 <expected>개와 "싫어요로 뺀 글" 예시 <expected>개가 들어 있다

    Examples:
      | count | expected |
      | 0     | 0        |
      | 1     | 1        |
      | 2     | 2        |

  # ---------- 보안 ----------

  @FBK-11 @new
  Scenario Outline: 버튼을 누른 뒤 돌아갈 곳은 이 서비스의 읽기 화면만 허용한다
    Given 어느 주제에도 속하지 않은 글 "Stream night"가 있다
    When 돌아갈 곳을 "<target>"로 지정해서 그 글에 주제 "OTT"의 주제로를 누른다
    Then 돌아가는 곳은 "<result>"이다

    Examples:
      | target                      | result            |
      | /reader/topic/1             | /reader/topic/1   |
      | https://evil.example.com/   | 그 글의 페이지    |
      | //evil.example.com/         | 그 글의 페이지    |
      | /settings                   | 그 글의 페이지    |

  @FBK-12 @new
  Scenario: 다른 사이트에서 온 버튼 요청은 거부한다
    Given 어느 주제에도 속하지 않은 글 "Stream night"가 있다
    When 다른 사이트에서 그 글에 주제 "OTT"의 주제로 요청을 보낸다
    Then 요청은 거부되고 글은 주제에 들어가지 않는다
