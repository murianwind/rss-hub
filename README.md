# RSS Hub

RSS 피드와 RSS가 없는 웹페이지를 구독해서, 새 글을 **한국어 제목과 요약**으로 바꾸고, 원하는 주제의 글만 골라 **Discord로 알려 주는** 셀프 호스팅 서비스입니다. 알림에 들어 있는 링크를 누르면 서비스에 내장된 읽기 화면(안 읽은 글 수, 북마크, 검색, 글 전문 보기)이 열립니다.

> 화면과 알림 문구는 **한국어만** 지원합니다. 요약에는 OpenRouter의 무료 모델을 쓰며, OpenRouter 키가 없어도 Discord 웹훅만으로 쓸 수 있습니다([키 없이 쓰기](#openrouter-키-없이-쓰기)).

## 할 수 있는 일

| 기능 | 설명 |
|---|---|
| 구독 | RSS/Atom 피드, 사이트 주소만으로 피드 자동 찾기, **RSS가 없는 사이트의 글 목록 페이지 구독**, OPML 가져오기와 내보내기 |
| 수집 | 5분 단위 슬롯으로 피드를 나눠 점검하고, 글이 자주 올라오는 피드는 더 자주 점검 |
| 요약 | 영문 글의 제목 번역과 한국어 요약. 호출 한도(하루, 분당)를 지키고 모델 장애 때는 다음 모델로 넘어감 |
| 주제 | 키워드로 후보를 먼저 거르고 LLM이 확인. 주제마다 다른 Discord 채널로 전송, 싫어요/"주제로" 피드백과 키워드 개선 제안 |
| 알림 | Discord 웹훅. 기본, 카테고리, 피드, 주제 순서로 보낼 채널을 정함 |
| 읽기 화면 | 사이드바(RSS, 카테고리, 주제), 읽음/안 읽음, 북마크, 검색, 글 전문(원문 페이지에서 본문 추출), 라이트/다크 테마 |
| 모델 관리 | OpenRouter 무료 모델 스캔, 벤치마크, 추천, 승인 후 교체 |
| 백업·복원 | 구독, 카테고리, 주제, 글, 읽음·북마크, 설정을 JSON 파일로 내려받고 되돌림(웹훅 주소와 키는 제외) |
| 운영 | 모든 설정을 웹 화면에서 변경(환경 변수 없음, 재시작 불필요), 변경 이력, `/healthz` 상태 확인 |

## 준비물

- Docker와 Docker Compose
- (선택) [OpenRouter](https://openrouter.ai) API 키(무료 모델만 사용). 없으면 번역과 요약 없이 원문 제목과 링크만 알립니다
- 알림을 받을 Discord 서버의 [웹훅 주소](https://discord.com/developers/docs/resources/webhook)
- 서비스에 접속할 수 있는 주소: Discord 알림 안의 링크가 이 주소로 만들어집니다(예: `http://192.168.0.10:8000` 또는 리버스 프록시의 HTTPS 주소)

## 빠른 시작

```
git clone https://github.com/murianwind/rss-hub.git
cd rss-hub
docker compose -f compose.yaml -f compose.build.yaml up -d --build
curl http://localhost:8000/healthz
```

`{"status":"ok", ...}`가 나오면 브라우저에서 <http://localhost:8000> 을 엽니다.

미리 빌드된 이미지를 쓰려면 `compose.yaml`만으로 실행합니다(이미지는 GitHub Actions가 `ghcr.io/murianwind/rss-hub`에 게시합니다. 패키지가 비공개이면 로그인이 필요하므로 위의 직접 빌드를 쓰세요).

```
docker compose up -d
```

데이터(SQLite 데이터베이스와 설정)는 이름 있는 볼륨 `rss-hub-data`(컨테이너의 `/data`)에 저장되므로 컨테이너를 다시 만들어도 남습니다.

## 처음 설정

**기본 웹훅과 서비스 주소를 설정하기 전에는 요약과 발송이 기다리기만 하고 아무것도 보내지 않습니다.** OpenRouter 키는 선택입니다.

1. **환경 설정 > 설정**에서 *서비스 주소*를 입력합니다(접속하는 주소를 그대로 입력하면 후보로 제안됩니다).
2. (선택) *OpenRouter 키*를 저장하고 **키 확인**을 눌러 확인합니다. 키는 저장한 뒤에는 다시 보이지 않습니다. 키가 없으면 아래 [키 없이 쓰기](#openrouter-키-없이-쓰기)대로 동작합니다.
3. *웹훅*을 추가하고 **시험 전송**으로 채널에 메시지가 오는지 확인한 뒤, 기본 웹훅으로 지정합니다.
4. 읽기 화면 사이드바의 **RSS 피드 옆 `+`**에 사이트 주소를 넣어 피드를 추가하거나(RSS가 없으면 웹페이지 구독 후보가 나옵니다), **환경 설정 > 피드 관리**에서 기존 구독 목록을 OPML 파일로 가져옵니다.
5. (선택) **주제**를 만들어 키워드와 설명을 넣으면, 그 주제에 해당하는 글만 지정한 웹훅으로 따로 보냅니다.

새로 구독한 피드의 첫 점검은 현재 글을 알림 없이 "이미 본 글"로만 기록합니다. 이후에 올라오는 글부터 알림이 갑니다. 서비스를 5분 슬롯(0, 5, 10분…)이 아닌 시각에 시작하면 첫 수집은 다음 슬롯까지 최대 5분 걸립니다.

## OpenRouter 키 없이 쓰기

기본 웹훅과 서비스 주소만 있고 OpenRouter 키가 없으면 LLM을 한 번도 부르지 않습니다. 새 글은 **원문 제목과 서비스 글 링크**만 Discord로 가고(번역과 요약 없음), 읽기 화면에도 원문 제목으로 보입니다.

- 주제는 **키워드가 맞는 것만** 해당합니다. 키워드 없이 LLM의 판단만으로 정하는 주제는 키가 있어야 동작합니다.
- 상태 화면에서 OpenRouter 키는 "선택"으로 표시됩니다.
- 키를 나중에 넣으면 그 뒤에 수집한 글부터 요약합니다. 이미 원문 제목으로 보낸 글은 다시 요약하거나 보내지 않습니다.

## 보안

로그인 기능은 의도적으로 두지 않았습니다. 외부에 공개할 때는 리버스 프록시의 접근 제어나 VPN 뒤에 두세요. 다른 사이트를 통한 요청 위조(CSRF)는 막고, 사설망 주소로의 요청(SSRF)은 피드 수집, 가져오기, 원문 가져오기에서 모두 차단합니다. 그래서 같은 네트워크 안의 `192.168.x.x` 같은 주소로 제공되는 피드는 구독할 수 없습니다. 자세한 내용은 [docs/deployment.md](docs/deployment.md)와 [docs/architecture.md](docs/architecture.md#보안-장치)를 보세요.

## 사용량과 한도

OpenRouter 무료 모델에는 호출 한도가 있습니다([공식 한도 문서](https://openrouter.ai/docs/api-reference/limits)). 서비스는 설정한 값(기본: 하루 700회, 분당 15회, 80%에서 경고)을 넘지 않게 호출하고, 한도나 장애가 생기면 시스템 알림 웹훅으로 알립니다. 글 한 건의 제목 번역, 요약, 주제 판별은 호출 한 번으로 처리합니다.

## 업데이트와 백업

```
docker compose pull && docker compose up -d      # 미리 빌드된 이미지
docker compose -f compose.yaml -f compose.build.yaml up -d --build    # 직접 빌드(git pull 뒤)
```

## 백업과 복원

**환경 설정 > 설정 > 백업과 복원**에서 합니다.

- **백업 파일 내려받기**: 구독(피드, 카테고리), 주제, 글(읽음, 북마크, 전문 포함), 설정을 JSON 파일 하나로 받습니다. **웹훅 주소와 OpenRouter 키는 들어 있지 않습니다.** 웹훅은 이름만 적힙니다.
- **복원**: 파일을 올리고 확인란을 선택하면 현재 구독, 글, 읽음 상태, 설정이 **모두 파일의 내용으로 바뀝니다**. 하나의 트랜잭션이라 중간에 실패하면 아무것도 바뀌지 않습니다.
  - 파일에 적힌 웹훅 이름과 같은 이름의 웹훅이 지금 있으면 다시 연결합니다. 없으면 지정을 해제하고 결과 화면에서 알려 주니, 웹훅을 만들어 다시 지정하세요.
  - 웹훅 주소와 키, 변경 이력, LLM 호출 기록, 모델 스캔 결과는 복원 대상이 아닙니다(현재 것을 그대로 둡니다).
  - 더 새로운 버전에서 만든 백업은 복원할 수 없습니다. 파일 크기는 100MB까지입니다.
- 서비스를 옮길 때는 새 서비스에서 웹훅 주소와 키를 먼저 설정하고, 같은 이름의 웹훅을 만든 뒤 복원하면 지정까지 이어집니다.

`/data` 볼륨을 통째로 압축하는 방법(키와 웹훅 주소까지 모두 포함)은 [docs/deployment.md](docs/deployment.md#업데이트와-백업)에 있습니다.

## 문서

| 문서 | 내용 |
|---|---|
| [docs/deployment.md](docs/deployment.md) | 배포: 이미지 게시, 리버스 프록시(NPM), 업데이트와 백업, 문제 해결, 확인 목록 |
| [docs/architecture.md](docs/architecture.md) | 구조: 계층, 잡, 데이터 흐름, 저장소, 보안 장치 |
| [docs/testing.md](docs/testing.md) | 테스트: BDD 시나리오와 키워드 계층, 품질 게이트 |

## 개발

Python 3.12 이상이 필요합니다.

```
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
make check          # 린트 + 타입 + 데드코드 + 테스트
make coverage       # 커버리지 보고
```

`make`가 없는 환경(Windows)에서는 Makefile의 명령을 그대로 실행하세요.

내 PC에서 직접 실행해 보려면(데이터는 `./data`에 저장됩니다. 서비스는 환경 변수를 쓰지 않으므로 Docker 밖에서는 경로를 코드로 지정합니다):

```
python - <<'EOF'
from pathlib import Path
import uvicorn
from rss_hub.runtime import build_runner
from rss_hub.web.app import create_app

uvicorn.run(create_app(data_dir=Path("data"), runner_factory=build_runner), port=8000)
EOF
```

### 기여

이슈와 풀 리퀘스트를 환영합니다. 변경은 [BDD 시나리오](features/)를 먼저 추가하거나 고치고, 시험이 통과하는 최소 구현을 더하는 순서로 해 주세요. `make check`가 통과해야 합니다(CI도 같은 검사를 하며 커버리지 95% 미만이면 실패합니다). 자세한 방법은 [docs/testing.md](docs/testing.md)에 있습니다.

## 저장소 구성

```
src/rss_hub/
  domain/      순수 규칙(스케줄, 키워드, 요약 검증, 본문 정제, URL 규칙 등)
  storage/     SQLite 저장소와 마이그레이션
  services/    수집, 요약, 발송, 설정, 모델 관리 같은 동작과 외부 연결 인터페이스(ports)
  adapters/    HTTP 피드 수집기, OpenRouter 클라이언트, Discord 웹훅 전송기
  jobs/        수집/요약/발송 잡을 주기에 맞춰 실행하는 스케줄러
  web/         FastAPI 앱, 템플릿, 정적 파일
features/      Gherkin 시나리오(행동 명세, 한국어)
tests/         시험(키워드 계층 tests/keywords 포함)
Dockerfile  compose.yaml  compose.build.yaml
```

## 라이선스

[MIT](LICENSE)
