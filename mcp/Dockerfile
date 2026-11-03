FROM node:26.13.0-bookworm-slim AS ui
WORKDIR /ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY ui/ ./
RUN npm run build

FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /usr/local/bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    OTEL_TRACES_EXPORTER=console \
    OTEL_LOGS_EXPORTER=console \
    OTEL_METRICS_EXPORTER=console \
    OTEL_AWS_APPLICATION_SIGNALS_ENABLED=false \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src/ ./src/
COPY --from=ui /src/exploration_mcp/ui/dashboard.html ./src/exploration_mcp/ui/dashboard.html
RUN uv sync --locked --no-dev --no-editable \
    && .venv/bin/explore-mcp prepare-sample

USER 10001:10001
EXPOSE 8000
CMD ["opentelemetry-instrument", "uvicorn", "exploration_mcp.server:create_agentcore_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
