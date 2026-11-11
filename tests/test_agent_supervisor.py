import hashlib
import json
import subprocess
import uuid

import pytest

from app.agent_protocol import AgentWorkerRequest, AgentWorkerResult, canonical_json
from app.agent_registry import DEFAULT_AGENT_MANIFEST
from app.agent_catalog import load_agent_catalog


SOURCE_COMMIT = "a" * 40
IMAGE_ID = "sha256:" + "b" * 64
CONTAINER_ID = "c" * 64


def _request():
    profile = "codeact"
    role = "Builder"
    model_output = "structured advisory output"
    return AgentWorkerRequest.from_json(canonical_json({
        "schema": "ola.agent-worker.request/v1",
        "request_id": str(uuid.uuid4()),
        "run_id": str(uuid.uuid4()),
        "agent_id": "builder-primary",
        "agent_instance_id": str(uuid.uuid4()),
        "specialist_role": role,
        "profile": profile,
        "task": "Calculate 17 * 23",
        "context": {"previous_output": {}, "upstream_agents": [], "upstream_execution": []},
        "capability": {"name": "safe_expression", "allowed": True},
        "model_response": {
            "provider": "ollama",
            "model": "qwen2.5:0.5b-instruct",
            "invocation_type": "real_llm",
            "response_id": "ollama-response-001",
            "prompt_digest": "1" * 64,
            "output_digest": hashlib.sha256(model_output.encode()).hexdigest(),
            "output": model_output,
        },
    }).encode())


def _image_inspect(source=SOURCE_COMMIT):
    return [{
        "Id": IMAGE_ID,
        "Os": "linux",
        "Architecture": "amd64",
        "Config": {
            "Entrypoint": ["python", "-m", "app.agent_worker"],
            "Cmd": None,
            "User": "65532:65532",
            "Labels": {"org.opencontainers.image.revision": source},
            "Env": ["PATH=/usr/local/bin:/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE=1"],
        },
    }]


def _container_inspect(network="none"):
    request = _request()
    result = {
        "capability": "executed_safe_expression",
        "tool": "safe_expression",
        "tool_output": "391",
        "result": "safe execution returned 391",
        "provider": "ollama",
        "model": "qwen2.5:0.5b-instruct",
        "invocation_type": "real_llm",
        "response_id": "ollama-response-001",
        "prompt_digest": "1" * 64,
        "model_output_digest": hashlib.sha256(b"structured advisory output").hexdigest(),
        "model_output_role": "advisory_only",
        "action_result_source": "registered_capability",
    }
    response = AgentWorkerResult(
        request_id=request.request_id,
        run_id=request.run_id,
        agent_id=request.agent_id,
        agent_instance_id=request.agent_instance_id,
        specialist_role=request.specialist_role,
        profile=request.profile,
        status="COMPLETED",
        worker_pid=1,
        result=result,
        result_digest=hashlib.sha256(canonical_json(result).encode()).hexdigest(),
    ).to_json()
    return {
        "Id": CONTAINER_ID,
        "Image": IMAGE_ID,
        "Config": {
            "Image": IMAGE_ID,
            "Entrypoint": ["python", "-m", "app.agent_worker"],
            "Cmd": None,
            "User": "65532:65532",
            "Env": ["PATH=/usr/local/bin:/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE=1"],
        },
        "HostConfig": {
            "NetworkMode": network,
            "ReadonlyRootfs": True,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true"],
            "PidsLimit": 16,
            "NanoCpus": 500_000_000,
            "Memory": 512 * 1024 * 1024,
            "MemorySwap": 512 * 1024 * 1024,
            "Binds": None,
            "Privileged": False,
        },
        "Mounts": [],
        "NetworkSettings": {"Networks": {"none": {}} if network == "none" else {network: {}}},
        "State": {"Status": "exited", "ExitCode": 0},
        "_test_response": response,
    }


class FakeDocker:
    def __init__(self, *, network="none", source=SOURCE_COMMIT, timeout=False):
        self.network = network
        self.source = source
        self.timeout = timeout
        self.calls = []
        self.request_bytes = None
        self.inspect_calls = 0

    def __call__(self, args, **kwargs):
        self.calls.append(list(args))
        command = args[1]
        if command == "image" and args[2] == "inspect":
            return subprocess.CompletedProcess(args, 0, json.dumps(_image_inspect(self.source)).encode(), b"")
        if command == "create":
            return subprocess.CompletedProcess(args, 0, (CONTAINER_ID + "\n").encode(), b"")
        if command == "inspect":
            self.inspect_calls += 1
            inspected = _container_inspect(self.network)
            if self.inspect_calls == 2:
                inspected["State"] = {"Status": "created", "ExitCode": None}
            response = inspected.pop("_test_response")
            self.response = response
            return subprocess.CompletedProcess(args, 0, json.dumps([inspected]).encode(), b"")
        if command == "start":
            self.request_bytes = kwargs.get("input")
            if self.timeout:
                raise subprocess.TimeoutExpired(args, kwargs.get("timeout"))
            return subprocess.CompletedProcess(args, 0, self.response, b"")
        if command in {"kill", "rm"}:
            return subprocess.CompletedProcess(args, 0, b"", b"")
        raise AssertionError(f"unexpected Docker command: {args}")


