from dataclasses import asdict, dataclass, field
from enum import Enum
import hashlib
import json
from pathlib import Path
import re
from typing import Any


GENESIS_HASH = "0" * 64
SOURCE_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")


class AgentStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class AgentContext:
    repo_root: Path
    source_commit: str
    timeout_seconds: int = 900

    def __post_init__(self) -> None:
        root = Path(self.repo_root).resolve()
        object.__setattr__(self, "repo_root", root)
        if not SOURCE_COMMIT_PATTERN.fullmatch(self.source_commit):
            raise ValueError("source_commit must be a full 40-character lowercase SHA-1")
        if isinstance(self.timeout_seconds, bool) or not 1 <= self.timeout_seconds <= 3600:
            raise ValueError("timeout_seconds must be an integer from 1 to 3600")
        if not root.exists() or not root.is_dir():
            raise ValueError("repo_root must be an existing directory")


@dataclass(frozen=True)
class AgentFinding:
    code: str
    severity: str
    message: str
    evidence_refs: tuple[str, ...] = ()
    remediation: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "evidence_refs": list(self.evidence_refs),
            "remediation": self.remediation,
        }


@dataclass(frozen=True)
class AgentReport:
    role: str
    status: AgentStatus
    findings: list[AgentFinding] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.role or not isinstance(self.role, str):
            raise ValueError("role must be a non-empty string")
        if not isinstance(self.status, AgentStatus):
            object.__setattr__(self, "status", AgentStatus(self.status))
        if not isinstance(self.findings, list):
            raise ValueError("findings must be a list")
        if not isinstance(self.metrics, dict):
            raise ValueError("metrics must be a dictionary")

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "status": self.status.value,
            "findings": [item.to_dict() for item in self.findings],
            "metrics": self.metrics,
        }


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def event_hash(event_without_hash: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(event_without_hash).encode("utf-8")).hexdigest()


def verify_event_chain(events: list[dict[str, Any]]) -> bool:
    """Independently verify event hashes, sequence, and paired lifecycle order."""
    if not isinstance(events, list) or len(events) < 2:
        return False

    previous_hash = GENESIS_HASH
    run_id = None
    active_agent = None

    try:
        for index, event in enumerate(events):
            if not isinstance(event, dict):
                return False
            supplied_hash = event.get("event_hash")
            body = {key: value for key, value in event.items() if key != "event_hash"}

            if body.get("sequence") != index:
                return False
            if not isinstance(body.get("run_id"), str) or not body["run_id"]:
                return False
            if run_id is None:
                run_id = body["run_id"]
            if body["run_id"] != run_id or body.get("previous_hash") != previous_hash:
                return False
            if not isinstance(body.get("timestamp"), str) or not body["timestamp"]:
                return False
            if supplied_hash != event_hash(body):
                return False

            event_type = body.get("event_type")
            payload = body.get("payload")
            if not isinstance(payload, dict):
                return False

            if event_type == "run.start":
                if index != 0 or active_agent is not None:
                    return False
            elif event_type == "agent.start":
                role = payload.get("role")
                if active_agent is not None or not isinstance(role, str) or not role:
                    return False
                active_agent = role
            elif event_type == "agent.end":
                if active_agent is None or payload.get("role") != active_agent:
                    return False
                active_agent = None
            elif event_type == "run.end":
                if index != len(events) - 1 or active_agent is not None:
                    return False
            else:
                return False

            previous_hash = supplied_hash

        return (
            events[0].get("event_type") == "run.start"
            and events[-1].get("event_type") == "run.end"
        )
    except (TypeError, ValueError, KeyError):
        return False
