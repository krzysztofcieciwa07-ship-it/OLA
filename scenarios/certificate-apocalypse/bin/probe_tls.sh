#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
RUNTIME="$ROOT/scenarios/certificate-apocalypse/runtime"
ENV_FILE="$RUNTIME/scenario.env"
[[ -f "$ENV_FILE" ]] || { echo "run make up first" >&2; exit 2; }
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a
python3 "$ROOT/scripts/chaos/probe_tls.py" "$@"
