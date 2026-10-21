# 구조

## 계층

```
web ──▶ services ──▶ domain
 │          │  ▲
 │          ▼  │ (ports: Protocol)
 └──▶ storage   adapters ──▶ 외부(피드 사이트, OpenRouter, Discord)
jobs ──▶ services
```

| 계층 | 경로 | 책임 | 의존해도 되는 것 |
|---|---|---|---|
| domain | `src/rss_hub/domain/` | 순수 규칙. 입출력과 시계를 모른다(스케줄, 키워드, 요약 검증, 본문 정제, URL 규칙, 설정 검증) | 표준 라이브러리 |
| storage | `storage/` | SQLite 저장소와 마이그레이션. 저장소마다 표 몇 개를 맡는다 | domain, 시계 |
| services | `services/` | 한 가지 동작을 맡는 서비스(수집, 요약, 발송, 설정, 모델 스캔·벤치마크 등)와 외부 연결 모양(`ports.py`의 Protocol) | domain, storage, ports |
| adapters | `adapters/` | ports의 실제 구현: HTTP 피드 수집기, OpenRouter 클라이언트, Discord 웹훅 전송기 | domain, ports, requests |
| jobs | `jobs/` | 서비스를 주기에 맞춰 실행하는 스케줄러(1초마다 점검, 작업마다 스레드) | services |
| web | `web/` | FastAPI 앱, Jinja 템플릿, 정적 파일. 요청을 서비스와 저장소 호출로 바꾼다 | 전부 |

서비스는 포트(Protocol)에만 의존하므로 시험에서는 가짜 수집기, 가짜 LLM, 가짜 시계로 바꿔 끼웁니다. 실제 구현을 엮는 곳은 `runtime.py`(잡 구성)와 `web/app.py`(앱 구성) 두 군데뿐입니다.

## 실행

`rss_hub.main:create_service_app`이 앱 팩토리입니다(`uvicorn rss_hub.main:create_service_app --factory`). 앱이 시작되면 잡 스케줄러 스레드를 함께 시작하고, 종료 신호를 받으면 새 작업을 멈추고 진행 중인 발송은 지금 글까지 마칩니다. 데이터 위치는 코드의 `DEFAULT_DATA_DIR`(`/data`)이며 `create_app(data_dir=...)`로 바꿉니다. 환경 변수는 쓰지 않습니다(`tests/unit/test_no_environment_variables.py`가 이를 확인합니다).

## 잡

| 잡 | 주기 | 하는 일 |
|---|---|---|
| collect | 수집 주기(분, 60의 약수, 기본 5)의 슬롯 | 이번 슬롯에 배정된 피드를 가져와 새 글 저장. 피드 활동량에 따라 시간당 1~3회로 배정하고, 첫 점검은 기존 글을 "이미 본 글"로만 기록 |
| summarize | 기본 60초 | 수집된 글을 LLM으로 제목 번역, 요약, 주제 판별. 한도와 장애를 처리하고, 끝까지 실패하면 원문 발췌로 대신. OpenRouter 키가 없으면 LLM 없이 원문 제목으로 확정한다(한 번에 50건까지, 주제는 키워드가 맞는 것만) |
| deliver | 기본 60초 | 요약이 끝난 글을 기본/카테고리/피드/주제 웹훅으로 발송 |
| retention | 6시간 | 보관 기간(기본 90일)이 지난 글 삭제. 북마크한 글과 "이미 본 글" 기록은 남김 |
| model_scan | 24시간 | OpenRouter 무료 모델 목록을 확인하고 체인 모델이 사라지면 알림 |

한 잡이 오래 걸려도 다른 잡은 막히지 않으며, 같은 잡이 겹쳐 실행되지는 않습니다. `/healthz`는 수집이 오래 멈추면 503(`stale`)으로 답합니다.

## 글의 일생

```
피드 가져오기 ──▶ collected ──▶ ready ──▶ delivered
(archived: 첫 점검 때 읽기 화면에만 보관)
```

