# Build context: repository root (..)
ARG BUILD_TARGET=stub

FROM node:22-bookworm-slim AS base

LABEL org.opencontainers.image.title="OpenLabelServer Frontend"
LABEL org.opencontainers.image.description="Vue 3 web interface for OpenLabelServer"

ENV OLS_SERVICE=frontend \
    OLS_PORT=5173

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl python3 \
    && rm -rf /var/lib/apt/lists/*

COPY scripts/entrypoints/frontend.sh /entrypoint.sh
COPY scripts/stubs/stub_http.py /app/scripts/stubs/stub_http.py

RUN chmod +x /entrypoint.sh \
    && npm install -g serve@14.2.4

EXPOSE 5173

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${OLS_PORT}/health" || exit 1

FROM base AS stub
ENTRYPOINT ["/entrypoint.sh"]

FROM base AS app
COPY frontend/package.json frontend/package-lock.json* /app/frontend/
WORKDIR /app/frontend
RUN npm ci
COPY frontend/ /app/frontend/
RUN npm run build
WORKDIR /app
ENV OLS_MODE=app
ENTRYPOINT ["/entrypoint.sh"]

FROM ${BUILD_TARGET} AS final
