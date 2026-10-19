# M1 설계: 수집 · 요약 · 알림 이식 + 최소 관리 화면

범위: 기존 Hermes cron 스크립트 7개의 기능을 독립 서비스로 옮긴다(요구사항 9, 10).
변경 이력: 이번 판에서 ① 설정은 환경 변수가 아니라 웹 화면에서 한다 ② 수집·요약·발송 주기를 설정으로 뺀다 ③ 서비스 주소를 설정으로 뺀다 ④ 기존 구독은 OPML 업로드로 가져온다 ⑤ **웹훅 구조(기본, 카테고리, 주제)와 주제 알림(OTT 일반화)을 M1에 넣는다**를 반영했다. ⑤에 해당하는 아래 서술은 `docs/12-topic-routing-design.md`가 우선한다.
상태: **사용자 확인 대기** (확인 후 테스트 코드 작성 → 구현 순서로 진행)

---

## 1. 범위

### 포함
- 피드 수집(적응형 스케줄, 날짜/중복 필터, 조건부 GET, 신규 피드 기준선)
- LLM 제목 번역 · 요약 · **주제 판별**, 응답 검증과 재시도, 원문 발췌 폴백
- Discord 웹훅 발송(피드 → 카테고리 → 기본 라우팅 + OTT 추가 발송), 시스템 알림
- OpenRouter 호출 예산 가드, 모델 체인
- **최소 관리 화면 3개**: 상태, 피드 가져오기(OPML 업로드), 설정
- 전환(시험용 웹훅으로 병행 확인 후 운영 웹훅으로 교체)
- 임시 글 링크 `/a/{id}`와 `/healthz`, `/status`
- Docker 이미지와 compose 파일(환경 변수 없음)

### 제외 (이후 마일스톤)
| 항목 | 마일스톤 |
|---|---|
| 구독 목록 화면(조회, 편집, 삭제), URL 입력으로 개별 등록과 피드 자동 탐색, OPML 내보내기 | M2 |
| 카테고리 관리 화면, 피드·카테고리에 웹훅을 지정하는 편집 화면 | M2 |
| 무료 모델 스캔 · 벤치마크 · 추천 · 승인 교체, 모델 변경 알림 | M3 |
| 글 뷰어(원문 표시, 번역은 Safari 페이지 번역), 본문 추출, 원문 읽기 버튼 | M4 |
| 좋아요/싫어요, 주제 목록 제외, 키워드 개선 제안, 주제의 적용 범위(카테고리별) | M5, M2 |
| 관리 화면 보호(선택 기능) | 보류 |

M1의 관리 화면은 "서비스를 켜고 쓰기 시작하는 데 꼭 필요한 것"만 둔다. 이전 판에서 M2에 있던 OPML 가져오기는 기존 구독을 옮기는 데 필요해서 M1으로 당겼다.

---

## 2. 기존 스크립트 → 새 구성요소 대응

| 기존 | 새 구성요소 | 비고 |
|---|---|---|
| `rss_collector.py` | `domain/schedule`, `domain/guid`, `domain/dates`, `services/collect` | 스케줄·GUID·날짜 로직은 순수 함수로 분리 |
| `rss_gizmodo_collector.py` | (삭제) 피드 설정 `every_slot` + `max_entries=120` | 가져오기 화면의 프리셋 |
| `rss_translator.py`, `rss_gizmodo_translator.py` | `services/summarize`, `domain/validation`, `domain/korean` | 사실상 동일 → 하나로 |
| `rss_llm.py` | `adapters/openrouter`, `services/llm_gateway`, `services/budget` | 프로바이더 순회·재시도·예산을 분리 |
| `rss_reporter.py`, `rss_gizmodo_reporter.py` | `domain/ott`, `domain/routing`, `domain/message`, `services/deliver`, `adapters/discord` | 사실상 동일 → 하나로 |
| `rss_valid_feeds.json`, OPML | **피드 가져오기(업로드)** | 서버가 기존 폴더를 읽지 않는다 |
| `rss_sent_guids.json`, `rss_pending.json` | **가져오지 않음** | 새 피드의 첫 점검에서 현재 글을 "이미 본 글"로 기록(기준선) |
| 코드 안 웹훅 주소, 환경 변수 | 설정 화면(쓰기 전용 비밀) | |
| Hermes cron | APScheduler 잡 3개, 주기는 설정 | §5 |

기능별 추적은 `docs/02-m1-test-design.md`의 추적성 매트릭스를 본다.

---

## 3. 아키텍처

### 3-1. 계층

```
jobs (APScheduler)            ← 언제 실행할지만 안다. 주기는 설정에서 읽는다
  └ services                  ← 유스케이스 조립. 순서와 트랜잭션 경계
      ├ domain (순수 함수)    ← 규칙. 외부 입출력과 시간을 직접 쓰지 않는다
      └ ports (Protocol)      ← 외부 세계의 모양
          └ adapters          ← SQLite, HTTP(피드), OpenRouter, Discord
web
  ├ admin (서버 렌더링 화면)  ← 상태, 피드 가져오기, 설정
  └ api  (/healthz, /status, /a/{id})
```

의존 방향은 위에서 아래로만 흐른다. `domain`은 어떤 것도 import하지 않는다.

### 3-2. 모듈과 단일 책임

