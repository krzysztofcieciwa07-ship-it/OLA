#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
RUNTIME="$ROOT/scenarios/certificate-apocalypse/runtime"
python3 "$ROOT/scripts/chaos/assertions.py" --runtime "$RUNTIME"
