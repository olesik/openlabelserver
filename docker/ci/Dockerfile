# CI tooling image — schema validation, lint helpers, and specification checks.
# Build context: repository root (..)

FROM python:3.12-slim-bookworm

LABEL org.opencontainers.image.title="OpenLabelServer CI"
LABEL org.opencontainers.image.description="Continuous integration tooling for OpenLabelServer"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /workspace

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        shellcheck \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --upgrade pip

COPY docker/ci/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

# Hadolint static binary (architecture-aware)
ARG HADOLINT_VERSION=2.12.0
RUN arch="$(dpkg --print-architecture)" \
    && case "${arch}" in \
         amd64) hadolint_arch="x86_64" ;; \
         arm64) hadolint_arch="arm64" ;; \
         *) echo "Unsupported architecture: ${arch}" >&2; exit 1 ;; \
       esac \
    && curl -fsSL \
         "https://github.com/hadolint/hadolint/releases/download/v${HADOLINT_VERSION}/hadolint-Linux-${hadolint_arch}" \
         -o /usr/local/bin/hadolint \
    && chmod +x /usr/local/bin/hadolint

COPY scripts/ /workspace/scripts/
RUN chmod +x /workspace/scripts/*.sh /workspace/scripts/entrypoints/*.sh

ENTRYPOINT ["/workspace/scripts/ci-entrypoint.sh"]
