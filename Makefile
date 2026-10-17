# 품질 게이트. 모든 단계가 통과해야 한다.
.PHONY: test lint typecheck deadcode check golden coverage

test:
	pytest

golden:
	pytest -m golden

coverage:
	pytest --cov --cov-report=term-missing

lint:
	ruff check src tests tools
	ruff format --check src tests tools

typecheck:
	mypy

# BDD 스텝 함수와 FastAPI 라우트는 데코레이터로 등록되어 vulture가 사용처를 찾지 못한다.
# row_factory는 sqlite3 연결의 표준 속성이고, do_GET 등은 http.server가, ConnectionCls 등은 urllib3와
# requests가 읽는 이름이다.
# tools/는 배포 대상이 아니다.
deadcode:
	vulture src tests --min-confidence 60 --ignore-decorators "@given*,@when*,@then*,@pytest.fixture,@app.*,@router.*" --ignore-names "pytestmark,row_factory,do_GET,do_POST,do_DELETE,log_message,daemon_threads,block_on_close,ConnectionCls,pool_classes_by_scheme,trust_env,lifespan_context"

check: lint typecheck deadcode test
