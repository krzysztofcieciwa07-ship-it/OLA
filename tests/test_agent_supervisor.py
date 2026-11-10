import importlib
import importlib.util
import json

import pytest
from pathlib import Path
from subprocess import CompletedProcess

import pytest


IMAGE_DIGEST = "sha256:" + "b" * 64
CONTAINER_ID = "c" * 64


@pytest.fixture(autouse=True)
def _trusted_source_commit(monkeypatch):
    monkeypatch.setenv("OLA_SOURCE_COMMIT", "a" * 40)
    monkeypatch.delenv("OLA_AGENT_MANIFEST_PATH", raising=False)


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
    request = AgentWorkerRequest.model_validate_json(json.dumps({
        "schema_version": 1,
        "run_id": "00000000-0000-4000-8000-000000000011",
        "agent_id": agent.agent_id,
        "agent_instance_id": "00000000-0000-4000-8000-000000000012",
        "specialist_role": agent.specialist_role,
        "execution_profile": agent.execution_profile,
        "capability": "tool.safe_expression",
        "allowed_capabilities": ["tool.safe_expression"],
        "task": "Calculate 17 times 23.",
        "capability_input": {"expression": "17 * 23"},
        "model_output": {"output": {"status": "needs_tool", "tool_name": "tool.safe_expression", "tool_arguments_json": '{"expression":"17 * 23"}'}},
        "source_commit": "a" * 40,
    }))
    return agent, request


