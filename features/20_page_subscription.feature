@m5
Feature: 웹페이지 구독: RSS가 없는 사이트의 글 목록 페이지를 구독한다

  피드 주소를 넣었는데 RSS가 없으면, 글 목록 페이지에서 글(제목, 주소, 날짜)을 찾아 구독할 수 있다.
  새 글은 일반 피드와 같은 규칙(첫 점검은 기록만, 이후 오늘 올라온 새 글만)으로 모으고, 사이트 구조가 바뀌어
  글을 못 찾으면 실패로 기록되어 상태 점이 빨갛게 바뀌므로 주소를 다시 확인해 고치면 된다.

  Background:
    Given 사이트 "자유 블로그"가 있다

  @WPS-01 @new
  Scenario Outline: 피드가 없는 사이트의 글 목록 페이지는 글이 3개 이상 보이면 웹페이지 구독 후보로 나온다
    Given 피드가 없는 사이트의 글 목록 페이지에 글이 <count>개 있다
    When 그 주소를 피드 추가에서 확인한다
    Then <result>

    Examples:
      | count | result                                                              |
      | 5     | 후보 "웹페이지 구독"에 글 5개와 최근 글 5개가 한 줄에 하나씩 목록으로 보인다   |
      | 3     | 후보 "웹페이지 구독"에 글 3개와 최근 글 3개가 한 줄에 하나씩 목록으로 보인다   |
      | 2     | "이 주소에서 피드를 찾지 못했습니다"가 보인다                            |

  @WPS-02 @new
  Scenario: 메뉴, 푸터, 쪽 번호, 태그와 분류, 다른 사이트의 링크는 글로 세지 않는다
    Given 피드가 없는 사이트의 글 목록 페이지에 글이 4개 있고 메뉴와 푸터와 쪽 번호와 태그와 다른 사이트 링크도 있다
    When 그 주소를 피드 추가에서 확인한다
    Then 후보 "웹페이지 구독"에 글 4개와 최근 글 4개가 한 줄에 하나씩 목록으로 보인다

  @WPS-03 @new
  Scenario: 목록의 날짜와 분류 이름은 제목에서 떼어 내고 앞부분이 잘린 제목은 더 완전한 것을 고른다
    Given 날짜와 분류 이름이 앞에 붙은 글 목록 페이지가 있다
    When 그 주소를 피드 추가에서 확인한다
    Then 후보의 최근 글 목록은 "The Slow Death of Age and Gender", "Summer Signals: Reading Guide to the Season That Was", "The New Front Door to Financial Decision Making"이다

  @WPS-04 @new
  Scenario: 등록하면 첫 점검은 기록만 하고 이후 올라온 새 글만 본문과 함께 저장한다
    Given 글 목록 페이지에 글이 3개 있는 웹페이지 구독을 등록했다
    When 점검한다
    Then 저장된 글은 없고 글 3개가 이미 본 글로 기록된다
    When 새 글 "post-4"가 올라오고 점검한다
    Then 새 글 1개만 저장되고 그 글의 본문이 글 페이지에서 채워져 있다

  @WPS-05 @new
  Scenario: 사이트 구조가 바뀌어 글 목록을 못 찾으면 실패로 기록되어 빨간 점과 이유가 보인다
    Given 글 목록 페이지에 글이 3개 있는 웹페이지 구독을 등록했다
    And 점검했다
    When 사이트 구조가 바뀌어 글 목록에서 글이 보이지 않는 상태로 점검한다
    Then 피드 상태는 오류이고 피드 관리에는 "글 목록을 찾지 못했습니다(사이트 구조가 바뀌었을 수 있습니다)"가 보인다

  @WPS-06 @new
  Scenario Outline: 주소를 다시 입력해 고치면 새 주소의 글 목록을 확인한 뒤에만 저장하고 처음부터 다시 점검한다
    Given 글 목록 페이지에 글이 3개 있는 웹페이지 구독을 등록했다
    And 새 주소 "<new>"는 "<state>" 상태다
    When 주소를 "<new>"로 고쳐 저장한다
    Then <result>

    Examples:
      | new                              | state   | result                                                                |
      | https://blog.example.com/news-v2 | 글 목록 있음 | 주소가 바뀌고 처음부터 다시 점검하는 상태가 된다                            |
      | https://blog.example.com/empty   | 글 목록 없음 | "새 주소를 확인하지 못했습니다"로 거부되고 주소는 그대로다 |

  @WPS-07 @new
  Scenario: 웹페이지 구독은 피드 관리에 표시되고 OPML 내보내기에서는 빠진다
    Given 글 목록 페이지에 글이 3개 있는 웹페이지 구독을 등록했다
    Then 피드 관리에서 그 구독에 "웹페이지" 표시가 있고 "자유 블로그"에는 없다
    And OPML 내보내기에는 그 구독이 없고 "자유 블로그"는 있다

  @WPS-08 @new
  Scenario Outline: 피드 주소를 고칠 때 RSS가 있는지 먼저 보고, 없으면 웹페이지 구독으로 있으면 피드로 바뀐다
    Given 일반 피드 "자유 블로그"의 주소를 고치려고 한다
    And 새 주소 "<new>"는 "<state>" 상태다
    When 주소를 "<new>"로 고쳐 저장한다
    Then <result>

    Examples:
      | new                                | state             | result                                                     |
      | https://blog.example.com/feed.xml  | RSS 피드          | 구독 종류는 "feed"로 저장되고 처음부터 다시 점검한다               |
      | https://blog.example.com/news-v2   | RSS 없는 글 목록   | 구독 종류는 "page"로 저장되고 처음부터 다시 점검한다               |
      | https://blog.example.com/with-feed | RSS를 알려 주는 웹페이지 | "버튼으로 찾아서 고르세요"로 거부되고 종류와 주소는 그대로다 |

  @WPS-09 @new
  Scenario: 설정의 주소 "변경"에서 찾으면 후보만 보이고 아무것도 등록되지 않으며 선택하면 그 주소가 칸에 들어간다
    Given 피드가 없는 사이트의 글 목록 페이지에 글이 4개 있다
    When 피드 설정의 "변경"에서 그 주소를 확인한다
    Then 후보에는 "선택" 버튼만 있고 이름, 카테고리, 웹훅, 등록 칸은 없으며 구독은 늘지 않는다
    And 스크립트는 "선택"을 누르면 주소 칸에 그 주소를 넣고 저장 전에는 아무것도 바꾸지 않는다

  @WPS-10 @new
  Scenario: 피드 설정의 주소 칸은 읽기 전용이고 "변경" 버튼으로만 바꾼다
    When 피드 "자유 블로그"의 설정 패널을 연다
    Then 주소 칸은 읽기 전용이고 "변경" 버튼이 있으며 안내에 "변경" 버튼으로 바꾼다고 적혀 있다

