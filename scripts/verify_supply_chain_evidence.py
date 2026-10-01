import argparse
import hashlib
import json
from pathlib import Path

REQUIRED = ("sbom.spdx.json", "trivy-image.json", "ola-image.tar", "attestation.verified", "slsa.verified", "sigstore.verified", "in-toto.verified")

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--root", default=".")
    p.add_argument("--commit", required=True)
    p.add_argument("--output", default="security-evidence-manifest.json")
    args = p.parse_args()
    root = Path(args.root)
    missing = [x for x in REQUIRED if not (root / x).is_file()]
    if missing:
        print(json.dumps({"status":"BLOCK","reason":"missing security evidence","missing":missing}, sort_keys=True))
        return 1
    artifacts = [{"name":n,"size":(root/n).stat().st_size,"sha256":sha256(root/n)} for n in REQUIRED]
    manifest = {
        "schema":"ola.security-evidence-manifest.v1",
        "status":"EVIDENCE_COLLECTED",
        "source_commit":args.commit,
        "components":{"openssf_scorecard":"REQUIRED","zizmor":"REQUIRED","gitleaks":"REQUIRED","trivy":"REQUIRED","sbom":"REQUIRED","artifact_attestation":"REQUIRED","slsa_provenance":"REQUIRED","sigstore":"REQUIRED","in_toto":"REQUIRED"},
        "artifacts":artifacts,
        "verification":{"artifact_hashes":"LOCAL_SHA256","attestation":"GITHUB_ATTESTATION_VERIFY","tamper":"REQUIRED_BY_OLA_GATE","replay":"REQUIRED_BY_OLA_GATE","human_gate":"REQUIRED_BY_OLA_GATE"}
    }
    Path(args.output).write_text(json.dumps(manifest, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    print(json.dumps({"status":"EVIDENCE_COLLECTED","artifact_count":len(artifacts),"output":args.output}, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
