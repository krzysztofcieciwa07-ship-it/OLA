FROM golang:1.27-alpine AS gh-builder

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

FROM python:3.13-alpine AS python-deps

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

RUN apk add --no-cache --virtual .build-deps build-base libffi-dev openssl-dev

COPY requirements.txt ./

RUN python -m venv /opt/venv \
    && /opt/venv/bin/python -m pip install --no-cache-dir --force-reinstall -r requirements.txt \
    && /opt/venv/bin/python -m pip check \
    && /opt/venv/bin/python -c "import msgpack, setuptools, urllib3, wheel; print('DEPENDENCY_VERSIONS', msgpack.__version__, setuptools.__version__, urllib3.__version__, wheel.__version__)" \
    && rm -rf /opt/venv/lib/python3.13/site-packages/pip \
              /opt/venv/lib/python3.13/site-packages/pip-*.dist-info \
              /opt/venv/lib/python3.13/site-packages/setuptools \
              /opt/venv/lib/python3.13/site-packages/setuptools-*.dist-info \
              /opt/venv/lib/python3.13/site-packages/wheel \
              /opt/venv/lib/python3.13/site-packages/wheel-*.dist-info \
              /opt/venv/lib/python3.13/site-packages/pkg_resources

FROM python:3.13-alpine AS runtime

ARG OLA_SOURCE_COMMIT=UNKNOWN
LABEL org.opencontainers.image.revision=${OLA_SOURCE_COMMIT}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OLA_EG_DB_PATH=/data/ola.db \
    OLA_BUILD_INFO_PATH=/app/ola-build-info.json \
    PATH=/opt/venv/bin:$PATH

WORKDIR /app

COPY --from=gh-builder /out/gh /usr/local/bin/gh
COPY --from=python-deps /opt/venv /opt/venv

COPY app ./app
COPY scripts ./scripts
COPY tests ./tests
COPY web ./web

RUN apk add --no-cache ca-certificates libgcc libffi openssl \
    && OLA_SOURCE_COMMIT="$OLA_SOURCE_COMMIT" python -c 'import json,os,pathlib; pathlib.Path("/app/ola-build-info.json").write_text(json.dumps({"schema":"ola-build-info/v1","source_commit":os.environ["OLA_SOURCE_COMMIT"]},sort_keys=True),encoding="utf-8")' \
    && adduser -D --uid 10001 ola \
    && mkdir -p /data \
    && chown -R root:root /app \
    && chmod -R a-w /app \
    && chown -R ola:ola /data \
    && gh attestation verify --help >/dev/null

USER ola
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).read()"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