| 모듈 | 책임(한 줄) |
|---|---|
| `domain/schedule` | 피드 목록, 통계, 수집 주기로 시간당 슬롯 배치를 계산한다 |
| `domain/guid` | GUID 선택과 정규화 |
| `domain/dates` | 피드 항목의 발행 시각을 서비스 시간대로 해석한다 |
| `domain/korean` | 한국어 글 판별(한글 비율 ≥ 10%) |
| `domain/validation` | LLM 응답이 채택 가능한지 판정하고 이유를 돌려준다 |
| `domain/ott` | LLM 판정 + 키워드로 OTT 여부를 정한다 |
| `domain/routing` | 글 하나의 발송 대상 웹훅 목록을 정한다 |
| `domain/message` | Discord 메시지를 만든다(길이 제한 포함) |
| `domain/feed_url` | 피드 주소의 검증과 중복 판단용 정규화 |
| `domain/settings_rules` | 설정 값 검증(주소, 웹훅 형식, 주기, 시간대) |
| `services/collect` | 슬롯의 피드를 점검해 새 글을 저장한다 |
| `services/summarize` | 대기 글을 골라 요약하고 결과를 저장한다 |
| `services/deliver` | 발송 대상별로 보내고 결과를 기록한다 |
| `services/llm_gateway` | 모델 체인을 순회하며 호출한다(재시도, 장애 신호) |
| `services/budget` | 날짜별 호출 수를 세고 상한/경고를 판단한다 |
| `services/alerts` | 시스템 알림을 쿨다운과 함께 보낸다 |
| `services/settings` | 설정의 저장, 조회, 변경 이력, 비밀 값 마스킹 |
| `services/feed_import` | 업로드 파일을 해석해 미리보기를 만들고, 확정 시 저장한다 |
| `services/job_control` | 설정이 바뀌면 잡의 실행 간격을 다시 등록한다 |
| `adapters/*` | 각각 하나의 외부 시스템과의 통신만 담당한다 |

### 3-3. 포트(인터페이스) 초안

```python
class Clock(Protocol):
    def now(self) -> datetime: ...                      # 서비스 시간대 aware

class FeedFetcher(Protocol):
    def fetch(self, feed: Feed) -> FetchResult: ...     # status(200/304), entries, etag, last_modified

class LlmClient(Protocol):                              # 구현: services/ports.py, adapters/openrouter_client.py
    def complete(self, model: str, prompt: str, options: CallOptions) -> LlmResult: ...
    def model_parameters(self, model: str) -> frozenset[str] | None: ...   # 모델이 지원하는 옵션(없으면 None)
    def server_usage(self) -> ServerUsage | None: ...   # 서버가 알려 주는 오늘 호출 수. 채팅 호출이 아니다
    # 실패는 LlmCallError(kind: RATE_LIMITED / UNAVAILABLE / PAYMENT_REQUIRED / UNAUTHORIZED / POLICY /
    #   UNSUPPORTED_PARAMETER / OTHER, retry_after)로 올린다

class WebhookSender(Protocol):                          # 구현: adapters/discord_webhook.py
    def send(self, webhook_url: str, content: str) -> SendResult: ...   # 실패도 예외가 아니라 결과(status, retry_after, 남은 횟수, 메시지 id, 오류 종류)로 돌려준다

class FeedRepo, ArticleRepo, DeliveryRepo, UsageRepo, SettingsRepo, WebhookRepo, SeenRepo, ImportStagingRepo
```

저장소를 하나의 거대한 `Repository`로 두지 않고 역할별로 나눈다.

---

## 4. 데이터 모델 (M1 사용분)

```sql
categories(id, name, webhook_id NULL)
webhooks(id, name, created_at)                                  -- 주소는 secrets에 따로 보관

feeds(id, url UNIQUE, url_key UNIQUE,                           -- url_key: 중복 판단용 정규화 주소
      name, html_url, category_id NULL, webhook_id NULL,
      emoji DEFAULT '📢', poll_priority DEFAULT 'normal',       -- 'normal' | 'every_slot'
      (ott_check, webhook_id 열은 더 이상 쓰지 않는다)  max_entries NULL,                    -- NULL이면 설정의 기본값
      status DEFAULT 'baseline_pending',                        -- baseline_pending | active
      fail_count DEFAULT 0, last_error NULL,
      etag NULL, last_modified NULL, last_checked_at NULL, created_at)

feed_stats(feed_id PK, recent_count_7d, target_date_count, last_published_dt, updated_at)

articles(id, feed_id, guid UNIQUE,                              -- 정규화된 GUID. 피드 간 전역 중복 방지(기존 동작)
         title, link, content_html, published_dt, published_date, discovered_at,
         status,                                                -- collected | ready | delivered
          title_ko NULL, summary_ko NULL, llm_topics NULL, llm_model NULL,   -- llm_topics: LLM이 고른 주제 번호의 JSON 배열(is_ott 열은 쓰지 않는다)
         retry_count DEFAULT 0)

deliveries(id, article_id, webhook_id, purpose,                 -- purpose: primary | ott
           status,                                              -- pending | sent | failed_permanent
           attempts DEFAULT 0, last_error NULL, sent_at NULL,
           UNIQUE(article_id, webhook_id, purpose))

seen_guids(guid PK, reason, first_seen_at)                      -- baseline | delivered | skipped
llm_usage(day_utc, model, requests, failures, PRIMARY KEY(day_utc, model))
alert_log(kind, subject, last_sent_at, PRIMARY KEY(kind, subject))

settings(key PK, value, updated_at)                             -- 일반 설정 (평문)
secrets(key PK, value)                                          -- OpenRouter 키, 웹훅 주소. 쓰기 전용: 어떤 화면/API도 값을 돌려주지 않는다
settings_audit(id, key, changed_at, summary)                    -- 비밀 값은 값 없이 "변경됨"만
import_staging(token PK, payload, created_at, expires_at)       -- 가져오기 미리보기 보관(기본 60분)
```

- `seen_guids`가 중복 방지의 단일 기준이다. 글 저장, 기준선, 발송 완료, 전환 때 "건너뛰기"를 모두 여기에 기록한다.
- 시간은 UTC로 저장하고 표시할 때만 서비스 시간대로 바꾼다. 단, "오늘"의 기준은 설정의 서비스 시간대다.
- 마이그레이션은 `storage/migrations.py`의 순서 있는 SQL 목록과 SQLite의 `PRAGMA user_version`으로 관리한다. 이미 적용된 항목은 고치지 않고 목록 끝에 추가한다(§15에서 Alembic 대신 이 방식을 쓰게 된 이유).
- 비밀 값은 **암호화하지 않고** DB에 둔다. 복호화 키를 같은 볼륨에 둬야 해서 보호 효과가 작기 때문이다. 따라서 데이터 볼륨에 접근할 수 있는 사람은 비밀 값에도 접근할 수 있다.

