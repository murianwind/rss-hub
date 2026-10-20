# M1 테스트 설계

개발 순서: 계획 → 설계 → **사용자 확인** → **테스트(이 문서)** → 구현 → 테스트 → 리팩토링.
이 문서와 `features/*.feature`는 사용자 확인을 받은 뒤 테스트 코드(스텝 정의, 단위 테스트)로 옮긴다.

---

## 1. 원칙

1. **시나리오가 인수 기준이다.** `features/`의 시나리오가 전부 통과하면 M1이 끝난다.
2. **기존 동작은 골든 데이터로 고정한다.** `tests/golden/legacy_golden.json`은 기존 스크립트를 실제로 실행해서 만든 값이다. `parity`는 새 구현이 같아야 하고, `known_defects`는 다르게 나와야 한다.
3. **테스트 가능한 구조가 먼저다.** 시간, 네트워크, LLM, Discord는 포트 뒤에 둔다. 테스트는 가짜 구현을 주입한다.
4. **데이터베이스는 가짜로 만들지 않는다.** 서비스 테스트는 실제 SQLite(임시 파일)를 쓴다. 쿼리와 제약 조건이 테스트 대상이기 때문이다.
5. **실제 외부 호출은 기본으로 꺼 둔다.** OpenRouter와 Discord 실호출 테스트는 `live` 표식을 붙여 명시적으로만 실행한다(하루 한도 소모).
6. **설정은 환경 변수가 아니라 저장소(DB)에서 읽는다.** 테스트는 설정 저장소에 값을 넣어 시작하고, 환경 변수 없이도 서비스가 뜨는지를 시나리오(SET-01)로 확인한다.

---

## 2. 테스트 계층

| 계층 | 대상 | 도구 | 비중 | 속도 |
|---|---|---|---|---|
| 단위 | `domain/*` 순수 함수 | pytest, 매개변수화 | 약 55% | 밀리초 |
| 골든(parity) | 기존 동작 대비 | pytest + `legacy_golden.json` | 단위에 포함 | 밀리초 |
| 시나리오(BDD) | `services/*` 유스케이스 | pytest-bdd + 가짜 포트 + 실제 SQLite | 약 28% | 수십 밀리초 |
| 어댑터 | `adapters/*` | respx(HTTP 모킹), 임시 SQLite | 약 8% | 수십 밀리초 |
| 웹 | 관리 화면 3개, `/healthz`, `/status`, `/a/{id}` | FastAPI `TestClient`(HTML과 응답 검사) | 약 7% | 수십 밀리초 |
| 보안 | 업로드, 설정, 비밀 노출 | 시나리오 + 응답/로그 스캔 | 위 계층에 포함 | |
| 실호출(live) | OpenRouter, Discord | pytest `-m live` | 약 2% | 초 단위, **기본 제외** |

웹 화면은 서버가 만든 HTML의 내용과 동작(폼 제출, 오류 메시지, 확인 단계)을 검사한다. **실제 화면 렌더링은 자동 테스트로 보장하지 않으므로 §10의 수동 점검을 함께 한다.**

---

## 3. 테스트 더블

| 포트 | 가짜 구현 | 할 수 있는 것 |
|---|---|---|
| `Clock` | `FakeClock` | 시각 지정, 시간 진행, UTC/서비스 시간대 전환 (기존의 `RSS_TARGET_DATE` 환경 변수 대신 사용) |
| `FeedFetcher` | `FakeFeedFetcher` | RSS/Atom XML 픽스처 반환, 304, 시간 초과, 오류 주입 |
| `LLMClient` | `ScriptedLLM` | 호출 순서별 응답 스크립트(정상, 불량, 429+Retry-After, 5xx, 402), 호출 기록, 키 정보 응답 |
| `WebhookSender` | `RecordingSender` | 전송 기록, 웹훅별 응답 스크립트(2xx, 429, 401/403/404, 5xx) |
| 대기 | `FakeSleeper` | `Retry-After` 대기를 실제로 기다리지 않고 기록만 함 |
| 잡 스케줄러 | `FakeScheduler` | 등록된 잡과 간격을 조회, 재등록 확인 (SET-04, SCH-15) |

가짜는 `tests/fakes/`에 한 번만 만들고 모든 시나리오가 공유한다.

