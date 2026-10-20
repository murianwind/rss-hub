@m4
Feature: 글 전문: 원문 페이지에서 본문을 가져와 보여 준다

  글을 처음 열 때 서버가 원문 페이지를 가져와 본문만 뽑아 저장하고 보여 준다. 두 번째부터는 저장한 전문을
  쓴다. 가져오지 못하거나 본문을 찾지 못하면 RSS 본문과 이유를 보여 주고, 같은 글을 열 때마다 다시 가져오지
  않는다. 외부 페이지는 사설망 주소 차단과 본문 정제를 거치므로 어떤 내용이 와도 화면에서 실행되지 않는다.

  Background:
    Given 사이트 "자유 블로그"가 있다

  @FTX-01 @new
  Scenario: 글을 열면 원문 페이지의 본문만 전문으로 보인다
    Given 원문 페이지에는 메뉴와 하단 안내와 긴 본문이 있고 RSS에는 요약만 있는 글이 있다
    When 그 글을 연다
    Then 본문에는 원문의 긴 본문이 보이고 메뉴와 하단 안내와 RSS 요약은 없다
    And 원문 페이지에서 가져온 전문이라는 안내와 다시 가져오기 버튼이 있다

  @FTX-02 @new
  Scenario: 전문은 처음 한 번만 가져오고 저장한 것을 쓴다
    Given 원문 페이지에는 메뉴와 하단 안내와 긴 본문이 있고 RSS에는 요약만 있는 글이 있다
    When 그 글을 두 번 연다
    Then 원문 페이지는 한 번만 요청했다

  @FTX-03 @new
  Scenario Outline: 가져오지 못하면 RSS 본문과 이유를 보여 주고 다시 가져오지 않는다
    Given 원문 페이지가 <case>인 글이 있다
    When 그 글을 두 번 연다
    Then RSS 본문과 "<reason>" 이유가 보이고 원문 페이지는 한 번만 요청했다

    Examples:
      | case              | reason                                  |
      | 시간 초과로 실패한다  | 원문 전문을 가져오지 못해 RSS 본문을 보여 줍니다 |
      | 본문이 없는 페이지다  | 본문을 찾지 못했습니다                         |

  @FTX-04 @new
  Scenario: 다시 가져오기 버튼은 앞선 실패 뒤에도 다시 시도한다
    Given 원문 페이지가 시간 초과로 실패한다
    And 그 글을 열었다
    When 원문 페이지가 복구된 뒤 다시 가져오기 버튼을 누른다
    Then 글 페이지로 돌아와 "원문에서 전문을 다시 가져왔습니다." 알림이 보이고 전문이 보인다

  @FTX-05 @new
  Scenario Outline: 쓸 수 없거나 사설망을 가리키는 원문 주소는 요청하지 않는다
    Given 원문 주소가 "<link>"인 글이 있다
    When 그 글을 연다
    Then 원문 페이지는 한 번도 요청하지 않았고 RSS 본문이 보인다

    Examples:
      | link                  |
      |                       |
      | http://127.0.0.1/x    |
      | http://192.168.1.5/x  |
      | http://localhost/x    |
      | javascript:alert(1)   |

  @FTX-06 @new
  Scenario: 원문 페이지에 악성 내용이 있어도 화면에서 실행되지 않는다
    Given 원문 페이지에 스크립트와 이벤트 속성과 위험한 링크와 iframe이 들어 있는 글이 있다
    When 그 글을 연다
    Then 본문에는 정상 문장만 남고 위험한 요소는 하나도 없다

  @FTX-07 @new
  Scenario: 영상은 재생하지 않고 주소 없이 "영상 보기" 링크가 되어 새 창으로 열린다
    Given 원문 페이지의 본문 중간에 유튜브 영상이 들어 있는 글이 있다
    When 그 글을 연다
    Then 영상이 있던 자리에 "영상 보기" 링크가 있고 화면 글자에는 영상 주소가 보이지 않는다
    And 그 링크는 새 창으로 열리고 영상 페이지 주소를 가리킨다

  @FTX-08 @new
  Scenario Outline: 알려진 영상 사이트가 아닌 프레임이나 쓸 수 없는 주소는 지우고 링크도 만들지 않는다
    Given 원문 페이지에 "<frame>" 주소의 프레임이 들어 있는 글이 있다
    When 그 글을 연다
    Then 본문에는 "영상 보기" 링크도 프레임도 없다

    Examples:
      | frame                           |
      | https://ads.example.com/banner  |
      | javascript:alert(1)             |
      | https://evil.example.org/embed  |