---

## 5. 처리 파이프라인과 잡

```
collected ──(요약 성공 또는 원문 발췌 확정)──▶ ready ──(모든 목적지 발송)──▶ delivered
```

| 잡 | 기본 주기 | 설정 범위 | 하는 일 |
|---|---|---|---|
| collect | 5분 | 60의 약수(1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30, 60분) | 현재 슬롯의 피드 점검 → `collected` 저장 |
| summarize | 60초 | 10~3600초 | 대상 글 최대 N개 요약 → `ready` |
| deliver | 60초 | 10~3600초 | `ready` 글의 목적지별 발송 → `delivered` |

- collect는 **시각의 분이 수집 주기의 배수일 때** 실행한다(5분이면 :00, :05, …). 슬롯 번호(`분 ÷ 주기`)와 실행 시각이 어긋나지 않게 하려는 것이다.
- 주기를 바꾸면 `services/job_control`이 진행 중인 실행을 끝까지 두고 다음부터 새 간격으로 다시 등록한다. 재시작은 필요 없다.
- 세 잡 모두 `max_instances=1`, `coalesce=True`로 겹침을 막고 밀린 실행은 합친다.
- 잡 하나의 예외가 다른 잡에 번지지 않도록 잡 단위로 예외를 잡고 로그와 시스템 알림으로 남긴다.
- **필요한 설정이 비어 있으면 잡은 등록은 되지만 아무것도 호출하거나 보내지 않고 기다린다.** 상태 화면이 무엇이 비었는지 알려 준다.
- **전달 보장은 "최소 한 번(at-least-once)"** 이다. Discord 웹훅에는 멱등 키가 없어서, 발송 직후 DB 기록 전에 프로세스가 죽으면 같은 글이 한 번 더 나갈 수 있다.

---

## 6. 스케줄 알고리즘

기존 알고리즘을 유지하되 ① 매 슬롯 점검 피드를 보장하고 ② 수집 주기를 설정으로 일반화한다.

1. 시간당 슬롯 수 `S = 60 ÷ 수집 주기`(기본 5분 → 12).
2. **매 슬롯 점검(`every_slot`) 피드를 S개 슬롯 모두에 예약**한다.
3. 나머지 피드를 슬롯에 번갈아 한 번씩 배정한다(기본 보장: 시간당 1회).
4. 배치 크기 = `max(기본 15, ceil((예약 + 기본 보장 합계) ÷ S))`, 용량 = 배치 크기 × S.
5. 남는 용량만큼 활동 점수(`오늘 글 수 × 100 + 7일 글 수 × 10`)가 높은 피드부터 추가 점검을 배정한다. 목표 횟수는 3회(오늘 ≥ 3 또는 7일 ≥ 7), 2회(오늘 ≥ 1 또는 7일 ≥ 2), 1회다.
6. 추가 점검은 그 피드가 아직 없는 가장 한산한 슬롯에 넣는다.
7. 스케줄은 `(시간, 대상 날짜, 피드 구성 해시, 수집 주기)`가 같으면 재사용한다.

수집 주기를 길게 하면 한 번에 점검하는 피드가 늘어난다(예: 60분이면 134개를 한 번에). 이때 한 번의 실행이 길어질 수 있으니 주기는 짧게 두는 것을 권장한다.

기존 결함(골든 데이터로 확인): 활동 통계가 없거나 다른 피드의 점수가 더 높으면 "매 슬롯 점검" 피드가 1개 슬롯에만 들어갔다.

---

## 7. LLM 호출

### 7-1. 요청/응답 계약
- 프롬프트는 영어 지시문, 출력은 JSON 한 개: `{"title_ko": str, "summary_ko": str}`. 키워드가 맞은 후보 주제(키워드가 없는 주제 포함)가 있으면 그 번호와 설명만 요청에 넣고 `"topics": [번호, ...]`도 받는다(`docs/12` §8).
- 한국어 글은 `title_ko`를 무시하고 원제목을 쓴다.
- 입력 본문은 HTML 제거 후 앞 1500자.
- `max_tokens`와 추론 비활성화: **스파이크 S1에서 확인했다**(`docs/07-spike-s1-result.md`). 추론 토큰이 `max_tokens=350`을 먼저 소진한다는 가설이 맞았고, `reasoning: {"effort": "none"}`으로 해결된다. 호출 방식 확정안은 §7-5에 적었다.

### 7-2. 검증 규칙(`domain/validation`)
다음 중 하나라도 해당하면 폐기하고 재시도 횟수를 1 올린다.
JSON 아님 · 필수 항목 누락 · 제목/요약 비어 있음 · 한자 포함(제목과 요약) · 사고 과정 문구(`We need to translate`, `Korean summary`) · 형식 표지 잔류(`TITLE:`, `SUMMARY:`) · `finish_reason == length`.
금지 문구 목록은 설정(고급)에서 편집할 수 있다.

### 7-3. 장애와 불량 응답의 구분
| 구분 | 예 | 재시도 횟수 | 결과 |
|---|---|---|---|
| 불량 응답 | 한자 혼입, JSON 깨짐 | +1 | 3회 누적 시 원문 발췌 확정 |
| 장애 | 전 모델 429/5xx, 402, 상한 도달 | 변화 없음 | 글은 `collected`로 대기, 수집 후 대기 허용 시간(기본 60분)이 지나면 원문 발췌 확정 |

