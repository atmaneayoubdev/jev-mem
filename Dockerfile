# syntax=docker/dockerfile:1.7
# JevMem: API server + built demo UI in one image.
#
#   docker build -t jevmem .
#   docker build -t jevmem --build-arg EXTRAS="--extra embeddings" .   # adds the dense baseline (large)

# --- 1) frontend build ---------------------------------------------------------------------
FROM node:22-alpine AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY frontend/ ./
RUN npm run build

# --- 2) python runtime -----------------------------------------------------------------------
FROM python:3.12-slim AS runtime
ARG EXTRAS=""
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    DATA_DIR=/app/data \
    DATABASE_URL=sqlite:////app/data/jevmem.db
COPY --from=ghcr.io/astral-sh/uv:0.10 /uv /usr/local/bin/uv
WORKDIR /app

COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --frozen --no-dev --no-install-project ${EXTRAS}
COPY src/ src/
RUN uv sync --frozen --no-dev ${EXTRAS}

COPY benchmarks/params/ benchmarks/params/
COPY --from=frontend /frontend/dist/ frontend/dist/

RUN useradd --create-home --uid 10001 jevmem && mkdir -p /app/data && chown -R jevmem /app/data
USER jevmem
VOLUME ["/app/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4).status == 200 else 1)"
CMD ["uv", "run", "--no-sync", "jevmem", "serve", "--host", "0.0.0.0", "--port", "8000"]
