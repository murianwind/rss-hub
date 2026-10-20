# RSS 통합 서비스 — M1

상태: **M1~M5 구현 완료, 실제 사용하며 다듬는 단계** — 수집, 요약(주제 판별), Discord 발송, 피드 가져오기와 개별 등록, 구독 편집과 OPML 내보내기, 뷰어, **주제 피드백(싫어요, 주제로, 키워드 개선 제안)**, **무료 모델 스캔, 벤치마크, 추천과 교체**, 잡 연결, Docker/Actions까지 구현했다. 남은 것은 운영하면서 확인할 것들(`docs/17-m3-m5-review.md` §7).
  18-ui-redesign-review.md 읽기 화면 재구현 1단계 점검 기록과 2단계 계획
  19-ui-redesign-2-review.md 읽기 화면 재구현 2단계 점검 기록
  20-ui-feedback-1-review.md 사용 피드백 22개 항목의 처리 현황과 점검 기록
  21-ui-feedback-2-review.md 사용 피드백 2차 반영 점검 기록
  22-full-text-review.md 글 전문 보기 점검 기록
  23-ui-feedback-3-review.md 사용 피드백 3차 반영 점검 기록
  24-ui-feedback-4-review.md 사용 피드백 4차 반영 점검 기록
  25-fulltext-review-and-ui-5.md 전문 검토(실제 페이지 3개)와 사용 피드백 5차 점검 기록
  26-ui-feedback-6-review.md 사용 피드백 6차 반영 점검 기록
설계 확인 사항은 `docs/00-final-plan.md` §6, **배포는 `docs/04-deploy-guide.md`**.

> 서비스를 시작하면 수집(5분 슬롯), 요약, 발송이 자동으로 돌고, 설정 화면에서 바꾼 값이 재시작 없이 반영된다. **웹훅과 OpenRouter 키, 서비스 주소를 설정하기 전에는 요약과 발송이 기다리기만 하고 아무것도 보내지 않는다.** 서버를 슬롯(0, 5, 10분…)이 아닌 시각에 시작하면 첫 수집은 다음 슬롯까지 최대 5분 기다린다.
> 인증이 없으므로 외부에 열 때는 NPM Access List를 권장한다(`docs/04-deploy-guide.md` §6).

## 빠른 시작

```
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
make check          # 린트 + 타입 + 데드코드 + 테스트 (모두 통과해야 한다)
pytest -m golden    # 기존 스크립트와 동작 비교만
pytest --cov        # 커버리지
```

`make`가 없는 환경(Windows)에서는 Makefile의 명령을 그대로 실행한다.

Docker로 바로 확인하려면(저장소를 받은 상태에서):
```
docker compose -f compose.yaml -f compose.build.yaml up -d --build
curl.exe http://localhost:8000/healthz
```

## 구성

```
.github/workflows/
  ci.yml                  PR/브랜치: 린트, 타입, 데드코드, 테스트 + Docker 이미지 빌드와 기동 확인
  image.yml               main/태그: CI 통과 후 ghcr.io에 이미지 게시
  dependabot.yml          pip, docker, github-actions 주간 업데이트(.github/ 바로 아래)
Dockerfile  compose.yaml  compose.build.yaml  .dockerignore
docs/
  00-final-plan.md        합의한 결정, 범위, 마일스톤, 위험, 확인 대기 항목
  01-m1-design.md         M1 설계: 아키텍처, 데이터 모델, 관리 화면, 설정, 의도적 변경점
  02-m1-test-design.md    테스트 전략, 추적성 매트릭스, 품질 게이트, 완료 기준
  03-step1-review.md      1단계 점검 기록(체크리스트 결과, 변이 확인, 발견한 문제)
  04-deploy-guide.md      GitHub → Actions → 이미지 → Docker 스택 → NPM 가이드
  05-step2-review.md      2단계 점검 기록(설정 저장소와 화면, 보안 장치, 변이 확인)
  06-step3-review.md      3단계 점검 기록(수집 서비스, 저장소, HTTP 수집기, 변이 확인)
  07-spike-s1-result.md   스파이크 S1(OpenRouter) 결과와 설계 반영
  08-step4-review.md      4단계 점검 기록(LLM 게이트웨이, 호출 예산, 요약 서비스, 변이 확인)
  09-spike-s2-result.md   스파이크 S2(Discord 웹훅) 결과와 설계 반영
  10-step5-review.md      5단계 점검 기록(발송 서비스, Discord 웹훅 어댑터, 변이 확인)
  11-step6-review.md      6단계 점검 기록(피드 가져오기, 사설망 주소 차단)
  12-topic-routing-design.md  웹훅 구조(기본, 카테고리, 주제)와 주제 알림 설계
  13-step7a-review.md     주제 알림 반영 점검 기록
  14-step7-review.md      7단계 점검 기록(잡 연결, 피드 웹훅 복구)
  15-m1-wrapup-m2-review.md  M1 마무리와 M2 점검 기록
  16-m4-review.md         주제 판정 방식 검토와 M4(뷰어) 점검 기록
  17-m3-m5-review.md      M3(모델 관리)와 M5(주제 피드백) 점검 기록
features/                 BDD 시나리오 9개 파일, 142개 시나리오 (Gherkin, 한국어 본문)
src/rss_hub/
  domain/                 도메인 계층(순수 규칙 12개 모듈)
  storage/                SQLite 연결, 마이그레이션, 피드와 글 저장소
  services/               설정, 수집, LLM 게이트웨이, 요약, 발송, 시스템 알림 서비스와 포트, 시계
  adapters/               HTTP 피드 수집기, OpenRouter 클라이언트, Discord 웹훅 전송기와 알림 전송기
  web/                    FastAPI 앱: 상태, 설정 화면(templates/), /healthz, 보안 장치
  version.py
tests/
  unit/  golden/  bdd/  web/  services/  storage/  fakes/
tools/generate_legacy_golden.py   골든 데이터 생성기 (Linux/Docker에서 실행)
tools/spike.py, tools/SPIKE.md    스파이크 S1(OpenRouter), S2(Discord) 시험 스크립트와 안내
```

