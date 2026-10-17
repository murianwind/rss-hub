@scheduling
Feature: 수집 스케줄
  수집 주기마다 한 슬롯씩 실행해서 한 시간 안에 모든 피드를 최소 한 번 점검한다.
  수집 주기는 설정에서 바꿀 수 있고 기본은 5분(시간당 12슬롯)이다.
  활동량이 많은 피드는 여유 용량 안에서 더 자주 점검한다.

  # 태그 규약
  #   @legacy-parity : 기존 스크립트와 같은 결과여야 한다 (골든 데이터로 검증)
  #   @improvement   : 기존 결함/한계를 의도적으로 고친 동작 (docs/01-m1-design.md §11 승인 대상)
  #   @new           : 기존에 없던 동작

  Background:
    Given 서비스 시간대는 "Asia/Seoul"이다
    And 수집 주기는 5분이다
    And 한 슬롯의 기본 배치 크기는 15이다
    # 시간당 슬롯 수 = 60 / 수집 주기. 아래 시나리오의 "12개 슬롯"은 기본 주기(5분) 기준이다

  @SCH-01 @legacy-parity @legacy:rss_collector.build_hourly_schedule
  Scenario: 모든 피드는 한 시간에 최소 한 번 점검된다
    Given 활성 피드 134개가 있다
    When 이번 시간의 스케줄을 만든다
    Then 12개 슬롯에 걸쳐 모든 피드가 1번 이상 포함된다

  @SCH-02 @legacy-parity @legacy:rss_collector.build_hourly_schedule
  Scenario Outline: 피드가 많으면 배치 크기를 늘려 모든 피드를 포함한다
    Given 활성 피드 <feeds>개가 있다
    When 이번 시간의 스케줄을 만든다
    Then 배치 크기는 <batch_size>이다
    And 모든 슬롯의 피드 수는 <batch_size> 이하이다

    Examples:
      | feeds | batch_size |
      | 134   | 15         |
      | 180   | 15         |
      | 181   | 16         |
      | 200   | 17         |

  @SCH-03 @legacy-parity @legacy:rss_collector.desired_checks_per_hour
  Scenario Outline: 활동량에 따라 시간당 목표 점검 횟수가 정해진다
    Given 어떤 피드의 오늘 글 수는 <today>건이고 최근 7일 글 수는 <week>건이다
    Then 이 피드의 시간당 목표 점검 횟수는 <checks>회이다
    And 이 피드의 활동 점수는 <score>이다

    Examples:
      | today | week | checks | score |
      | 0     | 0    | 1      | 0     |
      | 0     | 2    | 2      | 20    |
      | 0     | 6    | 2      | 60    |
      | 1     | 1    | 2      | 110   |
      | 2     | 0    | 2      | 200   |
      | 0     | 7    | 3      | 70    |
      | 3     | 0    | 3      | 300   |

  @SCH-04 @legacy-parity @legacy:rss_collector.build_hourly_schedule
  Scenario: 추가 점검은 여유 용량 안에서 활동 점수가 높은 피드부터 배정된다
    Given 활성 피드 134개가 있고 한 시간 용량은 180회이다
    And 목표 점검 횟수의 합이 용량을 넘을 만큼 활동이 많은 피드가 있다
    When 이번 시간의 스케줄을 만든다
    Then 추가 점검은 46회를 넘지 않는다
    And 추가 점검을 일부라도 받지 못한 피드의 활동 점수는 추가 점검을 모두 받은 어떤 피드의 점수보다도 높지 않다

  @SCH-05 @legacy-parity @legacy:rss_collector.build_hourly_schedule
  Scenario: 같은 피드의 반복 점검은 서로 다른 슬롯에 배치된다
    Given 시간당 3회 점검 대상인 피드가 있다
    When 이번 시간의 스케줄을 만든다
    Then 이 피드는 서로 다른 3개 슬롯에 들어 있다
    And 한 슬롯에 같은 피드가 두 번 들어가지 않는다

  @SCH-06 @improvement @legacy:rss_collector.desired_checks_per_hour
  Scenario: 매 슬롯 점검 피드는 활동 이력이 없어도 12개 슬롯 모두에 들어간다
    # 기존: 활동 통계가 없으면(첫 실행·통계 유실) 1개 슬롯에만 배정되었다
    Given 폴링 우선순위가 "every_slot"인 피드가 1개 있고 활동 통계는 비어 있다
    When 이번 시간의 스케줄을 만든다
    Then 이 피드는 12개 슬롯 모두에 들어 있다

  @SCH-07 @improvement @legacy:rss_collector.build_hourly_schedule
  Scenario: 매 슬롯 점검 피드는 다른 피드의 높은 활동 점수에 밀리지 않는다
    # 기존: 다른 피드의 점수가 더 높으면 여유 용량을 먼저 소진해 1개 슬롯에만 배정되었다
    Given 폴링 우선순위가 "every_slot"인 피드가 1개 있다
    And 다른 모든 피드의 활동 점수가 이 피드보다 높다
    When 이번 시간의 스케줄을 만든다
    Then 이 피드는 12개 슬롯 모두에 들어 있다

  @SCH-08 @improvement
  Scenario: 매 슬롯 점검 피드가 많으면 배치 크기를 늘려 일반 피드의 최소 점검을 보장한다
    Given 폴링 우선순위가 "every_slot"인 피드가 20개 있다
    And 일반 피드가 114개 있다
    When 이번 시간의 스케줄을 만든다
    Then 배치 크기는 30이다
    And "every_slot" 피드 20개는 모두 12개 슬롯에 들어 있다
    And 일반 피드 114개는 모두 1번 이상 점검된다

  @SCH-09 @legacy-parity @legacy:rss_collector.current_slot
  Scenario Outline: 현재 시각의 분과 수집 주기로 슬롯 번호를 정한다
    # 수집 주기 5분 행은 기존 동작과 같다(골든 데이터). 나머지는 같은 규칙(분 ÷ 주기)을 일반화한 것이다
    Given 수집 주기가 <interval>분이다
    When 현재 시각이 14시 <minute>분이다
    Then 슬롯 번호는 <slot>이다

    Examples:
      | interval | minute | slot |
      | 5        | 0      | 0    |
      | 5        | 4      | 0    |
      | 5        | 5      | 1    |
      | 5        | 59     | 11   |
      | 10       | 25     | 2    |
      | 15       | 44     | 2    |
      | 60       | 59     | 0    |

  @SCH-10 @improvement @legacy:rss_collector.get_schedule
  Scenario Outline: 스케줄 입력이 바뀌면 스케줄을 다시 만든다
    # 기존: 시간, 대상 날짜, 피드 "개수"만 비교했다 (개수가 같은 구성 변경은 반영되지 않았다)
    Given 이번 시간의 스케줄이 이미 만들어져 있다
    When <change>
    Then 스케줄을 새로 만든다

    Examples:
      | change                            |
      | 다음 시간이 되었다                |
      | 대상 날짜가 바뀌었다              |
      | 피드가 추가되었다                 |
      | 피드가 삭제되었다                 |
      | 피드의 폴링 우선순위가 바뀌었다   |
      | 피드 개수는 같지만 피드 구성이 바뀌었다 |
      | 수집 주기 설정이 바뀌었다         |

  @SCH-11 @legacy-parity @legacy:rss_collector.get_schedule
  Scenario: 입력이 바뀌지 않으면 만들어 둔 스케줄을 다시 쓴다
    Given 이번 시간의 스케줄이 이미 만들어져 있다
    When 같은 시간 안에서 다음 슬롯을 실행한다
    Then 스케줄을 새로 만들지 않는다

  @SCH-12 @new
  Scenario: 이전 실행이 끝나지 않았으면 다음 슬롯 실행은 건너뛴다
    Given 수집 작업이 아직 실행 중이다
    When 다음 슬롯 시각이 된다
    Then 수집 작업은 겹쳐 실행되지 않는다
    And 건너뛴 사실이 기록된다

  @SCH-13 @legacy-parity
  Scenario: 서비스가 멈춰 있던 동안 지나간 슬롯은 따라잡지 않는다
    Given 서비스가 14시 00분부터 14시 20분까지 꺼져 있었다
    When 14시 20분에 서비스가 다시 시작된다
    Then 14시 20분 슬롯만 실행된다
    And 14시 00분부터 14시 15분까지의 슬롯은 실행되지 않는다

  @SCH-14 @new
  Scenario Outline: 수집 주기에 따라 시간당 슬롯 수와 배치 크기가 정해진다
    # 한 시간에 모든 피드를 최소 한 번 점검해야 하므로 주기가 길수록 한 번에 더 많이 점검한다
    Given 수집 주기가 <interval>분이고 활성 피드 134개가 있다
    When 이번 시간의 스케줄을 만든다
    Then 시간당 슬롯 수는 <slots>이다
    And 배치 크기는 <batch_size>이다
    And 모든 피드가 1번 이상 점검된다

    Examples:
      | interval | slots | batch_size |
      | 1        | 60    | 15         |
      | 5        | 12    | 15         |
      | 10       | 6     | 23         |
      | 15       | 4     | 34         |
      | 30       | 2     | 67         |
      | 60       | 1     | 134        |

  @SCH-15 @new
  Scenario Outline: 수집 잡은 시각의 분이 수집 주기의 배수일 때 실행한다
    # 슬롯 번호(분 ÷ 주기)와 실제 실행 시각이 어긋나지 않게 하려는 것이다
    Given 수집 주기가 <interval>분이다
    When 14시 한 시간 동안의 수집 실행 시각을 계산한다
    Then 실행은 <count>번이고 첫 시각은 14:00, 마지막 시각은 <last>이다
    And 모든 실행 시각의 분은 수집 주기의 배수이다

    Examples:
      | interval | count | last  |
      | 5        | 12    | 14:55 |
      | 10       | 6     | 14:50 |
      | 30       | 2     | 14:30 |
      | 60       | 1     | 14:00 |
