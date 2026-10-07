# Build context: repository root (..)
ARG BUILD_TARGET=stub

FROM debian:bookworm-slim AS base

LABEL org.opencontainers.image.title="OpenLabelServer Printing"
LABEL org.opencontainers.image.description="CUPS and IPP print integration service"

ENV OLS_SERVICE=printing \
    OLS_PORT=8002 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        python3 \
        python3-pip \
        python3-venv \
        cups-client \
        ipp-usb \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip

ENV PATH="/opt/venv/bin:${PATH}"

COPY docker/printing/requirements.stub.txt /tmp/requirements.stub.txt
COPY scripts/entrypoints/printing.sh /entrypoint.sh
COPY scripts/stubs/stub_http.py /app/scripts/stubs/stub_http.py

RUN chmod +x /entrypoint.sh \
    && pip install --no-cache-dir -r /tmp/requirements.stub.txt

EXPOSE 8002

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${OLS_PORT}/health" || exit 1

FROM base AS stub
ENTRYPOINT ["/entrypoint.sh"]

FROM base AS app
COPY printing/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY printing/ /app/printing/
ENV OLS_MODE=app
ENTRYPOINT ["/entrypoint.sh"]

FROM ${BUILD_TARGET} AS final
