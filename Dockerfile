FROM golang:1.27-alpine@sha256:fa3d596898d9f126af7c01d14ee7597bab3f39cccf392ef36b69fe77cd681f18 AS gh-builder

ARG GH_CLI_COMMIT=63837fb778d6a39f02be0ce76ff89f2bc8d74bdc
ARG GO_NET_VERSION=v0.62.0

RUN apk add --no-cache git ca-certificates build-base

RUN git clone --filter=blob:none https://github.com/cli/cli.git /src \
    && git -C /src checkout --detach "$GH_CLI_COMMIT" \
    && test "$(git -C /src rev-parse HEAD)" = "$GH_CLI_COMMIT" \
    && cd /src \
    && go mod edit -require="golang.org/x/net@$GO_NET_VERSION" \
    && go mod tidy \
    && module_version="$(go list -m -f '{{.Version}}' golang.org/x/net)" \
    && printf 'SELECTED_GOLANG_X_NET=%s\\n' "$module_version" \
    && test "$module_version" = "$GO_NET_VERSION" \
    && mkdir -p /out \
    && go run script/build.go bin/gh GH_VERSION=v2.103.3 \
    && cp bin/gh /out/gh \
    && go version -m /out/gh

FROM python:3.13-alpine@sha256:1e1f6334529d1fb26a2ef619d7cffb30a7c7d7cc1cc7338ebee283a58d1aeaca AS python-deps

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

RUN apk add --no-cache --virtual .build-deps build-base libffi-dev openssl-dev

COPY requirements-runtime.txt ./

RUN python -m venv /opt/venv \
    && /opt/venv/bin/python -m pip install --no-cache-dir -r requirements-runtime.txt \
    && /opt/venv/bin/python -m pip check \
    && /opt/venv/bin/python -c "import fastapi, sqlalchemy, httpx, msgpack, urllib3, psycopg, cryptography, authlib, joserfc; print('RUNTIME_DEPENDENCIES=OK')" \
    && rm -rf /opt/venv/lib/python3.13/site-packages/pip \
              /opt/venv/lib/python3.13/site-packages/pip-*.dist-info \
              /opt/venv/lib/python3.13/site-packages/setuptools \
              /opt/venv/lib/python3.13/site-packages/setuptools-*.dist-info \
              /opt/venv/lib/python3.13/site-packages/wheel \
              /opt/venv/lib/python3.13/site-packages/wheel-*.dist-info \
              /opt/venv/lib/python3.13/site-packages/pkg_resources \
              /opt/venv/bin/pip*

# Copy only the interpreter and standard library needed at runtime.
# The base image's global site-packages and ensurepip are deliberately excluded;
# the final stage does not inherit any Python-image layers.
RUN python - <<'PY'
from pathlib import Path
import shutil

source = Path("/usr/local")
runtime = Path("/opt/python-runtime")
(runtime / "bin").mkdir(parents=True)
(runtime / "lib").mkdir(parents=True)

shutil.copy2(source / "bin/python3.13", runtime / "bin/python3.13")
shared_python = source / "lib/libpython3.13.so.1.0"
if not shared_python.is_file():
    raise SystemExit(f"missing shared Python runtime: {shared_python}")
shutil.copy2(shared_python, runtime / "lib/libpython3.13.so.1.0")

shutil.copytree(
    source / "lib/python3.13",
    runtime / "lib/python3.13",
    ignore=shutil.ignore_patterns(
        "site-packages",
        "ensurepip",
        "test",
        "tests",
        "idlelib",
        "tkinter",
        "turtledemo",
        "__pycache__",
    ),
)
PY

# Start from a clean Alpine image rather than deleting files from a Python
# base-image layer. No inherited pip/ensurepip bytes remain in the final image.
FROM alpine:3.24@sha256:be2656061b536c1883c4034790e21d0a09c5aaaf51968b89368a3c0371ea2c9a AS runtime

ARG OLA_SOURCE_COMMIT=UNKNOWN
LABEL org.opencontainers.image.revision=${OLA_SOURCE_COMMIT}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OLA_EG_DB_PATH=/data/ola.db \
    OLA_BUILD_INFO_PATH=/app/ola-build-info.json \
    PATH=/opt/venv/bin:/usr/local/bin:/usr/bin:/bin \
    LD_LIBRARY_PATH=/usr/local/lib

WORKDIR /app

RUN apk add --no-cache \
      ca-certificates \
      libgcc \
      libffi \
      openssl \
      sqlite-libs \
      zlib \
      bzip2-libs \
      xz-libs \
      libstdc++ \
      readline

COPY --from=gh-builder /out/gh /usr/local/bin/gh
COPY --from=python-deps /opt/python-runtime/bin/python3.13 /usr/local/bin/python3.13
COPY --from=python-deps /opt/python-runtime/lib/ /usr/local/lib/
COPY --from=python-deps /opt/venv /opt/venv

COPY app ./app
COPY scripts ./scripts
COPY web ./web

RUN ln -sf python3.13 /usr/local/bin/python3 \
    && ln -sf python3.13 /usr/local/bin/python \
    && ldd /usr/local/bin/python3.13 > /tmp/python-ldd.txt \
    && if grep -q "not found" /tmp/python-ldd.txt; then cat /tmp/python-ldd.txt; exit 1; fi \
    && mkdir -p /data \
    && adduser -D --uid 10001 ola \
    && OLA_SOURCE_COMMIT="$OLA_SOURCE_COMMIT" python -c 'import json,os,pathlib; pathlib.Path("/app/ola-build-info.json").write_text(json.dumps({"schema":"ola-build-info/v1","source_commit":os.environ["OLA_SOURCE_COMMIT"]},sort_keys=True),encoding="utf-8")' \
    && chown -R root:root /app \
    && chmod -R a-w /app \
    && chown -R ola:ola /data \
    && gh attestation verify --help >/dev/null \
    && python - <<'PY'
from importlib import metadata, util
from pathlib import Path

import authlib
import bz2
import cryptography
import ctypes
import fastapi
import httpx
import joserfc
import lzma
import msgpack
import psycopg
import sqlalchemy
import sqlite3
import ssl
import urllib3
import zlib

for forbidden in ("pip", "pytest", "setuptools", "wheel"):
    if util.find_spec(forbidden) is not None:
        raise SystemExit(f"build/test module leaked into runtime: {forbidden}")
    try:
        metadata.version(forbidden)
    except metadata.PackageNotFoundError:
        pass
    else:
        raise SystemExit(f"build/test distribution leaked into runtime: {forbidden}")

for forbidden_path in (
    Path("/usr/local/lib/python3.13/site-packages"),
    Path("/usr/local/lib/python3.13/ensurepip"),
    Path("/opt/venv/lib/python3.13/site-packages/pip"),
    Path("/opt/venv/lib/python3.13/site-packages/pytest"),
    Path("/app/tests"),
):
    if forbidden_path.exists():
        raise SystemExit(f"build/test payload leaked into runtime: {forbidden_path}")

print("RUNTIME_IMPORTS=OK")
print("RUNTIME_BUILD_TOOLS=ABSENT")
print("RUNTIME_TESTS=ABSENT")
PY

USER ola
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).read()"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