---

## 4. 픽스처와 데이터

```
tests/
  features/            ← features/*.feature (심볼릭 링크 또는 복사)
  steps/               ← pytest-bdd 스텝 정의 (기능별 파일, 공용 스텝은 common.py)
  unit/                ← 순수 함수 단위 테스트
  adapters/            ← 어댑터 테스트
  web/                 ← 화면/엔드포인트 테스트
  fakes/               ← 가짜 포트 구현
  fixtures/
    feeds/             ← rss_basic.xml, atom_basic.xml, naver_tracking.xml, no_date.xml, many_entries.xml
    uploads/           ← 가져오기 파일은 OPML만 쓴다. 현재 테스트는 파일을 코드로 만들어서 쓴다
                          (정상, 폴더 구조, BOM, 잘못된 주소, XML이 아님, 빈 파일, 5MB 초과, 2000개 초과,
                          외부 엔티티 file://와 http://, 엔티티 폭탄)
    llm/               ← good.json, reasoning_leak.json, hanja.json, truncated.json ...
  golden/
    legacy_golden.json
```

- 피드 픽스처는 실제 피드 형태를 따르되 내용은 자체 작성한 가짜 글이다.
- 가져오기 픽스처는 실제 구독 파일의 **구조만** 따르고 값은 가짜로 채운다. 실제 구독 주소, 웹훅 주소, 키를 테스트 저장소에 넣지 않는다.
- 공격용 XML(`xxe_*`, `billion_laughs`)은 서버 파일이나 외부 주소를 실제로 읽지 못하도록 **테스트 안에서 존재하지 않는 경로/주소**를 가리키게 만든다.
- 용량/개수 초과 파일은 테스트 실행 중에 생성한다(저장소에 큰 파일을 두지 않는다).
- 골든 JSON은 `tools/generate_legacy_golden.py`로 만든다. 기존 코드가 바뀌지 않는 한 다시 만들 필요가 없다.

---

## 5. 시나리오 구성

| 파일 | 시나리오 | 펼친 케이스 | 주 대상 |
|---|---:|---:|---|
| `01_scheduling.feature` | 15 | 44 | 슬롯 배치, 수집 주기, 점검 횟수, 재생성, 겹침 방지 |
| `02_collection.feature` | 24 | 38 | 날짜 필터, GUID, 중복, 기준선, 오류 격리 |
| `03_summarization.feature` | 20 | 32 | 요약 계약, 검증, 재시도, 폴백, 장애 구분 |
| `04_topic_judgement.feature` | 15 | 28 | 주제 판정(LLM 확인 + 키워드 보완) |
| `05_delivery.feature` | 23 | 32 | 라우팅, 메시지, 길이 제한, 실패 처리, 서비스 주소 |
| `06_llm_budget.feature` | 17 | 17 | 모델 체인, 예산, 알림 쿨다운, 설정 즉시 반영 |
| `07_feed_import.feature` | 19 | 44 | OPML 업로드, 미리보기, 확정, 보안, 프리셋, 사설망 차단 |
| `08_service_endpoints.feature` | 8 | 10 | 상태 확인, 임시 링크, 종료 |
| `09_settings.feature` | 19 | 49 | 설정 화면, 검증, 비밀 값, 주기 변경, 요청 출처 확인 |
| `10_topics_and_categories.feature` | 14 | 18 | 기본 주제, 주제 입력 규칙, 카테고리 웹훅 |
| `11_feed_management.feature` | 14 | 26 | M2: 개별 등록, 자동 탐색, 편집, 삭제, OPML 내보내기 |
| `12_viewer.feature` | 14 | 24 | M4: 사이드바, 글 목록, 글 페이지, 본문 정제, 보관 글과 정리 |
| `13_topic_feedback.feature` | 12 | 20 | M5: 싫어요, 주제로, 키워드 개선 제안, 요청의 예시 |
| `14_model_management.feature` | 12 | 17 | M3: 무료 모델 스캔, 벤치마크, 추천, 교체 |
| `15_reader_ui.feature` | 12 | 23 | 읽기 화면: 사이드바, 읽음, 북마크, 검색과 필터, 돌아가기, 인라인 금지 |
| `16_ui_management.feature` | 12 | 22 | 슬라이드 패널, 순서와 이동, 설정 탭, 디스플레이 설정 |
| **합계** | **250** | **444** | (Scenario Outline 58개 포함) |