### 7-4. 모델 체인과 예산
- 체인: 설정의 모델 목록 순서대로 시도. 429는 `Retry-After`(최대 30초) 후 같은 모델에 1회 재시도, 이후 다음 모델.
- 호출마다 `llm_usage`에 UTC 날짜별로 기록한다. 실패도 센다(재시도, 모델 전환도 각각 한 번으로 센다).
- 운영 상한(기본 700/일), 경고 비율(80%), 분당 상한(15), 대기 허용 시간(60분), 요약 묶음(5)은 모두 설정에서 바꾼다. 바꾸면 재시작 없이 다음 실행부터 반영된다.
- OpenRouter 공식 문서 기준 무료 모델은 분당 20회, 하루 50회(구매 이력 10크레딧 미만) 또는 1,000회다. S1에서 확인한 키 정보: `is_free_tier`는 `false`, 키에 월 한도 10이 걸려 있고 사용액은 0이다(무료 모델은 비용이 들지 않는다). 키 응답에는 `free_model_daily_requests` 항목이 있지만 **값은 아직 확인하지 못했다**(`python tools/spike.py key`로 확인). 확인되기 전까지 운영 상한은 설정의 기본값(700/일)을 쓴다.

**서버가 알려 주는 남은 호출 수**: 키 정보(`/api/v1/key`)의 `free_model_daily_requests`(`used`, `limit`, `remaining`)는 이 키로 호출한 **모든 프로그램의 합계**다. 실제 값은 `{"used": 33, "limit": 1000, "remaining": 967}`이었다(이 계정의 하루 무료 한도는 1000회). 같은 키를 쓰는 기존 크론이 쓴 호출은 우리 서비스의 기록에 없으므로, 호출 전에 서버가 알려 준 남은 수가 **예비분(설정 `llm_reserve_calls`, 기본 20) 이하**이면 새 호출을 막고 "서버 한도 임박" 알림을 보낸다. 이 값은 5분 동안 재사용하고, 조회에 실패하면 우리 서비스의 기록만으로 판단하며 1분 뒤에 다시 묻는다. 조회는 채팅 호출이 아니라서 한도를 쓰지 않는다.

**호출을 막는 순서**: 하루 상한 → 서버가 알려 준 남은 수 → 분당 상한. 하루 상한에 도달했을 때는 서버에 묻지 않는다. 분당 상한은 알림 없이 잠깐 기다리게만 한다. 막혔을 때 글의 재시도 횟수는 올리지 않는다.

**모든 모델에 똑같이 일어나는 문제**(잔액 부족 402, 키 오류 401/403, 개인정보 설정 404)는 체인의 다른 모델을 시도하지 않고 멈추고 시스템 알림을 보낸다(같은 이유로 모델마다 호출을 낭비하지 않으려는 것이다). 같은 알림은 쿨다운(기본 6시간) 동안 반복하지 않는다. 80% 경고만 UTC 하루에 한 번이다.

**처음 쓸 때**: 키, 기본 웹훅, 서비스 주소가 모두 채워지기 전에는 요약 작업이 LLM을 호출하지 않고 글을 그대로 둔다(SET-21).

### 7-5. 호출 방식 (스파이크 S1 결과 반영)
근거와 수치는 `docs/07-spike-s1-result.md`.
- **프롬프트**: JSON 객체 하나(`title_ko`, `summary_ko`, 후보 주제가 있으면 `topics`)를 요청한다.
- **추론 끄기**: 모델의 `supported_parameters`에 `reasoning`이 있으면 항상 `reasoning: {"effort": "none"}`을 보낸다. S1에서 두 모델 모두 이 값으로 추론 토큰이 0이 되었고 통과율이 100%였다.
- **JSON 강제**: 모델이 `response_format`을 지원하면 `{"type": "json_object"}`와 `provider.require_parameters: true`를 보낸다. 지원하지 않거나 4xx로 거부하면 이 옵션을 빼고 한 번 다시 시도하고, 그 모델의 "옵션 거부" 기록을 메모리에 남겨서 반복하지 않는다(제공자가 줄어드는 위험을 피하려는 것이다).
- **`max_tokens`**: 500. 추론을 끈 응답의 출력은 90~161토큰이었다. 추론이 켜져 있으면 200~600토큰을 먼저 쓰기 때문에 350, 700은 모두 부족했다.
- **제한 시간**: 연결 5초, 읽기 30초. 응답 시간은 0.8~10.9초였고(사전 확인의 22초 1건 제외) 한 모델은 30초 안에 응답하지 않았다. 30초를 넘으면 다음 모델로 넘어간다.
- **`finish_reason`이 `length`**: 실패로 보고 재시도한다(잘린 JSON을 쓰지 않는다).
- **체인 순서**: 기본값은 `nemotron-3-super-120b-a12b`, `nemotron-3.5-super-vl`.

---

## 8. 알림

### 8-1. 라우팅
발송 대상은 **피드 웹훅 → 카테고리 웹훅 → 기본 웹훅** 중 첫 지정값 하나에, 글이 해당한 주제들의 서로 다른 웹훅을 더한 것이다(`docs/12-topic-routing-design.md` §7). 피드 웹훅은 카테고리에 속하지 않은 피드에만 지정할 수 있고, 지정한 웹훅으로 가면 기본 웹훅에서는 빠진다. 주제에 해당하려면 LLM이 그 주제를 골랐고, 키워드가 등록된 주제는 제목이나 본문에 키워드가 하나라도 있어야 한다. 같은 웹훅은 한 번만 보낸다. 기본, 시스템 웹훅은 설정 화면에서 지정하고, 피드, 카테고리, 주제의 웹훅은 각각 `/feeds`, `/categories`, `/topics`에서 지정한다.

### 8-2. 메시지 형식
```
📢 **[사이트] 새 글 알림** `HH:MM`
**번역 제목**
요약 2~3문장
🔗 [글 읽기](<설정의 서비스 주소>/a/<id>)
```
- 이모지는 피드 설정(Gizmodo 프리셋은 🧪). 시각은 서비스 시간대. 원문 링크는 넣지 않는다(결정 사항).
- 전체 1900자 이하. 초과하면 **요약을 줄여서** 링크가 살아남게 한다.
- **서비스 주소가 설정되어 있지 않으면 발송을 보류**한다(링크 없는 알림 방지).

