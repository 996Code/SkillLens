FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

RUN uv run playwright install chromium --with-deps

ENV HOST=0.0.0.0 PORT=8710
EXPOSE 8710

CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn app.main:app --host $HOST --port $PORT"]
