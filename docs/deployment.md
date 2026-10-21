# 배포 가이드

RSS Hub는 컨테이너 하나로 동작합니다. 설정은 전부 웹 화면에서 하므로 **환경 변수가 없고**, 컨테이너에 주는 것은 데이터 볼륨(`/data`)과 포트(8000)뿐입니다.

## 실행 방법 고르기

| 방법 | 언제 | 명령 |
|---|---|---|
| 직접 빌드 | 이미지를 받을 수 없거나 코드를 고쳐서 쓸 때 | `docker compose -f compose.yaml -f compose.build.yaml up -d --build` |
| 게시된 이미지 | 포크해서 Actions로 이미지를 게시했거나 공개 이미지를 쓸 때 | `docker compose up -d` |
| Portainer | 스택을 화면에서 관리할 때 | Stacks > Add stack > Web editor에 `compose.yaml` 붙여넣기 > Deploy the stack |

확인:

```
docker compose ps                        # 상태가 healthy가 될 때까지 최대 30~40초
curl http://localhost:8000/healthz       # {"status":"ok","version":"..."}
```

`compose.yaml`의 `image:`는 `ghcr.io/<소유자>/<저장소>`(소문자)입니다. 포크해서 쓰면 소유자를 바꾸세요. 태그는 `latest`, `sha-xxxxxxx`(커밋), `0.1.0`(버전 태그) 중에서 고릅니다. 운영 중에는 `latest` 대신 고정 태그를 권장합니다.

데이터는 이름 있는 볼륨 `rss-hub-data`에 저장됩니다. Windows 폴더를 직접 연결(바인드 마운트)하면 SQLite 파일 잠금과 권한 문제가 생길 수 있어 권장하지 않습니다. 컨테이너는 일반 사용자(uid 10001)로 실행되고, 볼륨에 쓸 수 없으면 `/healthz`가 503(`data_dir_not_writable`)을 돌려줍니다.

## 이미지 게시(GitHub Actions)

| 워크플로 | 언제 | 하는 일 |
|---|---|---|
| `CI` (`ci.yml`) | PR, main 외 브랜치 푸시 | 린트, 타입, 데드코드, 테스트(커버리지 95% 이상). Docker 이미지를 빌드해 컨테이너를 띄우고 `/healthz`, 일반 사용자 실행, API 문서(`/docs`) 비노출을 확인 |
| `Image` (`image.yml`) | main 푸시, `v*` 태그, 수동 실행 | `CI`를 먼저 호출하고 통과하면 `linux/amd64`, `linux/arm64` 이미지를 `ghcr.io`에 게시 |

버전 태그는 `git tag v0.1.0 && git push origin v0.1.0`으로 만듭니다. ARM 장비를 쓰지 않으면 `image.yml`에서 QEMU 단계와 `platforms`의 `linux/arm64`를 지워 빌드 시간을 줄일 수 있습니다.

처음 게시된 패키지는 비공개입니다. 공개하려면 GitHub 프로필 > Packages > `rss-hub` > Package settings > Change visibility에서 Public으로 바꿉니다. 비공개로 두면 `docker login ghcr.io`(`read:packages` 권한의 토큰)가 필요합니다.

## 리버스 프록시(Nginx Proxy Manager)

1. 서비스가 도는 장비의 LAN 주소를 고정합니다.
2. Proxy Hosts > Add Proxy Host: Scheme `http`, Forward Hostname/IP는 그 장비, Forward Port `8000`. Block Common Exploits를 켜고, SSL 탭에서 인증서 발급과 Force SSL을 켭니다.
3. 프록시가 다른 장비에서 돈다면 서비스 장비의 방화벽에서 TCP 8000을 허용합니다.
4. OPML 업로드가 413으로 거절되면 Advanced > Custom Nginx Configuration에 `client_max_body_size 10m;`를 넣습니다(nginx 기본 업로드 제한이 작습니다).
5. 프록시가 `/static/*`을 막거나 `Content-Security-Policy` 헤더를 덮어쓰지 않아야 합니다. 화면 스크립트는 `script-src 'self'` 정책으로 같은 서비스 주소의 `/static`에서 로드됩니다.

**이 서비스에는 인증이 없습니다.** 외부에 열 때는 프록시의 Access List(Basic 인증)나 VPN을 반드시 앞에 두세요. 단, 인증을 걸면 Discord가 알림 안의 링크 미리보기를 가져오지 못합니다.

## 확인 목록

처음 배포한 뒤 아래를 순서대로 확인하면 주요 경로가 모두 동작하는지 알 수 있습니다.