def test_supervisor_runs_one_shot_container_with_required_isolation_and_scoped_input(monkeypatch):
    from app.agent_supervisor import AgentSupervisor

    fake = FakeDocker()
    monkeypatch.setenv("OLA_RUNTIME_COMMIT", SOURCE_COMMIT)
    monkeypatch.setenv("OLA_WORKER_IMAGE", f"ola-agent-worker:{SOURCE_COMMIT}")
    supervisor = AgentSupervisor(docker_runner=fake)
    instance = next(item for item in DEFAULT_AGENT_MANIFEST if item.agent_id == "builder-primary")

    execution = supervisor.execute(instance, _request())

    create = next(call for call in fake.calls if call[1] == "create")
    assert "--network" in create and create[create.index("--network") + 1] == "none"
    assert "--read-only" in create
    assert "--cap-drop" in create and create[create.index("--cap-drop") + 1] == "ALL"
    assert "--security-opt" in create and "no-new-privileges:true" in create
    assert "--pids-limit" in create and create[create.index("--pids-limit") + 1] == "16"
    assert "--cpus" in create and "--memory" in create
    assert "--memory-swap" in create and "--user" in create
    assert not any(arg in {"-v", "--volume", "--mount", "--privileged", "--network=host"} for arg in create)
    assert create[-1] == IMAGE_ID
    assert create[0:2] == ["docker", "create"]
    assert fake.request_bytes and b"Calculate 17 * 23" in fake.request_bytes
    assert execution.container_id == CONTAINER_ID
    assert execution.image_id == IMAGE_ID
    assert execution.worker_result.result["tool_output"] == "391"
    assert execution.isolation_report["network_mode"] == "none"
    assert execution.isolation_report["readonly_rootfs"] is True
    assert execution.isolation_report["mounts"] == []
    assert execution.isolation_report["docker_socket_mounted"] is False
    assert any(call[1] == "rm" for call in fake.calls)


def test_supervisor_blocks_worker_image_with_wrong_source_commit(monkeypatch):
    from app.agent_supervisor import AgentSupervisor, AgentSupervisorError

    fake = FakeDocker(source="f" * 40)
    monkeypatch.setenv("OLA_RUNTIME_COMMIT", SOURCE_COMMIT)
    monkeypatch.setenv("OLA_WORKER_IMAGE", f"ola-agent-worker:{SOURCE_COMMIT}")
    supervisor = AgentSupervisor(docker_runner=fake)
    instance = next(item for item in DEFAULT_AGENT_MANIFEST if item.agent_id == "builder-primary")

    with pytest.raises(AgentSupervisorError, match="source revision"):
        supervisor.execute(instance, _request())

    assert not any(call[1] == "create" for call in fake.calls)


def test_supervisor_blocks_container_when_docker_inspect_disagrees_with_isolation_policy(monkeypatch):
    from app.agent_supervisor import AgentSupervisor, AgentSupervisorError

    fake = FakeDocker(network="bridge")
    monkeypatch.setenv("OLA_RUNTIME_COMMIT", SOURCE_COMMIT)
    monkeypatch.setenv("OLA_WORKER_IMAGE", f"ola-agent-worker:{SOURCE_COMMIT}")
    supervisor = AgentSupervisor(docker_runner=fake)
    instance = next(item for item in DEFAULT_AGENT_MANIFEST if item.agent_id == "builder-primary")

    with pytest.raises(AgentSupervisorError, match="isolation"):
        supervisor.execute(instance, _request())

    assert not any(call[1] == "start" for call in fake.calls)
    assert any(call[1] == "rm" for call in fake.calls)


def test_supervisor_cleans_timed_out_worker_and_never_returns_a_result(monkeypatch):
    from app.agent_supervisor import AgentSupervisor, AgentSupervisorError

    fake = FakeDocker(timeout=True)
    monkeypatch.setenv("OLA_RUNTIME_COMMIT", SOURCE_COMMIT)
    monkeypatch.setenv("OLA_WORKER_IMAGE", f"ola-agent-worker:{SOURCE_COMMIT}")
    supervisor = AgentSupervisor(docker_runner=fake)
    instance = next(item for item in DEFAULT_AGENT_MANIFEST if item.agent_id == "builder-primary")

    with pytest.raises(AgentSupervisorError, match="timeout"):
        supervisor.execute(instance, _request())

    assert any(call[1] == "kill" for call in fake.calls)
    assert any(call[1] == "rm" for call in fake.calls)


def test_supervisor_rejects_unpinned_image_reference(monkeypatch):
    from app.agent_supervisor import AgentSupervisor, AgentSupervisorError

    fake = FakeDocker()
    monkeypatch.setenv("OLA_RUNTIME_COMMIT", SOURCE_COMMIT)
    monkeypatch.setenv("OLA_WORKER_IMAGE", "python:3.13-slim")
    supervisor = AgentSupervisor(docker_runner=fake)
    instance = next(item for item in DEFAULT_AGENT_MANIFEST if item.agent_id == "builder-primary")

    with pytest.raises(AgentSupervisorError, match="must be pinned"):
        supervisor.execute(instance, _request())