### 8-3. 실패 처리
| 응답 | 동작 |
|---|---|
| 2xx | `sent` 기록 |
| 429 | `Retry-After`(없으면 본문의 `retry_after`, 둘 다 없으면 5초, 최대 30초) 대기 후 1회 재시도. 또 실패하면 **이번 실행을 멈추고** 다음 실행으로 |
| 401/403/404 등 4xx(408, 429 제외) | `failed_permanent` + 시스템 알림(웹훅마다 쿨다운). 글은 `ready`로 남고, 그 대상으로는 다시 보내지 않는다. 사용자가 기본 웹훅 등을 바꾸면 새 대상으로 보낸다 |
| 5xx, 408, 네트워크 | `pending` 유지, 시도 횟수 +1, 오류 종류 기록. **3번 연속 실패하면 이번 실행을 멈춘다**(Discord가 내려갔을 때 모든 글에서 시간을 낭비하지 않는다) |

**속도 조절**: 보낸 직후 응답 헤더의 남은 횟수가 0이면 `reset-after`(최대 10초)만큼 기다린다. S2에서 한도가 5회/약 2초임을 확인했다(`docs/09-spike-s2-result.md`).
**한 번에 보내는 글**: 한 실행에 최대 25개. 나머지는 다음 실행으로 넘어간다.
**멘션 차단**: 글 제목이나 요약에 `@everyone` 같은 문구가 있어도 알림이 가지 않게 `allowed_mentions`를 비워서 보낸다.
**기본 웹훅이 없을 때**: 발송을 멈추고 시스템 알림을 보낸다(쿨다운). 서비스 주소가 없을 때는 알림 없이 멈추고, 상태 화면에 "서비스 주소 필요"를 표시한다.

---

## 9. 관리 화면 (M1)

서버 렌더링 화면 3개이고 모바일에서도 쓸 수 있게 반응형으로 만든다.

```
┌─────────────────────────────────────┐
│ [상태]  [피드 가져오기]  [설정]     │
├─────────────────────────────────────┤
│ 상태                                │
│  ⚠ 설정 필요: 서비스 주소 · 기본 웹훅│
│  마지막 수집 14:35 · 요약 14:36 · 발송 14:36 │
│  대기 글 4 · 오늘 LLM 호출 120/700  │
│  실패 피드 2  [상세]                │
└─────────────────────────────────────┘
```

**설정**
```
일반      서비스 주소 [https://rss.example.com    ] [현재 접속 주소 사용]
          시간대     [Asia/Seoul ▾]
주기      수집(분) [5 ▾]   요약(초) [60]   발송(초) [60]
LLM       OpenRouter 키  설정됨   [새 키 입력] [키 확인]
          모델 체인  1 model-a  2 model-b   [추가] [순서 변경]
          하루 상한 [700]  경고 [80]%  분당 [15]  장애 대기(분) [60]  요약 묶음 [5]
알림      웹훅  rss ✓기본  [시험] [삭제]   ott ✓OTT  [시험] [삭제]   [추가]
          역할  기본 [rss ▾]  OTT [ott ▾]  시스템 [sys ▾]
고급      요약 금지 문구 목록(주제의 키워드는 `/topics`에서 편집한다)
이력      2026-10-16 14:20 서비스 주소 변경 · 14:21 OpenRouter 키 변경됨
```

**피드 가져오기**
```
[파일 선택 (OPML)]  [미리보기]
신규 4 · 중복 1 · 오류 1      ☑ OPML 폴더를 카테고리로 가져오기
 ✔ Gizmodo        프리셋 ☑ Gizmodo (매 슬롯 · 최대 120 · 🧪)   웹훅 [gizmodo ▾]
 ✔ awesome-blogs  프리셋 ☑ 매 슬롯 점검
 ✔ 일반 피드 2개
 ✖ 오류 1: ftp:// 주소 (http, https만 가능)
[확정]  [취소]          미리보기는 60분 동안 보관됩니다
```

---

## 10. 설정과 비밀

**컨테이너에 필요한 환경 변수는 없다.** compose 파일은 포트와 데이터 볼륨만 정한다.

```yaml
services:
  rss-hub:
    image: rss-hub:latest
    ports: ["8000:8000"]
    volumes: ["rss-hub-data:/data"]     # SQLite 위치. 이름 있는 볼륨 권장(§14 S3)
    restart: unless-stopped
volumes:
  rss-hub-data:
```

| 설정(화면 항목) | 기본값 | 검증 | 비고 |
|---|---|---|---|
| 서비스 주소 | (빈 값) | http/https, 끝 슬래시 정리 | 비면 발송 보류. "현재 접속 주소 사용" 제안 |
| 서비스 시간대 | Asia/Seoul | IANA 이름 | 컨테이너 시간대와 무관 |
| 수집 주기(분) | 5 | 60의 약수 | |
| 요약 / 발송 주기(초) | 60 / 60 | 10~3600 | |
| 슬롯 기본 배치 크기 | 15 | 1 이상 정수 | |
| 피드 기본 최대 검사 항목 | 50 | 1~500 | 피드별 값이 우선 |
| OpenRouter 키 | (비밀) | 비어 있지 않음 | 쓰기 전용, "키 확인" 버튼 |
| 서버 남은 호출 예비분 | 20 | 0~1000 | 서버가 알려 준 오늘 남은 무료 호출이 이 값 이하이면 새 호출을 멈춘다(같은 키를 쓰는 다른 프로그램의 몫을 남겨 둔다) |
| 모델 체인 | 스파이크 S1에서 응답하고 통과율이 높았던 무료 모델 2개(`nemotron-3-super-120b-a12b`, `nemotron-3.5-super-vl`) | 1개 이상, 중복 제거 | 이전에 쓰던 `nemotron-3-ultra-550b-a55b`는 S1에서 30초 안에 응답하지 않아 기본값에서 뺐다. M3에서 추천/교체 연결 |
| LLM 하루 상한 / 경고 / 분당 | 700 / 80% / 15 | 양의 정수 | |
| 장애 대기 허용(분) / 요약 묶음 | 60 / 5 | 양의 정수 | |
| 웹훅 목록(이름 + 주소) | (빈 값) | Discord 웹훅 형식만(https, discord.com·discordapp.com 계열, `/api/webhooks/{id}/{token}`) | 쓰기 전용, "시험 전송" 버튼 |
| 웹훅 역할(기본 / 시스템) | 없음 | 목록 중에서 선택 | 기본 웹훅이 없으면 발송 보류 |
| 알림 쿨다운(시간) | 6 | 양의 정수 | |
| 요약 금지 문구 | 기존 목록 | 문자열 목록 | 고급 |

