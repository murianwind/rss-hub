@settings
Feature: 설정 화면
  Docker 컨테이너에는 환경 변수를 주지 않고, 설정은 모두 웹 화면에서 한다.
  컨테이너가 알아야 하는 것은 데이터 볼륨과 포트뿐이다.
  비밀 값(OpenRouter 키, 웹훅 주소)은 저장한 뒤 다시 보여 주지 않는다.

  # 인증은 보류되어 있다(NPM으로 외부 공개). 그래서 설정 화면에서 할 수 있는 일은 아래처럼 제한하고
  # 변경 이력을 남긴다. 관리 화면 보호(선택 기능)는 이후 마일스톤에서 설정 항목으로 추가한다.

  # ---------- 첫 실행 ----------

  @SET-01 @new
  Scenario: 환경 변수와 저장된 설정이 하나도 없어도 서비스는 시작하고 필요한 설정을 안내한다
    Given 컨테이너에 사용자가 정한 환경 변수가 하나도 없다
    And 저장된 설정이 비어 있다
    When 서비스를 시작한다
    Then 서비스는 정상적으로 시작된다
    And 상태 화면에 다음 항목이 "미설정"으로 표시된다
      | 항목          |
      | OpenRouter 키 |
      | 기본 웹훅     |
      | 서비스 주소   |

  @SET-02 @new
  Scenario: 필요한 설정을 모두 채우면 재시작 없이 상태 화면의 안내가 사라진다
    Given 서비스가 설정 없이 시작되어 있다
    When OpenRouter 키, 기본 웹훅, 서비스 주소를 저장한다
    Then 상태 화면의 "미설정" 안내가 사라진다
    And 서비스를 다시 시작하지 않았다

  @SET-21 @new
  Scenario: 필요한 설정이 없으면 작업은 기다리고, 채우면 재시작 없이 동작을 시작한다
    # 수집 · 요약 · 발송 잡이 만들어지는 단계에서 연결한다
    Given 서비스가 설정 없이 시작되어 있고 수집된 글 1개가 "collected" 상태이다
    Then 요약 작업은 LLM을 호출하지 않고 글은 그대로 남는다
    When OpenRouter 키, 기본 웹훅, 서비스 주소를 저장한다
    Then 다음 요약 작업부터 LLM을 호출한다
    And 요약이 끝난 글은 다음 발송 작업에서 보낸다

  # ---------- 반영 방식 ----------

  @SET-03 @new
  Scenario Outline: 설정을 저장하면 재시작 없이 다음 실행부터 반영된다
    When "<setting>"을 "<value>"로 바꿔 저장한다
    Then <effect>

    Examples:
      | setting         | value                   | effect                                          |
      | 서비스 주소     | https://new.example.com | 새 메시지의 링크가 새 주소로 만들어진다         |
      | LLM 하루 상한   | 100                     | 오늘 호출 수가 100이 되면 호출이 멈춘다         |
      | 모델 체인       | model-c                 | model-c만 호출한다                              |
      | 서비스 시간대   | America/New_York        | "오늘" 판단이 새 시간대 기준으로 바뀐다         |

  @SET-04 @new
  Scenario: 수집 · 요약 · 발송 주기를 바꾸면 진행 중인 작업을 끝낸 뒤 새 주기로 다시 등록한다
    Given 요약 작업이 실행 중이다
    When 요약 주기를 60초에서 30초로 바꿔 저장한다
    Then 실행 중인 요약 작업은 끝까지 마친다
    And 그다음부터 요약 작업은 30초 간격으로 실행된다
    And 서비스를 다시 시작할 필요가 없다

  # ---------- 비밀 값 ----------

  @SET-05 @new
  Scenario: 비밀 값은 저장한 뒤 화면과 응답에 다시 나타나지 않는다
    Given OpenRouter 키와 웹훅 주소를 저장했다
    When 설정 화면과 설정 API 응답을 확인한다
    Then 각 항목은 "설정됨"으로만 표시된다
    And 키와 웹훅 주소의 값은 어디에도 없다
    And 서버 로그에도 값이 남아 있지 않다

  @SET-06 @new
  Scenario: 비밀 입력칸을 비워 두고 저장하면 기존 값을 유지한다
    Given OpenRouter 키가 이미 저장되어 있다
    When 키 입력칸을 비워 둔 채 다른 설정만 바꿔 저장한다
    Then 저장된 OpenRouter 키는 그대로이다

  @SET-07 @new
  Scenario: 웹훅을 지우려면 명시적으로 삭제해야 하고, 역할로 지정된 곳은 비워진다
    # 피드와 카테고리의 웹훅 지정이 비워지는 부분은 해당 화면이 생기는 M2에서 연결한다
    Given 웹훅 "dev"가 저장되어 있고 시스템 알림 웹훅으로 지정되어 있다
    When 웹훅 "dev"를 삭제한다
    Then 웹훅 "dev"는 목록에서 사라진다
    And 시스템 알림 웹훅 지정은 비워진다

  # ---------- 입력 검증 ----------

  @SET-08 @new
  Scenario Outline: 서비스 주소는 http, https 주소만 받고 끝의 슬래시를 정리한다
    When 서비스 주소를 "<input>"으로 저장한다
    Then 결과: <result>

    Examples:
      | input                         | result                                      |
      | https://rss.example.com/      | 저장되고 값은 https://rss.example.com       |
      | http://192.168.0.5:8000       | 저장되고 값은 http://192.168.0.5:8000       |
      | https://example.com/rss/      | 저장되고 값은 https://example.com/rss       |
      | rss.example.com               | 오류 "http:// 또는 https://로 시작해야 함"  |
      | ftp://rss.example.com         | 오류 "http:// 또는 https://로 시작해야 함"  |
      | javascript:alert(1)           | 오류 "http:// 또는 https://로 시작해야 함"  |

  @SET-09 @new
  Scenario Outline: 웹훅 주소는 Discord 웹훅 형식만 받는다
    # 인증 없는 화면에서 임의의 주소로 요청이 나가는 것(SSRF)을 막기 위한 제한이다
    When 웹훅 주소를 "<url>"로 저장한다
    Then 결과: <result>

    Examples:
      | url                                                  | result                                |
      | https://discord.com/api/webhooks/123/abcDEF          | 저장된다                              |
      | https://discordapp.com/api/webhooks/123/abcDEF       | 저장된다                              |
      | https://ptb.discord.com/api/webhooks/123/abcDEF      | 저장된다                              |
      | http://discord.com/api/webhooks/123/abcDEF           | 오류 "https만 가능"                   |
      | https://evil.example.com/api/webhooks/123/abcDEF     | 오류 "Discord 웹훅 주소가 아님"       |
      | https://discord.com.evil.example.com/api/webhooks/1/a | 오류 "Discord 웹훅 주소가 아님"      |
      | https://192.168.0.10/api/webhooks/123/abcDEF         | 오류 "Discord 웹훅 주소가 아님"       |
      | https://discord.com/api/other/123/abc                | 오류 "Discord 웹훅 주소가 아님"       |

  @SET-10 @new
  Scenario Outline: 주기 설정은 허용 범위 안의 값만 받는다
    When <setting>을 "<value>"로 저장한다
    Then 결과: <result>

    Examples:
      | setting         | value | result                                  |
      | 수집 주기(분)   | 5     | 저장된다                                |
      | 수집 주기(분)   | 60    | 저장된다                                |
      | 수집 주기(분)   | 7     | 오류 "60의 약수만 가능(1,2,3,4,5,6,10,12,15,20,30,60)" |
      | 수집 주기(분)   | 0     | 오류 "60의 약수만 가능(1,2,3,4,5,6,10,12,15,20,30,60)" |
      | 요약 주기(초)   | 10    | 저장된다                                |
      | 요약 주기(초)   | 9     | 오류 "10~3600초 사이"                   |
      | 발송 주기(초)   | 3600  | 저장된다                                |
      | 발송 주기(초)   | 3601  | 오류 "10~3600초 사이"                   |

  @SET-11 @new
  Scenario Outline: 시간대는 IANA 이름만 받는다
    When 서비스 시간대를 "<zone>"으로 저장한다
    Then 결과: <result>

    Examples:
      | zone             | result                       |
      | Asia/Seoul       | 저장된다                     |
      | UTC              | 저장된다                     |
      | KST              | 오류 "IANA 시간대 이름이 아님" |
      | Korea Standard   | 오류 "IANA 시간대 이름이 아님" |

  @SET-12 @new
  Scenario Outline: 모델 체인은 비어 있지 않아야 하고 순서와 중복을 정리해서 저장한다
    When 모델 체인을 "<input>"으로 저장한다
    Then 결과: <result>

    Examples:
      | input                  | result                         |
      | model-a, model-b       | 저장되고 순서는 model-a, model-b |
      | model-a, model-a       | 저장되고 값은 model-a 하나      |
      |                        | 오류 "모델이 하나 이상 필요"    |

  # ---------- 확인 도구 ----------

  @SET-13 @new
  Scenario: 웹훅 시험 전송은 선택한 웹훅으로 시험 메시지 한 건만 보내고 결과를 알려 준다
    Given 웹훅 "dev"가 저장되어 있다
    When 웹훅 "dev"의 시험 전송을 누른다
    Then "dev"로 시험 메시지 1건이 나간다
    And 성공하면 "성공"이, 실패하면 상태 코드와 이유가 표시된다
    And 웹훅 주소는 결과 화면에 나타나지 않는다

  @SET-14 @new
  Scenario: OpenRouter 키 확인은 키 정보만 조회하고 채팅 호출은 하지 않는다
    Given OpenRouter 키가 저장되어 있다
    When 키 확인을 누른다
    Then 키가 유효한지 여부와 사용량 정보가 표시된다
    And 요약용 채팅 호출은 일어나지 않는다
    And 오늘 운영 호출 수는 늘지 않는다

  @SET-15 @new
  Scenario: 현재 접속한 주소를 서비스 주소 후보로 제안하되, 확인해야만 저장한다
    Given 설정 화면을 "https://rss.example.com"으로 열었다
    And 서비스 주소가 비어 있다
    Then "https://rss.example.com"이 후보로 표시된다
    And 후보를 확인하기 전에는 저장되지 않는다

  # ---------- 이력 ----------

  @SET-18 @new
  Scenario: 설정을 바꾸면 항목, 시각, 요약을 변경 이력에 남기고 비밀 값은 값 없이 "변경됨"만 남긴다
    When 서비스 주소를 바꾸고 OpenRouter 키를 새로 저장한다
    Then 변경 이력에 "서비스 주소 변경"과 "OpenRouter 키 변경됨"이 시각과 함께 남는다
    And 이력에는 이전 키 값도 새 키 값도 없다

  # ---------- 인증이 없는 화면을 지키는 최소 장치 ----------

  @SET-19 @new
  Scenario Outline: 다른 사이트에서 보낸 설정 변경 요청은 거부한다
    # 인증이 없으므로, 사용자의 브라우저를 이용해 다른 사이트가 설정을 바꾸는 것(CSRF)을 막는다
    Given 서비스 주소가 "https://old.example.com"으로 저장되어 있다
    When <source>에서 서비스 주소를 "https://evil.example.com"으로 바꾸는 요청이 온다
    Then 요청은 <result>

    Examples:
      | source                                         | result                           |
      | 같은 주소의 화면(Origin이 서비스 주소와 같음)  | 받아들여지고 주소가 바뀐다       |
      | 다른 사이트(Origin이 다른 주소)                | 거부되고 주소는 그대로이다       |
      | 브라우저가 "cross-site"로 표시한 요청          | 거부되고 주소는 그대로이다       |
      | 프록시가 넘긴 공개 주소와 Origin이 같은 요청   | 받아들여지고 주소가 바뀐다       |

  @SET-20 @new
  Scenario: 화면 응답에는 캐시 금지와 보안 헤더가 붙는다
    When 설정 화면을 연다
    Then 응답에 캐시를 막는 헤더가 있다
    And 응답에 다른 사이트의 프레임 삽입과 외부 스크립트 실행을 막는 헤더가 있다
