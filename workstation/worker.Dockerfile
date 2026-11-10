# PYTHON_BASE_IMAGE must be supplied as an immutable image reference:
# python:3.13-slim@sha256:<verified-digest>
ARG PYTHON_BASE_IMAGE
FROM ${PYTHON_BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN python -m pip install --no-cache-dir --disable-pip-version-check pydantic==2.14.3 \
    && python -m pip check \
    && groupadd --gid 65532 ola-worker \
    && useradd --uid 65532 --gid 65532 --no-create-home --shell /usr/sbin/nologin ola-worker

COPY --chown=root:root app/agent_catalog.py app/agent_protocol.py app/agent_worker.py /app/app/

RUN chmod -R a-w /app

USER 65532:65532

ENTRYPOINT ["python", "-m", "app.agent_worker"]