**비밀 값 규칙**
- OpenRouter 키와 웹훅 주소는 저장 후 화면, API, 로그 어디에도 값을 보여 주지 않고 "설정됨"만 표시한다.
- 입력칸을 비워 저장하면 기존 값을 유지한다. 지우려면 명시적으로 삭제한다.
- 설정 변경은 `settings_audit`에 항목과 시각을 남긴다. 비밀 값은 "변경됨"만 남긴다.
- **웹훅 주소는 Discord 호스트만 허용한다.** 인증 없는 화면에서 임의 주소로 요청을 보내게 하는 것(SSRF)을 막는 장치다.

**인증이 없는 것의 의미(사용자 결정으로 보류)**: 설정 화면과 가져오기 화면이 NPM으로 외부에 열리면, 주소를 아는 누구나 설정을 바꾸고 피드를 가져올 수 있다. 값을 읽을 수는 없지만 덮어쓰기(웹훅을 자기 것으로 교체, 키 교체, 피드 추가)는 가능하다. 변경 이력과 위 검증은 피해를 줄이고 알아채게 하는 장치일 뿐 접근을 막지는 못한다. 관리 화면 보호는 "설정 항목으로 켜고 끄는 선택 기능"으로 이후에 추가한다.

**인증 없이 쓰는 동안 이미 넣은 최소 장치(2단계)**
- 상태를 바꾸는 요청(POST)은 `Origin`, `Sec-Fetch-Site` 헤더로 출처를 확인하고, 다른 사이트에서 온 요청은 403으로 거부한다(CSRF). 리버스 프록시가 넘긴 `X-Forwarded-Host`도 인정한다. 이 헤더가 없는 요청(curl 등)은 브라우저를 통한 공격 경로가 아니라서 통과시킨다.
- 모든 응답에 `Cache-Control: no-store`, `Content-Security-Policy`(스크립트와 외부 자원 차단, 프레임 삽입 금지, 폼은 같은 주소로만), `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`를 붙인다.
- 삭제 같은 되돌리기 어려운 동작은 확인란을 선택해야 한다. 화면에는 스크립트가 없다.
- 이것들은 "다른 사이트가 내 브라우저를 이용하는 공격"을 막을 뿐, **주소를 아는 사람이 직접 접속해서 바꾸는 것은 막지 못한다.**

---

## 11. 기존 데이터 이전과 전환

### 가져오기 (업로드)
- 지원 형식: **OPML만**(`.opml`, `.xml`). JSON은 지원하지 않는다(사용자 결정). 폴더 구조는 카테고리로 가져올 수 있고, 항목 이름은 `text`, `title`, 주소 순으로 정한다.
- 올리면 바로 저장하지 않고 **미리보기(신규/중복/오류)** → 확정. 미리보기는 60분 뒤 만료된다.
- 제한: 5MB, 2000개. XML은 `defusedxml`로 읽고 **DTD와 엔티티가 있으면 통째로 거부**한다(외부 엔티티, 엔티티 폭탄 방지). 깊게 중첩된 파일도 반복문으로 읽어서 서버가 죽지 않는다. 오류 메시지에는 파일 내용을 되돌려 주지 않는다. 주소는 http/https만 받는다.
- **사설망 주소는 항상 거부한다(사용자 결정).** 인증 없이 열린 서비스에서 서버가 사용자가 준 주소로 요청을 보내면 집 안의 다른 장치나 클라우드 메타데이터 주소(`169.254.169.254`)로 요청을 보내게 만들 수 있다(SSRF). 두 겹으로 막는다.
  1. 가져올 때: 루프백, 사설 대역, 링크 로컬, 멀티캐스트, 예약 주소, `localhost`, `.local`·`.internal`·`.lan` 같은 내부 도메인, 점 없는 한 단어 호스트(`nas`), `2130706433`·`0x7f000001`·`127.1` 같은 변형 IP 표기를 오류로 보여 준다.
  2. 가져오는 때: 이름이 공개 주소처럼 보여도 실제로 사설망으로 풀리거나 리다이렉트로 사설망에 닿는 경우는 1번으로는 못 잡는다. 그래서 **실제로 연결된 소켓의 상대 IP를 연결 직후에 검사**한다(HTTPS는 TLS 협상 전에, 리다이렉트도 새 연결마다). 환경 변수의 프록시 설정은 쓰지 않는다. 시나리오 IMP-19~21.
  - 결과: 집 안의 FreshRSS 같은 **사설망 피드는 등록도 수집도 안 된다.**
- 중복 판단: 호스트 대소문자와 끝 슬래시를 정규화한 주소가 같으면 같은 피드.
- Gizmodo, awesome-blogs는 **프리셋으로 제안**하고 사용자가 고른다(숨은 규칙이 아니다).
- 기존 발송 이력과 대기 글은 가져오지 않는다. 새로 등록한 피드(`baseline_pending`)는 첫 점검에서 지금 있는 글을 "이미 본 글"로만 기록하므로 기존 cron이 보낸 글이 다시 나가지 않는다.

### 전환 절차 (제안)
발송 모드(live/dry_run) 같은 스위치는 두지 않는다. 대신 **시험용 Discord 채널의 웹훅**으로 먼저 돌려 보고, 확인이 끝나면 웹훅을 운영 채널로 바꾼다. 웹훅이 하나도 지정되어 있지 않으면 아무것도 보내지 않는다(DLV-15).

