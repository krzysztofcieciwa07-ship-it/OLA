from datetime import datetime, timezone
import hashlib
import uuid
from typing import Iterable

from .contracts import (
    GENESIS_HASH,
    AgentContext,
    AgentFinding,
    AgentReport,
    AgentStatus,
    canonical_json,
    event_hash,
    verify_event_chain,
)


class AgentOrchestrator:
    """Sequential, fail-closed coordinator for enabled specialist agents."""

    def __init__(self, agents: Iterable[object], planned_roles: Iterable[str]):
        self.agents = list(agents)
        self.planned_roles = list(planned_roles)
        if not self.planned_roles or len(set(self.planned_roles)) != len(self.planned_roles):
            raise ValueError("planned_roles must be non-empty and unique")

        enabled_roles = [getattr(agent, "role", None) for agent in self.agents]
        if any(not isinstance(role, str) or not role for role in enabled_roles):
            raise ValueError("every agent must declare a non-empty role")
        if len(set(enabled_roles)) != len(enabled_roles):
            raise ValueError("enabled agent roles must be unique")
        if any(role not in self.planned_roles for role in enabled_roles):
            raise ValueError("every enabled agent role must appear in planned_roles")

    def run(self, context: AgentContext) -> dict:
        run_id = uuid.uuid4().hex
        events: list[dict] = []
        agent_results: list[dict] = []

        def append_event(event_type: str, payload: dict) -> None:
            previous_hash = events[-1]["event_hash"] if events else GENESIS_HASH
            body = {
                "sequence": len(events),
                "run_id": run_id,
                "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "event_type": event_type,
                "payload": payload,
                "previous_hash": previous_hash,
            }
            events.append({**body, "event_hash": event_hash(body)})

        enabled_roles = [agent.role for agent in self.agents]
        not_enabled = [role for role in self.planned_roles if role not in enabled_roles]
        append_event(
            "run.start",
            {
                "schema": "ola-assurance-team-events-v1",
                "source_commit": context.source_commit,
                "planned_roles": self.planned_roles,
                "enabled_roles": enabled_roles,
            },
        )

        for agent in self.agents:
            role = agent.role
            append_event("agent.start", {"role": role, "source_commit": context.source_commit})
            try:
                result = agent.run(context)
                if not isinstance(result, AgentReport) or result.role != role:
                    raise TypeError("agent returned a report that violates its role contract")
                # Reject output that cannot be represented in the JSON evidence contract.
                canonical_json(result.to_dict())
            except Exception as exc:
                error_code = "AGENT_CONTRACT_VIOLATION" if isinstance(exc, TypeError) else "AGENT_EXECUTION_EXCEPTION"
                result = AgentReport(
                    role=role,
                    status=AgentStatus.FAIL,
                    findings=[
                        AgentFinding(
                            code=error_code,
                            severity="high",
                            message=f"Agent {role} did not produce a valid report ({type(exc).__name__}).",
                            remediation="Correct the specialist implementation and its contract tests before enabling it.",
                        )
                    ],
                    metrics={},
                )

            result_dict = result.to_dict()
            agent_results.append(result_dict)
            append_event(
                "agent.end",
                {
                    "role": role,
                    "source_commit": context.source_commit,
                    "report": result_dict,
                },
            )

        statuses = [AgentStatus(item["status"]) for item in agent_results]
        if AgentStatus.FAIL in statuses:
            overall = AgentStatus.FAIL
        elif AgentStatus.BLOCKED in statuses:
            overall = AgentStatus.BLOCKED
        elif AgentStatus.UNKNOWN in statuses:
            overall = AgentStatus.UNKNOWN
        else:
            overall = AgentStatus.PASS

        append_event(
            "run.end",
            {
                "status": overall.value,
                "source_commit": context.source_commit,
                "completed_agents": enabled_roles,
            },
        )
        chain_valid = verify_event_chain(events)
        if not chain_valid:
            overall = AgentStatus.BLOCKED

        events_jsonl = "".join(canonical_json(item) + "\n" for item in events)
        return {
            "schema": "ola-assurance-team-report-v1",
            "run_id": run_id,
            "source_commit": context.source_commit,
            "status": overall.value,
            "coverage": {
                "planned": list(self.planned_roles),
                "enabled": enabled_roles,
                "not_enabled": not_enabled,
                "coverage_status": "COMPLETE" if not not_enabled else "PARTIAL",
            },
            "agent_results": agent_results,
            "event_chain_valid": chain_valid,
            "event_count": len(events),
            "events_sha256": hashlib.sha256(events_jsonl.encode("utf-8")).hexdigest(),
            "events": events,
        }
