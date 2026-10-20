# 배포 가이드: GitHub → Actions → 이미지 → Docker 스택 → NPM

## 0. 먼저 알아둘 것

**지금 올라가는 서비스는 상태 화면(`/`), 설정 화면(`/settings`), `/healthz`만 있다.** 수집, 요약, Discord 알림은 아직 구현되지 않았다. 설정 화면에서 키와 웹훅을 저장할 수는 있지만 그 값으로 아직 아무것도 하지 않는다. 그래서 이 가이드의 목적은 서비스를 쓰는 것이 아니라 **배포 경로 전체가 끝까지 동작하는지, 설정이 재시작 뒤에도 남는지 미리 확인하는 것**이다.

```
이 ZIP → GitHub 저장소 → Actions(검사 + 이미지 빌드) → ghcr.io 이미지 → Docker 스택(PC) → NPM(HTTPS) → 접속 확인
```

이 경로를 지금 열어 두면, 이후 단계(설정 화면, 수집 등)는 코드를 푸시하고 이미지를 다시 받는 것만으로 반영된다. 또 설계 문서의 스파이크 S3(Docker Desktop 볼륨), S5(NPM 프록시), S6(NPM 헤더)을 이 단계에서 확인할 수 있다.

**이 가이드의 검증 범위**: 앱은 깨끗한 가상환경에 설치해서 실제로 기동하고 `/healthz`와 `HEALTHCHECK` 명령까지 확인했다. 워크플로 구문은 `actionlint`로 확인했다. **Dockerfile 빌드와 GitHub Actions 실행은 만든 환경에 Docker가 없어서 직접 실행하지 못했다.** 첫 푸시에서 Actions가 처음으로 이 둘을 검증한다. 실패하면 Actions 로그를 보내 주면 고친다(§8).

| 준비물 | 비고 |
|---|---|
| GitHub 계정, Git | 저장소 소유자 이름은 아래 예시에서 `Murianwind`로 적었다. 다르면 바꿔서 읽는다 |
| PC의 Docker Desktop | 시작 시 자동 실행 설정 권장(§5) |
| (선택) Portainer | 스택을 화면에서 관리할 때 |
| NPM(Nginx Proxy Manager)과 도메인 | 외부 HTTPS 접속용 |

---

## 1. GitHub 저장소 만들기와 올리기

1. GitHub에서 새 저장소를 만든다. 이름 예시 `rss-hub`. **비공개(Private) 권장.**
2. ZIP을 풀어서 `rss-hub-m1-spec` 폴더 안에서 다음을 실행한다.

```
cd rss-hub-m1-spec
git init -b main
git add .
git commit -m "chore: 초기 코드"
git remote add origin https://github.com/Murianwind/rss-hub.git
git push -u origin main
```

GitHub CLI(`gh`)가 있으면 저장소 만들기와 푸시를 한 번에 할 수 있다.
```
gh repo create Murianwind/rss-hub --private --source=. --push
```

**푸시 전 확인**: 이 코드에는 웹훅 주소, API 키가 없다(검사함). 앞으로도 웹훅과 키는 코드가 아니라 서비스 설정 화면에만 넣는다.

---

## 2. Actions가 하는 일

| 워크플로 | 언제 | 하는 일 |
|---|---|---|
| `CI` (`ci.yml`) | PR, main 외 브랜치 푸시 | ① 린트, 타입, 데드코드, 테스트(커버리지 95% 이상) ② Docker 이미지를 빌드해서 컨테이너를 띄우고 `/healthz`, 일반 사용자 실행, API 문서 비노출을 확인 |
| `Image` (`image.yml`) | main 푸시, `v*` 태그, 수동 실행 | `CI`를 먼저 호출 → 통과하면 이미지를 빌드해서 `ghcr.io/<소유자>/<저장소>`(소문자)에 게시 |

**첫 푸시 후 확인**: 저장소의 Actions 탭 → `Image` 실행 → `ci` 두 작업과 `publish`가 모두 초록색이면 된다.

게시되는 태그:
| 태그 | 의미 |
|---|---|
| `latest` | main의 최신 |
| `sha-xxxxxxx` | 커밋 단위. 정확한 버전 고정과 되돌리기에 쓴다 |
| `0.1.0`, `0.1` | `v0.1.0` 같은 태그를 푸시했을 때 |

버전 태그 만들기: `git tag v0.1.0 && git push origin v0.1.0`