1. M1 인수 기준 통과.
2. 서비스를 띄우고 설정을 채운다. 웹훅은 **시험용 채널의 웹훅 하나만** 등록해서 기본, OTT, 시스템 역할을 모두 그 웹훅으로 지정한다.
3. 기존 구독을 업로드해 가져온다. 기존 cron은 그대로 켜 둔다(운영 채널은 기존 cron이 계속 채운다). 새 피드는 첫 점검에서 현재 글을 기록만 하므로 같은 글이 다시 나가지 않는다.
4. 24~48시간 병행하며 비교한다. 기존이 운영 채널에 보낸 글이 시험 채널에도 있는지, 시험 채널에만 있는 글은 왜인지 본다.
5. 승인하면 **기존 cron을 중지**하고, 설정 화면에서 운영 채널 웹훅을 추가해 기본, OTT 역할을 운영 웹훅으로 바꾼다(시험 웹훅은 삭제). 이 순서로 하면 잠깐 사이에 올라온 글은 시험 채널로 가고 운영 채널에 같은 글이 두 번 올라오지 않는다. 시험 채널에 이미 보낸 글은 발송 완료로 기록되어 운영 채널로 다시 나가지 않는다.
6. 7일 관찰 후 기존 스크립트를 보관하고 cron을 제거한다.

### 롤백
기본, OTT 역할을 시험 웹훅으로 되돌리거나 서비스를 멈추고 기존 cron을 다시 켠다. 새 서비스가 운영 채널로 보낸 글 중 **그날 발행된 글**은 기존 cron이 한 번 더 보낼 수 있다(기존 cron은 새 서비스의 발송 이력을 모르기 때문). 이전 판에서 제안했던 "새 이력을 기존 파일 형식으로 내보내는 명령"은 기존 폴더를 읽지 않는 방향으로 바뀌면서 제외했다. 필요하면 별도로 요청해 달라.

---

## 12. 기존 동작에서 의도적으로 바꾸는 부분 (승인 대상)

| # | 변경 | 이유 | 시나리오 |
|---|---|---|---|
| 1 | 매 슬롯 점검 피드를 확실히 모든 슬롯에 예약 | 기존은 통계가 없거나 점수가 밀리면 1슬롯만 점검 | SCH-06~08 |
| 2 | 스케줄 재생성 조건을 "피드 구성 해시"로 | 기존은 피드 "개수"만 비교 | SCH-10 |
| 3 | 한자 검사를 제목에도 적용 | 기존은 요약만 | SUM-05 |
| 4 | LLM 장애와 불량 응답을 구분, 장애는 60분까지 대기 | 기존은 장애 15분 만에 영문 원문 발송 | SUM-10, 11 |
| 5 | 요약과 발송을 발행 시각이 오래된 글부터 | 기존은 최신 글부터라 채널 순서가 거꾸로 | SUM-12, DLV-16 |
| 6 | OTT 영문 키워드를 단어 단위로 정확히 일치(`ott`, `disney+` 등 포함) | 기존은 `bottle`, `lotto`도 일치하고, `disney+`는 뒤에 공백이 오면 일치하지 않았다 | TPC-03, TPC-08 |
| 7 | 주제 키워드 검사에서 HTML 제외 | 기존은 이미지 주소의 `movie`에도 반응 | TPC-04 |
| 8 | 긴 메시지는 요약을 줄여 링크를 보존 | 기존은 끝을 잘라 링크가 사라짐 | DLV-09, 10 |
| 9 | 목적지별 발송 기록과 재시도 | 기존은 한쪽만 성공해도 완료 처리 | DLV-11 |
| 10 | Gizmodo, awesome-blogs를 가져오기 프리셋(피드 설정)으로 통합 | 중복 코드와 하드코딩 제거 | IMP-16, 17 |
| 11 | 중복 피드 판단에 호스트 대소문자와 끝 슬래시 정규화 | 기존은 같은 문자열만 중복 | IMP-07 |
| 12 | 메시지에 서비스 링크만 (**사용자 결정**) | | DLV-06 |
| 13 | 기존 발송 이력과 대기 글을 가져오지 않고 기준선 방식 (**사용자 결정**) | 업로드만으로 이전 | IMP-18 |
| 14 | 설정은 환경 변수가 아니라 화면에서 (**사용자 결정**) | | SET 전체 |
| 15 | 피드가 아닌 응답(HTML 페이지 등)은 "글이 0개인 피드"가 아니라 **수집 실패(NotAFeed)** 로 기록 | 기존은 이런 응답을 영원히 성공으로 처리해서 잘못된 주소를 알아챌 수 없었다 | COL-23 |

신규(기존에 없던) 동작: 조건부 GET(304), 신규 피드 기준선, 응답 크기 제한(5MB), 호출 예산 가드, `/healthz`, 시스템 알림 쿨다운, 설정 변경 이력, 웹훅 Discord 호스트 제한, 안전한 XML 파서.

---

## 13. 기존 코드 점검 결과 (정리 대상)

도구(`vulture`, `pyflakes`)와 직접 실행으로 확인했다.

| 구분 | 내용 | 새 설계에서 |
|---|---|---|
| 실행 오류 | `rss_gizmodo_collector.py`가 `feedparser`를 import하지 않고 사용(`NameError`) | 의존성을 `requirements`로 고정 |
| 데드코드 | 두 reporter의 `OTT_KEYWORDS` 상수(미사용) | 삭제 |
| 데드코드 | `rss_translator.py`의 `TARGET_DATE`(대입만 하고 쓰지 않음)와 그것만 쓰는 `datetime` import | 삭제 |
| 데드코드 | `rss_llm.summarize_item`의 `token` 인자(사용 안 함)와 `get_anthropic_token`(이름과 달리 Anthropic과 무관, 결과가 쓰이지 않음) | 삭제 |
| 데드코드 | `rss_llm._call_gemini`(체인에 gemini 모델이 없어 도달 불가), `status` 변수, `site` 변수, 미사용 import(`re`, `datetime`) | 삭제 |
| 데드코드 | `rss_llm._send_alert_webhook`(호출처 없음) | 시스템 알림으로 **되살려** 사용 |
| 불일치 | `rss_llm.py` 독스트링은 "Ollama → OpenRouter", 실제 코드는 OpenRouter 우선 | 설정과 문서를 일치 |
| 중복 | collector 2개, translator 2개, reporter 2개가 거의 같음. `load_json`, `save_json`, `parsed_entry_datetime` 등이 파일마다 복사됨 | 한 곳으로 |
| 보안 | 웹훅 URL 3개가 코드에 하드코딩 | 설정 화면의 쓰기 전용 비밀로만, 저장소 스캔으로 차단 |
| 이식성 | 파일이 CRLF 줄바꿈 | `.gitattributes`로 LF 고정 |

