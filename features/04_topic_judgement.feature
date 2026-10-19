@topic
Feature: 주제 판정

  기존 "OTT 글 판정"을 일반화한 것이다. 글이 주제에 해당하려면 LLM이 그 주제를 골라야 하고(LLM 확인),
  키워드가 등록된 주제는 제목이나 본문에 키워드가 하나라도 있어야 한다(키워드 보완).
  키워드는 LLM이 근거 없이 주제를 고르는 것(환각)을 걸러 준다. OTT는 처음 설치할 때 기본으로 만들어지는 주제 하나다.

  Background:
    Given 주제 "OTT"가 있고 기본 OTT 키워드가 등록되어 있다

  @TPC-01 @legacy-parity @legacy:rss_reporter.is_ott_related
  Scenario Outline: LLM 판정과 키워드 확인을 모두 통과해야 주제 글이다
    Given 글의 제목은 "<title>"이고 본문은 비어 있다
    And LLM의 "OTT" 주제 판정은 <llm>이다
    When 주제 "OTT" 해당 여부를 판단한다
    Then 결과는 <result>이다

    Examples:
      | title                  | llm    | result |
      | New Netflix drama      | 맞음   | 참     |
      | Apple event recap      | 맞음   | 거짓   |
      | 스트리밍 서비스 요금   | 맞음   | 참     |
      | New Netflix drama      | 아님   | 거짓   |
      | New Netflix drama      | 없음   | 거짓   |

  @TPC-02 @legacy-parity @legacy:rss_reporter.is_ott_related
  Scenario Outline: 영문 키워드는 단어 단위로, 대소문자 구분 없이 일치한다
    Given 글의 제목은 "<title>"이고 LLM의 "OTT" 주제 판정은 맞음이다
    When 주제 "OTT" 해당 여부를 판단한다
    Then 결과는 <result>이다

    Examples:
      | title               | result |
      | movie night         | 참     |
      | Season finale       | 참     |
      | filmmaker interview | 거짓   |
      | seasoning tips      | 거짓   |

  @TPC-03 @improvement @legacy:rss_reporter.is_ott_related
  Scenario Outline: 영문 약어 "ott"는 단어 안에서 일치하지 않는다
    # 기존: 한글 키워드 목록에 들어 있어 부분 문자열로 일치했다 (bottle, lotto 등이 OTT로 분류)
    Given 글의 제목은 "<title>"이고 LLM의 "OTT" 주제 판정은 맞음이다
    When 주제 "OTT" 해당 여부를 판단한다
    Then 결과는 거짓이다

    Examples:
      | title             |
      | A bottle of water |
      | Lotto results     |
      | gotta love it     |

  @TPC-04 @improvement @legacy:rss_reporter.is_ott_related
  Scenario Outline: HTML 태그, 속성, 주소 안의 단어는 키워드 확인에서 제외한다
    # 기존: 본문 HTML을 그대로 검사해서 이미지 주소의 "movie" 같은 단어에도 반응했다
    Given 글의 제목은 "Apple event recap"이고 LLM의 "OTT" 주제 판정은 맞음이다
    And 글의 본문은 '<content>'이다
    When 주제 "OTT" 해당 여부를 판단한다
    Then 결과는 거짓이다

    Examples:
      | content                                      |
      | <img src="https://x.com/movie.jpg"> text     |
      | <a class="trailer-link">text</a>             |

  @TPC-05 @improvement
  Scenario: 태그 밖의 본문 텍스트에 키워드가 있으면 주제에 해당한다
    Given 글의 제목은 "Weekend picks"이고 LLM의 "OTT" 주제 판정은 맞음이다
    And 글의 본문은 "<p>New <b>trailer</b> released today</p>"이다
    When 주제 "OTT" 해당 여부를 판단한다
    Then 결과는 참이다

  @TPC-06 @new
  Scenario: 키워드 목록은 코드가 아닌 사용자가 편집하는 데이터다
    Given 주제 "OTT"의 키워드에 "stage play"를 추가했다
    And 글의 제목은 "Stage play adaptation announced"이고 LLM의 "OTT" 주제 판정은 맞음이다
    When 주제 "OTT" 해당 여부를 판단한다
    Then 결과는 참이다

  @TPC-07 @new
  Scenario: 꺼진 주제는 판정하지 않는다
    # 피드마다 OTT 판정을 끄던 기능은 없어졌다. 주제를 끄면 모든 피드에서 판정하지 않는다
    Given 주제 "OTT"는 꺼져 있다
    And 글의 제목은 "New Netflix drama"이고 LLM의 "OTT" 주제 판정은 맞음이다
    When 주제 "OTT" 해당 여부를 판단한다
    Then 결과는 거짓이다

  @TPC-08 @improvement @legacy:rss_reporter.is_ott_related
  Scenario Outline: "+"로 끝나는 키워드는 뒤에 공백이 와도 일치하고, 글자가 붙으면 일치하지 않는다
    # 기존: 단어 경계 규칙 때문에 "Disney+ announces"는 일치하지 않고 "disney+x"는 일치했다
    Given 글의 제목은 "<title>"이고 LLM의 "OTT" 주제 판정은 맞음이다
    When 주제 "OTT" 해당 여부를 판단한다
    Then 결과는 <result>이다

    Examples:
      | title                          | result |
      | Disney+ announces a new slate  | 참     |
      | Paramount+ pricing             | 참     |
      | disney+x launch                | 거짓   |

  @TPC-09 @new
  Scenario: 키워드를 등록하지 않은 주제는 LLM의 판단만으로 정한다
    Given 주제 "OTT"의 키워드가 비어 있다
    And 글의 제목은 "Apple event recap"이고 LLM의 "OTT" 주제 판정은 맞음이다
    When 주제 "OTT" 해당 여부를 판단한다
    Then 결과는 참이다

  @TPC-10 @new
  Scenario: 글은 여러 주제에 동시에 해당할 수 있다
    Given 주제 "게임"이 있고 키워드는 "steam"이다
    And 글의 제목은 "Netflix game adaptation on Steam"이고 LLM이 "OTT"와 "게임" 주제를 골랐다
    When 해당하는 주제를 모두 찾는다
    Then 해당 주제는 "OTT"와 "게임"이다

  @TPC-11 @new
  Scenario: LLM이 다른 주제를 골랐다면 키워드가 있어도 해당하지 않는다
    Given 주제 "게임"이 있고 키워드는 "steam"이다
    And 글의 제목은 "New Netflix drama on Steam"이고 LLM이 "게임" 주제만 골랐다
    When 해당하는 주제를 모두 찾는다
    Then 해당 주제는 "게임"뿐이다

  # ---------- 판별 시험(주제 화면) ----------
  # 새 프롬프트와 키워드를 실제 모델로 확인하는 도구다. 실제 요약과 같은 프롬프트와 게이트웨이를 쓴다.

  @TPC-12 @new
  Scenario: 판별 시험은 주제마다 키워드, LLM에게 물었는지와 선택, 최종 결과를 보여 준다
    Given 주제 "OTT"(키워드 "netflix")와 주제 "게임"(키워드 "steam")이 켜져 있다
    And LLM이 "OTT" 주제를 고른다
    When 제목 "Netflix announces a new show"로 판별을 시험한다
    Then "OTT"는 키워드 "netflix", LLM 선택, 결과 "해당"으로 표시된다
    And "게임"은 키워드 없음, LLM에 묻지 않음, 결과 "해당 안 함"으로 표시된다

  @TPC-13 @new
  Scenario: 판별 시험은 LLM 호출 한 번만 쓰고 글이나 알림을 만들지 않는다
    Given 주제 "OTT"가 켜져 있다
    When 제목 "Netflix drama"로 판별을 시험한다
    Then LLM 호출은 1번이고 오늘 호출 수가 1 늘어난다
    And 글과 발송 기록은 만들어지지 않는다

  @TPC-14 @new
  Scenario Outline: 시험할 수 없으면 이유를 알려 주고 LLM을 호출하지 않는다
    Given <situation>
    When 제목 "Netflix drama"로 판별을 시험한다
    Then 오류 "<message>"가 표시된다
    And LLM 호출은 일어나지 않는다

    Examples:
      | situation                                    | message                      |
      | OpenRouter 키가 없고 주제 "OTT"가 켜져 있다 | OpenRouter 키가 설정되지 않았습니다 |
      | 켜진 주제가 하나도 없다                      | 켜진 주제가 없습니다         |

  @TPC-15 @new
  Scenario: 키워드가 맞은 주제가 없으면 LLM을 호출하지 않고 그 이유를 보여 준다
    Given 주제 "OTT"가 켜져 있다
    When 제목 "Spring gardening tips"로 판별을 시험한다
    Then LLM 호출은 일어나지 않는다
    And 결과에 "키워드가 맞은 주제가 없어서 LLM을 호출하지 않았습니다"가 표시된다
