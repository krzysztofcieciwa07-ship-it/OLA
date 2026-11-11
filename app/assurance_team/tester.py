import hashlib
import re
import subprocess
import sys
import time

from .contracts import AgentContext, AgentFinding, AgentReport, AgentStatus


TEST_PATHS = (
    "tests/test_agent_runtime.py",
    "tests/test_agent_runtime_finalization.py",
    "tests/test_agent_run_safety_gate.py",
    "tests/test_agent_capabilities.py",
    "tests/test_evidence_concurrency.py",
    "tests/test_independent_verifier_tamper.py",
    "tests/test_nina_workflow_gate.py",
    "tests/test_nina_workflow_api.py",
    "tests/test_ollama_generation_budget.py",
    "tests/test_runtime_provenance.py",
)
_PYTEST_SUMMARY = re.compile(
    r"(?P<summary>\d+ passed(?:, \d+ skipped)?(?:, \d+ failed)?(?:, \d+ error)?(?: in [0-9.]+s)?)"
)


class TesterAgent:
    """Run a fixed, bounded pytest allowlist; never execute a caller command."""

    role = "tester"

    def run(self, context: AgentContext) -> AgentReport:
        command = [sys.executable, "-m", "pytest", *TEST_PATHS]
        timeout = min(context.timeout_seconds, 900)
        started = time.perf_counter()

        try:
            completed = subprocess.run(
                command,
                cwd=context.repo_root,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                shell=False,
            )
            duration = round(time.perf_counter() - started, 3)
            combined = f"{completed.stdout or ''}\n{completed.stderr or ''}"
            output_digest = hashlib.sha256(combined.encode("utf-8", errors="replace")).hexdigest()
            summary_matches = list(_PYTEST_SUMMARY.finditer(combined))
            summary = summary_matches[-1].group("summary") if summary_matches else None
            if completed.returncode != 0:
                status = AgentStatus.FAIL
                findings = [
                    AgentFinding(
                        code="TEST_SUITE_FAILED",
                        severity="high",
                        message=f"Allowlisted pytest suite exited with code {completed.returncode}.",
                        evidence_refs=(f"sha256:{output_digest}",),
                        remediation="Inspect the GitHub Actions job log for the exact source commit and fix the failing assertion or runtime defect.",
                    )
                ]
            elif summary is None:
                status = AgentStatus.UNKNOWN
                findings = [
                    AgentFinding(
                        code="TEST_SUMMARY_UNRECOGNIZED",
                        severity="medium",
                        message="pytest returned zero but did not emit a recognized test summary.",
                        evidence_refs=(f"sha256:{output_digest}",),
                        remediation="Verify pytest collection and output format; do not promote an uncounted run to PASS.",
                    )
                ]
            else:
                status = AgentStatus.PASS
                findings = []
            return AgentReport(
                role=self.role,
                status=status,
                findings=findings,
                metrics={
                    "test_paths": list(TEST_PATHS),
                    "return_code": completed.returncode,
                    "duration_seconds": duration,
                    "summary": summary,
                    "output_sha256": output_digest,
                    "shell": False,
                    "timeout_seconds": timeout,
                },
            )
        except subprocess.TimeoutExpired as exc:
            duration = round(time.perf_counter() - started, 3)
            partial = exc.stdout or b""
            if isinstance(partial, str):
                partial = partial.encode("utf-8", errors="replace")
            digest = hashlib.sha256(partial).hexdigest()
            return AgentReport(
                role=self.role,
                status=AgentStatus.FAIL,
                findings=[
                    AgentFinding(
                        code="TEST_SUITE_TIMEOUT",
                        severity="high",
                        message=f"Allowlisted pytest suite exceeded its {timeout}-second timeout.",
                        evidence_refs=(f"sha256:{digest}",),
                        remediation="Reduce test scope or fix the test/runtime hang; do not increase the timeout without a measured reason.",
                    )
                ],
                metrics={
                    "test_paths": list(TEST_PATHS),
                    "duration_seconds": duration,
                    "timeout_seconds": timeout,
                    "output_sha256": digest,
                },
            )
        except OSError as exc:
            return AgentReport(
                role=self.role,
                status=AgentStatus.BLOCKED,
                findings=[
                    AgentFinding(
                        code="TEST_RUNNER_UNAVAILABLE",
                        severity="high",
                        message=f"Unable to launch the local pytest process ({type(exc).__name__}).",
                        remediation="Install the pinned project test dependencies and verify the Python executable.",
                    )
                ],
                metrics={
                    "test_paths": list(TEST_PATHS),
                    "timeout_seconds": timeout,
                },
            )
