#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
RUNTIME="$ROOT/scenarios/certificate-apocalypse/runtime"
python3 "$ROOT/scripts/chaos/generate_tls_material.py" bad --runtime "$RUNTIME"
python3 "$ROOT/scripts/chaos/record_event.py" bad_certificate_installed --runtime "$RUNTIME"
