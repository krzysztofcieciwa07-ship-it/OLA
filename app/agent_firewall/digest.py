"""Canonical action commitments for approval and execution binding."""

import hashlib
import json
import re


_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


def canonical_action_bytes(
    *,
    action_type: str,
    unit: str,
    target_id: str,
    target_config_digest: str,
    environment: str,
    tenant_id: str,
    agent_id: str,
    policy_version: str,
) -> bytes:
    values = (
        action_type, unit, target_id, environment,
        tenant_id, agent_id, policy_version,
    )
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError("action digest fields must be non-empty strings")
    if not isinstance(target_config_digest, str) or not _HEX64_RE.fullmatch(target_config_digest):
        raise ValueError("target_config_digest must be lowercase SHA-256")
    payload = {
        "schema": "ola.agent-firewall.action.v1",
        "action": {"type": action_type, "unit": unit},
        "target": {"id": target_id, "config_digest": target_config_digest},
        "environment": environment,
        "tenant_id": tenant_id,
        "agent_id": agent_id,
        "policy_version": policy_version,
    }
    try:
        return json.dumps(
            payload, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("action digest contains non-UTF-8 text") from None


def action_digest(**kwargs) -> str:
    return hashlib.sha256(canonical_action_bytes(**kwargs)).hexdigest()
