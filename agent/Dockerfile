FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /usr/local/bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src/ ./src/

RUN uv sync --locked --no-dev --no-editable

USER 10001:10001
EXPOSE 8080

CMD ["uvicorn", "exploration_agent.agentcore_server:create_agentcore_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
