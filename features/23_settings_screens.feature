@screens
Feature: 환경 설정 화면 구성
  환경 설정 메뉴는 목적별 화면으로 나뉜다. 설정, 피드 관리, 주제 관리, Discord, 모델, 백업·복원, 상태.
  입력 칸마다 짧은 설명이 있고, 하위 화면에서는 상위 화면으로 돌아갈 수 있다.

  Background:
    Given 서비스가 시작되어 있다

  @SCR-01
  Scenario: 환경 설정 메뉴는 목적별 화면으로 나뉜다
    When 읽기 화면을 연다
    Then 환경 설정 메뉴는 "설정, 피드 관리, 주제 관리, Discord, 모델, 백업·복원, 상태" 순서이다

  @SCR-02
  Scenario: 설정 화면에는 서비스 주소, 수집과 보관, 화면 항목만 있다
    When 설정 화면을 연다
    Then 항목은 "서비스 주소와 시간대, 수집과 보관, 화면" 순서이다
    And OpenRouter 키, 웹훅, 변경 이력, 백업은 이 화면에 없다

  @SCR-03
  Scenario: Discord 화면에서 웹훅과 역할과 알림 쿨다운을 다룬다
    Given 웹훅 "RSS"와 "OTT"가 등록되어 있다
    When Discord 화면을 연다
    Then 웹훅마다 한 줄에 이름과 시험 전송과 삭제가 있다
    And 웹훅 추가 양식과 역할 지정과 알림 쿨다운이 있다

  @SCR-04
  Scenario: 모델 화면에서 키와 호출 한도와 모델 체인을 다룬다
    When 모델 화면을 연다
    Then OpenRouter 키, 모델 체인, 호출 한도, 무료 모델 스캔이 한 화면에 있다

  @SCR-05
  Scenario: 키를 저장하면 모델 화면에 그대로 머물고 키는 설정됨으로 보인다
    When 모델 화면에서 OpenRouter 키를 저장한다
    Then 모델 화면에 머물고 키는 설정됨으로 보인다

  @SCR-06
  Scenario: 입력 오류는 그 설정이 있는 화면에 표시된다
    When 모델 화면에서 LLM 하루 상한에 "abc"를 저장한다
    And Discord 화면에서 알림 쿨다운에 "abc"를 저장한다
    Then 각각 그 화면에서 오류가 보이고 값은 바뀌지 않는다

  @SCR-07
  Scenario: 백업과 복원은 별도 화면이다
    When 백업·복원 화면을 연다
    Then 내려받기 링크와 파일 올리기 양식이 있다

  @SCR-08
  Scenario: 변경 이력은 상태 화면 아래에 있다
    Given 설정을 한 번 바꿨다
    When 상태 화면을 연다
    Then 변경 이력 항목에 방금 바꾼 설정이 보인다

  @SCR-09
  Scenario: 모든 설정 항목에 짧은 설명이 있다
    Then 설정 항목마다 한 줄 설명이 있다
    And 설정, Discord, 모델 화면의 입력 칸마다 그 설명이 보인다

  @SCR-10
  Scenario Outline: 하위 화면에는 상위 화면으로 돌아가는 링크가 있다
    When <화면>을 연다
    Then "<링크 이름>" 링크가 "<상위>"로 연결된다

    Examples:
      | 화면                  | 링크 이름     | 상위    |
      | 피드 가져오기         | 피드 관리로   | /feeds  |
      | 카테고리 관리         | 피드 관리로   | /feeds  |
      | 복원 결과             | 백업·복원으로 | /backup |

  @SCR-11
  Scenario: 주제 관리는 주제 목록, 판별 시험 순서이다
    Given 주제가 하나 있다
    When 주제 관리 화면을 연다
    Then 제목은 "주제 목록", "판별 시험" 순서로 나온다
