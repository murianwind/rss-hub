# 품질 게이트. 모든 단계가 통과해야 한다.
.PHONY: test lint typecheck deadcode check golden coverage

test:
	pytest

golden:
	pytest -m golden

coverage:
	pytest --cov --cov-report=term-missing

lint:
	ruff check src tests
	ruff format --check src tests

typecheck:
	mypy

# 시험은 검사 대상이 아니다(시험이 쓰기만 해도 "사용 중"이 되어 제품의 죽은 코드를 가린다).
# 템플릿과 프레임워크가 읽는 이름은 vulture_whitelist.py에 이유와 함께 적는다.
# row_factory는 sqlite3 연결의 표준 속성이고, do_GET 등은 http.server가, ConnectionCls 등은 urllib3와
# requests가 읽는 이름이며, handle_*는 html.parser가 부르는 이름이다.
deadcode:
	vulture src vulture_whitelist.py --min-confidence 60 --ignore-decorators "@app.*,@router.*" --ignore-names "row_factory,do_GET,do_POST,do_DELETE,log_message,daemon_threads,block_on_close,ConnectionCls,pool_classes_by_scheme,trust_env,lifespan_context,handle_starttag,handle_endtag,handle_data"

check: lint typecheck deadcode test
