@summarization
Feature: 제목 번역과 요약
  수집된 글을 LLM으로 "한국어 제목 + 2~3문장 요약 + 해당 주제"로 만든다.
  불량 응답은 폐기하고 재시도하며, 끝까지 실패하면 원문 발췌로 확정해서 알림이 막히지 않게 한다.

  Background:
    Given 한 번 실행에서 처리하는 최대 글 수는 5이다 (설정값, 기본 5)
    And LLM은 JSON으로 "title_ko", "summary_ko"를 답하고, 켜진 주제가 있으면 "topics"도 답하도록 요청받는다

  # ---------- 요청과 결과 ----------

  @SUM-01 @new
  Scenario: 한 번의 호출로 제목 번역, 요약, 주제 판정을 함께 받는다
    Given 영문 글 "Apple unveils new phone"이 수집되어 있다
    And LLM이 제목 "애플, 새 폰 공개", 요약 "애플이 새 폰을 공개했다.", 해당 주제 없음으로 답한다
    When 요약 작업을 실행한다
    Then 글의 번역 제목은 "애플, 새 폰 공개"이다
    And 글의 요약은 "애플이 새 폰을 공개했다."이다
    And 글의 주제 판정은 없음으로 기록된다
    And LLM 호출은 1번이다
    And 사용한 모델 이름이 글에 기록된다

  @SUM-02 @legacy-parity @legacy:rss_translator.is_korean
  Scenario Outline: 한글 비율이 10% 이상이면 한국어 글로 본다
    Given 글의 제목과 본문을 합친 텍스트가 "<text>"이다
    When 한국어 글인지 판별한다
    Then 판별 결과는 <korean>이다

    Examples:
      | text                         | korean |
      | 가aaaaaaaaa                  | 참     |
      | 가aaaaaaaaaa                 | 거짓   |
      | hello world                  | 거짓   |
      | <p></p>                      | 거짓   |

  @SUM-03 @legacy-parity @legacy:rss_translator.main
  Scenario: 한국어 글은 제목을 원문 그대로 쓰고 요약만 한국어로 받는다
    Given 한국어 글 "스프링 부트 4 마이그레이션 후기"가 수집되어 있다
    And LLM이 제목 "Spring Boot 4 migration"과 요약 "마이그레이션 과정을 정리했다."로 답한다
    When 요약 작업을 실행한다
    Then 글의 번역 제목은 "스프링 부트 4 마이그레이션 후기"이다
    And 글의 요약은 "마이그레이션 과정을 정리했다."이다

  @SUM-04 @legacy-parity @legacy:rss_translator.main
  Scenario: LLM에는 HTML을 제거한 본문의 앞 1500자만 보낸다
    Given 글의 본문이 HTML 태그를 포함한 3000자이다
    When 요약 작업을 실행한다
    Then LLM 요청에 HTML 태그는 없다
    And LLM 요청의 본문 길이는 1500자이다

  # ---------- 응답 검증 ----------

  @SUM-05 @legacy-parity @improvement @legacy:rss_translator.needs_retranslation
  Scenario Outline: 불량 응답은 채택하지 않고 재시도 횟수를 1 올린다
    # 한자 검사는 기존에 요약에만 적용됐고, 이제 제목에도 적용한다
    Given 영문 글이 수집되어 있고 재시도 횟수는 0이다
    And LLM이 <bad_response> 응답을 준다
    When 요약 작업을 실행한다
    Then 응답은 채택되지 않는다
    And 글의 재시도 횟수는 1이다
    And 글의 상태는 "collected"로 남는다

    Examples:
      | bad_response                                  |
      | JSON이 아닌 문장 형태의                       |
      | 필수 항목이 빠진 JSON                         |
      | 요약이 빈 문자열인                            |
      | 제목이 빈 문자열인                            |
      | 요약에 한자가 섞인                            |
      | 제목에 한자가 섞인                            |
      | "We need to translate"로 시작하는 사고 과정이 담긴 |
      | "Korean summary"라는 문구가 담긴              |
      | "TITLE:" 같은 형식 표지가 본문에 남아 있는   |
      | 길이 제한으로 잘린(finish_reason이 length인)  |

  @SUM-06 @legacy-parity @legacy:rss_translator.main
  Scenario: 요약에 성공하면 재시도 횟수를 지운다
    Given 영문 글의 재시도 횟수는 2이다
    And LLM이 정상 응답을 준다
    When 요약 작업을 실행한다
    Then 글의 상태는 "ready"이다
    And 글의 재시도 횟수는 0이다

  @SUM-07 @legacy-parity @legacy:rss_translator.main
  Scenario: 정상 응답에 주제 항목이 없으면 해당 주제가 없는 것으로 보고 요약은 채택한다
    Given 영문 글이 수집되어 있다
    And LLM이 제목과 요약만 있고 "topics"가 없는 JSON으로 답한다
    When 요약 작업을 실행한다
    Then 글의 상태는 "ready"이다
    And 글의 주제 판정은 없음으로 기록된다

  # ---------- 끝까지 실패할 때 ----------

  @SUM-08 @legacy-parity @legacy:rss_translator.main
  Scenario: 불량 응답이 3번 쌓이면 원문 발췌로 확정하고 알림을 진행시킨다
    Given 영문 글의 재시도 횟수는 2이다
    And 글의 본문은 HTML을 제거하면 500자이다
    And LLM이 불량 응답을 준다
    When 요약 작업을 실행한다
    Then 글의 요약은 본문 앞 300자에 "..."을 붙인 값이다
    And 글의 번역 제목은 원문 제목이다
    And 사용한 모델은 "fallback-final"로 기록된다
    And 글의 상태는 "ready"이다

  @SUM-09 @legacy-parity @legacy:rss_translator.needs_retranslation
  Scenario: 원문 발췌로 확정된 글은 다시 요약하지 않는다
    Given 사용 모델이 "fallback-final"인 글이 있다
    When 요약 대상 글을 고른다
    Then 이 글은 대상에 포함되지 않는다

  @SUM-10 @improvement
  Scenario: 모든 모델이 응답하지 못하는 장애는 재시도 횟수를 소모하지 않는다
    # 기존: 장애도 실패 1회로 세어 15분 만에 영문 원문이 그대로 발송되었다
    Given 영문 글의 재시도 횟수는 0이다
    And 모든 모델이 한도 초과(429) 또는 서버 오류로 응답하지 못한다
    When 요약 작업을 실행한다
    Then 글의 재시도 횟수는 0이다
    And 글의 상태는 "collected"로 남는다

  @SUM-11 @improvement
  Scenario: 장애가 오래 이어지면 일정 시간 뒤에 원문 발췌로 확정한다
    Given 영문 글이 수집된 지 61분이 지났다
    And 대기 허용 시간은 60분이다
    And 모든 모델이 응답하지 못한다
    When 요약 작업을 실행한다
    Then 글은 원문 발췌로 확정되고 상태는 "ready"가 된다
    And 사용한 모델은 "fallback-final"로 기록된다

  # ---------- 처리 순서와 양 ----------

  @SUM-12 @legacy-parity @improvement @legacy:rss_translator.main
  Scenario: 처음 처리하는 글을 재시도 글보다 먼저, 같은 그룹에서는 오래된 글부터 처리한다
    Given 재시도 횟수 0인 글 A(10:00 발행)와 B(10:30 발행)가 있다
    And 재시도 횟수 1인 글 C(09:00 발행)가 있다
    When 처리 대상 순서를 정한다
    Then 순서는 A, B, C이다

  @SUM-13 @legacy-parity @legacy:rss_translator.main
  Scenario: 한 번 실행에서 최대 5개까지만 처리한다
    Given 요약 대상 글이 12개 있다
    When 요약 작업을 실행한다
    Then LLM 호출은 최대 5번이다
    And 나머지 7개는 다음 실행으로 남는다

  @SUM-14 @legacy-parity @legacy:rss_translator.main
  Scenario: 한 글의 처리 중 예외가 나도 나머지 글은 계속 처리한다
    Given 요약 대상 글 3개가 있고 두 번째 글에서 예상하지 못한 예외가 난다
    When 요약 작업을 실행한다
    Then 첫 번째와 세 번째 글은 정상 처리된다
    And 두 번째 글의 재시도 횟수는 1이다

  # ---------- 주제 판별 ----------
  # 주제를 판별해도 LLM 호출은 늘지 않는다. 켜진 주제의 번호와 설명을 같은 요청에 넣어서 한 번에 받는다.

  @SUM-15 @new
  Scenario: 키워드가 맞은 주제만 번호와 설명이 요청에 들어간다
    # 키워드가 먼저 후보를 거르고, LLM은 그 후보만 확인한다. 후보가 아닌 주제는 묻지 않는다
    Given 주제 "OTT"(설명 "스트리밍 소식")와 주제 "게임"이 켜져 있다
    And 꺼진 주제 "보안"이 있다
    And 제목이 "Netflix announces a new drama"인 영문 글이 수집되어 있다
    And LLM이 제목과 요약만 있고 "topics"가 없는 JSON으로 답한다
    When 요약 작업을 실행한다
    Then 요청에 "1. OTT: 스트리밍 소식"이 들어 있다
    And 요청에 키워드가 맞지 않은 주제 "2. 게임"은 들어 있지 않다
    And 요청에 꺼진 주제 "보안"은 들어 있지 않다
    And LLM 호출은 1번이다

