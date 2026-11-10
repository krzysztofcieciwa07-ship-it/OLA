import importlib
import importlib.util
import json
from pathlib import Path
from subprocess import CompletedProcess

import pytest


IMAGE_DIGEST = "sha256:" + "b" * 64
CONTAINER_ID = "c" * 64


def _supervisor_module():
    spec = importlib.util.find_spec("app.agent_supervisor")
    assert spec is not None, "Docker-isolated supervisor is not implemented"
    return importlib.import_module("app.agent_supervisor")


def _request_and_agent():
    from app.agent_protocol import AgentWorkerRequest
    from app.agent_registry import make_agent_instance_spec

    agent = make_agent_instance_spec(
        "hermes-supervisor-01",
        "Hermes",
        "react",
        capabilities=("tool.safe_expression",),
    )
    request = AgentWorkerRequest.model_validate({
        "schema_version": 1,
        "run_id": "run-supervisor-001",
        "agent_id": agent.agent_id,
        "agent_instance_id": "instance-supervisor-001",
        "specialist_role": agent.specialist_role,
        "execution_profile": agent.execution_profile,
        "capability": "tool.safe_expression",
        "allowed_capabilities": ["tool.safe_expression"],
        "task": "Calculate 17 times 23.",
        "capability_input": {"expression": "17 * 23"},
        "model_output": {"proposal": "Evaluate the arithmetic expression."},
        "source_commit": "a" * 40,
    })
    return agent, request


def _docker_inspect():
    return {
        "Id": CONTAINER_ID,
        "Image": IMAGE_DIGEST,
        "State": {"Status": "exited", "ExitCode": 0},
        "Config": {"User": "65532:65532"},
        "HostConfig": {
            "NetworkMode": "none",
            "ReadonlyRootfs": True,
            "PidsLimit": 32,
            "Memory": 512 * 1024 * 1024,
            "NanoCpus": 1_000_000_000,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true"],
            "Binds": [],
            "Mounts": [],
            "Privileged": False,
        },
        "Mounts": [],
    }


def test_supervisor_launches_a_fresh_hardened_worker_with_no_host_mounts(tmp_path):
    supervisor_module = _supervisor_module()
    from app.agent_worker import run_agent_worker

    agent, request = _request_and_agent()
    calls = []
    cidfile_path = None

    def fake_runner(args, **kwargs):
        nonlocal cidfile_path
        calls.append((args, kwargs))
        if args[1:3] == ["image", "inspect"]:
            return CompletedProcess(args, 0, stdout=IMAGE_DIGEST, stderr="")
        if args[1] == "run":
            cidfile_path = args[args.index("--cidfile") + 1]
            Path(cidfile_path).write_text(CONTAINER_ID, encoding="ascii")
            result = run_agent_worker(request)
            return CompletedProcess(args, 0, stdout=result.model_dump_json(), stderr="")
        if args[1] == "inspect":
            return CompletedProcess(args, 0, stdout=json.dumps(_docker_inspect()), stderr="")
        if args[1:3] == ["rm", "-f"]:
            return CompletedProcess(args, 0, stdout="", stderr="")
        raise AssertionError(f"unexpected docker command: {args}")

    supervisor = supervisor_module.AgentSupervisor(
        image_digest=IMAGE_DIGEST,
        runner=fake_runner,
        temp_dir=str(tmp_path),
    )
    result = supervisor.execute(agent, request)

    assert result.status == "COMPLETED"
    assert result.container_id == CONTAINER_ID
    assert result.image_digest == IMAGE_DIGEST
    assert result.worker_result.capability_result == {"value": 391}
    run_args = next(args for args, _ in calls if len(args) > 1 and args[1] == "run")
    assert "--network" in run_args and run_args[run_args.index("--network") + 1] == "none"
    assert "--read-only" in run_args
    assert "--cap-drop" in run_args and run_args[run_args.index("--cap-drop") + 1] == "ALL"
    assert "--security-opt" in run_args and "no-new-privileges:true" in run_args
    assert "--pids-limit" in run_args and run_args[run_args.index("--pids-limit") + 1] == "32"
    assert "--memory" in run_args and run_args[run_args.index("--memory") + 1] == "512m"
    assert "--cpus" in run_args and run_args[run_args.index("--cpus") + 1] == "1"
    assert "--user" in run_args and run_args[run_args.index("--user") + 1] == "65532:65532"
    assert "--tmpfs" in run_args
    assert "--pull=never" in run_args
    assert IMAGE_DIGEST in run_args
    assert not any("/var/run/docker.sock" in item or "/home/" in item for item in run_args)
    assert not any(item in {"--privileged", "-v", "--volume", "--mount"} for item in run_args)
    assert "sh" not in run_args and "bash" not in run_args
    assert cidfile_path is not None


def test_supervisor_rejects_mutable_or_missing_worker_image_before_docker():
    supervisor_module = _supervisor_module()
    agent, request = _request_and_agent()
    calls = []
    runner = lambda *args, **kwargs: calls.append(args)  # noqa: E731

    for image in (None, "ola-agent-worker:latest", "sha256:not-a-digest"):
        supervisor = supervisor_module.AgentSupervisor(
            image_digest=image,
            runner=runner,
        )
        result = supervisor.execute(agent, request)
        assert result.status == "BLOCKED"
    assert calls == []


def test_supervisor_blocks_request_identity_mismatch_before_docker():
    supervisor_module = _supervisor_module()
    agent, request = _request_and_agent()
    calls = []
    supervisor = supervisor_module.AgentSupervisor(
        image_digest=IMAGE_DIGEST,
        runner=lambda *args, **kwargs: calls.append(args),
    )
    altered = request.model_copy(update={"agent_id": "different-agent"})

    result = supervisor.execute(agent, altered)

    assert result.status == "BLOCKED"
    assert calls == []


def test_supervisor_fails_closed_on_worker_timeout_and_cleans_container(tmp_path):
    supervisor_module = _supervisor_module()
    agent, request = _request_and_agent()
    calls = []

    def fake_runner(args, **kwargs):
        calls.append(args)
        if args[1:3] == ["image", "inspect"]:
            return CompletedProcess(args, 0, stdout=IMAGE_DIGEST, stderr="")
        if args[1] == "run":
            cidfile = args[args.index("--cidfile") + 1]
            Path(cidfile).write_text(CONTAINER_ID, encoding="ascii")
            raise TimeoutError("worker timeout")
        if args[1:3] == ["rm", "-f"]:
            return CompletedProcess(args, 0, stdout="", stderr="")
        raise AssertionError(f"unexpected docker command: {args}")

    supervisor = supervisor_module.AgentSupervisor(
        image_digest=IMAGE_DIGEST,
        runner=fake_runner,
        temp_dir=str(tmp_path),
    )
    result = supervisor.execute(agent, request)

    assert result.status == "FAILED"
    assert result.container_id == CONTAINER_ID
    assert any(args[1:3] == ["rm", "-f"] for args in calls)
