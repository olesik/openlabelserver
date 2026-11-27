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
    && rm -rf /var/lib/apt/lists/*

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
# Every accepted body is checked against its published schema (API §5.3): RenderSpec
# for templates, StockSpec and CalibrationSpec for their resources.
COPY specs/renderspec/schema.json /app/specs/renderspec/schema.json
COPY specs/stockspec/schema.json /app/specs/stockspec/schema.json
COPY specs/calibrationspec/schema.json /app/specs/calibrationspec/schema.json
ENV OLS_MODE=app
# The stub answers /health; the application serves the versioned route only, so
# the healthcheck inherited from `base` would probe a path it does not serve.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${OLS_PORT}/v1/health" || exit 1
ENTRYPOINT ["/entrypoint.sh"]

# The final stage is chosen by the BUILD_TARGET build arg (see docker/docker-compose.yml),
# so this FROM names a build stage rather than an untagged image.
# hadolint ignore=DL3006
FROM ${BUILD_TARGET} AS final
