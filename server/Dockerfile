FROM python:3.12-slim

# 固定 uv 版本（与开发机一致）：latest 随上游发版漂移，破坏构建可复现性
COPY --from=ghcr.io/astral-sh/uv:0.8.4 /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

# 非 root 运行：浏览器装到共享路径（/root 对 appuser 不可读）；
# /data 预建并授权（named volume 首挂载继承镜像内目录属主）
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN groupadd -r appuser && useradd -r -g appuser -d /home/appuser appuser \
    && mkdir -p /home/appuser && chown appuser:appuser /home/appuser \
    && uv run playwright install chromium --with-deps \
    && chown -R appuser:appuser /ms-playwright /app \
    && mkdir -p /data/artifacts && chown -R appuser:appuser /data

ENV HOST=0.0.0.0 PORT=8710
EXPOSE 8710
USER appuser

CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn app.main:app --host $HOST --port $PORT"]
