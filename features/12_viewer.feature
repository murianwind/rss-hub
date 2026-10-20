@m4
Feature: 뷰어(M4): 사이드바, 글 목록, 글 페이지

  Discord로 알림을 받는 것 말고도 서비스 안에서 글을 볼 수 있어야 한다. 사이드바는 RSS, 카테고리, 주제가
  같은 레벨이고, 글 본문은 외부 사이트가 준 HTML이라 항상 정제해서 보여 준다. 번역은 Safari의 페이지 번역에
  맡기고, 글 영역에 언어를 표시한다.

  Background:
    Given 사이트 "뉴스 블로그"(카테고리 "뉴스")와 "자유 블로그"(카테고리 없음)가 등록되어 있다
    And 주제 "OTT"가 있다

  # ---------- 사이드바 ----------

  @VWR-01 @new
  Scenario: 사이드바에는 RSS, 카테고리, 주제, 환경 설정 네 구역이 있다
    When 읽기 화면을 연다
    Then 사이드바에는 "RSS", "카테고리", "주제", "환경 설정" 구역이 이 순서로 있다
    And RSS 아래에는 등록된 사이트 전체("뉴스 블로그", "자유 블로그")가 있다
    And 카테고리 "뉴스" 아래에는 사이트 "뉴스 블로그"가 있고 "자유 블로그"는 없다
    And 주제 아래에는 사이트 없이 주제 "OTT"만 있다

  @VWR-13 @new
  Scenario: 좁은 화면에서는 사이드바가 서랍으로 열린다
    When 읽기 화면을 연다
    Then 사이드바는 한 곳에만 있고 메뉴 버튼으로 서랍처럼 열 수 있다

  # ---------- 글 목록 ----------

  @VWR-02 @new
  Scenario: 사이트를 고르면 그 사이트의 글만 최신순으로 나온다
    Given 사이트 "뉴스 블로그"에 글 "오래된 글"(10시 00분)과 "새 글"(10시 30분)이 있다
    And 사이트 "자유 블로그"에 글 "다른 글"이 있다
    When 사이드바에서 사이트 "뉴스 블로그"를 고른다
    Then 글 목록은 "새 글", "오래된 글" 순서이고 "다른 글"은 없다

  @VWR-03 @new
  Scenario: 카테고리를 고르면 그 카테고리 사이트들의 글이 나온다
    Given 사이트 "뉴스 블로그"에 글 "뉴스 글"이 있다
    And 사이트 "자유 블로그"에 글 "다른 글"이 있다
    When 사이드바에서 카테고리 "뉴스"를 고른다
    Then 글 목록에는 "뉴스 글"만 있다

  @VWR-04 @new
  Scenario: 주제를 고르면 그 주제로 분류된 글만 나오고, 알림을 보냈는지와 상관없다
    Given 사이트 "자유 블로그"에 주제 "OTT"로 분류된 글 "OTT 글"이 있고 아직 알림을 보내지 않았다
    And 사이트 "자유 블로그"에 글 "일반 글"이 있다
    When 사이드바에서 주제 "OTT"를 고른다
    Then 글 목록에는 "OTT 글"만 있다

  @VWR-05 @new
  Scenario: 글 목록은 30개씩 쪽으로 나뉜다
    Given 사이트 "자유 블로그"에 글 35개가 있다
    When 읽기 화면을 연다
    Then 글 30개가 나오고 "다음" 링크가 있다
    When 2쪽을 연다
    Then 글 5개가 나오고 "이전" 링크가 있다

  @VWR-14 @new
  Scenario: 없는 목록이나 글은 404로 답하고 사이드바는 그대로 보인다
    When 없는 카테고리 목록을 연다
    Then 404로 답하고 사이드바가 그대로 있다
    When 없는 글을 연다
    Then 404로 답하고 사이드바가 그대로 있다

  # ---------- 글 페이지 ----------

  @VWR-06 @new
  Scenario: 글 페이지는 번역 제목, 요약, 해당 주제와 키워드, 원문으로 가는 제목 링크를 보여 준다
    Given 사이트 "자유 블로그"에 원래 제목 "Netflix announces a drama", 번역 제목 "넷플릭스 신작 공개", 요약 "신작이 공개된다"인 글이 있다
    And 그 글은 주제 "OTT"에 키워드 "netflix"로 해당했다
    When 그 글을 연다
    Then 제목 "넷플릭스 신작 공개"와 원래 제목, 요약 "신작이 공개된다"가 보인다
    And 주제 "OTT"와 키워드 "netflix"가 보인다
    And 제목은 원문으로 가는 링크다

  @VWR-09 @new
  Scenario Outline: 제목의 원문 링크는 새 탭에서 열리고, 이동할 수 없는 주소면 제목은 링크가 아니다
    Given 사이트 "자유 블로그"에 원문 주소가 "<link>"인 글이 있다
    When 그 글을 연다
    Then 제목은 <result>

    Examples:
      | link                       | result                                |
      | https://example.com/orig   | 원문으로 가는 링크이고 새 탭에서 안전하게 열린다 |
      | javascript:alert(1)        | 링크가 아니다                            |
      | ftp://example.com/file     | 링크가 아니다                            |

  @VWR-07 @new
  Scenario Outline: 본문의 위험한 내용은 지우고 글자만 보여 준다
    Given 사이트 "자유 블로그"에 본문이 "<p>안전한 글</p><payload>"인 글이 있다
    When 그 글을 연다
    Then 본문에 "안전한 글"은 보이고 "<danger>"는 없다

    Examples:
      | payload                                          | danger         |
      | <script>alert(1)</script>                        | <script        |
      | <img src=x onerror=alert(1)>                     | onerror        |
      | <a href="javascript:alert(1)">링크</a>           | javascript:    |
      | <iframe src="https://evil.example.com"></iframe> | <iframe        |
      | <p onclick="alert(1)">클릭</p>                   | onclick        |
      | <div style="position:fixed">덮개</div>           | style=         |
      | <form action="https://evil.example.com"></form>  | <form          |

  @VWR-08 @new
  Scenario: 본문의 이미지는 https만 보이고 추적용 1픽셀 이미지와 http 이미지는 지운다
    Given 사이트 "자유 블로그"에 본문에 https 이미지, http 이미지, 1픽셀 이미지가 하나씩 있는 글이 있다
    When 그 글을 연다
    Then 본문에는 https 이미지만 있다
    And 이미지는 referrer 없이 늦게 불러오도록 표시된다

  @VWR-12 @new
  Scenario Outline: 글 영역에 언어를 표시해서 Safari의 페이지 번역이 동작하게 한다
    Given 사이트 "자유 블로그"에 본문이 "<body>"인 글이 있다
    When 그 글을 연다
    Then 본문 영역의 언어 표시는 "<lang>"이다

    Examples:
      | body                                                   | lang |
      | 스프링 부트 마이그레이션 후기를 정리했다               | ko   |
      | The new phone has a bigger battery and a better camera | en   |
      | これは日本語の文章です                                 | 없음 |

  # ---------- 보관 글과 정리 ----------

  @VWR-10 @new
  Scenario: 첫 점검 때 최근 글 5개가 알림 없이 보관 글로 저장되어 뷰어에 보인다
    Given 방금 가져온 피드에 글 30개가 있다
    When 이 피드를 처음 점검한다
    Then 뷰어에는 가장 최근 글 5개가 보인다
    And 보관 글은 요약하거나 발송하지 않는다
    And 다음 점검에서도 그 글들이 다시 수집되지 않는다

  @VWR-11 @new
  Scenario: 보관 기간이 지난 글은 지워지고 같은 글이 다시 수집되지 않는다
    Given 사이트 "자유 블로그"에 글 "오래된 글"이 있다
    And 100일이 지났다
    And 사이트 "자유 블로그"에 글 "새 글"이 있다
    When 보관 기간 정리를 실행한다
    Then 목록에는 "새 글"만 있다
    And "오래된 글"은 다시 수집되지 않는다
