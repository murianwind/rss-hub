@delivery
Feature: Discord 알림 발송
  요약이 끝난 글을 웹훅으로 보낸다. 보낼 웹훅은 "피드 → 카테고리 → 기본" 순서로 정하고,
  OTT 글은 그 웹훅에 더해 OTT 웹훅으로도 보낸다.
  메시지에는 서비스 글 링크만 넣고, 원문 링크는 뷰어 화면에만 둔다.

  Background:
    Given 서비스 시간대는 "Asia/Seoul"이다
    And 설정의 서비스 주소는 "https://rss.example.com"이다
    And 설정에 기본 웹훅 "rss", 웹훅 "ott", "gizmodo", "dev"가 등록되어 있다

  # ---------- 라우팅 ----------

  @DLV-01 @new
  Scenario Outline: 발송할 웹훅은 피드 웹훅, 카테고리 웹훅, 기본 웹훅 순서로 정한다
    # 피드 웹훅은 카테고리에 속하지 않은 피드에만 지정할 수 있다. 지정한 웹훅으로 가면 기본 웹훅에서는 빠진다
    Given 피드의 웹훅 지정은 <feed_webhook>이고 카테고리의 웹훅 지정은 <category_webhook>이다
    And 글은 어떤 주제에도 해당하지 않는다
    When 발송 대상을 정한다
    Then 발송 대상은 "<target>" 웹훅 하나이다

    Examples:
      | feed_webhook | category_webhook | target  |
      | gizmodo      | 없음             | gizmodo |
      | 없음         | dev              | dev     |
      | 없음         | 없음             | rss     |

  @DLV-02 @legacy-parity @legacy:rss_gizmodo_reporter.main
  Scenario: 주제에 해당하는 글은 기본 대상에 더해 주제 웹훅으로도 보낸다
    Given 카테고리의 웹훅 지정은 gizmodo이다
    And 글은 주제 "OTT"에 해당한다
    When 발송 대상을 정한다
    Then 발송 대상은 "gizmodo"와 "ott" 두 곳이다

  @DLV-03 @new
  Scenario: 기본 대상이 주제 웹훅과 같으면 한 번만 보낸다
    Given 카테고리의 웹훅 지정은 ott이다
    And 글은 주제 "OTT"에 해당한다
    When 발송 대상을 정한다
    Then 발송 대상은 "ott" 한 곳뿐이다

  @DLV-04 @new
  Scenario: 어떤 주제에도 해당하지 않는 글은 주제 웹훅으로 보내지 않는다
    Given 글은 어떤 주제에도 해당하지 않는다
    When 발송 대상을 정한다
    Then 발송 대상에 "ott"는 없다

  @DLV-23 @new
  Scenario Outline: 기본 웹훅에서 빠진 피드의 주제 글은 지정한 웹훅과 주제 웹훅으로만 간다
    # 피드나 카테고리의 웹훅으로 가는 피드는 기본 웹훅에서 제외된다. 주제 글이어도 기본 웹훅으로는 가지 않는다
    Given 피드의 웹훅 지정은 <feed_webhook>이고 카테고리의 웹훅 지정은 <category_webhook>이다
    And 글은 주제 "OTT"에 해당한다
    When 발송 대상을 정한다
    Then 발송 대상은 "<target>"와 "ott" 두 곳이고 "rss"는 없다

    Examples:
      | feed_webhook | category_webhook | target  |
      | gizmodo      | 없음             | gizmodo |
      | 없음         | dev              | dev     |

  @DLV-24 @new
  Scenario: 기본 웹훅으로 가는 피드의 주제 글은 기본 웹훅과 주제 웹훅으로 간다
    Given 피드의 웹훅 지정은 없음이고 카테고리의 웹훅 지정은 없음이다
    And 글은 주제 "OTT"에 해당한다
    When 발송 대상을 정한다
    Then 발송 대상은 "rss"와 "ott" 두 곳이다

  @DLV-21 @new
  Scenario: 웹훅이 같은 두 주제에 해당해도 그 웹훅에는 한 번만 보낸다
    Given 주제 "게임"과 주제 "만화"의 웹훅은 모두 gizmodo이다
    And 글은 주제 "게임"과 "만화"에 해당한다
    When 발송 대상을 정한다
    Then 발송 대상은 "rss"와 "gizmodo" 두 곳이다

  @DLV-22 @new
  Scenario: 글이 해당한 주제와 일치한 키워드를 기록한다
    # 나중에 좋아요/싫어요로 키워드를 개선하는 데 쓴다(M5)
    Given 주제 "OTT"에 해당하는 글의 발송 대상은 "rss"와 "ott"이다
    When 발송 작업을 실행한다
    Then 주제 "OTT"에 해당했다는 기록과 일치한 키워드가 남는다

  @DLV-05 @legacy-parity @legacy:rss_reporter.main
  Scenario: 요약이 끝난 글만 발송한다
    Given 상태가 "collected"인 글과 "ready"인 글이 각각 1개 있다
    When 발송 작업을 실행한다
    Then "ready"인 글만 발송된다
    And "collected"인 글은 그대로 남는다

  # ---------- 메시지 형식 ----------

  @DLV-06 @legacy-parity @improvement @legacy:rss_reporter.format_discord_message
  Scenario: 메시지는 머리말, 제목, 요약, 서비스 글 링크로 구성한다
    # 기존에는 마지막 줄이 원문 링크였다. 이제 서비스 글 링크만 넣는다
    Given 글 123의 사이트는 "Blog", 번역 제목은 "새 아이폰 배터리", 요약은 "배터리가 커졌다."이다
    And 글의 발행 시각은 서비스 시간대 14시 32분이다
    And 글의 원문 주소는 "https://example.com/original"이다
    When 메시지를 만든다
    Then 메시지는 다음과 같다
      """
      📢 **[Blog] 새 글 알림** `14:32`
      **새 아이폰 배터리**
      배터리가 커졌다.
      🔗 [글 읽기](https://rss.example.com/a/123)
      """
    And 메시지에 "https://example.com/original"은 들어 있지 않다

  @DLV-07 @legacy-parity @legacy:rss_reporter.format_discord_message
  Scenario Outline: 발행 시각은 서비스 시간대의 시:분으로 표시하고, 없으면 생략한다
    Given 글의 발행 시각 값이 "<published>"이다
    When 메시지를 만든다
    Then 머리말 끝에 <time_part>

    Examples:
      | published                 | time_part                |
      | 2026-10-16T14:32:00+09:00 | `14:32`이 붙는다         |
      | 2026-10-16T05:32:00+00:00 | `14:32`가 붙는다         |
      |                           | 시각은 붙지 않는다       |
      | 해석할 수 없는 값         | 시각은 붙지 않는다       |

  @DLV-08 @legacy-parity @legacy:rss_gizmodo_reporter.format_discord_message
  Scenario Outline: 머리말의 이모지는 피드 설정을 따른다
    Given 피드 "<site>"의 머리말 이모지 설정은 "<emoji>"이다
    When 메시지를 만든다
    Then 머리말은 "<emoji> **[<site>] 새 글 알림**"으로 시작한다

    Examples:
      | site    | emoji |
      | Gizmodo | 🧪    |
      | Blog    | 📢    |

  @DLV-09 @improvement @legacy:rss_reporter.send_discord
  Scenario: 요약이 길어도 링크는 잘리지 않고 전체 길이는 1900자를 넘지 않는다
    # 기존: 전체를 1900자에서 잘라 링크(마지막 줄)가 사라졌다
    Given 요약이 2500자인 글이 있다
    When 메시지를 만든다
    Then 메시지 길이는 1900자 이하이다
    And 머리말, 제목, 서비스 글 링크는 그대로 들어 있다
    And 요약은 말줄임표로 끝난다

  @DLV-10 @improvement
  Scenario: 제목이 극단적으로 길어도 길이 제한을 지키고 링크를 보존한다
    Given 번역 제목이 3000자인 글이 있다
    When 메시지를 만든다
    Then 메시지 길이는 1900자 이하이다
    And 서비스 글 링크는 그대로 들어 있다

  # ---------- 발송 기록과 재시도 ----------

  @DLV-11 @improvement @legacy:rss_reporter.main
  Scenario: 목적지마다 발송 결과를 따로 기록하고, 실패한 곳만 다시 보낸다
    # 기존: 일반 채널과 OTT 채널 중 한쪽만 성공해도 "발송 완료"로 처리해 실패한 쪽은 영영 못 받았다
    Given 주제 "OTT"에 해당하는 글의 발송 대상은 "rss"와 "ott"이다
    And "rss"는 성공하고 "ott"는 서버 오류로 실패한다
    When 발송 작업을 실행한다
    Then "rss" 발송은 "sent"로 기록된다
    And "ott" 발송은 "pending"으로 남고 시도 횟수가 1 오른다
    And 글의 상태는 아직 "delivered"가 아니다
    When "ott"가 복구되고 발송 작업을 다시 실행한다
    Then "ott"로만 1번 더 보낸다
    And "rss"로는 다시 보내지 않는다
    And 글의 상태는 "delivered"가 된다

  @DLV-12 @legacy-parity @legacy:rss_reporter.main
  Scenario: 모든 목적지로 보내면 글을 발송 완료로 두고 같은 글을 다시 수집하지 않게 기록한다
    Given 글의 발송 대상이 모두 성공한다
    When 발송 작업을 실행한다
    Then 글의 상태는 "delivered"이다
    And 글의 GUID는 "이미 본 글"로 기록된다

  @DLV-13 @new
  Scenario: Discord가 429로 답하면 지정된 시간만큼 기다린 뒤 한 번 다시 시도한다
    Given 웹훅이 429와 Retry-After 2초로 답한다
    When 발송 작업을 실행한다
    Then 2초 뒤에 같은 웹훅으로 한 번 더 보낸다
    And 그래도 실패하면 이번 실행에서는 더 시도하지 않고 다음 실행으로 넘긴다

  @DLV-14 @new
  Scenario Outline: 웹훅이 삭제되었거나 거부하면 영구 실패로 두고 시스템 알림을 한 번 보낸다
    Given 웹훅 "dev"가 <status> 상태 코드로 답한다
    When 발송 작업을 실행한다
    Then "dev" 대상 발송은 "failed_permanent"로 기록된다
    And 시스템 웹훅으로 알림이 1번 간다
    And 같은 웹훅의 같은 실패는 쿨다운 동안 다시 알리지 않는다

    Examples:
      | status |
      | 401    |
      | 403    |
      | 404    |

  @DLV-15 @new
  Scenario: 기본 웹훅이 지정되어 있지 않으면 발송을 보류하고 시스템 알림을 보낸다
    Given 기본 웹훅이 등록되어 있지 않다
    And 피드는 카테고리에 속하지 않는다
    And "ready"인 글이 있다
    When 발송 작업을 실행한다
    Then 글은 발송되지 않고 "ready"로 남는다
    And 시스템 웹훅이 있으면 알림이 1번 간다

  @DLV-16 @improvement @legacy:rss_collector.main
  Scenario: 같은 실행에서 여러 글을 보낼 때는 발행 시각이 오래된 글부터 보낸다
    # 기존: 최신 글부터 보내서 채널에서는 시간 순서가 거꾸로 보였다
    Given 발송 대기 글이 10:00, 10:20, 10:10에 발행되었다
    When 발송 작업을 실행한다
    Then 발송 순서는 10:00, 10:10, 10:20이다

  # ---------- 안전 ----------

  @DLV-17 @new
  Scenario: 웹훅 주소와 API 키는 로그, 상태 화면, 오류 메시지에 나오지 않는다
    Given 웹훅 주소와 OpenRouter 키가 설정되어 있다
    When 발송 실패, LLM 실패, 상태 조회가 일어난다
    Then 로그와 응답 어디에도 웹훅 주소의 토큰 부분과 API 키 전체가 없다

  # ---------- 서비스 주소 설정 ----------

  @DLV-19 @new
  Scenario: 서비스 주소가 설정되어 있지 않으면 발송을 보류한다
    # 링크 없는 알림이 나가면 글을 열 수 없으므로 주소가 생길 때까지 기다린다
    Given 설정의 서비스 주소가 비어 있다
    And "ready"인 글이 있다
    When 발송 작업을 실행한다
    Then 글은 발송되지 않고 "ready"로 남는다
    And 상태 화면에 "서비스 주소 필요"가 표시된다

  @DLV-20 @new
  Scenario: 서비스 주소를 바꾸면 이후 메시지부터 새 주소를 쓴다
    Given 글 123이 "ready"이고 서비스 주소는 "https://old.example.com"이다
    When 서비스 주소를 "https://new.example.com"으로 바꾸고 발송 작업을 실행한다
    Then 메시지의 링크는 "https://new.example.com/a/123"이다
    And 이미 Discord로 나간 메시지는 바꾸지 않는다
