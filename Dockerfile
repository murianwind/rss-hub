# syntax=docker/dockerfile:1

# ---- 1단계: 패키지 설치 ----
FROM python:3.14-slim AS build
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir --prefix=/install .

# ---- 2단계: 실행 이미지 ----
FROM python:3.14-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# 일반 사용자로 실행한다. /data는 이름 있는 볼륨이 처음 연결될 때 이 소유권을 그대로 물려받는다.
RUN useradd --system --uid 10001 --no-create-home app \
 && mkdir /data \
 && chown app:app /data

COPY --from=build /install /usr/local

USER app
VOLUME ["/data"]
EXPOSE 8000

# /healthz는 데이터 디렉터리에 쓸 수 있는지까지 확인한다(503이면 예외가 나서 비정상으로 표시된다)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"]

CMD ["uvicorn", "rss_hub.main:create_service_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
