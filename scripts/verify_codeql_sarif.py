"""Fail-closed CodeQL SARIF policy for security findings >= 7.0.

CodeQL attaches security-severity primarily to rule metadata, not result metadata.
"""
from __future__ import annotations

import glob
import json
import math
import sys
from pathlib import Path

HIGH_THRESHOLD = 7.0


def _rules(run: dict) -> dict:
    tool = run.get("tool", {})
    rules = {}
    for component in [tool.get("driver", {}), *tool.get("extensions", [])]:
        for rule in component.get("rules", []):
            if isinstance(rule, dict) and isinstance(rule.get("id"), str):
                rules[rule["id"]] = rule
    return rules


def _score(raw):
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and 0 <= value <= 10 else None


def _security_tagged(rule: dict, result: dict) -> bool:
    for item in (rule, result):
        tags = item.get("properties", {}).get("tags", [])
        if isinstance(tags, list) and any(
            isinstance(t, str)
            and (t.lower() == "security" or t.lower().startswith("external/cwe/"))
            for t in tags
        ):
            return True
    return False


def assess_report(report: dict) -> dict:
    if not isinstance(report, dict) or not isinstance(report.get("runs"), list) or not report["runs"]:
        raise ValueError("SARIF runs list missing or empty")
    high, unknown = [], []
    examined = 0
    for run in report["runs"]:
        if not isinstance(run, dict) or not isinstance(run.get("results", []), list):
            raise ValueError("invalid SARIF run or results")
        driver = run.get("tool", {}).get("driver", {})
        if not isinstance(driver, dict) or not driver.get("name"):
            raise ValueError("SARIF tool driver missing")
        rules = _rules(run)
        for result in run.get("results", []):
            if not isinstance(result, dict):
                raise ValueError("invalid SARIF finding")
            examined += 1
            rule_id = result.get("ruleId")
            rule = rules.get(rule_id, {})
            if not rule and isinstance(result.get("ruleIndex"), int):
                idx = result["ruleIndex"]
                entries = driver.get("rules", [])
                if 0 <= idx < len(entries):
                    rule = entries[idx]
            rp = result.get("properties", {})
            metadata = rule.get("properties", {})
            raw = rp.get("security-severity", metadata.get("security-severity"))
            score = _score(raw)
            finding = {
                "tool": driver["name"],
                "rule": rule_id,
                "message": result.get("message", {}).get("text", ""),
            }
            if score is not None and score >= HIGH_THRESHOLD:
                high.append({**finding, "severity": score})
            elif score is None and (raw is not None or _security_tagged(rule, result)):
                unknown.append({**finding, "reason": "security-severity missing or invalid"})
    return {
        "high_or_critical_findings": high,
        "unknown_security_severity": unknown,
        "examined_results": examined,
    }


def check_paths(paths: list[str]) -> dict:
    if not paths:
        return {"status": "BLOCK", "reason": "no SARIF files found", "codeql_sarif_files": []}
    result = {
        "status": "PASS",
        "codeql_sarif_files": paths,
        "high_or_critical_findings": [],
        "unknown_security_severity": [],
        "examined_results": 0,
    }
    for path in paths:
        try:
            contents = json.loads(Path(path).read_text(encoding="utf-8"))
            scan = assess_report(contents)
            for key, value in scan.items():
                if isinstance(value, list):
                    result[key].extend(value)
                else:
                    result[key] += value
        except (OSError, ValueError, TypeError, KeyError) as exc:
            return {**result, "status": "BLOCK", "reason": f"invalid SARIF: {path}: {exc}"}
    if result["high_or_critical_findings"] or result["unknown_security_severity"]:
        result["status"] = "BLOCK"
    return result


def main() -> int:
    result = check_paths(sorted(glob.glob("codeql-results/*.sarif")))
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