정정: 처음 검토에서 `rss_translator.py`의 `combined` 변수를 미사용으로 적었으나 `is_korean(combined)`에서 쓰이고 있어 **잘못된 지적**이었다. 위 표가 정정된 목록이다.

### 새 코드의 점검 체크리스트 (단계마다 수행)
항상 포함: **단일 수행 원칙 · 유지보수성 · 확장성 · 데드코드/미사용 변수·함수**

| 영역 | 점검 항목 |
|---|---|
| 구조 | 함수/클래스가 한 가지 일만 하는가, 순수 규칙과 입출력이 분리되었는가, 모듈 간 순환 의존이 없는가 |
| 유지보수성 | 매직 넘버와 문자열이 설정/상수로 있는가, 이름이 의도를 드러내는가, 중복이 없는가 |
| 확장성 | 새 프로바이더/웹훅/피드 유형/가져오기 형식을 코드 수정 없이 설정이나 어댑터 추가로 붙일 수 있는가 |
| 데드코드 | `vulture`, `ruff`(F401, F841)로 미사용 import, 변수, 함수, 인자가 없는가 |
| 안정성 | 모든 네트워크 호출에 타임아웃이 있는가, 재시도가 상한이 있고 멱등한가, 트랜잭션 경계가 명확한가, 주기 변경이 진행 중 작업을 깨지 않는가 |
| 시간/인코딩 | 시간대가 명시되었는가, UTF-8(BOM 포함)을 처리하는가, 날짜 경계(자정, UTC)를 다뤘는가 |
| 보안 | 비밀이 로그와 응답에 없는가, 외부 입력(피드 주소, 링크 스킴, 웹훅 호스트)을 검증하는가, 업로드 크기·개수 제한과 안전한 XML 파서를 쓰는가, 의존성 버전이 고정되었는가 |
| 화면 | 입력 오류 메시지가 값 자체를 되돌려 주지 않는가, 변경에 확인 단계가 있는가(삭제, 전환) |
| 관찰 가능성 | 실패가 삼켜지지 않고 기록되는가(기존 코드는 `except: pass`가 많다), 설정 변경 이력이 남는가 |

---

## 14. 구현 전 스파이크 (실제 호출로 확인할 것)

S1(OpenRouter)과 S2(Discord)는 `tools/spike.py`로 실행한다. 사용법은 `tools/SPIKE.md`, 스크립트 자체는 가짜 서버로 검증했다(`tests/tools/`).

**진행 상태**: S1은 실행했고 결과를 `docs/07-spike-s1-result.md`에, S2는 `docs/09-spike-s2-result.md`에 정리했다(남은 항목: 429 응답의 모양, 삭제된 웹훅의 응답).

| # | 확인 항목 | 이유 |
|---|---|---|
| S1 | OpenRouter: JSON 출력 강제 지원 여부, 추론 비활성화 파라미터, `finish_reason` 값, `/api/v1/key`의 `is_free_tier` 의미와 키 확인이 호출 수에 포함되는지, 일일 집계 기준(UTC 여부), 실패 요청의 한도 소진 | 요약 품질, 예산, 키 확인 버튼의 전제 |
| S2 | Discord 웹훅: 429 응답의 `Retry-After` 형식, 삭제된 웹훅의 응답 코드, `?wait=true` 응답 | 발송 실패 처리의 전제 |
| S3 | Docker Desktop(Windows): 이름 있는 볼륨에서 SQLite(WAL) 동작, 자동 시작과 `restart: unless-stopped` | SQLite를 Windows 경로 바인드 마운트에 두면 잠금 문제가 있을 수 있어 이름 있는 볼륨을 권장(미검증) |
| S4 | 컨테이너 안의 `feedparser`로 골든 데이터와 날짜 해석이 일치하는지 | parity 보장 |
| S5 | NPM 프록시: PC의 고정 IP와 포트로 프록시되는지, **업로드 크기 제한**(nginx 기본값이 작아서 큰 OPML이 413으로 거절될 수 있음. 미검증) | 외부 접속 경로와 가져오기 |
| S6 | NPM이 넘겨주는 `X-Forwarded-Host`, `X-Forwarded-Proto` 헤더 | "현재 접속 주소 사용" 제안 |

---

## 15. 제안 기술 스택 (확인 필요)

Python 3.12 · FastAPI · Jinja2(서버 렌더링, 스크립트 없음) · 표준 라이브러리 `sqlite3`(WAL) + 간단한 마이그레이션 러너 · APScheduler · requests · feedparser · defusedxml · python-multipart · pytest · pytest-bdd · httpx2(테스트용) · ruff · mypy · vulture. 버전은 `pyproject.toml`에 고정했다.

**처음 제안(SQLAlchemy 2 + Alembic)에서 바꾼 점**: 2단계에서 `sqlite3`와 직접 쓴 SQL, `user_version` 기반 마이그레이션 러너로 바꿨다. 이유는 ① 단일 사용자, 단일 파일 DB라서 ORM이 주는 이득이 작고 ② 의존성과 설정 파일(alembic.ini, env.py)이 줄고 ③ 저장소 테스트가 실제 SQLite 임시 파일로 간단히 돌기 때문이다. 표가 늘어나 복잡해지면 SQLAlchemy로 옮길 수 있다.
