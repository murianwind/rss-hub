@import
Feature: 구독 피드 가져오기 (OPML 업로드)
  기존에 쓰던 피드 목록을 OPML 파일로 올려서 가져온다.
  올린 파일은 바로 저장하지 않고, 미리보기에서 신규 · 중복 · 오류를 확인한 뒤 확정해야 저장한다.
  기존 시스템의 발송 이력이나 대기 글은 가져오지 않는다. 새로 등록한 피드는 첫 점검에서
  지금 있는 글을 "이미 본 글"로만 기록하므로(COL-17) 같은 글이 다시 나가지 않는다.

  Background:
    Given 구독 목록에 주소 "https://a.example.com/feed"와 "https://b.example.com/rss" 피드가 이미 있다

  # ---------- 미리보기 ----------

  @IMP-01 @legacy-parity @legacy:rss_collector.parse_opml
  Scenario: OPML을 올리면 저장하기 전에 신규와 중복을 구분해서 보여 준다
    Given OPML 파일에 피드 5개가 있고 그중 1개는 이미 구독 중인 "https://a.example.com/feed"이다
    When OPML 파일을 올린다
    Then 미리보기에 신규 4개와 중복 1개가 표시된다
    And 이 시점에는 구독 목록이 바뀌지 않는다

  @IMP-04 @legacy-parity @legacy:rss_collector.parse_opml
  Scenario Outline: 피드 이름은 text, title, 주소 순서로 정한다
    Given OPML의 피드 항목에 text가 "<text>", title이 "<title>"로 있고 주소는 "https://n.example.com/rss"이다
    When OPML 파일을 올린다
    Then 미리보기의 피드 이름은 "<name>"이다

    Examples:
      | text   | title  | name                       |
      | 이름A  | 제목B  | 이름A                      |
      |        | 제목B  | 제목B                      |
      |        |        | https://n.example.com/rss  |

  @IMP-05 @new
  Scenario: OPML의 폴더 구조는 카테고리로 가져올 수 있다
    Given OPML에 "IT" 폴더 아래 피드 2개와 "뉴스" 폴더 아래 피드 1개가 있다
    When OPML 파일을 올린다
    Then 미리보기에 새 카테고리 "IT"와 "뉴스"가 제안된다
    When 카테고리 가져오기를 켜고 확정한다
    Then 카테고리 "IT"와 "뉴스"가 만들어진다
    And 각 피드는 자기 폴더의 카테고리에 속한다

  @IMP-06 @new
  Scenario: 카테고리 가져오기를 끄면 피드만 카테고리 없이 등록한다
    Given OPML에 "IT" 폴더 아래 피드 2개가 있다
    When OPML 파일을 올리고 카테고리 가져오기를 끄고 확정한다
    Then 피드 2개가 등록된다
    And 카테고리는 만들어지지 않는다

  # ---------- 중복과 잘못된 항목 ----------

  @IMP-07 @legacy-parity @improvement @legacy:rss_collector.parse_opml
  Scenario Outline: 같은 주소의 피드는 한 번만 가져온다
    # 기존은 정확히 같은 문자열만 중복으로 보았다. 호스트의 대소문자와 끝의 슬래시 차이도 같은 주소로 본다
    Given 파일에 "<first>"와 "<second>" 두 항목이 있다
    When 파일을 올린다
    Then 미리보기에 신규 1개가 표시된다

    Examples:
      | first                       | second                       |
      | https://n.example.com/rss   | https://n.example.com/rss    |
      | https://n.example.com/rss   | https://N.Example.com/rss    |
      | https://n.example.com/rss/  | https://n.example.com/rss    |

  @IMP-08 @new
  Scenario Outline: 주소가 올바르지 않은 항목은 건너뛰고 이유를 보여 준다
    Given 파일에 정상 피드 2개와 주소가 "<url>"인 항목 1개가 있다
    When 파일을 올린다
    Then 미리보기에 신규 2개와 오류 1개가 표시된다
    And 오류 항목에 이유 "<reason>"이 표시된다

    Examples:
      | url                          | reason                     |
      |                              | 주소 없음                  |
      | ftp://x.example.com/feed     | http, https만 가능         |
      | javascript:alert(1)          | http, https만 가능         |
      | https://                     | 호스트 없음                |

  @IMP-09 @new
  Scenario Outline: 파일 자체가 올바르지 않으면 아무것도 저장하지 않고 이유를 알려 준다
    Given <problem> 파일이 있다
    When 파일을 올린다
    Then 오류 메시지 "<message>"가 표시된다
    And 구독 목록은 바뀌지 않는다

    Examples:
      | problem                         | message                                 |
      | XML이 아닌 .opml                | OPML 형식이 올바르지 않음               |
      | 지원하지 않는 확장자(.txt, .json) | OPML 파일만 올릴 수 있음              |
      | 비어 있는                       | 파일이 비어 있음                        |
      | 5MB를 넘는                      | 파일이 너무 큼(최대 5MB)                |
      | 피드가 2000개를 넘는            | 한 번에 가져올 수 있는 피드는 2000개까지 |

  @IMP-10 @new
  Scenario: 한글 이름과 UTF-8 BOM이 있는 파일도 깨지지 않게 읽는다
    Given UTF-8 BOM이 붙은 OPML 파일에 이름이 "스프링 개발 블로그"인 피드가 있다
    When OPML 파일을 올린다
    Then 미리보기의 이름은 "스프링 개발 블로그"이다

  @IMP-11 @new
  Scenario Outline: 외부 엔티티나 엔티티 폭탄이 들어 있는 OPML은 거부한다
    # 인증 없이 열려 있는 업로드 창구이므로 XML 파서를 안전하게 쓴다
    Given <attack>이 들어 있는 OPML 파일이 있다
    When OPML 파일을 올린다
    Then 파일은 거부된다
    And 서버 파일 내용이나 외부 요청 결과가 화면과 로그 어디에도 나타나지 않는다
    And 서버는 계속 정상 응답한다

    Examples:
      | attack                                         |
      | 서버 파일을 읽으려는 외부 엔티티(file://)      |
      | 외부 주소를 호출하려는 외부 엔티티(http://)    |
      | 엔티티를 중첩 확장하는 폭탄(billion laughs)    |

  # ---------- 확정과 취소 ----------

  @IMP-12 @new
  Scenario: 확정하면 신규 피드만 등록하고 결과를 요약해서 보여 준다
    Given 미리보기에 신규 4개, 중복 1개, 오류 1개가 있다
    When 확정한다
    Then 피드 4개가 상태 "baseline_pending"으로 등록된다
    And 결과에 신규 4개, 중복 1개, 오류 1개가 표시된다

  @IMP-13 @new
  Scenario: 확정하지 않고 취소하면 아무것도 저장하지 않는다
    Given 미리보기에 신규 4개가 있다
    When 취소한다
    Then 구독 목록은 바뀌지 않는다

  @IMP-14 @new
  Scenario: 미리보기가 오래되어 만료되면 확정할 수 없고 다시 올리도록 안내한다
    Given 미리보기를 만든 지 61분이 지났다
    And 미리보기 보관 시간은 60분이다
    When 확정한다
    Then 오류 메시지 "미리보기가 만료됨, 파일을 다시 올려 주세요"가 표시된다
    And 구독 목록은 바뀌지 않는다

  @IMP-15 @new
  Scenario: 같은 파일을 다시 올려도 신규는 없다
    Given 같은 파일을 이미 확정까지 가져왔다
    When 같은 파일을 다시 올린다
    Then 미리보기에 신규 0개가 표시된다

  # ---------- 특수 피드와 전환 ----------

  @IMP-16 @improvement @legacy:rss_gizmodo_collector.is_gizmodo_feed
  Scenario Outline: Gizmodo, awesome-blogs 피드는 전용 설정을 제안한다
    # 기존: Gizmodo는 별도 수집기와 보고기, awesome-blogs는 코드 안 하드코딩 주소로 처리했다.
    # 이제는 숨은 규칙이 아니라, 미리보기에서 보여 주고 사용자가 고르는 "프리셋"이다
    Given 피드의 <where>에 "<marker>"가 들어 있다
    When 파일을 올린다
    Then 이 피드에 프리셋 "<preset>"이 제안된다
    When 프리셋을 그대로 두고 확정한다
    Then 이 피드의 폴링 우선순위는 "every_slot"이다
    And 이 피드의 최대 검사 항목 수는 <max_entries>이다
    And 이 피드의 머리말 이모지는 "<emoji>"이다

    Examples:
      | where       | marker        | preset       | max_entries | emoji |
      | 이름        | gizmodo       | Gizmodo      | 120         | 🧪    |
      | 피드 주소   | gizmodo.com   | Gizmodo      | 120         | 🧪    |
      | 사이트 주소 | gizmodo       | Gizmodo      | 120         | 🧪    |
      | 피드 주소   | awesome-blogs | 매 슬롯 점검 | 50          | 📢    |

  @IMP-17 @new
  Scenario: 프리셋 제안을 해제하면 일반 피드로 등록한다
    Given 미리보기에서 Gizmodo 피드에 프리셋이 제안되어 있다
    When 프리셋을 해제하고 확정한다
    Then 이 피드의 폴링 우선순위는 "normal"이다
    And 이 피드의 최대 검사 항목 수는 기본값이다

  @IMP-18 @new
  Scenario: 기존 시스템에서 옮겨 온 피드의 현재 글은 다시 발송하지 않는다
    # 기존 cron이 이미 보낸 글이 새 서비스에서 다시 나가는 것을 막는 핵심 안전장치
    Given 방금 가져온 피드에 오늘 발행된 글 30개가 있다
    When 이 피드를 처음 점검한다
    Then 30개 글은 "이미 본 글"로 기록된다
    And Discord로 나가는 메시지는 없다
    When 그 뒤에 새 글이 올라와서 다음 점검을 한다
    Then 새 글만 수집된다

  # ---------- 서버가 요청을 보내면 안 되는 주소 ----------
  # 인증 없이 열린 서비스에서 서버가 사용자가 준 주소로 요청을 보내게 되므로(SSRF),
  # 집 안의 다른 장치나 클라우드 메타데이터 주소로 가는 요청을 막는다. 사설망 주소는 항상 거부한다(사용자 결정).

  @IMP-19 @new
  Scenario Outline: 사설망, 내부 주소는 가져오지 않는다
    Given 파일에 정상 피드 2개와 주소가 "<url>"인 항목 1개가 있다
    When 파일을 올린다
    Then 미리보기에 신규 2개와 오류 1개가 표시된다
    And 오류 항목에 이유 "사설망·내부 주소는 허용하지 않음"이 표시된다

    Examples:
      | url                                       |
      | http://127.0.0.1/feed                     |
      | http://localhost/rss                      |
      | http://192.168.0.10/rss                   |
      | http://10.0.0.5/rss                       |
      | http://172.16.0.1/rss                     |
      | http://169.254.169.254/latest/meta-data   |
      | http://[::1]/rss                          |
      | http://2130706433/rss                     |
      | http://nas/rss                            |
      | http://printer.local/rss                  |

  @IMP-20 @new
  Scenario: 이름은 공개 주소처럼 보여도 실제로 사설망에 연결되면 점검하는 단계에서 막는다
    # 파일을 가져올 때는 알 수 없고, 연결된 상대의 IP를 보고서야 알 수 있다
    Given 주소가 공개 이름이지만 사설망 주소로 풀리는 피드가 있다
    When 이 피드를 점검한다
    Then 점검은 "ForbiddenAddress"로 실패로 기록된다
    And 사설망 서버는 아무 요청도 받지 않는다

  @IMP-21 @new
  Scenario: 공개 주소의 피드가 사설망으로 리다이렉트해도 막는다
    Given 공개 주소의 피드가 사설망 주소로 리다이렉트한다
    When 이 피드를 점검한다
    Then 점검은 "ForbiddenAddress"로 실패로 기록된다
    And 사설망 서버는 아무 요청도 받지 않는다

