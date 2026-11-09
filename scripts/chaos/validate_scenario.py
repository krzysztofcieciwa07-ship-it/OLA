#!/usr/bin/env python3
"""Validate a scenario document against the versioned JSON Schema."""
import argparse
import json
from pathlib import Path
from jsonschema import Draft202012Validator


def validate_document(scenario_path, schema_path):
    scenario = json.loads(Path(scenario_path).read_text(encoding="utf-8"))
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(scenario), key=lambda item: list(item.absolute_path))
    if errors:
        return False, ["/".join(str(part) for part in error.absolute_path) + ": " + error.message for error in errors]
    weights = scenario["scoring"]["weights"]
    if abs(sum(weights.values()) - 1.0) > 1e-9:
        return False, ["scoring.weights must sum to exactly 1.0"]
    thresholds = scenario["scoring"]["thresholds"]
    if not (thresholds["pass"] < thresholds["merit"] < thresholds["elite"]):
        return False, ["score thresholds must be strictly increasing"]
    window = scenario["anti_llm"]["randomized_fault_window"]
    if window["min_seconds"] >= window["max_seconds"]:
        return False, ["randomized_fault_window.min_seconds must be below max_seconds"]
    return True, []


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", type=Path, default=Path("scenarios/certificate-apocalypse/scenario.json"))
    parser.add_argument("--schema", type=Path, default=Path("schemas/chaos-scenario-v0.schema.json"))
    args = parser.parse_args()
    valid, errors = validate_document(args.scenario, args.schema)
    if not valid:
        for error in errors:
            print("SCENARIO_INVALID:", error)
        raise SystemExit(1)
    print("SCENARIO_SCHEMA=VALID")


if __name__ == "__main__":
    main()
