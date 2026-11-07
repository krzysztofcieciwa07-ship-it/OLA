FROM golang:1.27.3-bookworm AS gh-builder

ARG GH_CLI_COMMIT=63837fb778d6a39f02be0ce76ff89f2bc8d74bdc
ARG GO_NET_VERSION=v0.62.0

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --filter=blob:none https://github.com/cli/cli.git /src \
    && git -C /src checkout --detach "$GH_CLI_COMMIT" \
    && test "$(git -C /src rev-parse HEAD)" = "$GH_CLI_COMMIT" \
    && cd /src \
    && go mod edit -require="golang.org/x/net@$GO_NET_VERSION" \
    && go mod tidy \
    && module_version="$(go list -m -f '{{.Version}}' golang.org/x/net)" \
    && printf 'SELECTED_GOLANG_X_NET=%s\n' "$module_version" \
    && test "$module_version" = "$GO_NET_VERSION" \
    && mkdir -p /out \
    && go run script/build.go bin/gh GH_VERSION=v2.103.3 \
    && cp bin/gh /out/gh \
    && go version -m /out/gh

# Build dependencies in Chainguard's Python 3.13 development image. The
# final image uses the matching minimal Python 3.13 runtime on Wolfi.
FROM cgr.dev/chainguard/python:3.13-dev AS python-deps

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /tmp/ola-build

ARG OLA_SOURCE_COMMIT=UNKNOWN

COPY requirements.txt ./

RUN python -m venv --without-pip /tmp/venv \
    && pip --python /tmp/venv/bin/python install --no-cache-dir --force-reinstall -r requirements.txt \
    && pip --python /tmp/venv/bin/python check \
    && /tmp/venv/bin/python -c "import msgpack, setuptools, urllib3, wheel; print('DEPENDENCY_VERSIONS', msgpack.__version__, setuptools.__version__, urllib3.__version__, wheel.__version__)" \
    && mkdir -p /tmp/ola-data \
    && OLA_SOURCE_COMMIT="$OLA_SOURCE_COMMIT" python -c 'import json,os,pathlib; pathlib.Path("/tmp/ola-build-info.json").write_text(json.dumps({"schema":"ola-build-info/v1","source_commit":os.environ["OLA_SOURCE_COMMIT"]},sort_keys=True),encoding="utf-8")'

FROM cgr.dev/chainguard/python:3.13 AS runtime

ARG OLA_SOURCE_COMMIT=UNKNOWN
LABEL org.opencontainers.image.revision=${OLA_SOURCE_COMMIT}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OLA_EG_DB_PATH=/data/ola.db \
    OLA_BUILD_INFO_PATH=/app/ola-build-info.json \
    PATH=/opt/venv/bin:$PATH

WORKDIR /app

COPY --from=gh-builder /out/gh /usr/bin/gh
COPY --from=python-deps --chown=0:0 /tmp/venv /opt/venv
COPY --from=python-deps --chown=0:0 /tmp/ola-build-info.json /app/ola-build-info.json
COPY --from=python-deps --chown=65532:65532 /tmp/ola-data /data

COPY --chown=0:0 app ./app
COPY --chown=0:0 scripts ./scripts
COPY --chown=0:0 tests ./tests
COPY --chown=0:0 web ./web

# Fail the build if the copied GitHub CLI cannot execute in the minimal runtime.
RUN ["/usr/bin/gh", "attestation", "verify", "--help"]

USER 65532:65532
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).read()"]

CMD ["-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
