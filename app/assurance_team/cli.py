import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

from .architecture import ArchitectureAgent
from .contracts import AgentContext, AgentStatus, canonical_json
from .orchestrator import AgentOrchestrator
from .tester import TesterAgent


PLANNED_ROLES = ("tester", "architecture", "performance", "protection", "legal")


def _resolve_output_dir(repo_root: Path, raw_output_dir: str) -> Path:
    """Keep evidence writes inside the selected repository checkout."""
    root = repo_root.resolve()
    candidate = Path(raw_output_dir)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("output_dir must remain inside repo_root") from exc
    return resolved


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the OLA evidence-driven assurance agent team.")
    parser.add_argument("--repo-root", default=".", help="Repository checkout to inspect.")
    parser.add_argument("--source-commit", required=True, help="Full 40-character Git commit SHA.")
    parser.add_argument("--output-dir", required=True, help="Directory for the evidence bundle.")
    parser.add_argument("--timeout-seconds", type=int, default=900)
    args = parser.parse_args(argv)

    try:
        context = AgentContext(
            repo_root=Path(args.repo_root),
            source_commit=args.source_commit,
            timeout_seconds=args.timeout_seconds,
        )
        output_dir = _resolve_output_dir(context.repo_root, args.output_dir)
        orchestrator = AgentOrchestrator(
            agents=[TesterAgent(), ArchitectureAgent()],
            planned_roles=PLANNED_ROLES,
        )
        report = orchestrator.run(context)
        if not report["event_chain_valid"]:
            raise RuntimeError("independent lifecycle event verification failed")

        output_dir.mkdir(parents=True, exist_ok=True)
        # Re-check after creation so a pre-existing or concurrently substituted
        # symlink cannot redirect the evidence bundle outside the checkout.
        output_dir = _resolve_output_dir(context.repo_root, str(output_dir))
        events_content = "".join(canonical_json(event) + "\n" for event in report["events"])
        report_content = json.dumps(report, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
        _atomic_write(output_dir / "team-report.json", report_content)
        _atomic_write(output_dir / "team-events.jsonl", events_content)

        report_digest = hashlib.sha256(report_content.encode("utf-8")).hexdigest()
        events_digest = hashlib.sha256(events_content.encode("utf-8")).hexdigest()
        manifest = (
            f"{report_digest}  team-report.json\n"
            f"{events_digest}  team-events.jsonl\n"
        )
        _atomic_write(output_dir / "team-evidence.sha256", manifest)

        print(json.dumps({
            "run_id": report["run_id"],
            "source_commit": report["source_commit"],
            "status": report["status"],
            "coverage": report["coverage"],
            "event_chain_valid": report["event_chain_valid"],
            "artifact_dir": str(output_dir),
        }, sort_keys=True))
        if report["status"] == AgentStatus.PASS.value:
            return 0
        if report["status"] == AgentStatus.FAIL.value:
            return 1
        return 2
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({
            "status": "BLOCKED",
            "error_type": type(exc).__name__,
            "message": str(exc),
        }, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