**BDD 연결 현황(읽기 화면 재구현 2단계 시점)**: 250개 시나리오를 모두 `.feature` 그대로 실행한다(연결하지 못한 것 없음). 패널, 순서와 이동, 설정 탭(PNL-01~12)이 이번에 더해졌다. 스크립트(`app.js`)는 자동 시험이 없고 실제 크롬으로 확인했다(사용자 결정).

### 태그 규약
| 태그 | 의미 | 검증 방법 |
|---|---|---|
| `@legacy-parity` | 기존과 같아야 함 | 골든 `parity` 값과 비교 |
| `@improvement` | 의도적으로 바꿈 | 골든 `known_defects`의 `new_expected`와 비교, 설계 문서 §12 승인 |
| `@new` | 신규 동작 | 시나리오 자체 |
| `@legacy:<파일.함수>` | 대응하는 기존 코드 | 추적성 매트릭스 |
| `@XXX-NN` | 시나리오 ID | 문서와 커밋 메시지에서 참조 |

---

## 6. 추적성 매트릭스 (기존 기능 → 시나리오)

요구사항 10번("기존 스크립트의 모든 기능 유지")의 검증 근거다. 비어 있는 행이 없어야 한다.

| 기존 코드 | 기능 | 시나리오 |
|---|---|---|
| `rss_collector.get_feeds` / `parse_opml` | 피드 목록 로드, 이름 결정 순서, 중복 제거 | IMP-01~04, IMP-07 |
| `rss_collector.is_gizmodo_feed` + Gizmodo 수집기 | Gizmodo 분리 | IMP-16, IMP-17, SCH-06 |
| `rss_collector.normalize_guid` | 추적 파라미터 제거 | COL-09, COL-10 |
| `rss_collector.guid_for` | GUID 우선순위 | COL-08 |
| `rss_collector.parsed_entry_datetime` | 발행 시각 해석 | COL-03~06 |
| `rss_collector.fetch_feed` | 시간 제한, 리다이렉트, 조건부 요청, 피드가 아닌 응답, 크기 제한 | COL-21, 22, 23, 24 (어댑터 테스트 포함) |
| `rss_collector.current_slot` | 슬롯 번호 | SCH-09, SCH-15 |
| `rss_collector.desired_checks_per_hour` / `feed_activity_score` | 활동량별 횟수와 점수 | SCH-03, SCH-06, SCH-07 |
| `rss_collector.build_hourly_schedule` / `get_schedule` | 슬롯 배치, 용량, 재사용 | SCH-01, 02, 04, 05, 08, 10, 11, 14 |
| `rss_collector.update_feed_stats` | 활동 통계 | COL-15 |
| `rss_collector.main` | 오늘 글 필터, 중복, 최대 항목 수, 오류 격리, 본문 보관 | COL-01, 02, 11~14, 16, 19 |
| `rss_translator.strip_html` | HTML 제거, 1500자 | SUM-04 |
| `rss_translator.is_korean` | 한글 비율 판별 | SUM-02, SUM-03 |
| `rss_translator.needs_retranslation` | 불량 응답 판정(형식 표지, 사고 과정 문구, 한자) | SUM-05, SUM-09 |
| `rss_translator.main` / Gizmodo 번역기 | 요약, 재시도, 3회 폴백, 처리 개수 | SUM-01, 03, 06~08, 12~14 |
| `rss_llm.summarize_item` | 프롬프트, 모델 순회, 429 대기 | SUM-01, BUD-01~04, BUD-13 |
| `rss_llm._send_alert_webhook` (미사용) | 시스템 알림 | BUD-07, 08, 11, 12, DLV-14, 15 |
| `rss_reporter.is_ott_related` | LLM + 키워드(이제 기본 주제 "OTT"의 판별) | TPC-01~08 |
| `rss_reporter.format_discord_message` | 메시지 형식, 시각 | DLV-06~08 |
| `rss_reporter.send_discord` | 길이 제한 | DLV-09, 10 |
| `rss_reporter.main` / Gizmodo 보고기 | 발송 대상, OTT 추가 발송, 기록, 제거 | DLV-02, 05, 11, 12 |
| 코드 안 웹훅 주소, 환경 변수(`RSS_BATCH_SIZE` 등) | 설정 | SET-01~18, DLV-17 |
| `rss_sent_guids.json`, `rss_pending.json` 이전 | **이전하지 않음**(기준선 방식) | COL-17, COL-18, IMP-18, SET-16 |
| `RSS_TARGET_DATE` 환경 변수 | 시험용 날짜 고정 | 제거. 테스트에서는 `FakeClock` 사용 |

