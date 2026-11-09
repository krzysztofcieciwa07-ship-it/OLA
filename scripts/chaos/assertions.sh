#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
RUNTIME="$ROOT/scenarios/certificate-apocalypse/runtime"
SCENARIO="$ROOT/scenarios/certificate-apocalypse/scenario.json"
python3 "$ROOT/scripts/chaos/assertions.py" --runtime "$RUNTIME" --scenario "$SCENARIO"
