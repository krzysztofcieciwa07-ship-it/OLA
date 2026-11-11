import hashlib
import json
import subprocess
import uuid

import pytest

from app.agent_protocol import AgentWorkerRequest, AgentWorkerResult, canonical_json, sha256_json
from app.agent_registry import DEFAULT_AGENT_MANIFEST


SOURCE_COMMIT = "a" * 40
IMAGE_ID = "sha256:" + "b" * 64
CONTAINER_ID = "c" * 64
MEMORY_BYTES = 512 * 1024 * 1024


def _request():
    model_output = "structured advisory output"
    return AgentWorkerRequest.from_json(canonical_json({
        "schema": "ola.agent-worker.request/v1",
        "request_id": str(uuid.uuid4()),
        "run_id": str(uuid.uuid4()),
        "agent_id": "builder-primary",
        "agent_instance_id": str(uuid.uuid4()),
        "specialist_role": "Builder",
        "profile": "codeact",
        "runtime_profile": "test",
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


def _container_inspect(network="none", state="created"):
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
            "Memory": MEMORY_BYTES,
            "MemorySwap": MEMORY_BYTES,
            "Binds": None,
            "Privileged": False,
        },
        "Mounts": [],
        "NetworkSettings": {"Networks": {"none": {}} if network == "none" else {network: {}}},
        "State": {"Status": state, "ExitCode": 0 if state == "exited" else None},
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
            return subprocess.CompletedProcess(
                args, 0, json.dumps(_image_inspect(self.source)).encode(), b""
            )
        if command == "create":
            return subprocess.CompletedProcess(args, 0, (CONTAINER_ID + "\n").encode(), b"")
        if command == "inspect":
            self.inspect_calls += 1
            state = "created" if self.inspect_calls == 1 else "exited"
            return subprocess.CompletedProcess(
                args, 0, json.dumps([_container_inspect(self.network, state)]).encode(), b""
            )
        if command == "start":
            self.request_bytes = kwargs.get("input")
            if self.timeout:
                raise subprocess.TimeoutExpired(args, kwargs.get("timeout"))
            request = AgentWorkerRequest.from_json(self.request_bytes)
            result = {
                "capability": "executed_safe_expression",
                "tool": "safe_expression",
                "tool_output": "391",
                "result": "safe execution returned 391",
                "provider": request.model_provider,
                "model": request.model_name,
                "invocation_type": request.invocation_type,
                "response_id": request.model_response_id,
                "prompt_digest": request.prompt_digest,
                "model_output_digest": request.model_output_digest,
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
                result_digest=sha256_json(result),
            ).to_json()
            return subprocess.CompletedProcess(args, 0, response, b"")
        if command in {"kill", "rm"}:
            return subprocess.CompletedProcess(args, 0, b"", b"")
        raise AssertionError(f"unexpected Docker command: {args}")


def test_supervisor_runs_one_shot_container_with_required_isolation_and_scoped_input(monkeypatch):
    from app.agent_supervisor import AgentSupervisor

    fake = FakeDocker()
    monkeypatch.setenv("OLA_RUNTIME_PROFILE", "test")
    monkeypatch.setenv("OLA_WORKER_IMAGE", f"ola-agent-worker:{SOURCE_COMMIT}")
    supervisor = AgentSupervisor(docker_runner=fake, source_commit=SOURCE_COMMIT)
    instance = next(item for item in DEFAULT_AGENT_MANIFEST if item.agent_id == "builder-primary")

    execution = supervisor.execute(instance, _request())

    create = next(call for call in fake.calls if call[1] == "create")
    assert "--network" in create and create[create.index("--network") + 1] == "none"
    assert "--read-only" in create
    assert "--cap-drop" in create and create[create.index("--cap-drop") + 1] == "ALL"
    assert "--security-opt" in create and "no-new-privileges:true" in create
    assert "--pids-limit" in create and create[create.index("--pids-limit") + 1] == "16"
    assert "--cpus" in create and "--memory" in create and "--memory-swap" in create
    assert "--user" in create and create[create.index("--user") + 1] == "65532:65532"
    assert not any(arg in {"-v", "--volume", "--mount", "--privileged"} for arg in create)
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
    monkeypatch.setenv("OLA_RUNTIME_PROFILE", "test")
    monkeypatch.setenv("OLA_WORKER_IMAGE", f"ola-agent-worker:{SOURCE_COMMIT}")
    supervisor = AgentSupervisor(docker_runner=fake, source_commit=SOURCE_COMMIT)
    instance = next(item for item in DEFAULT_AGENT_MANIFEST if item.agent_id == "builder-primary")

    with pytest.raises(AgentSupervisorError, match="source revision"):
        supervisor.execute(instance, _request())

    assert not any(call[1] == "create" for call in fake.calls)


def test_supervisor_blocks_container_when_docker_inspect_disagrees_with_isolation_policy(monkeypatch):
    from app.agent_supervisor import AgentSupervisor, AgentSupervisorError

    fake = FakeDocker(network="bridge")
    monkeypatch.setenv("OLA_RUNTIME_PROFILE", "test")
    monkeypatch.setenv("OLA_WORKER_IMAGE", f"ola-agent-worker:{SOURCE_COMMIT}")
    supervisor = AgentSupervisor(docker_runner=fake, source_commit=SOURCE_COMMIT)
    instance = next(item for item in DEFAULT_AGENT_MANIFEST if item.agent_id == "builder-primary")

    with pytest.raises(AgentSupervisorError, match="isolation"):
        supervisor.execute(instance, _request())

    assert not any(call[1] == "start" for call in fake.calls)
    assert any(call[1] == "rm" for call in fake.calls)


def test_supervisor_cleans_timed_out_worker_and_never_returns_a_result(monkeypatch):
    from app.agent_supervisor import AgentSupervisor, AgentSupervisorError

    fake = FakeDocker(timeout=True)
    monkeypatch.setenv("OLA_RUNTIME_PROFILE", "test")
    monkeypatch.setenv("OLA_WORKER_IMAGE", f"ola-agent-worker:{SOURCE_COMMIT}")
    supervisor = AgentSupervisor(docker_runner=fake, source_commit=SOURCE_COMMIT)
    instance = next(item for item in DEFAULT_AGENT_MANIFEST if item.agent_id == "builder-primary")

    with pytest.raises(AgentSupervisorError, match="timeout"):
        supervisor.execute(instance, _request())

    assert any(call[1] == "kill" for call in fake.calls)
    assert any(call[1] == "rm" for call in fake.calls)


def test_supervisor_rejects_unpinned_image_reference(monkeypatch):
    from app.agent_supervisor import AgentSupervisor, AgentSupervisorError

    fake = FakeDocker()
    monkeypatch.setenv("OLA_RUNTIME_PROFILE", "test")
    monkeypatch.setenv("OLA_WORKER_IMAGE", "python:3.13-slim")
    supervisor = AgentSupervisor(docker_runner=fake, source_commit=SOURCE_COMMIT)
    instance = next(item for item in DEFAULT_AGENT_MANIFEST if item.agent_id == "builder-primary")

    with pytest.raises(AgentSupervisorError, match="pinned"):
        supervisor.execute(instance, _request())
