@collection
Feature: 수집과 필터
  슬롯에 배정된 피드를 가져와서 "오늘 발행된 새 글"만 대기열에 넣는다.
  이미 발송했거나 대기열에 있는 글은 날짜와 상관없이 다시 넣지 않는다.

  Background:
    Given 서비스 시간대는 "Asia/Seoul"이다
    And 오늘은 "2026-10-16"이다
    And 피드당 최대 검사 항목 수 기본값은 50이다

  # ---------- 날짜 필터 ----------

  @COL-01
  Scenario: 오늘 발행된 글만 수집한다
    Given 피드에 오늘 발행된 글 2개와 어제 발행된 글 1개가 있다
    When 이 피드를 점검한다
    Then 오늘 발행된 글 2개가 수집 대기열에 들어간다
    And 어제 발행된 글은 들어가지 않는다

  @COL-02
  Scenario: 발행 시각을 알 수 없는 글은 수집하지 않는다
    Given 피드에 발행 시각이 없는 글이 있다
    When 이 피드를 점검한다
    Then 그 글은 수집 대기열에 들어가지 않는다

  @COL-03
  Scenario Outline: 발행 시각 문자열을 서비스 시간대로 해석한다
    Given 글의 발행 시각 문자열이 "<published>"이다
    When 발행 시각을 해석한다
    Then 서비스 시간대 기준 시각은 "<local>"이다

    Examples:
      | published                         | local                     |
      | Fri, 16 Oct 2026 01:30:00 +0900   | 2026-10-16T01:30:00+09:00 |
      | Fri, 16 Oct 2026 01:30:00 GMT     | 2026-10-16T10:30:00+09:00 |
      | 2026-10-16T01:30:00Z              | 2026-10-16T10:30:00+09:00 |
      | 2026-10-16T01:30:00               | 2026-10-16T01:30:00+09:00 |
      | Fri, 16 Oct 2026 01:30:00         | 2026-10-16T01:30:00+09:00 |

  @COL-04
  Scenario: 피드 파서가 해석한 발행 시각을 문자열보다 우선한다
    Given 글에 파서가 해석한 발행 시각이 UTC 2026-10-15 16:30:00으로 있다
    And 같은 글의 발행 시각 문자열은 "Fri, 16 Oct 2026 23:00:00 +0900"이다
    When 발행 시각을 해석한다
    Then 서비스 시간대 기준 시각은 "2026-10-16T01:30:00+09:00"이다

  @COL-05
  Scenario: 발행 시각이 없으면 수정 시각을 사용한다
    Given 글에 발행 시각은 없고 파서가 해석한 수정 시각이 UTC 2026-10-16 00:05:00으로 있다
    When 발행 시각을 해석한다
    Then 서비스 시간대 기준 시각은 "2026-10-16T09:05:00+09:00"이다

  @COL-06
  Scenario Outline: 해석할 수 없는 발행 시각은 없는 것으로 취급한다
    Given 글의 발행 시각 문자열이 "<published>"이다
    When 발행 시각을 해석한다
    Then 발행 시각은 알 수 없음이다

    Examples:
      | published   |
      | not a date  |
      |             |

  @COL-07
  Scenario: 컨테이너의 시스템 시간대가 UTC여도 "오늘"은 서비스 시간대로 판단한다
    # "오늘"은 컨테이너(프로세스)의 시간대가 아니라 설정의 서비스 시간대로 판단한다.
    # 컨테이너에는 TZ 같은 환경 변수를 따로 주지 않아도 된다
    Given 컨테이너 시스템 시간대는 UTC이다
    And 피드에 UTC 2026-10-15 16:30:00에 발행된 글이 있다
    When 이 피드를 점검한다
    Then 그 글의 발행일은 "2026-10-16"이다
    And 그 글은 수집 대기열에 들어간다

  # ---------- GUID와 중복 ----------

  @COL-08
  Scenario Outline: 글의 고유 식별자(GUID)는 정해진 우선순위로 고른다
    Given 글에 <fields>가 있다
    When 글의 GUID를 정한다
    Then GUID는 "<guid>"이다

    Examples:
      | fields                                                  | guid                                     |
      | id "https://x.com/a?trackingCode=1"                     | https://x.com/a                          |
      | guid "g1"                                               | g1                                       |
      | link "https://x.com/l?fromRss=true"                     | https://x.com/l                          |
      | 제목 "t"와 요약 "s"만                                   | 4402abb98f9559cbfb6d73029f928227b498069b |

  @COL-09
  Scenario Outline: 추적용 파라미터를 제거해 같은 글을 같은 GUID로 만든다
    When GUID "<raw>"를 정규화한다
    Then 결과는 "<normalized>"이다

    Examples:
      | raw                                                                  | normalized                                  |
      | https://blog.naver.com/abc/123?fromRss=true&trackingCode=rss         | https://blog.naver.com/abc/123              |
      | https://blog.naver.com/abc/123?fromRss=true&trackingCode=rss&x=1     | https://blog.naver.com/abc/123?x=1          |
      | https://example.com/p?a=1&a=2                                        | https://example.com/p?a=1                   |
      | https://example.com/p?q=hello world&z=%EA%B0%80                      | https://example.com/p?q=hello+world&z=%EA%B0%80 |
      | tag:example.com,2026:post-1                                          | tag:example.com,2026:post-1                 |
      | https://example.com/post#frag                                        | https://example.com/post#frag               |

  @COL-10
  Scenario: 이미 정규화한 GUID를 다시 정규화해도 값이 같다
    Given 위 정규화 예시의 모든 입력이 있다
    When 각 입력을 두 번 정규화한다
    Then 한 번 정규화한 결과와 두 번 정규화한 결과가 모두 같다

  @COL-11
  Scenario: 이미 발송한 글은 발행일이 오늘이어도 다시 수집하지 않는다
    Given GUID "g-100"인 글은 이미 발송되었다
    And 피드에 오늘 발행된 GUID "g-100" 글이 있다
    When 이 피드를 점검한다
    Then 수집 대기열에 새로 들어가는 글은 없다

  @COL-12
  Scenario: 이미 대기열에 있는 글은 중복으로 넣지 않는다
    Given GUID "g-200"인 글이 이미 수집 대기열에 있다
    And 피드에 오늘 발행된 GUID "g-200" 글이 있다
    When 이 피드를 점검한다
    Then 대기열의 "g-200" 글은 1개뿐이다

  @COL-13
  Scenario: 서로 다른 피드가 같은 GUID의 글을 주면 한 번만 수집한다
    Given 피드 A와 피드 B가 같은 GUID "g-300"의 글을 오늘 발행했다
    When 두 피드를 같은 슬롯에서 점검한다
    Then 대기열의 "g-300" 글은 1개뿐이다

  # ---------- 한 번에 읽는 양 ----------

  @COL-14
  Scenario Outline: 피드에서 앞쪽 N개 항목만 검사한다
    Given 피드에 오늘 발행된 글이 80개 있고 이 피드의 최대 검사 항목 수는 <max_entries>이다
    When 이 피드를 점검한다
    Then 수집 대기열에 들어가는 글은 <collected>개이다

    Examples:
      | max_entries | collected |
      | 50          | 50        |
      | 120         | 80        |

  @COL-15
  Scenario: 점검할 때마다 피드의 활동 통계를 갱신한다
    Given 피드에 오늘 발행된 글 2개, 3일 전 글 1개, 10일 전 글 1개가 있다
    When 이 피드를 점검한다
    Then 최근 7일 글 수는 3이다
    And 오늘 글 수는 2이다
    And 가장 최근 발행 시각이 기록된다

  @COL-16
  Scenario: 수집한 글은 피드가 준 본문 요약을 HTML 그대로 보관한다
    Given 피드의 글에 HTML이 포함된 요약이 있다
    When 이 피드를 점검한다
    Then 대기열의 글에 요약 HTML이 가공 없이 보관된다
    And 글의 상태는 "collected"이다

  # ---------- 새 피드 ----------

  @COL-17
  Scenario: 새로 등록한 피드의 첫 점검은 기존 글을 알림 없이 기록만 한다
    Given 상태가 "baseline_pending"인 새 피드에 오늘 발행된 글 30개가 있다
    When 이 피드를 처음 점검한다
    Then 30개 글의 GUID가 "이미 본 글"로 기록된다
    And 수집 대기열에는 들어가지 않는다
    And 피드 상태는 "active"가 된다

  @COL-18
  Scenario: 기준선을 잡은 뒤에 올라온 새 글은 정상적으로 수집한다
    Given 새 피드의 기준선이 이미 기록되어 있다
    And 그 뒤에 오늘 발행된 새 글이 올라왔다
    When 이 피드를 점검한다
    Then 새 글은 수집 대기열에 들어간다

  # ---------- 오류와 효율 ----------

  @COL-19
  Scenario: 피드 하나가 실패해도 같은 슬롯의 나머지 피드는 계속 점검한다
    Given 슬롯에 피드 A, B, C가 있고 B는 시간 초과로 실패한다
    When 슬롯을 실행한다
    Then A와 C의 새 글은 수집된다
    And B는 실패한 피드로 기록되고 오류 종류가 남는다

  @COL-20
  Scenario: 피드 점검이 성공하면 연속 실패 횟수를 0으로 되돌린다
    Given 피드 B의 연속 실패 횟수가 3이다
    When 피드 B 점검이 성공한다
    Then 피드 B의 연속 실패 횟수는 0이다

  @COL-21
  Scenario: 서버가 변경 없음(304)으로 답하면 내용을 다시 해석하지 않는다
    Given 피드에 이전 응답의 ETag가 저장되어 있다
    And 서버가 304 Not Modified로 응답한다
    When 이 피드를 점검한다
    Then 피드 내용은 해석하지 않는다
    And 점검은 성공으로 기록된다

  @COL-22
  Scenario: 응답이 없는 피드는 제한 시간 뒤 실패로 처리한다
    Given 피드 서버가 연결은 되지만 응답하지 않는다
    When 이 피드를 점검한다
    Then 점검은 읽기 제한 시간 안에 실패로 끝난다
    And 서비스 전체는 멈추지 않는다

  @COL-23
  Scenario: 피드가 아닌 응답은 빈 피드가 아니라 실패로 기록한다
    # 배경(이전 스크립트의 동작): HTML 페이지 같은 응답도 "글이 0개인 피드"로 보고 영원히 성공으로 처리했다
    Given 피드 서버가 HTML 페이지를 돌려준다
    When 이 피드를 점검한다
    Then 점검은 "NotAFeed"로 실패로 기록된다
    And 피드의 연속 실패 횟수는 1이다

  @COL-24
  Scenario: 응답이 크기 제한을 넘으면 읽지 않고 실패로 기록한다
    Given 피드 서버가 제한(5MB)을 넘는 크기의 응답을 돌려준다
    When 이 피드를 점검한다
    Then 점검은 "TooLarge"로 실패로 기록된다
    And 피드의 연속 실패 횟수는 1이다
