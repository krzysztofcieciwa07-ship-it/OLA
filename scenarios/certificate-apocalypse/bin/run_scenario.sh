#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
SCENARIO="$ROOT/scenarios/certificate-apocalypse"
RUNTIME="$SCENARIO/runtime"
REPORT_ROOT="$SCENARIO/runs"
COMPOSE_FILE="$SCENARIO/compose.yaml"

rm -rf "$RUNTIME"
mkdir -p "$RUNTIME"
python3 "$ROOT/scripts/chaos/prepare_run.py" --output "$RUNTIME" >/dev/null
set -a
# shellcheck disable=SC1090
source "$RUNTIME/scenario.env"
set +a
COMPOSE=(docker compose --project-name "$OLA_COMPOSE_PROJECT" --env-file "$RUNTIME/scenario.env" -f "$COMPOSE_FILE")
STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
PROBE_PID=""
EVENTS_PID=""
PROBE_STATUS=0
K6_STATUS=0
ASSERT_STATUS=0
SCORE_STATUS=0

cleanup() {
  set +e
  if [[ -n "$EVENTS_PID" ]]; then kill "$EVENTS_PID" >/dev/null 2>&1; fi
  "${COMPOSE[@]}" logs --no-color >"$RUNTIME/docker-compose.log" 2>&1
  IDS="$("${COMPOSE[@]}" ps -q 2>/dev/null)"
  if [[ -n "$IDS" ]]; then
    # shellcheck disable=SC2086
    docker inspect $IDS >"$RUNTIME/docker-inspect.json" 2>&1
  else
    printf '[]\n' >"$RUNTIME/docker-inspect.json"
  fi
  "${COMPOSE[@]}" down --remove-orphans >/dev/null 2>&1
}
trap cleanup EXIT

python3 "$ROOT/scripts/chaos/record_event.py" scenario_started --runtime "$RUNTIME"
"$SCENARIO/bin/gen_good_cert.sh"
"${COMPOSE[@]}" up -d --build
docker events --since "$STARTED_AT" --filter "label=com.docker.compose.project=$OLA_COMPOSE_PROJECT" --format '{{json .}}' >"$RUNTIME/docker-events.jsonl" 2>&1 &
EVENTS_PID=$!

READY=0
for _ in $(seq 1 40); do
  if python3 "$ROOT/scripts/chaos/probe_tls.py" --expect success >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 1
done
[[ "$READY" == "1" ]] || { echo "TLS target did not become ready" >&2; exit 1; }

TOTAL_SECONDS="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["load_duration_seconds"])' "$RUNTIME/run_context.json")"
FAULT_AFTER="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["fault_after_seconds"])' "$RUNTIME/run_context.json")"
FAULT_DURATION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["fault_duration_seconds"])' "$RUNTIME/run_context.json")"
VUS="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["vus"])' "$RUNTIME/run_context.json")"

python3 "$ROOT/scripts/chaos/probe_tls.py" --watch --duration "$TOTAL_SECONDS" --interval 0.5 --output "$RUNTIME/probe-samples.jsonl" >/dev/null &
PROBE_PID=$!

SSL_CERT_FILE="$OLA_CERT_DIR/ca.crt" k6 run \
  --summary-export "$RUNTIME/k6-summary.json" \
  --env "BASE_URL=https://127.0.0.1:8443/health" \
  --env "RUN_ID=$OLA_SCENARIO_RUN_ID" \
  --env "CHALLENGE=$OLA_SCENARIO_CHALLENGE" \
  --env "FAULT_AFTER_SECONDS=$FAULT_AFTER" \
  --env "FAULT_DURATION_SECONDS=$FAULT_DURATION" \
  --env "LOAD_DURATION_SECONDS=$TOTAL_SECONDS" \
  --vus "$VUS" --duration "${TOTAL_SECONDS}s" \
  "$SCENARIO/k6_load.js" >"$RUNTIME/k6.log" 2>&1 &
K6_PID=$!

sleep "$FAULT_AFTER"
"$SCENARIO/bin/gen_bad_cert.sh"
cp -L "$OLA_CERT_DIR/current/server.crt" "$RUNTIME/bad-server.crt"
python3 "$ROOT/scripts/chaos/record_event.py" fault_injected --runtime "$RUNTIME" --detail "expired leaf certificate active"
sleep "$FAULT_DURATION"
"$SCENARIO/bin/gen_good_cert.sh"
cp -L "$OLA_CERT_DIR/current/server.crt" "$RUNTIME/good-server.crt"
python3 "$ROOT/scripts/chaos/record_event.py" fault_removed --runtime "$RUNTIME" --detail "valid leaf certificate restored"

set +e
wait "$PROBE_PID"
PROBE_STATUS=$?
wait "$K6_PID"
K6_STATUS=$?
set -e
python3 "$ROOT/scripts/chaos/record_event.py" scenario_observation_finished --runtime "$RUNTIME" --detail "probe_status=$PROBE_STATUS k6_status=$K6_STATUS"

"${COMPOSE[@]}" logs --no-color >"$RUNTIME/docker-compose.log" 2>&1
IDS="$("${COMPOSE[@]}" ps -q)"
if [[ -n "$IDS" ]]; then
  # shellcheck disable=SC2086
  docker inspect $IDS >"$RUNTIME/docker-inspect.json"
else
  printf '[]\n' >"$RUNTIME/docker-inspect.json"
fi
kill "$EVENTS_PID" >/dev/null 2>&1 || true
wait "$EVENTS_PID" 2>/dev/null || true
EVENTS_PID=""

set +e
"$ROOT/scripts/chaos/assertions.sh"
ASSERT_STATUS=$?
python3 "$ROOT/scripts/chaos/score.py" --runtime "$RUNTIME" --scenario "$SCENARIO/scenario.json" --schema "$ROOT/schemas/chaos-scenario-v0.schema.json" --output "$REPORT_ROOT/$OLA_SCENARIO_RUN_ID"
SCORE_STATUS=$?
set -e

echo "RUN_ID=$OLA_SCENARIO_RUN_ID"
echo "REPORT=$REPORT_ROOT/$OLA_SCENARIO_RUN_ID"
echo "PROBE_STATUS=$PROBE_STATUS K6_STATUS=$K6_STATUS ASSERT_STATUS=$ASSERT_STATUS SCORE_STATUS=$SCORE_STATUS"
[[ "$PROBE_STATUS" == "0" && "$K6_STATUS" == "0" && "$ASSERT_STATUS" == "0" && "$SCORE_STATUS" == "0" ]]
