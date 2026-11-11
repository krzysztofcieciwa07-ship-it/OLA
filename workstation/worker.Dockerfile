# Immutable Python 3.13.14 linux/amd64 base manifest digest from Docker Official Image.
FROM --platform=linux/amd64 python:3.13-slim@sha256:69e18bd8d831d88e0ef70239dc7771ab7c28bc296ae78ac75cde71e60aa4434f

ARG OLA_SOURCE_COMMIT
ARG OLA_WORKER_BASE_DIGEST=sha256:69e18bd8d831d88e0ef70239dc7771ab7c28bc296ae78ac75cde71e60aa4434f

LABEL org.opencontainers.image.title="OLA isolated specialist worker" \
      org.opencontainers.image.revision="${OLA_SOURCE_COMMIT}" \
      org.opencontainers.image.base.digest="${OLA_WORKER_BASE_DIGEST}" \
      org.opencontainers.image.description="One-shot, no-network, no-secret OLA capability worker"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONNOUSERSITE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN test -n "${OLA_SOURCE_COMMIT}" \
    && echo "${OLA_SOURCE_COMMIT}" | grep -Eq '^[0-9a-f]{40}$'

COPY --chown=0:0 app/__init__.py /app/app/__init__.py
COPY --chown=0:0 app/agent_catalog.py /app/app/agent_catalog.py
COPY --chown=0:0 app/agent_protocol.py /app/app/agent_protocol.py
COPY --chown=0:0 app/agent_capabilities.py /app/app/agent_capabilities.py
COPY --chown=0:0 app/agent_worker.py /app/app/agent_worker.py

RUN chmod -R a-w /app

USER 65532:65532

ENTRYPOINT ["python", "-m", "app.agent_worker"]