신규 기능의 시나리오: 라우팅(DLV-01, 03, 04), 기준선(COL-17, 18), 조건부 GET(COL-21), 겹침 방지(SCH-12), 예산(BUD-05~10, 14), 서비스 주소(DLV-19, 20, SET-08, 15), 엔드포인트(SVC-01~07, 10).

---

## 7. 골든 데이터 사용법

```
parity            새 구현(f)이 골든의 expected와 같아야 한다.            assert f(input) == expected
known_defects     새 구현이 레거시와 달라야 한다.                       assert f(input) == new_expected  and  legacy != new_expected
invariants        정확한 배치가 아니라 만족해야 할 성질.                 assert 조건
```

| 골든 섹션 | 대응 단위 테스트 | 비고 |
|---|---|---|
| `normalize_guid` | `domain/guid` | 입력 11개, 멱등성 포함 |
| `guid_for` | `domain/guid` | |
| `parsed_entry_datetime` | `domain/dates` | 서비스 시간대 `Asia/Seoul` 고정 |
| `is_korean` | `domain/korean` | 경계값(10%) 포함 |
| `needs_retranslation` | `domain/validation` | 레거시 불량 판정 규칙 중 형식 표지, 사고 과정 문구, 한자에 해당하는 부분. 이전 데이터 해석에는 더 이상 쓰지 않는다 |
| `desired_checks_per_hour` | `domain/schedule` | 점수 포함 |
| `current_slot` | `domain/schedule` | 수집 주기 5분 기준(일반화한 주기는 별도 단위 테스트) |
| `schedule.invariants` | `domain/schedule` | 정확한 배치 대신 불변식 |
| `schedule.known_defects` | `domain/schedule` | 레거시 1슬롯, 새 구현은 전체 슬롯 |
| `ott_gate` | `domain/ott` | parity와 known_defects(부분 문자열, HTML) |
| `discord_message.known_defects` | `domain/message` | 링크 보존, 1900자 이하 |

---

## 8. 품질 게이트 (매 단계 통과 조건)

| 게이트 | 도구 | 기준 |
|---|---|---|
| 포맷과 린트 | `ruff` | 오류 0, 미사용 import/변수(F401, F841) 0 |
| 정적 타입 | `mypy` | `domain`, `services`는 엄격 모드 오류 0 |
| 데드코드 | `vulture` | 허용 목록 외 0 |
| 테스트 | `pytest -m "not live"` | 전체 통과 |
| 커버리지 | `coverage` | `domain` 줄 90% 이상, `services` 80% 이상 (수치는 시작 값이며 첫 구현 후 조정) |
| 비밀 스캔 | 정규식 검사(`discord.com/api/webhooks/`, API 키 패턴) | 저장소, 픽스처, 테스트 출력에 0건 |
| 비밀 노출 검사 | 시나리오 DLV-17, SET-05, SET-13 | 모든 화면, API 응답, 로그 캡처에서 비밀 값 0건 |
| 업로드 안전 | 시나리오 IMP-09, IMP-11 | 공격용 파일이 거부되고 서버가 정상 응답 |
| 의존성 | 버전 고정 확인 | 범위 지정 없음 |
| 변경 승인 | 설계 문서 §12 | `@improvement` 시나리오는 승인된 항목만 |

선택 사항: 변이 테스트(`mutmut`)를 `domain/schedule`, `domain/validation`, `domain/message`, `domain/settings_rules`에만 적용해 테스트가 실제로 결함을 잡는지 확인한다.

---

## 9. 실행 방법

