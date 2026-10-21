@plain
Feature: OpenRouter 키 없이 쓰기
  OpenRouter 키가 없어도 Discord 웹훅과 서비스 주소가 있으면 서비스는 새 글을 번역과 요약 없이
  원문 제목과 서비스 글 링크로 알린다. LLM을 부르지 않는다.
  주제는 키워드가 맞는 것만 해당한다(키워드가 없어서 LLM만으로 정하는 주제는 해당하지 않는다).
  키를 나중에 넣으면 그 뒤에 수집한 글부터 요약한다.

  Background:
    Given OpenRouter 키는 설정하지 않았다
    And 기본 웹훅과 서비스 주소는 설정했다

  @PLN-01
  Scenario: 키가 없으면 원문 제목과 링크만 보낸다
    Given 새 글 "Apple unveils new phone"이 수집되었다
    When 요약 잡과 발송 잡이 차례로 실행된다
    Then LLM 호출은 없다
    And 기본 웹훅으로 "Apple unveils new phone"과 서비스 글 링크가 든 메시지가 한 건 간다
    And 메시지에 요약 줄은 없다

  @PLN-02
  Scenario: 키가 없어도 웹훅이나 서비스 주소가 없으면 기다린다
    Given 기본 웹훅 지정을 해제했다
    And 새 글 "Apple unveils new phone"이 수집되었다
    When 요약 잡과 발송 잡이 차례로 실행된다
    Then 글은 수집된 상태로 남고 아무것도 보내지 않는다

  @PLN-03
  Scenario: 키워드가 맞는 주제는 그 주제의 웹훅으로도 보낸다
    Given 키워드 "steam"이 있고 웹훅 "게임"이 지정된 주제 "게임"이 있다
    And 새 글 "Steam sale starts"이 수집되었다
    When 요약 잡과 발송 잡이 차례로 실행된다
    Then 기본 웹훅과 웹훅 "게임"으로 한 건씩 간다

  @PLN-04
  Scenario: 키워드가 없는 주제는 LLM이 있어야 해당하므로 키가 없으면 해당하지 않는다
    Given 키워드가 없고 웹훅 "게임"이 지정된 주제 "게임"이 있다
    And 새 글 "Steam sale starts"이 수집되었다
    When 요약 잡과 발송 잡이 차례로 실행된다
    Then 기본 웹훅으로만 한 건 간다

  @PLN-05
  Scenario: 키를 나중에 넣으면 이미 보낸 글은 그대로 두고 이후 글부터 요약한다
    Given 새 글 "Apple unveils new phone"이 수집되었다
    And 요약 잡과 발송 잡이 차례로 실행되었다
    When OpenRouter 키를 설정한다
    And 새 글 "Second story"이 수집되고 요약 잡이 실행된다
    Then 첫 글은 다시 요약되지 않고 LLM 호출은 두 번째 글에 대해서만 한 번 있다

  @PLN-06
  Scenario: 상태 화면은 OpenRouter 키를 선택 항목으로 보여 준다
    When 상태 화면을 연다
    Then "OpenRouter 키"는 "선택"으로 표시되고 필요한 설정이 모두 채워졌다고 안내한다
