import ast
import base64
import json
from pathlib import Path

from app import igor_evidence_verifier as independent


FIXTURES = Path(__file__).parent / "fixtures"


def _legacy_fixture():
    return json.loads((FIXTURES / "evidence_legacy_v1_v2_v3.json").read_text(encoding="utf-8"))


def _v4_fixture():
    return json.loads((FIXTURES / "evidence_v4_independent.json").read_text(encoding="utf-8"))


def _environment(legacy, v4):
    return {
        "OLA_API_KEY_PEPPER": legacy["provenance"]["v3_test_pepper"],
        "OLA_EVIDENCE_V4_KEYRING_JSON": json.dumps({
            v4["provenance"]["test_key_id"]: v4["provenance"]["test_key_base64"]
        }),
        "OLA_EVIDENCE_V4_ACTIVE_KEY_ID": v4["provenance"]["test_key_id"],
    }


def test_igor_independently_verifies_provenance_labelled_v1_v2_v3_v4_chain():
    legacy = _legacy_fixture()
    v4 = _v4_fixture()
    records = legacy["records"] + [v4["record"]]
    ok, reason = independent.verify_chain(records, _environment(legacy, v4))
    assert ok, reason
    assert independent.trusted_record(legacy["records"][0]) is False
    assert independent.trusted_record(legacy["records"][1]) is True
    assert independent.trusted_record(legacy["records"][2]) is True
    assert independent.trusted_record(v4["record"]) is True


def test_igor_fails_closed_when_v4_keyring_is_missing():
    legacy = _legacy_fixture()
    v4 = _v4_fixture()
    env = {"OLA_API_KEY_PEPPER": legacy["provenance"]["v3_test_pepper"]}
    ok, _ = independent.verify_chain(legacy["records"] + [v4["record"]], env)
    assert not ok


def test_igor_fails_closed_on_wrong_v3_pepper():
    legacy = _legacy_fixture()
    v4 = _v4_fixture()
    env = _environment(legacy, v4)
    env["OLA_API_KEY_PEPPER"] = "wrong-v3-test-pepper-material-0123456789"
    ok, _ = independent.verify_chain(legacy["records"] + [v4["record"]], env)
    assert not ok


def test_igor_fails_closed_on_v4_key_substitution():
    legacy = _legacy_fixture()
    v4 = _v4_fixture()
    row = dict(v4["record"])
    payload = json.loads(row["payload_json"])
    payload["__ola_evidence_v4__"]["key_id"] = "unknown-key"
    row["payload_json"] = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    ok, _ = independent.verify_chain(legacy["records"] + [row], _environment(legacy, v4))
    assert not ok


def test_igor_rejects_cross_tenant_legacy_record():
    legacy = _legacy_fixture()
    v4 = _v4_fixture()
    records = [dict(row) for row in legacy["records"]] + [v4["record"]]
    records[1]["tenant_id"] = "tenant-substitution"
    ok, reason = independent.verify_chain(records, _environment(legacy, v4))
    assert not ok
    assert reason == "tenant boundary mismatch"


def test_igor_verifier_has_no_shared_writer_verifier_imports():
    source = Path(independent.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
        elif isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
    assert not any(name in {"app.hashchain", "app.evidence_v4"} for name in imported)
