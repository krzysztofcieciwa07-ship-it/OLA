ROOT := $(shell git rev-parse --show-toplevel 2>/dev/null || pwd)
SCENARIO := $(ROOT)/scenarios/certificate-apocalypse
RUNTIME := $(SCENARIO)/runtime
ENV_FILE := $(RUNTIME)/scenario.env
COMPOSE_FILE := $(SCENARIO)/compose.yaml

.PHONY: up break fix probe assert score scenario down validate-chaos

validate-chaos:
	python3 scripts/chaos/validate_scenario.py

up:
	@if [ ! -f "$(ENV_FILE)" ]; then python3 scripts/chaos/prepare_run.py --output "$(RUNTIME)"; fi
	@if [ ! -f "$(RUNTIME)/certs/ca.crt" ]; then bash "$(SCENARIO)/bin/gen_good_cert.sh"; fi
	@set -a; . "$(ENV_FILE)"; set +a; docker compose --project-name "$$OLA_COMPOSE_PROJECT" --env-file "$(ENV_FILE)" -f "$(COMPOSE_FILE)" up -d --build

break:
	bash "$(SCENARIO)/bin/gen_bad_cert.sh"

fix:
	bash "$(SCENARIO)/bin/gen_good_cert.sh"

probe:
	bash "$(SCENARIO)/bin/probe_tls.sh" --expect any

assert:
	bash scripts/chaos/assertions.sh

score:
	@set -a; . "$(ENV_FILE)"; set +a; python3 scripts/chaos/score.py --runtime "$(RUNTIME)" --scenario "$(SCENARIO)/scenario.json" --schema schemas/chaos-scenario-v0.schema.json --output "$(SCENARIO)/runs/$$OLA_SCENARIO_RUN_ID"

scenario: validate-chaos
	bash "$(SCENARIO)/bin/run_scenario.sh"

down:
	@if [ -f "$(ENV_FILE)" ]; then set -a; . "$(ENV_FILE)"; set +a; docker compose --project-name "$$OLA_COMPOSE_PROJECT" --env-file "$(ENV_FILE)" -f "$(COMPOSE_FILE)" down --remove-orphans; else echo "No active scenario context"; fi
