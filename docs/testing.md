# 테스트

행동은 **BDD 시나리오**(`features/*.feature`, Gherkin, 한국어)로 정하고, 시나리오의 단계는 **키워드 계층**(`tests/keywords/`)의 동사로 구현합니다. 새 기능이나 버그 수정은 시나리오(또는 시험)를 먼저 쓰고 실패를 확인한 뒤 구현합니다.

## 실행

```
pip install -e ".[dev]"
make check        # lint + typecheck + deadcode + test
make test         # 시험만 (전체 약 6분)
make coverage     # 커버리지 보고
pytest tests/unit -q                 # 빠른 순수 규칙 시험
pytest -k "page_subscription" -q     # 이름으로 고르기
```

CI는 같은 검사를 하고 커버리지 95% 미만이면 실패시킵니다(현재 100%).

## 구성

| 폴더 | 무엇을 | 속도 |
|---|---|---|
| `features/` | 행동 명세. 시나리오마다 ID 태그(`@SCH-01` 등) | - |
| `tests/bdd/` | 시나리오의 단계 정의. `binding.py`가 ID로 시나리오를 골라 pytest 테스트로 연결 | 보통 |
| `tests/unit/` | domain 순수 규칙. 입출력 없음 | 빠름 |
| `tests/storage/` | 실제 SQLite(임시 폴더)로 저장소 | 빠름 |
| `tests/services/` | 서비스 + 가짜 포트(수집기, LLM, 웹훅, 시계) | 보통 |
| `tests/adapters/` | 어댑터 + 실제 로컬 HTTP 서버 | 보통 |
| `tests/jobs/` | 스케줄러 | 보통 |
| `tests/web/` | FastAPI `TestClient`로 화면과 요청 처리 | 느림 |
| `tests/golden/` | 기준 데이터(`reference_cases.json`)와 현재 규칙 비교 | 빠름 |
| `tests/fakes/` | 가짜 시계, 수집기, LLM, 웹훅, 로컬 HTTP 서버와 시험 환경(`*_env.py`) | - |
| `tests/keywords/` | **키워드 계층** | - |

## 키워드 계층

시험 파일이 HTTP 헤더, HTML 구조, 저장소 내부를 직접 알면 같은 코드가 파일마다 복사됩니다. 반복되는 "동사"는 `tests/keywords/`에 한 번만 둡니다.

| 모듈 | 키워드 |
|---|---|
| `browser` | `post(world, path, **data)`: 같은 출처의 브라우저가 양식을 보냄. `BROWSER`, `CROSS_SITE`, `FRAGMENT` 요청 머리글 |
| `page` | `card`, `row`, `text_of`, `body`, `rss_section`, `category_section`, `feed_ids`, `heading_link`: 화면 HTML에서 부분 찾기 |
| `backup` | `download_backup`, `restore_backup`, `edited`: 백업 내려받기, 올려서 복원하기, 내용 고치기 |
| `store` | `create_category`, `set_poll_priority`: 준비. `stored_stats`, `topic_matches`, `usage_breakdown`: 관찰(데이터베이스 표를 직접 읽음) |

규칙:

1. BDD 단계 함수는 얇게 씁니다. 단계의 문장을 키워드 호출과 단언으로 옮기는 것까지만 하고, 요청 만들기와 HTML 찾기는 키워드에 맡깁니다.
2. 키워드는 이름이 동사이고, 한 가지 일만 하며, 단언을 숨기지 않습니다(찾지 못하면 예외로 실패).
3. **시험에서만 필요한 조회는 제품 코드에 두지 않습니다.** 제품에서 쓰지 않는 메서드를 시험 때문에 남기면 죽은 코드가 됩니다. `store`처럼 시험 쪽 키워드로 두세요.
4. 두 파일 이상에서 같은 헬퍼가 필요해지면 파일마다 복사하지 말고 키워드로 올립니다.

## 시나리오와 시험 연결

`tests/bdd/binding.py`의 `bind(globals(), "<feature 파일>", [ID, ...])`가 시나리오를 ID로 골라 연결합니다. 연결하지 않은 시나리오가 있으면 목록에서 바로 보이도록, 새 시나리오를 쓰면 같은 변경에서 연결하세요. 시나리오 안의 `@태그`는 pytest 마커로 변환되지만 문서용이므로 등록하지 않습니다(경고 무시 설정은 `pyproject.toml`).

## 품질 게이트

`make check`가 순서대로 실행합니다.

| 단계 | 도구 | 비고 |
|---|---|---|
| lint | `ruff check`, `ruff format --check` | 규칙은 `pyproject.toml` |
| typecheck | `mypy` (strict, `src`만) | 타입이 없는 라이브러리는 `pyproject.toml`에서 예외 처리 |
| deadcode | `vulture src` | 데코레이터나 프레임워크가 부르는 이름은 `Makefile`에 적어 둠. **시험은 검사 대상에 넣지 않습니다**: 시험이 쓰기만 해도 "사용 중"이 되어 제품의 죽은 코드를 가리기 때문 |
| test | `pytest` | 외부 서비스를 부르는 시험은 `live` 마커로 기본 제외 |

## 기준 데이터

`tests/golden/reference_cases.json`은 이 서비스가 대체한 이전 스크립트들의 출력을 기록한 표입니다(GUID 정규화, 날짜 해석, 한국어 판별, 스케줄, 메시지 모양). 현재 규칙이 같은 입력에서 같은 결과를 내는지(또는 의도적으로 고친 결함만 다른지) 비교하는 회귀 시험의 기준이며, 값을 바꾸려면 바꾸는 이유를 같은 변경에 설명하세요.