> 빌드 시간을 줄이고 싶으면 `image.yml`에서 QEMU 단계와 `platforms`의 `linux/arm64`를 지운다. PC(amd64)만 쓰면 arm64 이미지는 필요 없다(오드로이드 같은 ARM 장비에 올릴 때만 필요).

---

## 3. 이미지를 받을 수 있게 하기 (ghcr.io)

처음 게시된 패키지는 비공개다. 둘 중 하나를 고른다.

**A. 이미지를 공개한다 (가장 간단)**: GitHub 프로필 → Packages → `rss-hub` → Package settings → Change visibility → Public. 이미지에는 비밀이 없지만(설정은 모두 DB에 저장되고 DB는 볼륨에 있다) **소스 코드가 들어 있다.** 코드를 공개해도 괜찮을 때만 고른다.

**B. 비공개로 두고 로그인한다**: GitHub에서 `read:packages` 권한의 개인 액세스 토큰(PAT)을 만든다. 패키지는 세분화 토큰이 아닌 **고전(classic) 토큰**이 필요한 것으로 알고 있다(최신 지원 여부는 확인하지 못했다).
- Docker Desktop: `docker login ghcr.io -u Murianwind` → 비밀번호 자리에 토큰
- Portainer: Registries → Add registry → Custom registry → URL `ghcr.io`, 사용자명, 토큰

---

## 4. 스택 파일

저장소의 `compose.yaml`이 스택 파일이다. 환경 변수가 없다.

```yaml
name: rss-hub
services:
  rss-hub:
    image: ghcr.io/murianwind/rss-hub:latest   # 소유자/저장소 이름(소문자)에 맞게 바꾼다
    pull_policy: always
    container_name: rss-hub
    restart: unless-stopped
    ports:
      - "8000:8000"
    volumes:
      - rss-hub-data:/data
    logging: { driver: json-file, options: { max-size: "10m", max-file: "3" } }
volumes:
  rss-hub-data:
```

- 데이터(나중에는 SQLite DB와 설정)는 **이름 있는 볼륨** `rss-hub-data`에 저장된다. 컨테이너를 지우거나 이미지를 바꿔도 남는다.
- Windows 폴더를 직접 연결(바인드 마운트)하지 않는 것을 권장한다. SQLite의 파일 잠금 문제와 권한 문제가 생길 수 있다(미검증).

---

## 5. 올리기

### 5-A. Docker Desktop (PC)
```
docker compose up -d
docker compose ps
curl.exe http://localhost:8000/healthz
```
`{"status":"ok","version":"0.1.0"}`처럼 나오면 된다. 상태가 `healthy`가 될 때까지 최대 30~40초 걸릴 수 있다.

**이미지를 받지 않고 PC에서 직접 빌드해서 확인하고 싶을 때**(GitHub 없이):
```
docker compose -f compose.yaml -f compose.build.yaml up -d --build
```

**Docker Desktop이 PC가 켜질 때 자동으로 시작되게**: Docker Desktop → Settings → General → "Start Docker Desktop when you sign in". 컨테이너는 `restart: unless-stopped`라서 Docker가 시작되면 함께 올라온다. (Windows 로그인 전에는 Docker Desktop이 시작되지 않는다는 점을 기억해 둔다.)

### 5-B. Portainer
Stacks → Add stack → Web editor에 `compose.yaml` 내용을 붙여넣기 → Deploy the stack. 비공개 이미지면 먼저 Registries에 `ghcr.io`를 등록해 둔다.

---

## 6. NPM으로 외부 HTTPS 열기

1. **PC의 LAN 주소를 고정**한다(공유기에서 DHCP 예약 권장). NPM이 이 주소로 연결한다.
2. NPM → Proxy Hosts → Add Proxy Host
   - Domain Names: 사용할 주소(예: `rss.example.com`)
   - Scheme `http`, Forward Hostname/IP: PC의 LAN 주소, Forward Port `8000`
   - Block Common Exploits 켜기, Websockets Support는 끔
   - SSL 탭: 인증서 발급, Force SSL, HTTP/2 켜기
3. NPM이 **다른 장비**에서 돌면 PC의 Windows 방화벽에서 TCP 8000 인바운드를 LAN에서 허용해야 한다.
4. (이후 OPML 업로드를 쓸 때) Proxy Host → Advanced → Custom Nginx Configuration에 `client_max_body_size 10m;`를 넣는다. nginx 기본 업로드 제한이 작아서 큰 파일이 413으로 거절될 수 있다(미검증, 스파이크 S5).