```
pytest -m "not live"                    # 기본: 단위 + 시나리오 + 어댑터 + 웹
pytest -m golden                        # 기존 동작 parity와 known_defects만
pytest tests/bdd/test_settings_screen.py  # 시나리오 연결 파일 하나만
pytest -m live                          # 실호출. OpenRouter 키와 시험용 웹훅이 필요(테스트 실행 인자나 로컬 설정으로 전달).
                                        # 하루 한도를 소모하므로 필요할 때만, 호출 수를 제한해서 실행
```

실호출 테스트는 최소 범위만 둔다: (1) OpenRouter 모델 1개로 샘플 글 3건 요약 계약 확인과 키 확인, (2) 시험용 Discord 채널로 메시지 1건 발송. 둘 다 구현 첫 스파이크(S1, S2)에서 한 번 실행해 결과를 설계 문서에 반영한다.

---

## 10. M1 완료 기준 (Definition of Done)

1. `features/`의 160개 시나리오가 모두 통과한다. 보류(`@wip`)나 건너뜀이 없다.
2. 골든 `parity`가 모두 일치하고 `known_defects`가 모두 새 기대값으로 나온다.
3. 품질 게이트 전부 통과.
4. 점검 체크리스트(설계 문서 §13)를 수행하고 결과를 기록했다. 단일 수행 원칙, 유지보수성, 확장성, 데드코드 점검 포함.
5. 스파이크 S1~S6 결과가 설계 문서에 반영되었다.
6. Docker 이미지로 컨테이너를 **환경 변수 없이** 띄워 `/healthz`가 200이고, 화면에서 설정을 채운 뒤 시험용 웹훅으로 실제 메시지 1건이 정상 형식으로 나간다.
7. **수동 화면 점검**(아래)을 PC와 iPhone에서 마쳤다.
8. 전환 절차의 병행 운전(시험용 웹훅으로 24~48시간) 비교 결과를 사용자가 확인했다.

### 수동 화면 점검 (자동 테스트가 보장하지 못하는 것)
| 화면 | 확인 |
|---|---|
| 상태 | 미설정 안내가 보이고 설정을 채우면 사라진다. 모바일 폭에서 줄바꿈이 깨지지 않는다 |
| 설정 | 비밀 칸에 저장된 값이 나타나지 않는다. 주기, 주소 오류 메시지가 이해된다. 모바일에서 입력과 저장이 된다 |
| 피드 가져오기 | 실제 기존 구독 파일(OPML)로 미리보기와 확정이 된다. NPM(HTTPS)을 거친 업로드가 된다(S5) |

### 병행 운전 비교 기준 (컷오버 전)
| 항목 | 합격 기준 |
|---|---|
| 기존이 운영 채널에 보낸 글 중 시험 채널에 없는 글 | 0건 (있으면 원인 규명 후 수정) |
| 새 서비스에만 있는 글 | 의도된 변경(예: 제목이 한자 혼입으로 재시도)으로 설명 가능해야 함 |
| 제목과 요약 품질 | 사용자가 샘플로 확인 |
| LLM 호출 수 | 하루 상한 이내 |
| 오류와 시스템 알림 | 예상하지 못한 반복 알림 없음 |

---

## 11. 구현 순서 제안 (테스트 우선)

각 단계에서 시나리오를 먼저 실패(red)하게 두고 구현해서 통과(green)시킨 뒤 리팩토링한다.

| 단계 | 내용 | 시나리오 |
|---|---|---|
| 0 | 스파이크 S1~S6, 프로젝트 골격, 가짜 포트, 품질 게이트 | — |
| 1 | `domain` 순수 함수 + 골든 테스트 | 골든, SCH-01~11, 14, 15, COL-03~10, SUM-02, OTT, DLV-06~10, SET-08~12(검증 규칙) |
| 2 | 설정 저장소(비밀 분리, 이력)와 설정 화면 | SET 전체 |
| 3 | 저장소와 수집 서비스 | COL 전체, SCH-12, 13 |
| 4 | LLM 게이트웨이, 예산, 요약 서비스 | BUD 전체, SUM 전체 |
| 5 | 발송 서비스와 알림 | DLV 전체 |
| 6 | 피드 가져오기(파서, 미리보기, 확정, 프리셋) | IMP 전체 |
| 7 | 웹 엔드포인트, 잡 연결(주기 재등록), Docker | SVC 전체, SCH-12, 13, SET-03, 04, 21 (완료) |
| 8 | 병행 운전, 컷오버 | DoD 6~8 |
