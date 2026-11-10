import json
import os
import re
import subprocess
import uuid

import pytest

from app.agent_protocol import AgentWorkerRequest
from app.agent_registry import make_agent_instance_spec
from app.agent_supervisor import AgentSupervisor


WORKER_IMAGE = os.getenv("OLA_AGENT_WORKER_IMAGE_DIGEST")
SOURCE_COMMIT = os.getenv("OLA_SOURCE_COMMIT")


@pytest.mark.skipif(
    not WORKER_IMAGE or not SOURCE_COMMIT,
    reason="requires a locally built, digest-pinned worker image",
)
def test_real_docker_worker_is_one_shot_isolated_and_cleaned_up():
    assert re.fullmatch(r"sha256:[a-f0-9]{64}", WORKER_IMAGE)
    assert re.fullmatch(r"[a-f0-9]{40}", SOURCE_COMMIT)

    agent = make_agent_instance_spec(
        "hermes-docker-integration-01",
        "Hermes",
        "react",
        capabilities=("tool.safe_expression",),
    )
    supervisor = AgentSupervisor(
        registry=[agent],
        image_digest=WORKER_IMAGE,
        expected_source_commit=SOURCE_COMMIT,
    )

    def make_request():
        return AgentWorkerRequest.model_validate_json(json.dumps({
            "schema_version": 1,
            "run_id": str(uuid.uuid4()),
            "agent_id": agent.agent_id,
            "agent_instance_id": str(uuid.uuid4()),
            "specialist_role": agent.specialist_role,
            "execution_profile": agent.execution_profile,
            "capability": "tool.safe_expression",
            "allowed_capabilities": ["tool.safe_expression"],
            "task": "Calculate 17 times 23.",
            "capability_input": {"expression": "17 * 23"},
            "model_output": {"proposal": "Evaluate the arithmetic expression."},
            "source_commit": SOURCE_COMMIT,
        }))

    first = supervisor.execute(agent, make_request())
    second = supervisor.execute(agent, make_request())

    assert first.status == "COMPLETED", first.reason
    assert second.status == "COMPLETED", second.reason
    assert first.container_id and second.container_id
    assert re.fullmatch(r"[a-f0-9]{64}", first.container_id)
    assert re.fullmatch(r"[a-f0-9]{64}", second.container_id)
    assert first.container_id != second.container_id
    assert first.image_digest == second.image_digest == WORKER_IMAGE
    assert first.worker_result.worker_pid == second.worker_result.worker_pid == 1
    assert first.worker_result.capability_result == {"value": 391}
    assert second.worker_result.capability_result == {"value": 391}
    assert first.worker_result.worker_nonce != second.worker_result.worker_nonce

    for container_id in (first.container_id, second.container_id):
        inspect = subprocess.run(
            ["docker", "inspect", container_id],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        assert inspect.returncode != 0, "completed worker container was not removed"