> **이 서비스는 인증이 없다(사용자 결정). 설정 화면이 생긴 지금부터는 주소를 아는 누구나 설정을 바꿀 수 있다.** 값을 읽을 수는 없지만, 웹훅이나 키를 자기 것으로 바꾸는 것은 가능하다(`docs/00-final-plan.md` §5). 다른 사이트를 통한 공격(CSRF)은 막아 두었지만 직접 접속은 막지 못한다.
>
> **실제로 쓰기 전까지는 NPM의 Access List(아이디/비밀번호)를 호스트 전체에 걸어 두는 것을 권장한다.** NPM → Access Lists → Add → 사용자 추가 → Proxy Host의 Access List에서 선택. 이 경우 Discord 링크 미리보기는 못 가져오지만 휴대폰 브라우저에서는 처음 한 번 로그인하면 된다. 설정을 모두 채우고 운영을 시작할 때 풀지 유지할지 정하면 된다.

---

## 7. 확인 체크리스트

| # | 확인 | 방법 | 기대 결과 |
|---|---|---|---|
| 1 | 이미지 게시 | Actions의 `Image`, Packages | 초록색, `latest`와 `sha-…` 태그 |
| 2 | 컨테이너 상태 | `docker compose ps` | `healthy` |
| 3 | 상태 응답 | `curl.exe http://localhost:8000/healthz` | 200, `"status":"ok"` |
| 3-1 | 화면 | 브라우저에서 `http://localhost:8000/`, `/settings` | 상태 화면에 "미설정" 3개, 설정 화면이 열림 |
| 3-2 | 설정 저장 | 설정 화면에서 `LLM 하루 상한`을 바꿔 저장 | "저장했습니다", 변경 이력에 기록 |
| 3-3 | 설정 유지 | `docker compose restart` 후 `/settings` | 바꾼 값이 그대로 |
| 3-4 | 비밀 값 | 키와 웹훅을 저장한 뒤 화면 | "설정됨"만 보이고 값은 안 보임 |
| 3-5 | 피드 가져오기 | `/import`에서 OPML 파일 올리기 → 미리보기 → 확정 | 신규, 중복, 오류가 먼저 보이고 확정 전에는 구독 목록이 안 바뀐다. 사설망 주소(192.168.x.x 등)는 오류로 표시된다 |
| 3-6 | 잡 | 서버를 시작하고 1분 뒤 `/status`의 "작업" 표에서 요약과 발송이 `ok`로 보인다. 수집은 다음 5분 슬롯(0, 5, 10분…) 이후에 `ok`로 바뀐다 | `/healthz`가 200이고 `last_summarize`, `last_deliver`에 시각이 있다. 수집이 15분 넘게 멈추면 503(`stale`)이 되어 컨테이너가 비정상으로 표시된다 |
| 3-7 | 웹훅 시험 전송 | 설정 화면의 웹훅 옆 "시험 전송" | 선택한 웹훅의 채널에 시험 메시지가 한 건 온다. 실패하면 상태 코드와 이유가 나온다(주소는 안 보인다) |
| 3-8 | OpenRouter 키 확인 | 설정 화면의 "키 확인" | "키가 유효합니다 · 오늘 무료 모델 호출 N/1000". 채팅 호출을 하지 않아서 오늘 호출 수는 늘지 않는다 |
| 3-9 | 주제 판별 시험 | `/topics`의 "판별 시험"에 실제 글 제목을 넣는다 | 켜진 주제마다 LLM 선택, 키워드, 해당 여부가 나온다. **새 요약 프롬프트를 실제 무료 모델로 확인하는 첫 기회**다(한 번에 LLM 호출 1회) |
| 3-10 | 피드 추가와 내보내기 | `/feeds`에서 웹사이트 주소를 넣어 확인, 등록한 뒤 "OPML로 내보내기" | 웹사이트가 알려 준 피드가 후보로 나온다. 내려받은 파일을 가져오기에 올리면 전부 "이미 구독 중"이다 |
| 3-11 | 뷰어 | 상단 메뉴의 "읽기" | 사이드바에 RSS, 카테고리, 주제 세 그룹이 있고, 새로 가져온 피드는 첫 점검 뒤에 최근 글 5개가 보인다. Discord 알림의 링크를 누르면 글 페이지가 열리고 "원문 보기"로 원문에 간다 |
| 3-12 | 보관 기간 | 설정의 "글 보관 기간" | 기본 90일. 지난 글은 6시간마다 자동으로 지워지고(0이면 유지) "이미 본 글" 기록은 남는다 |
| 3-13 | 주제 피드백 | 글 페이지의 "주제로", "싫어요", "되돌리기" | 싫어요는 그 주제 목록에서만 글을 뺀다. 주제로는 이미 보낸 알림을 다시 보내지 않는다. `/topics`의 "키워드 개선 제안"은 "주제로"를 2번 이상 눌러야 추가 제안이 나온다 |
| 3-14 | 모델 스캔 | 상단 메뉴의 "모델" → 스캔 | 무료 텍스트 모델 목록이 나오고 현재 체인의 모델에 "체인 N" 표시가 붙는다. 호출 한도를 쓰지 않는다 |
| 3-15 | 모델 벤치마크 | 모델을 1~2개 골라 "선택한 모델 벤치마크" | **모델 하나당 LLM 호출 6회**(오늘 호출 수에 포함, 약 30초). 점수(100점 만점)와 성공 횟수가 나온다. 점수 비중(성공률 50, 한국어 제목 20, 주제 판정 20, 속도 10)이 맞는지 처음 결과를 보고 판단한다 |
| 3-16 | 새 읽기 화면 | 주소 `/reader` | 왼쪽에 사이드바(RSS 피드, 카테고리, 주제, 환경 설정)가 있고 구역은 접혀 있다. 접기 버튼을 누르고 새로고침해도 접힌 채 유지된다. 업그레이드 직후 기존 글은 모두 읽음이라 안 읽은 글 수는 새로 수집되는 글부터 쌓인다 |
| 3-17 | 읽음과 북마크 | 글을 열고, 북마크 버튼 | 글을 열면 읽음이 되어 사이드바 뱃지가 줄어든다. 북마크한 글은 북마크 목록에 모이고 90일 정리에서 지워지지 않는다 |
| 3-18 | 리버스 프록시 | NPM 등 | 정적 파일 `/static/*`을 같은 서비스 주소로 전달해야 한다(별도 설정 없이 같은 경로면 된다). 보안 정책이 `script-src 'self'`로 바뀌었으므로 프록시가 CSP 헤더를 덮어쓰거나 `/static`을 막지 않는지 확인한다 |
| 3-19 | 슬라이드 패널 | 사이드바의 `+`, 톱니바퀴, `−` | 본문 위에서 패널이 내려온다. 피드 설정에서 이름을 바꾸고 저장하면 보던 화면으로 돌아와 "저장했습니다." 토스트가 뜬다. 삭제는 확인란을 선택해야만 보낼 수 있다 |
| 3-20 | 드래그 | 사이드바 항목의 손잡이(점 6개) | 같은 목록 안에서 끌어 순서를 바꾸면 새로고침해도 유지된다. 피드를 카테고리 머리글에 놓으면 옮겨지고, RSS 피드 머리글에 놓으면 카테고리에서 빠진다. 개별 웹훅이 있는 피드는 이유를 알리며 거부된다 |
| 3-21 | 설정 탭 | 환경 설정 메뉴 | 일반, 구독 & OPML, 알림, LLM · 모델, 디스플레이 및 테마, 주제 관리, 상태 일곱 항목. 탭에서 저장하면 같은 탭으로 돌아온다 |
| 3-22 | 테마와 글자 크기 | 디스플레이 및 테마 탭 | "어둡게"를 저장하면 모든 화면이 어두워지고 "크게"를 저장하면 글자가 17px이 된다. "기기 설정 따르기"는 기기의 밝기 설정을 따른다 |
| 3-23 | 피드 상태 점 | 사이드바의 피드 | 초록(정상), 빨강(마지막 점검 실패, 마우스를 올리면 이유), 회색(아직 수집 전)이 보인다 |
| 3-24 | 강제 새로고침 | 피드의 새로고침 버튼 | 지금 바로 다시 읽고 점과 개수가 화면을 다시 불러오지 않고 바뀐다. 실패하면 이유가 토스트로 나온다 |
| 3-25 | 피드 주소 변경 | 피드 설정 패널 | 주소를 바꾸면 점이 회색으로 돌아가고 처음부터 다시 점검한다. 예전 글은 알림으로 보내지 않는다 |
| 3-26 | 피드 관리 | 환경 설정 > 피드 관리 | 피드마다 상태 점, 활동량, **자동 배정된 수집 주기**(시간당 N회, 점검 분, 다음 점검), 마지막 점검, 알림 대상이 보인다. 상태 칩으로 거를 수 있다 |
| 3-27 | 설정 | 환경 설정 > 설정 | 서비스 주소, 수집과 보관, LLM, 알림, 화면, 변경 이력이 아코디언 한 페이지에 있다. 예전 `/settings/general` 같은 탭 주소는 더 이상 없다 |
| 3-28 | 자동 읽음 | 글 목록에서 스크롤 | 화면 가운데 위로 올라온 글(목록이 한 화면에 다 들어오면 전부)이 읽음이 되고 사이드바 개수가 줄어든다. 카드의 "안 읽음으로 표시"를 누른 글은 스크롤해도 읽음이 되지 않는다. 설정 > 화면에서 끌 수 있다 |
| 3-29 | 사이드바 폭 | PC에서 사이드바 오른쪽 경계 | 끌어서 폭을 바꾸고 새로고침해도 유지된다(220~480px). 두 번 누르면 기본 폭. 모바일에는 없다 |
| 3-30 | 업그레이드 | 첫 시작 | 마이그레이션 11(예전 "매 슬롯" 피드를 자동 배정으로), 12(안 읽음 고정 표시)가 자동 적용된다 |
| 4 | 외부 접속 | 휴대폰(모바일 데이터)에서 `https://<도메인>/healthz` | 200 |
| 5 | API 문서 비노출 | `https://<도메인>/docs` | 404 |
| 6 | 볼륨 쓰기 | 3번이 `ok`이면 `/data`에 쓸 수 있다는 뜻 | `503 data_dir_not_writable`이 아니어야 함 |
| 7 | 재시작 유지 | `docker compose restart` 후 3번 | 다시 200 |
| 8 | PC 재부팅 | 재부팅, Windows 로그인 후 3번 | 자동으로 200 |
| 9 | 인증서 | 브라우저 자물쇠 | 유효 |

