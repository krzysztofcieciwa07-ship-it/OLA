# PYTHON_BASE_IMAGE must be supplied as an immutable image reference:
# python:3.13-slim@sha256:<verified-digest>
ARG PYTHON_BASE_IMAGE
FROM ${PYTHON_BASE_IMAGE}

ARG PYTHON_BASE_IMAGE
RUN case "${PYTHON_BASE_IMAGE}" in *@sha256:*) ;; *) echo "PYTHON_BASE_IMAGE must be digest-pinned" >&2; exit 1 ;; esac
LABEL org.opencontainers.image.base.name=${PYTHON_BASE_IMAGE}

ARG OLA_SOURCE_COMMIT
RUN OLA_SOURCE_COMMIT="${OLA_SOURCE_COMMIT}" python -c 'import os,re; assert re.fullmatch(r"[a-f0-9]{40}", os.environ["OLA_SOURCE_COMMIT"])'
LABEL org.opencontainers.image.revision=${OLA_SOURCE_COMMIT}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN python -m pip install --no-cache-dir --disable-pip-version-check pydantic==2.14.3 cryptography==45.0.7 rfc8785==0.1.4 \
    && python -m pip check \
    && groupadd --gid 65532 ola-worker \
    && useradd --uid 65532 --gid 65532 --no-create-home --shell /usr/sbin/nologin ola-worker

COPY --chown=root:root app/agent_catalog.py app/canonical.py app/agent_protocol.py app/agent_worker.py /app/app/
COPY --chown=root:root app/provenance /app/app/provenance/

RUN chmod -R a-w /app

USER 65532:65532

ENTRYPOINT ["python", "-m", "app.agent_worker"]
