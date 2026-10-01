# HexWorld: one container serves the API, the WebSocket event stream and the built frontend.
#
#   docker build -t hexworld .
#   docker run -p 8080:8080 -e OPENAI_API_KEY=sk-... -v hexworld-data:/data hexworld
#
# Cloud Run sets $PORT; data (SQLite + generated PNGs) lives in $HEXWORLD_DATA_DIR (/data).

# ---- 1. frontend: Vite build -> /app/frontend/dist
FROM node:22-slim AS web
WORKDIR /app/frontend
RUN corepack enable && corepack prepare pnpm@10 --activate
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

# ---- 2. backend: Python 3.13 + uv, serving the API and the frontend build
FROM python:3.13-slim AS app
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONUNBUFFERED=1
WORKDIR /app/backend
# dependencies first (cached until pyproject/uv.lock change), then the code
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/hexworld ./hexworld
RUN uv sync --frozen --no-dev
# the API serves /app/frontend/dist at / (hexworld/api: REPO_ROOT/frontend/dist)
COPY --from=web /app/frontend/dist /app/frontend/dist
COPY services /app/services

ENV PATH=/app/.venv/bin:$PATH \
    HEXWORLD_DATA_DIR=/data \
    HEXWORLD_HOST=0.0.0.0 \
    HEXWORLD_LLM=openai \
    HEXWORLD_IMAGE=procedural \
    HEXWORLD_SUPER_MODEL=gpt-6-luna \
    HEXWORLD_TILE_MODEL=gpt-6-luna \
    HEXWORLD_ARTIST_MODEL=gpt-6-luna \
    PORT=8080

RUN useradd --create-home --uid 10001 hexworld && mkdir -p /data && chown hexworld /data
USER hexworld
VOLUME ["/data"]
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8080\")}/api/health', timeout=4)"
CMD ["sh", "-c", "exec hexworld serve --host 0.0.0.0 --port ${PORT:-8080}"]
