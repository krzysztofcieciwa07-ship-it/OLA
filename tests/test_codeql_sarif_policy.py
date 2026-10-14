import json

from scripts.verify_codeql_sarif import assess_report, check_paths


def sarif(rule_severity=None, result_severity=None, tags=None, include_finding=True):
    rule = {"id": "py/example", "properties": {"tags": tags or []}}
    if rule_severity is not None:
        rule["properties"]["security-severity"] = rule_severity
    finding = {"ruleId": "py/example", "message": {"text": "example"}}
    if result_severity is not None:
        finding["properties"] = {"security-severity": result_severity}
    return {
        "runs": [{
            "tool": {"driver": {"name": "CodeQL", "rules": [rule]}},
            "results": [finding] if include_finding else [],
        }]
    }


def test_high_severity_on_rule_blocks(tmp_path):
    path = tmp_path / "python.sarif"
    path.write_text(json.dumps(sarif(rule_severity="8.7")))
    result = check_paths([str(path)])
    assert result["status"] == "BLOCK"
    assert result["high_or_critical_findings"][0]["severity"] == 8.7


def test_medium_severity_on_rule_is_allowed():
    result = assess_report(sarif(rule_severity="4.0"))
    assert not result["high_or_critical_findings"]
    assert not result["unknown_security_severity"]


def test_high_severity_on_result_blocks():
    assert assess_report(sarif(result_severity="9.0"))["high_or_critical_findings"]


def test_security_tag_without_severity_blocks():
    assert assess_report(sarif(tags=["security", "external/cwe/cwe-79"]))["unknown_security_severity"]


def test_nonfinding_report_passes(tmp_path):
    path = tmp_path / "clean.sarif"
    path.write_text(json.dumps(sarif(include_finding=False)))
    assert check_paths([str(path)])["status"] == "PASS"


def test_missing_sarif_blocks():
    assert check_paths([])["status"] == "BLOCK"


def test_invalid_sarif_blocks(tmp_path):
    path = tmp_path / "broken.sarif"
    path.write_text("{bad json")
    assert check_paths([str(path)])["status"] == "BLOCK"


def test_nan_security_severity_blocks():
    assert assess_report(sarif(rule_severity="NaN", tags=["security"]))["unknown_security_severity"]