| 확인 | 방법 | 기대 결과 |
|---|---|---|
| 컨테이너 상태 | `docker compose ps` | `healthy` |
| 상태 응답 | `curl http://localhost:8000/healthz` | 200, `"status":"ok"` |
| 설정 유지 | 설정을 바꾸고 `docker compose restart` | 값이 그대로 |
| 비밀 값 | 키와 웹훅 저장 후 화면 | "설정됨"만 보이고 값은 안 보임 |
| 웹훅 | Discord 화면의 웹훅 "시험" | 채널에 시험 메시지 |
| OpenRouter 키 | 모델 화면의 "확인" | "키가 유효합니다 …". 채팅 호출을 하지 않으므로 호출 수는 늘지 않음 |
| 피드 | 사이드바의 RSS 피드 옆 `+`로 사이트 주소 추가, 피드 관리에서 OPML 가져오기와 내보내기 | 후보가 나오고, 내보낸 파일을 다시 가져오면 전부 "이미 구독 중" |
| 잡 | 시작 1분 뒤 `/status`의 작업 표 | 요약과 발송이 `ok`, 수집은 다음 5분 슬롯 뒤 `ok` |
| 정체 감지 | 수집이 15분(또는 수집 주기의 3배) 넘게 멈춤 | `/healthz`가 503(`stale`)이 되어 컨테이너가 비정상으로 표시됨 |
| 외부 접속 | 휴대폰(모바일 데이터)에서 `https://<도메인>/healthz` | 200 |
| API 문서 비노출 | `https://<도메인>/docs` | 404 |
| 재부팅 | 장비 재부팅 후 `/healthz` | 자동으로 200(`restart: unless-stopped`, Docker가 시작되어 있어야 함) |

## 업데이트와 백업

업데이트:

```
docker compose pull && docker compose up -d                           # 게시된 이미지
git pull && docker compose -f compose.yaml -f compose.build.yaml up -d --build   # 직접 빌드
```

데이터베이스 마이그레이션은 시작할 때 자동으로 적용됩니다. 되돌릴 때는 `image:` 태그를 이전 `sha-xxxxxxx`나 버전 태그로 바꿔 다시 `up -d` 하세요. 단, 새 버전이 이미 마이그레이션한 데이터베이스는 이전 버전이 읽지 못할 수 있으니 업데이트 전에 백업하세요.

백업은 두 가지입니다.

- **화면의 백업과 복원**(환경 설정 > 백업·복원): 구독, 글, 읽음·북마크, 설정을 JSON으로. 웹훅 주소와 OpenRouter 키는 들어 있지 않아 파일을 다루기 안전합니다. 복원 방법은 README의 [백업과 복원](../README.md#백업과-복원).
- **볼륨 통째로**: 키와 웹훅 주소까지 모두 포함합니다(서비스를 멈춘 상태에서 하는 것이 가장 안전합니다):

```
docker run --rm -v rss-hub-data:/data -v "$PWD":/backup alpine tar czf /backup/rss-hub-data.tgz -C /data .
```

복원은 같은 방식으로 `tar xzf`로 `/data`에 풉니다. 백업 파일에는 웹훅 주소와 OpenRouter 키가 들어 있으니 안전한 곳에 보관하세요.

## 문제 해결

| 증상 | 원인과 해결 |
|---|---|
| `docker pull`에서 `denied` | 패키지가 비공개인데 로그인하지 않았습니다. 직접 빌드하거나 `docker login ghcr.io`를 하세요 |
| Actions `publish`가 `denied`/`unauthorized` | 저장소 Settings > Actions > General > Workflow permissions를 "Read and write"로 바꾸세요 |
| 컨테이너 `unhealthy`, 503 `data_dir_not_writable` | `/data`에 쓸 수 없습니다. 폴더 연결 대신 이름 있는 볼륨을 쓰세요 |
| 503 `stale` | 수집 잡이 오래 멈췄습니다. `/status`의 작업 표에서 마지막 오류를 확인하세요 |
| 알림이 오지 않음 | 서비스 주소나 기본 웹훅이 비어 있으면 요약과 발송이 기다립니다. `/status`의 설정 점검 항목을 확인하세요. OpenRouter 키는 선택이며, 없으면 원문 제목과 링크만 갑니다 |
| 설정 저장에서 403 | 프록시가 `Origin`/`Sec-Fetch-Site` 헤더를 바꾸거나 nginx가 요청을 막은 경우입니다. 응답이 nginx의 "403 Forbidden"인지 앱의 "요청이 거부되었습니다"인지 구분하세요 |
| 외부에서 502 | 프록시의 Forward 주소/포트, 방화벽, 장비의 LAN 주소 변경을 확인하세요 |
