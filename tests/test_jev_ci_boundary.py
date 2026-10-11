"""Execute the actual workflow summary against trust/result combinations."""
import os
from pathlib import Path
import re
import subprocess

import pytest

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/decision-fabric.yml"


def test_live_jev_is_restricted_to_main_with_dedicated_environment():
    text = WORKFLOW.read_text()
    job = text.split("  live-jev:\n", 1)[1].split("  evidence:\n", 1)[0]
    assert "if: github.ref == 'refs/heads/main' && github.event_name != 'pull_request'" in job
    assert "environment:\n      name: ci-jev\n      deployment: false" in job


@pytest.mark.parametrize("contract,live,available,trusted,allowed,claim", [
    ("success", "skipped", "", "false", True, "NOT_PROVEN"),
    ("success", "success", "false", "true", True, "NOT_PROVEN"),
    ("success", "success", "true", "true", True, "VERIFIED"),
    ("success", "skipped", "", "true", False, None),
    ("success", "failure", "true", "true", False, None),
    ("success", "cancelled", "", "false", False, None),
    ("failure", "skipped", "", "false", False, None),
])
def test_summary_does_not_promote_skipped_or_failed_evidence(contract, live, available, trusted, allowed, claim):
    summary = WORKFLOW.read_text().split("      - name: Decision gate summary\n", 1)[1]
    script = summary.split("        run: |\n", 1)[1]
    script = re.sub(r"(?m)^          ", "", script)
    result = subprocess.run(["bash", "-e"], input=script, text=True, capture_output=True,
                            env={**os.environ, "CONTRACT_RESULT": contract, "LIVE_RESULT": live,
                                 "LIVE_AVAILABLE": available, "TRUSTED_MAIN": trusted})
    assert (result.returncode == 0) is allowed
    if claim:
        assert "LIVE_JEV=" + claim in result.stdout