@SUM-16 @new
  Scenario: LLM이 고른 후보 주제 번호가 글에 기록되고, 알 수 없는 번호는 걸러진다
    Given 주제 "OTT"(설명 "스트리밍 소식")와 주제 "게임"이 켜져 있다
    And 제목이 "Netflix game adaptation on Steam"인 영문 글이 수집되어 있다
    And LLM이 주제 번호로 1, 99, "2", true를 답한다
    When 요약 작업을 실행한다
    Then 글의 주제 판정은 "OTT"와 "게임"이다

@SUM-17 @new
  Scenario: 켜진 주제가 없으면 요청에 주제 항목을 넣지 않는다
    Given 영문 글이 수집되어 있다
    And LLM이 제목 "애플, 새 폰 공개"과 요약 "애플이 새 폰을 공개했다."로 답한다
    When 요약 작업을 실행한다
    Then 요청에 "topics"가 들어 있지 않다
    And 글의 상태는 "ready"이다

@SUM-18 @new
  Scenario: 키워드가 하나도 맞지 않으면 요청에 주제 항목을 넣지 않고 주제 판정도 없다
    Given 주제 "OTT"(설명 "스트리밍 소식")와 주제 "게임"이 켜져 있다
    And 영문 글이 수집되어 있다
    And LLM이 주제 번호로 1, 2를 답한다
    When 요약 작업을 실행한다
    Then 요청에 "Candidate topics"가 들어 있지 않다
    And 글의 주제 판정은 없음으로 기록된다

@SUM-19 @new
  Scenario: LLM이 후보가 아닌 주제를 골라도 무시한다
    Given 주제 "OTT"(설명 "스트리밍 소식")와 주제 "게임"이 켜져 있다
    And 제목이 "Netflix announces a new drama"인 영문 글이 수집되어 있다
    And LLM이 주제 번호로 1, 2를 답한다
    When 요약 작업을 실행한다
    Then 글의 주제 판정은 "OTT"뿐이다

@SUM-20 @new
  Scenario: 키워드가 없는 주제는 LLM만으로 정하므로 항상 물어본다
    Given 키워드가 없는 주제 "보안"(설명 "보안 소식")이 켜져 있다
    And 영문 글이 수집되어 있다
    And LLM이 주제 번호로 1을 답한다
    When 요약 작업을 실행한다
    Then 요청에 "1. 보안: 보안 소식"이 들어 있다
    And 글의 주제 판정은 "보안"뿐이다
