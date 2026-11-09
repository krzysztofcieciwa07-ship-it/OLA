import importlib.util
import json
from pathlib import Path

import pytest

try:
    from jsonschema import Draft202012Validator
except ImportError:  # Installed by the dedicated chaos workflow, not by OLA runtime CI.
    Draft202012Validator = None

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schemas/chaos-scenario-v0.schema.json").read_text())
SCENARIO = json.loads((ROOT / "scenarios/certificate-apocalypse/scenario.json").read_text())
FAULT_CATALOG = json.loads((ROOT / "schemas/chaos-fault-catalog-v0.json").read_text())
SCORE_PATH = ROOT / "scripts/chaos/score.py"
_spec = importlib.util.spec_from_file_location("ola_chaos_score", SCORE_PATH)
_score_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_score_module)
ASSERTIONS_PATH = ROOT / "scripts/chaos/assertions.py"
_assert_spec = importlib.util.spec_from_file_location("ola_chaos_assertions", ASSERTIONS_PATH)
_assert_module = importlib.util.module_from_spec(_assert_spec)
_assert_spec.loader.exec_module(_assert_module)


def require_jsonschema():
    if Draft202012Validator is None:
        pytest.skip("jsonschema is installed and exercised by the dedicated chaos workflow")


def test_certificate_apocalypse_matches_v0_schema():
    require_jsonschema()
    Draft202012Validator.check_schema(SCHEMA)
    errors = list(Draft202012Validator(SCHEMA).iter_errors(SCENARIO))
    assert errors == []


def test_fault_catalog_marks_only_tls_expiry_as_implemented():
    statuses = {item["id"]: item["status"] for item in FAULT_CATALOG["faults"]}
    assert statuses["tls_cert_expired"] == "implemented"
    assert all(status == "reserved" for key, status in statuses.items() if key != "tls_cert_expired")


def test_public_target_is_rejected_by_schema():
    require_jsonschema()
    invalid = json.loads(json.dumps(SCENARIO))
    invalid["target"]["base_url"] = "https://example.com"
    errors = list(Draft202012Validator(SCHEMA).iter_errors(invalid))
    assert any(list(error.absolute_path) == ["target", "base_url"] for error in errors)


def test_scoring_weights_are_normalized_and_thresholds_increase():
    weights = SCENARIO["scoring"]["weights"]
    assert sum(weights.values()) == pytest.approx(1.0)
    thresholds = SCENARIO["scoring"]["thresholds"]
    assert thresholds["pass"] < thresholds["merit"] < thresholds["elite"]


def test_unknown_fault_is_rejected_by_schema():
    require_jsonschema()
    invalid = json.loads(json.dumps(SCENARIO))
    invalid["fault"]["id"] = "pretend_certificate_was_fixed"
    errors = list(Draft202012Validator(SCHEMA).iter_errors(invalid))
    assert any(list(error.absolute_path) == ["fault", "id"] for error in errors)


def test_missing_stability_policy_is_rejected():
    require_jsonschema()
    invalid = json.loads(json.dumps(SCENARIO))
    del invalid["anti_llm"]["min_stable_seconds"]
    errors = list(Draft202012Validator(SCHEMA).iter_errors(invalid))
    assert any(list(error.absolute_path) == ["anti_llm"] for error in errors)


def test_scoring_uses_declared_slo_and_keeps_raw_components():
    metrics = {
        "baseline_availability": 0.99,
        "recovery_availability": 0.99,
        "p95_ms": 250,
        "p99_ms": 500,
        "mttr_seconds": 10,
        "restart_count": 0,
        "collateral_sentinel_failed": False
    }
    result = _score_module.calculate_score(
        metrics, SCENARIO["scoring"], True, SCENARIO["traffic"]["slo"]
    )
    assert result["status"] == "PASS"
    assert result["components"]["availability"] == pytest.approx(1.0)
    assert result["components"]["latency"] == pytest.approx(1.0)
    assert result["score"] >= SCENARIO["scoring"]["thresholds"]["merit"]


def test_unverified_assertions_cannot_become_a_pass():
    metrics = {
        "baseline_availability": 1.0,
        "recovery_availability": 1.0,
        "p95_ms": 20,
        "p99_ms": 30,
        "mttr_seconds": 1,
        "restart_count": 0,
        "collateral_sentinel_failed": False
    }
    result = _score_module.calculate_score(
        metrics, SCENARIO["scoring"], False, SCENARIO["traffic"]["slo"]
    )
    assert result["status"] == "FAIL"
    assert result["tier"] == "FAIL"


def test_slo_is_a_hard_gate_not_only_a_score_input():
    before = [{"target_ok": True}, {"target_ok": False}]
    after = [{"target_ok": True}, {"target_ok": True}]
    result = _assert_module.evaluate_slo(
        before, after, 100, 200, SCENARIO["traffic"]["slo"]
    )
    assert result["availability_ok"] is False
    assert result["latency_ok"] is True


def test_latency_slo_is_hard_gate():
    before = [{"target_ok": True} for _ in range(100)]
    after = [{"target_ok": True} for _ in range(100)]
    result = _assert_module.evaluate_slo(
        before, after, 501, 1001, SCENARIO["traffic"]["slo"]
    )
    assert result["availability_ok"] is True
    assert result["latency_ok"] is False


def test_published_docker_inspect_redacts_ephemeral_challenge():
    original = [{
        "Id": "container",
        "Config": {
            "Env": [
                "PATH=/usr/bin",
                "OLA_SCENARIO_RUN_ID=run-1",
                "OLA_SCENARIO_CHALLENGE=super-secret-challenge"
            ]
        }
    }]
    sanitized = _score_module.redact_runtime_secrets(json.loads(json.dumps(original)))
    assert "OLA_SCENARIO_CHALLENGE=super-secret-challenge" not in json.dumps(sanitized)
    assert "OLA_SCENARIO_CHALLENGE=<redacted>" in json.dumps(sanitized)
    assert original[0]["Config"]["Env"][-1] == "OLA_SCENARIO_CHALLENGE=super-secret-challenge"