def _docker_inspect():
    return {
        "Id": CONTAINER_ID,
        "Image": IMAGE_DIGEST,
        "State": {"Status": "exited", "ExitCode": 0},
        "Config": {"User": "65532:65532", "Entrypoint": ["python", "-m", "app.agent_worker"], "Cmd": None, "Volumes": {}, "Env": [], "Labels": {"org.opencontainers.image.revision": "a" * 40}},
        "HostConfig": {
            "NetworkMode": "none",
            "ReadonlyRootfs": True,
            "PidsLimit": 16,
            "Memory": 512 * 1024 * 1024,
            "MemorySwap": 512 * 1024 * 1024,
            "Tmpfs": {"/tmp": "rw,noexec,nosuid,nodev,size=16m"},
            "NanoCpus": 1_000_000_000,
            "CapDrop": ["ALL"],
            "CapAdd": [],
            "SecurityOpt": ["no-new-privileges:true"],
            "Binds": [],
            "Mounts": [],
            "Devices": [],
            "DeviceRequests": [],
            "PortBindings": {},
            "PidMode": "",
            "IpcMode": "private",
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
            result = run_agent_worker(request).model_copy(update={"worker_pid": 1})
            return CompletedProcess(args, 0, stdout=result.model_dump_json(), stderr="")
        if args[1] == "inspect":
            return CompletedProcess(args, 0, stdout=json.dumps(_docker_inspect()), stderr="")
        if args[1:3] == ["rm", "-f"]:
            return CompletedProcess(args, 0, stdout="", stderr="")
        raise AssertionError(f"unexpected docker command: {args}")

    supervisor = supervisor_module.AgentSupervisor(
        registry=[agent],
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
    assert "--pids-limit" in run_args and run_args[run_args.index("--pids-limit") + 1] == "16"
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
            registry=[agent],
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
        registry=[agent],
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
        registry=[agent],
        image_digest=IMAGE_DIGEST,
        runner=fake_runner,
        temp_dir=str(tmp_path),
    )
    result = supervisor.execute(agent, request)

    assert result.status == "FAILED"
    assert result.container_id == CONTAINER_ID
    assert any(args[1:3] == ["rm", "-f"] for args in calls)


def test_worker_image_requires_digest_pinned_base_and_fixed_entrypoint():
    source = (Path(__file__).resolve().parents[1] / "workstation" / "worker.Dockerfile").read_text()
    assert "ARG PYTHON_BASE_IMAGE" in source
    assert "FROM ${PYTHON_BASE_IMAGE}" in source
    assert "@sha256:" in source
    assert "ENTRYPOINT [\"python\", \"-m\", \"app.agent_worker\"]" in source
    assert "USER 65532:65532" in source
    assert "ARG OLA_SOURCE_COMMIT" in source
    assert "org.opencontainers.image.revision" in source


def _runner_for_inspect(agent, request, inspect_override=None, worker_pid=1, result_override=None):
    from app.agent_worker import run_agent_worker

    calls = []

    def runner(args, **kwargs):
        calls.append(args)
        if args[1:3] == ["image", "inspect"]:
            return CompletedProcess(args, 0, stdout=IMAGE_DIGEST, stderr="")
        if args[1] == "run":
            cidfile = args[args.index("--cidfile") + 1]
            Path(cidfile).write_text(CONTAINER_ID, encoding="ascii")
            result = result_override or run_agent_worker(request).model_copy(update={"worker_pid": worker_pid})
            return CompletedProcess(args, 0, stdout=result.model_dump_json(), stderr="")
        if args[1] == "inspect":
            return CompletedProcess(args, 0, stdout=json.dumps(inspect_override or _docker_inspect()), stderr="")
        if args[1:3] == ["rm", "-f"]:
            return CompletedProcess(args, 0, stdout="", stderr="")
        raise AssertionError(f"unexpected docker command: {args}")

    return runner, calls


def test_supervisor_rejects_container_with_wrong_source_revision_label(tmp_path):
    supervisor_module = _supervisor_module()
    agent, request = _request_and_agent()
    inspect = _docker_inspect()
    inspect["Config"]["Labels"]["org.opencontainers.image.revision"] = "f" * 40
    runner, _ = _runner_for_inspect(agent, request, inspect_override=inspect)
    supervisor = supervisor_module.AgentSupervisor(registry=[agent], image_digest=IMAGE_DIGEST, runner=runner, temp_dir=str(tmp_path))

    result = supervisor.execute(agent, request)

    assert result.status == "BLOCKED"
    assert result.reason == "worker_source_revision_mismatch"


def test_supervisor_rejects_worker_not_running_as_container_pid_one(tmp_path):
    supervisor_module = _supervisor_module()
    agent, request = _request_and_agent()
    runner, _ = _runner_for_inspect(agent, request, worker_pid=2)
    supervisor = supervisor_module.AgentSupervisor(registry=[agent], image_digest=IMAGE_DIGEST, runner=runner, temp_dir=str(tmp_path))

    result = supervisor.execute(agent, request)

    assert result.status == "BLOCKED"
    assert result.reason == "worker_process_identity_invalid"


def test_supervisor_rejects_added_linux_capabilities(tmp_path):
    supervisor_module = _supervisor_module()
    agent, request = _request_and_agent()
    inspect = _docker_inspect()
    inspect["HostConfig"]["CapAdd"] = ["NET_ADMIN"]
    runner, _ = _runner_for_inspect(agent, request, inspect_override=inspect)
    supervisor = supervisor_module.AgentSupervisor(registry=[agent], image_digest=IMAGE_DIGEST, runner=runner, temp_dir=str(tmp_path))

    result = supervisor.execute(agent, request)

    assert result.status == "BLOCKED"
    assert result.reason == "worker_capabilities_not_dropped"


def test_supervisor_rejects_manifest_capability_escalation_before_docker(tmp_path):
    from dataclasses import replace

    supervisor_module = _supervisor_module()
    agent, request = _request_and_agent()
    escalated_agent = replace(agent, capabilities=("production.deploy",))
    escalated_request = request.model_copy(update={
        "capability": "production.deploy",
        "allowed_capabilities": ("production.deploy",),
    })
    runner, calls = _runner_for_inspect(escalated_agent, escalated_request)
    supervisor = supervisor_module.AgentSupervisor(registry=[agent], image_digest=IMAGE_DIGEST, runner=runner, temp_dir=str(tmp_path))

    result = supervisor.execute(escalated_agent, escalated_request)

    assert result.status == "BLOCKED"
    assert calls == []


def test_supervisor_recomputes_worker_digests_instead_of_trusting_them(tmp_path):
    supervisor_module = _supervisor_module()
    agent, request = _request_and_agent()
    from app.agent_worker import run_agent_worker
    tampered = run_agent_worker(request).model_copy(update={"worker_pid": 1, "output_digest": "f" * 64})
    runner, _ = _runner_for_inspect(agent, request, result_override=tampered)
    supervisor = supervisor_module.AgentSupervisor(registry=[agent], image_digest=IMAGE_DIGEST, runner=runner, temp_dir=str(tmp_path))

    result = supervisor.execute(agent, request)

    assert result.status == "BLOCKED"
    assert result.reason == "worker_result_digest_mismatch"


def test_supervisor_blocks_when_trusted_source_commit_is_missing(monkeypatch, tmp_path):
    supervisor_module = _supervisor_module()
    agent, request = _request_and_agent()
    calls = []
    monkeypatch.delenv("OLA_SOURCE_COMMIT", raising=False)
    supervisor = supervisor_module.AgentSupervisor(
        registry=[agent],
        image_digest=IMAGE_DIGEST,
        runner=lambda *args, **kwargs: calls.append(args),
        temp_dir=str(tmp_path),
    )

    result = supervisor.execute(agent, request)

    assert result.status == "BLOCKED"
    assert result.reason == "source_commit_not_trusted"
    assert calls == []


def test_supervisor_blocks_request_from_a_different_source_commit(tmp_path):
    supervisor_module = _supervisor_module()
    agent, request = _request_and_agent()
    altered = request.model_copy(update={"source_commit": "f" * 40})
    runner, calls = _runner_for_inspect(agent, altered)
    supervisor = supervisor_module.AgentSupervisor(
        registry=[agent],
        image_digest=IMAGE_DIGEST,
        runner=runner,
        temp_dir=str(tmp_path),
    )

    result = supervisor.execute(agent, altered)

    assert result.status == "BLOCKED"
    assert result.reason == "source_commit_not_trusted"
    assert calls == []


def test_supervisor_blocks_malformed_worker_response_and_cleans_container(tmp_path):
    supervisor_module = _supervisor_module()
    agent, request = _request_and_agent()
    calls = []

    def runner(args, **kwargs):
        calls.append(args)
        if args[1:3] == ["image", "inspect"]:
            return CompletedProcess(args, 0, stdout=IMAGE_DIGEST, stderr="")
        if args[1] == "run":
            Path(args[args.index("--cidfile") + 1]).write_text(CONTAINER_ID, encoding="ascii")
            return CompletedProcess(args, 0, stdout="not-json", stderr="")
        if args[1] == "inspect":
            return CompletedProcess(args, 0, stdout=json.dumps(_docker_inspect()), stderr="")
        if args[1:3] == ["rm", "-f"]:
            return CompletedProcess(args, 0, stdout="", stderr="")
        raise AssertionError(f"unexpected docker command: {args}")

    supervisor = supervisor_module.AgentSupervisor(registry=[agent], image_digest=IMAGE_DIGEST, runner=runner, temp_dir=str(tmp_path))
    result = supervisor.execute(agent, request)

    assert result.status == "BLOCKED"
    assert result.reason == "worker_response_invalid"
    assert any(args[1:3] == ["rm", "-f"] for args in calls)


def test_supervisor_blocks_nonzero_worker_exit(tmp_path):
    supervisor_module = _supervisor_module()
    agent, request = _request_and_agent()
    calls = []

    def runner(args, **kwargs):
        calls.append(args)
        if args[1:3] == ["image", "inspect"]:
            return CompletedProcess(args, 0, stdout=IMAGE_DIGEST, stderr="")
        if args[1] == "run":
            Path(args[args.index("--cidfile") + 1]).write_text(CONTAINER_ID, encoding="ascii")
            return CompletedProcess(args, 1, stdout="", stderr="worker crash")
        if args[1] == "inspect":
            inspect = _docker_inspect()
            inspect["State"] = {"Status": "exited", "ExitCode": 1}
            return CompletedProcess(args, 0, stdout=json.dumps(inspect), stderr="")
        if args[1:3] == ["rm", "-f"]:
            return CompletedProcess(args, 0, stdout="", stderr="")
        raise AssertionError(f"unexpected docker command: {args}")

    supervisor = supervisor_module.AgentSupervisor(registry=[agent], image_digest=IMAGE_DIGEST, runner=runner, temp_dir=str(tmp_path))
    result = supervisor.execute(agent, request)

    assert result.status == "BLOCKED"
    assert result.reason == "worker_exit_not_clean"
    assert any(args[1:3] == ["rm", "-f"] for args in calls)


def test_supervisor_blocks_success_if_container_cleanup_fails(tmp_path):
    supervisor_module = _supervisor_module()
    agent, request = _request_and_agent()
    from app.agent_worker import run_agent_worker

    def runner(args, **kwargs):
        if args[1:3] == ["image", "inspect"]:
            return CompletedProcess(args, 0, stdout=IMAGE_DIGEST, stderr="")
        if args[1] == "run":
            Path(args[args.index("--cidfile") + 1]).write_text(CONTAINER_ID, encoding="ascii")
            result = run_agent_worker(request).model_copy(update={"worker_pid": 1})
            return CompletedProcess(args, 0, stdout=result.model_dump_json(), stderr="")
        if args[1] == "inspect":
            return CompletedProcess(args, 0, stdout=json.dumps(_docker_inspect()), stderr="")
        if args[1:3] == ["rm", "-f"]:
            return CompletedProcess(args, 1, stdout="", stderr="cleanup failed")
        raise AssertionError(f"unexpected docker command: {args}")

    supervisor = supervisor_module.AgentSupervisor(registry=[agent], image_digest=IMAGE_DIGEST, runner=runner, temp_dir=str(tmp_path))
    result = supervisor.execute(agent, request)

    assert result.status == "BLOCKED"
    assert result.reason == "worker_container_cleanup_failed"


def test_supervisor_blocks_agents_not_in_the_explicit_manifest_before_docker(tmp_path):
    supervisor_module = _supervisor_module()
    agent, request = _request_and_agent()
    calls = []

    def runner(args, **kwargs):
        calls.append(args)
        if args[1:3] == ["image", "inspect"]:
            return CompletedProcess(args, 0, stdout=IMAGE_DIGEST, stderr="")
        return CompletedProcess(args, 0, stdout="", stderr="")

    supervisor = supervisor_module.AgentSupervisor(
        image_digest=IMAGE_DIGEST,
        expected_source_commit="a" * 40,
        runner=runner,
        temp_dir=str(tmp_path),
    )
    result = supervisor.execute(agent, request)

    assert result.status == "BLOCKED"
    assert result.reason == "agent_not_registered"
    assert calls == []
