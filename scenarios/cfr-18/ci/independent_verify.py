"""Read-only evidence verifier; separate from producer's evidence-vault module."""
import argparse
import hashlib
import json
from pathlib import Path

GENESIS = hashlib.sha256(b"CFR-18-GENESIS").hexdigest()


def verify_chain(path):
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    assert rows, "empty evidence chain"
    previous = GENESIS
    for row in rows:
        assert row["prev_hash"] == previous, "chain linkage mismatch"
        unsigned = {k: v for k, v in row.items() if k != "hash"}
        actual = hashlib.sha256(json.dumps(unsigned, sort_keys=True).encode()).hexdigest()
        assert actual == row["hash"], "chain content hash mismatch"
        previous = actual
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--sha", required=True)
    args = parser.parse_args()
    root = Path(args.evidence)
    names = ("runtime-smoke.json", "fault-recovery.json",
             "clean-replay.json", "replay-verification.json")
    reports = [json.loads((root / name).read_text()) for name in names]
    assert all(x["source_sha"] == args.sha for x in reports), "source SHA mismatch"
    assert reports[0]["job_status"] == "done" and reports[0]["matching_workflows"] == 1
    assert reports[1]["matching_effects"] == 1 and reports[1]["completed_attempts"] == 2
    assert reports[2]["deterministic_replay"] == "PASS"
    assert reports[2]["cycles"][0] == reports[2]["cycles"][1]
    assert reports[3]["independent_consistency"] == "PASS"
    rows = verify_chain(root / "valid-chain.jsonl")
    assert rows[-1]["type"] == "evidence_commit"
    assert rows[-1]["payload"]["source_sha"] == args.sha
    for name in names:
        digest = hashlib.sha256((root / name).read_bytes()).hexdigest()
        assert rows[-1]["payload"]["sha256"][name] == digest, "evidence digest mismatch: " + name
    try:
        verify_chain(root / ".chain.jsonl")
    except (AssertionError, ValueError, KeyError):
        pass
    else:
        raise AssertionError("tampered negative fixture was accepted")
    print(json.dumps({"source_sha": args.sha, "result": "PASS",
                      "scope": "independent CI job and separate verifier implementation",
                      "valid_chain_entries": len(rows),
                      "owner_signature": "NOT_VERIFIED",
                      "human_gate": "NOT_VERIFIED"}, sort_keys=True))


if __name__ == "__main__":
    main()
