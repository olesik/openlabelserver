# Build context: repository root (..)
ARG BUILD_TARGET=stub

FROM python:3.12-slim-bookworm AS base

LABEL org.opencontainers.image.title="OpenLabelServer Renderer"
LABEL org.opencontainers.image.description="Deterministic RenderSpec rendering engine"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OLS_SERVICE=renderer \
    OLS_PORT=8001

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        ghostscript \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir --upgrade pip

COPY docker/renderer/requirements.stub.txt /tmp/requirements.stub.txt
COPY scripts/entrypoints/renderer.sh /entrypoint.sh
COPY scripts/stubs/stub_http.py /app/scripts/stubs/stub_http.py

RUN chmod +x /entrypoint.sh \
    && pip install --no-cache-dir -r /tmp/requirements.stub.txt

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${OLS_PORT}/health" || exit 1

FROM base AS stub
ENTRYPOINT ["/entrypoint.sh"]

FROM base AS app
COPY renderer/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY renderer/ /app/renderer/
ENV OLS_MODE=app
ENTRYPOINT ["/entrypoint.sh"]

FROM ${BUILD_TARGET} AS final