1. **collect**: 조건부 요청(ETag/Last-Modified)으로 피드를 가져오고, 글마다 고유 키(GUID)를 정규화해 중복을 거릅니다.
2. **summarize**: 제목과 본문에서 주제 키워드를 먼저 찾아 후보를 만들고, 후보가 있을 때만 LLM에게 확인을 맡깁니다. 한국어 글은 번역하지 않습니다. 모델 체인(1순위와 폴백)을 순서대로 시도합니다.
3. **deliver**: 글이 해당하는 목적지 각각에 한 번씩 보냅니다. 보낼 곳은 `피드 > 카테고리 > 기본` 순으로 첫 지정값 하나이고, 주제에 해당하면 그 주제의 웹훅으로 한 번 더 보냅니다.

읽기 화면은 같은 데이터를 읽고, 글을 처음 열 때 원문 페이지에서 본문을 추출해(`domain/fulltext.py`) 저장합니다. 이미지는 `https`만 표시하고 영상은 링크로 바꿉니다.

## 백업과 복원

`domain/backup.py`가 파일 모양을 검사하고, `storage/backup.py`가 읽고 쓰고, `services/backup.py`가 설정 값을 검증한다. 파일은 JSON 하나이며 `webhooks`(id와 이름만), `roles`(기본·시스템 웹훅의 이름), `tables`(categories, topics, feeds, feed_stats, articles, article_topics, deliveries, seen_guids, settings)로 이루어진다. 내보내기는 한 시점의 내용을 조각으로 흘려 보낸다. 복원은 `BEGIN IMMEDIATE` 트랜잭션 안에서 표를 비우고 파일의 행을 넣으며, 웹훅 번호는 이름으로 현재 웹훅에 다시 연결한다(없으면 해제하고 결과에 알림). `secrets`, `settings_audit`, `llm_usage`, `alert_log`, `job_runs`, 모델 목록과 벤치마크는 대상이 아니다.

## 저장소

SQLite 파일 하나(`/data/rss_hub.db`)입니다. 연결은 요청마다 열고, 성공하면 커밋하고 실패하면 버립니다. 마이그레이션은 `storage/migrations.py`의 번호 순서 목록이며 처음 연결할 때 적용됩니다. 시각은 UTC ISO 8601 문자열로 저장합니다(`storage/timestamps.py`).

표: `settings`, `secrets`, `settings_audit`, `webhooks`, `categories`, `feeds`, `feed_stats`, `seen_guids`, `articles`, `deliveries`, `topics`, `article_topics`, `llm_usage`, `alert_log`, `import_staging`, `job_runs`, `model_catalog`, `benchmark_runs`, `benchmark_scores`.

## 보안 장치

- **인증 없음**(설계 결정). 대신 `web/security.py`가 다른 사이트에서 온 상태 변경 요청을 거부하고(`Sec-Fetch-Site` 우선, 없으면 `Origin`), 모든 응답에 캐시 금지와 보안 헤더(CSP `script-src 'self'` 등)를 붙입니다.
- 비밀 값(OpenRouter 키, 웹훅 주소)은 쓰기 전용입니다. 저장 뒤에는 화면, 로그, 오류 메시지에 나오지 않습니다. 웹훅은 Discord 주소만 받습니다.
- 서비스가 보내는 모든 외부 요청(피드, 원문 페이지, OPML에 든 주소)은 `adapters/guarded_http.py`를 거칩니다. 사설망/루프백/링크 로컬 주소를 연결 시점에 거부하고, 응답 크기와 시간을 제한합니다. OPML은 `defusedxml`로 읽어 XML 공격을 막습니다.
- 글 본문은 `domain/sanitize.py`가 허용 목록 방식으로 정제합니다.
- 컨테이너는 일반 사용자(uid 10001)로 실행하고 API 문서 화면(`/docs`)은 열지 않습니다.