3~8이 통과하면 스파이크 S3(볼륨)와 S5(NPM)의 기본 확인이 끝난다. 결과를 알려 주면 설계 문서에 반영한다.

---

## 8. 업데이트, 되돌리기, 백업

**업데이트(최신 이미지로)**
```
docker compose pull
docker compose up -d
```
Portainer: 스택 → "Pull and redeploy".

**되돌리기**: `compose.yaml`의 `image:` 태그를 `latest`에서 이전 `sha-xxxxxxx`나 `0.1.0`으로 바꿔서 다시 `up -d`. 운영이 시작되면 `latest` 대신 버전 태그로 고정하는 것을 권장한다.

**볼륨 백업**(PowerShell)
```
docker run --rm -v rss-hub-data:/data -v ${PWD}:/backup alpine tar czf /backup/rss-hub-data.tgz -C /data .
```
**복원**: 같은 명령에서 `czf`를 `xzf`로, 방향을 바꿔 압축을 푼다. 서비스를 멈춘 상태에서 한다.

---

## 9. 문제 해결

| 증상 | 원인과 해결 |
|---|---|
| Actions `check`의 `린트와 포맷` 실패 | 로컬에서 `make lint` 실행 후 `ruff format src tests tools`로 정리 |
| Actions `docker-smoke` 실패 | 로그의 `docker logs` 출력 확인. 이 단계가 Dockerfile을 처음 검증한다. 로그를 보내 주면 고친다 |
| `publish`에서 `denied`/`unauthorized` | 저장소 Settings → Actions → General → Workflow permissions가 "Read and write"인지, 또는 패키지 접근 권한 확인 |
| `docker pull`에서 `denied` | 패키지가 비공개인데 로그인하지 않음(§3) |
| 컨테이너 `unhealthy`, `/healthz`가 503 `data_dir_not_writable` | `/data`에 실행 사용자(uid 10001)가 쓸 수 없음. **이름 있는 볼륨**을 쓰는지 확인(폴더를 직접 연결하면 이 문제가 생긴다) |
| 외부에서 502 | NPM의 Forward 주소/포트, PC 방화벽, PC의 LAN 주소가 바뀌었는지 확인 |
| 외부에서 접속 불가, 내부는 됨 | 공유기 포트포워딩(80/443 → NPM), DNS, 인증서 확인 |
| 재부팅 후 서비스가 안 올라옴 | Docker Desktop 자동 시작 설정(§5-A), Windows 로그인 필요 |

---

## 10. 이 단계 이후

이 경로가 확인되면 다음 단계(설정 저장소와 설정 화면)부터는 **코드를 main에 푸시 → Actions가 이미지 게시 → PC에서 `pull`과 `up -d`**만 반복하면 된다.