## 진행 상황

| 단계 | 내용 | 상태 |
|---|---|---|
| 0 | 프로젝트 골격, 품질 게이트 | 완료 |
| 1 | 도메인 계층 + 골든 parity + BDD 24개 시나리오 연결 | 완료 |
| 1.5 | 배포 경로 검증용 최소 서비스, Dockerfile, 스택, GitHub Actions | **완료**(Docker 빌드와 Actions 실행은 첫 푸시에서 검증) |
| 스파이크 | **S1 OpenRouter 완료**(`docs/07-spike-s1-result.md`: 추론 토큰이 답을 잘라 먹는 것이 원인, `reasoning.effort=none`으로 해결). **S2 Discord 완료**(`docs/09-spike-s2-result.md`: 한도 5회/약 2초, 2000자 한도, 메시지 id와 삭제 확인, 429 응답 형식은 미확인). S3 Docker 볼륨, S5 NPM은 `docs/04-deploy-guide.md` §7로 확인 가능 | 진행 중 |
| 2 | 설정 저장소와 설정 화면, 요청 출처 확인과 보안 헤더 | **완료** (594개 테스트, 커버리지 100%, BDD 33개 시나리오 연결) |
| 3 | 피드와 글 저장소, 수집 서비스, HTTP 수집기 | **완료** (717개 테스트, 커버리지 100%, BDD 59개 시나리오 연결) |
| 4 | LLM 게이트웨이, 호출 예산, 요약 서비스, 시스템 알림 | **완료** (996개 테스트, BDD 90개 시나리오 연결) |
| 5 | 발송 서비스, Discord 웹훅 어댑터, 시스템 알림 전송기 | **완료** (1138개 테스트, BDD 109개 시나리오 연결) |
| 6 | 피드 가져오기(OPML 업로드, 사설망 주소 차단) | **완료** |
| 6.5 | 웹훅 구조 변경(기본, 카테고리, 주제)과 주제 알림(OTT 일반화) | **완료** (1593개 테스트, BDD 145개 시나리오 연결) |
| 6.6 | 피드 웹훅 복구(카테고리와 상호 배제), 기본 웹훅에서 빠지는 규칙 | **완료** |
| 7 | 잡 연결(수집, 요약, 발송), `/healthz` 정체 판정, `/status`, `/a/{id}`, 종료 처리, Docker 시작 명령 | **완료** (1736개 테스트, BDD 165개 시나리오 연결) |
| 7.5 | M1 마무리: 웹훅 시험 전송, OpenRouter 키 확인, 주제 판별 시험 | **완료** |
| 8 | M2: 개별 등록과 피드 자동 탐색, 구독 편집과 삭제, OPML 내보내기 | **완료** (2015개 테스트, BDD 184개 시나리오 전부 연결) |
| 9 | 주제 판정 방식 변경: 키워드 먼저, LLM은 후보만 확인 | **완료** |
| 10 | M4: 뷰어(사이드바 RSS·카테고리·주제, 글 목록, 글 페이지, 본문 정제, 보관 글과 보관 기간 정리) | **완료** (2268개 테스트, BDD 202개 시나리오 전부 연결) |
| 11 | M5: 주제 피드백(싫어요, 되돌리기, 주제로, 키워드 개선 제안, 요청의 예시) | **완료** |
| 12 | M3: 무료 모델 스캔, 벤치마크, 추천, 승인 교체, 하루 한 번 자동 스캔 | **완료** (2560개 테스트, BDD 226개 시나리오 전부 연결) |
| 13 | 읽기 화면 재구현 1단계: 접히는 사이드바, 읽음과 안 읽은 글 수, 북마크, 검색과 필터, 돌아가기, 정적 스크립트(`script-src 'self'`) | **완료** (238개 시나리오 연결). 2단계는 14번 |
| 14 | 읽기 화면 재구현 2단계: 인라인 슬라이드 패널(추가, 설정, 삭제 확인), 드래그 정렬과 카테고리 이동, 설정 탭, 테마와 글자 크기 | **완료** (250개 시나리오 연결, 2842개 이상 테스트). `app.js`는 자동 시험 없음 |
| 15 | 사용 피드백 1차 반영(22개 중 14개): 항상 보이는 아이콘, 피드 상태 점과 강제 새로고침, 피드 주소 변경, 합친 설정 패널, 즉시 검색과 필터, 글 상세의 주제 메뉴, 위치 유지 등 | **완료**. 상세는 `docs/20-ui-feedback-1-review.md` |
| 16 | 사용 피드백 2차 반영(나머지 7개): 피드 관리 화면(상태, 자동 가변 수집 주기, 활동량), 설정 아코디언, 자동 읽음과 안 읽음 고정, 읽음 버튼, 사이드바 폭 조절 | **완료**(262개 시나리오 연결). `docs/21-ui-feedback-2-review.md` |
| 17 | 글 전문 보기: 글을 처음 열 때 원문 페이지에서 본문을 뽑아 저장(실패하면 RSS 본문과 이유, 다시 가져오기 버튼). 이미지는 https만 표시하고 영상은 "영상 보기" 링크(새 창)로 바꾼다 | **완료**(268개 시나리오 연결). `docs/22-full-text-review.md` |
| 18 | 사용 피드백 3차: 첫 접속은 글 목록(사이드바 접힘), 글 화면 정리(여백, 출처와 중복 버튼 제거), 북마크 위치, 숫자 버블은 읽지 않은 글 수만, 피드 관리 검색, 모델 잔여 사용량, 전문 군더더기 정리, 프록시 차단 규칙 회피, 글 언어를 따르는 페이지 언어 | **완료**(279개 시나리오 연결). `docs/23-ui-feedback-3-review.md` |
| 19 | 사용 피드백 4차: 목록 끊김 없는 이어 보기(스크립트가 없으면 쪽 표시와 이전/다음 버튼), 사이트 제목을 누르면 그 사이트가 새 창으로, 읽지 않은 글이 있는 사이트는 진하게 | **완료**(283개 시나리오 연결). `docs/24-ui-feedback-4-review.md` |
| 20 | 사용 피드백 5차와 전문 검토: 설정 버튼 다시 누르면 닫힘, 글 화면의 위쪽(제목 링크, 요약, 전문 다시 가져오기 버튼) 고정과 본문만 스크롤, 실제 페이지 3개(Gizmodo, InfoQ, HBR) 검토로 전문 정리 규칙 보강 | **완료**(287개 시나리오 연결). `docs/25-fulltext-review-and-ui-5.md` |
| 21 | 사용 피드백 6차: 모델 잔여 사용량을 서버가 알려 준 값("남은 호출/1000")으로, 삭제는 체크박스 대신 확인 창 한 번, 피드 주소를 바꿀 때 정상적인 피드인지 검사, 사이드바 세 구역을 한 화면에서(목록은 안에서 스크롤), 카테고리에 넣은 피드는 카테고리에만 | **완료**(291개 시나리오 연결). `docs/26-ui-feedback-6-review.md` |

## 골든 데이터 다시 만들기
```
python tools/generate_legacy_golden.py --legacy-dir <기존 스크립트 7개가 있는 폴더> --out tests/golden/legacy_golden.json
```
기존 스크립트가 바뀌지 않으면 다시 만들 필요가 없다.
