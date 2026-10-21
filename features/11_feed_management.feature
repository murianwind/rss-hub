@m2
Feature: 구독 관리(M2): 개별 등록과 피드 자동 탐색, 편집, 삭제, OPML 내보내기

  OPML을 올리는 것 말고도 주소 하나로 피드를 추가할 수 있어야 한다. 웹사이트 주소를 넣으면 그 페이지가 알려 준
  피드를 찾아서 보여 준다. 서버가 사용자가 준 주소로 요청을 보내므로 사설망 주소는 가져오기와 같은 규칙으로 막는다.

  Background:
    Given 구독 목록에 주소 "https://a.example.com/feed"의 피드 "이미 있는 피드"가 있다

  # ---------- 개별 등록 ----------

  @FED-01
  Scenario: 피드 주소를 확인하면 피드 제목이 나오고 등록할 수 있다
    Given 주소 "https://new.example.com/rss"는 제목이 "새 블로그"인 피드다
    When 주소 "https://new.example.com/rss"를 확인한다
    Then 등록 후보로 "새 블로그"가 표시된다
    When 후보 "새 블로그"를 등록한다
    Then 피드 "새 블로그"가 "baseline_pending" 상태로 등록된다

  @FED-02
  Scenario: 웹사이트 주소를 확인하면 그 페이지가 알려 준 피드를 찾아서 후보로 보여 준다
    Given 주소 "https://blog.example.com/"는 피드 "/feed.xml"과 "/comments.xml"을 알려 주는 웹페이지다
    And 두 피드는 각각 "글"과 "댓글"이라는 제목의 올바른 피드다
    When 주소 "https://blog.example.com/"를 확인한다
    Then 등록 후보로 "글"과 "댓글"이 표시된다
    And 후보의 주소는 전체 주소 "https://blog.example.com/feed.xml"과 "https://blog.example.com/comments.xml"이다

  @FED-03
  Scenario Outline: 피드를 찾지 못하면 이유를 알려 준다
    Given 주소 "<url>"의 응답은 <situation>이다
    When 주소 "<url>"를 확인한다
    Then 오류 "<message>"가 표시된다

    Examples:
      | url                           | situation               | message                              |
      | https://x.example.com/        | 피드 링크가 없는 웹페이지 | 이 주소에서 피드를 찾지 못했습니다   |
      | https://x.example.com/missing | HTTP 404                | 주소를 열지 못했습니다(HTTP 404)     |
      | https://x.example.com/down    | 연결 실패               | 주소에 연결하지 못했습니다           |

  @FED-04
  Scenario: 이미 구독 중인 주소는 중복이라고 알려 주고 요청을 보내지 않는다
    # 대소문자와 끝의 슬래시가 달라도 같은 주소로 본다
    When 주소 "https://A.Example.com/feed/"를 확인한다
    Then 오류 "이미 구독 중인 피드입니다"가 표시된다
    And 외부로는 어떤 요청도 나가지 않는다

  @FED-05
  Scenario Outline: 사설망 주소와 잘못된 주소는 요청을 보내기 전에 거절한다
    When 주소 "<url>"를 확인한다
    Then 오류 "<message>"가 표시된다
    And 외부로는 어떤 요청도 나가지 않는다

    Examples:
      | url                                       | message                         |
      | http://192.168.0.10/rss                   | 사설망·내부 주소는 허용하지 않음 |
      | http://localhost/rss                      | 사설망·내부 주소는 허용하지 않음 |
      | http://169.254.169.254/latest/meta-data   | 사설망·내부 주소는 허용하지 않음 |
      | ftp://x.example.com/feed                  | http, https만 가능              |
      | javascript:alert(1)                       | http, https만 가능              |

  @FED-06
  Scenario: 등록할 때 카테고리를 고를 수 있고, 웹훅은 카테고리가 없을 때만 고를 수 있다
    Given 카테고리 "뉴스"와 웹훅 "dev"가 있다
    And 주소 "https://new.example.com/rss"는 제목이 "새 블로그"인 피드다
    When 주소 "https://new.example.com/rss"를 카테고리 "뉴스"와 웹훅 "dev"로 등록한다
    Then 오류 "카테고리에 속한 피드는 웹훅을 지정할 수 없음"이 표시되고 피드는 등록되지 않는다
    When 주소 "https://new.example.com/rss"를 카테고리 "뉴스"로 등록한다
    Then 피드 "새 블로그"가 카테고리 "뉴스"에 속한다

  @FED-07
  Scenario: 등록할 때 다시 확인해서 피드가 아니면 등록하지 않는다
    # 화면에서 넘어온 값은 믿지 않는다. 확인 화면을 건너뛰고 등록 요청을 직접 보내도 마찬가지다
    Given 주소 "https://evil.example.com/x"의 응답은 피드 링크가 없는 웹페이지이다
    When 주소 "https://evil.example.com/x"를 확인 없이 바로 등록한다
    Then 오류 "피드가 아닙니다"가 표시되고 피드는 등록되지 않는다

  # ---------- 편집과 삭제 ----------

  @FED-08
  Scenario: 피드의 이름, 이모지, 점검 우선순위, 최대 검사 항목 수를 고칠 수 있다
    When 피드 "이미 있는 피드"를 이름 "새 이름", 이모지 "🧪", 우선순위 "every_slot", 최대 "120"으로 저장한다
    Then 피드 "새 이름"의 값은 이모지 "🧪", 우선순위 "every_slot", 최대 120이다
    When 피드 "새 이름"의 최대 검사 항목 수를 비워서 저장한다
    Then 피드 "새 이름"의 최대 검사 항목 수는 기본값을 쓴다

  @FED-09
  Scenario Outline: 규칙에 맞지 않는 값은 저장하지 않고 이유를 알려 준다
    When 피드 "이미 있는 피드"를 이름 "<name>", 이모지 "<emoji>", 우선순위 "<priority>", 최대 "<max>"으로 저장한다
    Then 오류 "<message>"가 표시된다
    And 피드 "이미 있는 피드"는 바뀌지 않았다

    Examples:
      | name        | emoji | priority   | max | message                              |
      | (빈 값)     | 📢    | normal     |     | 이름이 필요함                        |
      | (201자)     | 📢    | normal     |     | 이름은 200자까지                     |
      | 새 이름     | (빈 값) | normal   |     | 머리말 이모지가 필요함               |
      | 새 이름     | 📢    | high       |     | 점검 우선순위는 보통 또는 매 슬롯    |
      | 새 이름     | 📢    | normal     | 0   | 최대 검사 항목 수는 1~500 사이의 숫자 |
      | 새 이름     | 📢    | normal     | 501 | 최대 검사 항목 수는 1~500 사이의 숫자 |
      | 새 이름     | 📢    | normal     | abc | 최대 검사 항목 수는 1~500 사이의 숫자 |

  @FED-10
  Scenario: 피드를 삭제하면 그 피드의 글과 발송 기록도 지워지고, 같은 글이 다시 알림으로 나가지 않는다
    Given 피드 "이미 있는 피드"에 글 2개와 발송 기록이 있다
    When 피드 "이미 있는 피드"를 삭제를 확인하고 지운다
    Then 피드, 글, 발송 기록이 모두 사라진다
    And 지워진 글의 "이미 본 글" 기록은 남아 있다

  @FED-11
  Scenario: 삭제는 확인 값이 있어야 한다
    Given 피드 "이미 있는 피드"에 글 2개와 발송 기록이 있다
    When 피드 "이미 있는 피드"를 확인 없이 삭제 요청한다
    Then 오류 "삭제 확인이 필요합니다"가 표시된다
    And 피드와 글은 그대로 남아 있다

  # ---------- OPML 내보내기 ----------

  @FED-12
  Scenario: 내보낸 OPML은 카테고리를 폴더로, 이름, 주소, 사이트 주소를 담고 파일로 내려받는다
    Given 카테고리 "뉴스"에 속한 피드 "뉴스 블로그"(사이트 "https://news.example.com")가 있다
    And 피드 "이미 있는 피드"에 웹훅 "시험웹훅"이 지정되어 있다
    When OPML로 내보낸다
    Then 파일로 내려받는 응답이다
    And 폴더 "뉴스" 아래에 "뉴스 블로그"의 이름, 피드 주소, 사이트 주소가 있다
    And 카테고리가 없는 "이미 있는 피드"는 폴더 밖에 있다
    And 웹훅 주소나 웹훅 이름은 파일에 없다

  @FED-13
  Scenario: 내보낸 파일을 다시 가져오면 모두 이미 구독 중으로 나온다
    Given 카테고리 "뉴스"에 속한 피드 "뉴스 블로그"(사이트 "https://news.example.com")가 있다
    When OPML로 내보낸 파일을 가져오기 미리보기에 올린다
    Then 미리보기는 신규 0개, 중복 2개, 오류 0개다

  @FED-14
  Scenario: 이름에 특수 문자가 있어도 올바른 OPML이 나오고 다시 가져올 수 있다
    Given 피드 "꺾쇠 <b>와 & 앰퍼샌드"가 있다
    When OPML로 내보낸다
    Then 파일은 올바른 XML이고 스크립트로 해석될 내용은 없다
    And 그 파일을 다시 가져오면 이름이 그대로다
