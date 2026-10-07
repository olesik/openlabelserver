# Build context: repository root (..)
# Default target `stub` runs until application code is present.
# Build `app` once backend/ exists: docker build --target app -f docker/backend/Dockerfile .

ARG BUILD_TARGET=stub

FROM python:3.12-slim-bookworm AS base

LABEL org.opencontainers.image.title="OpenLabelServer Backend"
LABEL org.opencontainers.image.description="FastAPI REST API service for OpenLabelServer"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OLS_SERVICE=backend \
    OLS_PORT=8000

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir --upgrade pip

COPY docker/backend/requirements.stub.txt /tmp/requirements.stub.txt
COPY scripts/entrypoints/backend.sh /entrypoint.sh
COPY scripts/stubs/stub_http.py /app/scripts/stubs/stub_http.py

RUN chmod +x /entrypoint.sh \
    && pip install --no-cache-dir -r /tmp/requirements.stub.txt

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${OLS_PORT}/health" || exit 1

FROM base AS stub
ENTRYPOINT ["/entrypoint.sh"]

FROM base AS app
COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY backend/ /app/backend/
ENV OLS_MODE=app
ENTRYPOINT ["/entrypoint.sh"]

FROM ${BUILD_TARGET} AS final
