"""Trusted supervisor for fresh, one-shot Docker specialist workers.

This module runs on the trusted OLA host. It alone may access the Docker
engine; the worker container receives no socket, bind mount, host path, API
credential, database connection, or network route.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
import subprocess
from typing import Any

from .agent_catalog import load_agent_catalog
from .agent_protocol import AgentWorkerRequest, AgentWorkerResult, canonical_json
from .agent_registry import AgentInstanceSpec
from .runtime_provenance import runtime_source_commit


_IMAGE_TAG = re.compile(r"^ola-agent-worker:([0-9a-f]{40})$")
_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_CONTAINER_ID = re.compile(r"^[0-9a-f]{64}$")
_FIXED_ENTRYPOINT = ["python", "-m", "app.agent_worker"]
_SENSITIVE_ENV_NAMES = (
    "OPENAI_API_KEY", "STRIPE", "GITHUB", "DATABASE_URL", "OLA_DATABASE_URL",
    "OLA_API_KEY_PEPPER", "OLLAMA_BASE_URL", "DOCKER_HOST",
)


class AgentSupervisorError(RuntimeError):
    """Docker isolation or worker protocol could not be proven."""


@dataclass(frozen=True)
class AgentExecution:
    worker_result: AgentWorkerResult
    container_id: str
    image_id: str
    image_revision: str
    isolation_report: dict[str, Any]


class AgentSupervisor:
    def __init__(
        self,
        *,
        docker_runner=None,
        docker_binary: str | None = None,
        worker_image_ref: str | None = None,
        source_commit: str | None = None,
    ):
        self._runner = docker_runner or subprocess.run
        self._docker = docker_binary or os.getenv("OLA_DOCKER_BIN", "docker")
        self._image_ref = worker_image_ref or os.getenv("OLA_WORKER_IMAGE")
        self._source_commit = source_commit or runtime_source_commit()

    def _docker_call(self, args, *, input_bytes=None, timeout=20):
        command = [self._docker, *args]
        try:
            completed = self._runner(
                command,
                input=input_bytes,
                capture_output=True,
                timeout=timeout,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            raise AgentSupervisorError("Docker control command timed out") from None
        except OSError:
            raise AgentSupervisorError("Docker Engine is unavailable") from None
        if completed.returncode != 0:
            raise AgentSupervisorError("Docker control command failed")
        return completed.stdout or b""

    @staticmethod
    def _decode_json(raw, field):
        try:
            return json.loads(raw.decode("utf-8"))
        except (AttributeError, UnicodeDecodeError, json.JSONDecodeError):
            raise AgentSupervisorError(f"Docker returned invalid {field} JSON") from None

    def _resolve_image(self):
        if not isinstance(self._source_commit, str) or not re.fullmatch(
            r"[0-9a-f]{40}", self._source_commit
        ):
            raise AgentSupervisorError("trusted source commit is unavailable")
        match = _IMAGE_TAG.fullmatch(self._image_ref or "")
        if not match or match.group(1) != self._source_commit:
            raise AgentSupervisorError("worker image reference must be pinned to the exact source commit")

        inspected = self._decode_json(
            self._docker_call(["image", "inspect", self._image_ref]),
            "worker image",
        )
        if not isinstance(inspected, list) or len(inspected) != 1 or not isinstance(inspected[0], dict):
            raise AgentSupervisorError("worker image inspection was ambiguous")
        image = inspected[0]
        image_id = image.get("Id")
        config = image.get("Config") or {}
        labels = config.get("Labels") or {}
        if not isinstance(image_id, str) or not _IMAGE_ID.fullmatch(image_id):
            raise AgentSupervisorError("worker image has no immutable image ID")
        if labels.get("org.opencontainers.image.revision") != self._source_commit:
            raise AgentSupervisorError("worker image source revision does not match runtime")
        if image.get("Os") != "linux" or image.get("Architecture") != "amd64":
            raise AgentSupervisorError("worker image platform is not the pinned linux/amd64 target")
        if config.get("Entrypoint") != _FIXED_ENTRYPOINT or config.get("Cmd") not in (None, []):
            raise AgentSupervisorError("worker image entrypoint is not the fixed worker entrypoint")
        if config.get("User") != "65532:65532":
            raise AgentSupervisorError("worker image does not run as the unprivileged worker user")
        return image_id

    def _resource_limits(self, instance):
        catalog = load_agent_catalog()
        definition = catalog.get(instance.role)
        if definition is None or instance.execution_profile not in definition.execution_profiles:
            raise AgentSupervisorError("worker instance or profile is not registered")
        limits = definition.resource_limits
        if limits.measurement_status != "provisional_not_zbook_measured":
            raise AgentSupervisorError("resource policy must retain its explicit measurement state")
        return limits

    def _validate_provider(self, request, definition):
        if request.model_provider == "local":
            if (
                os.getenv("OLA_RUNTIME_PROFILE") == "zbook"
                or os.getenv("OLA_LLM_MODE", "deterministic") != "deterministic"
                or request.invocation_type != "local_deterministic_model"
            ):
                raise AgentSupervisorError("deterministic provider is test-only and cannot run on ZBook")
            return
        if request.model_provider not in definition.provider_policy.allowed_providers:
            raise AgentSupervisorError("provider is not allowed by the specialist policy")
        if os.getenv("OLA_RUNTIME_PROFILE") == "zbook":
            if request.model_provider != "ollama" or request.invocation_type != "real_llm":
                raise AgentSupervisorError("ZBook execution requires a real Ollama response")
            if not request.model_response_id:
                raise AgentSupervisorError("ZBook execution requires an Ollama response identity")

    def _create_command(self, image_id, limits):
        cpu = f"{limits.cpu_millis / 1000:.3f}"
        memory = f"{limits.memory_mb}m"
        return [
            "create",
            "--interactive",
            "--network", "none",
            "--read-only",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges:true",
            "--pids-limit", str(limits.max_pids),
            "--cpus", cpu,
            "--memory", memory,
            "--memory-swap", memory,
            "--user", "65532:65532",
            "--workdir", "/app",
            "--env", "PYTHONDONTWRITEBYTECODE=1",
            "--env", "PYTHONNOUSERSITE=1",
            "--env", "PYTHONUNBUFFERED=1",
            image_id,
        ]

    def _inspect_container(self, container_id):
        inspected = self._decode_json(
            self._docker_call(["inspect", container_id]),
            "worker container",
        )
        if not isinstance(inspected, list) or len(inspected) != 1 or not isinstance(inspected[0], dict):
            raise AgentSupervisorError("worker container inspection was ambiguous")
        return inspected[0]

    def _validate_container_config(self, inspected, *, image_id, limits):
        config = inspected.get("Config") or {}
        host = inspected.get("HostConfig") or {}
        mounts = inspected.get("Mounts") or []
        networks = (inspected.get("NetworkSettings") or {}).get("Networks") or {}
        expected_memory = limits.memory_mb * 1024 * 1024
        expected_nano_cpus = limits.cpu_millis * 1_000_000
        env = config.get("Env") or []
        env_names = {item.split("=", 1)[0] for item in env if isinstance(item, str)}

        checks = {
            "image_id": inspected.get("Image") == image_id,
            "fixed_entrypoint": config.get("Entrypoint") == _FIXED_ENTRYPOINT,
            "no_command_override": config.get("Cmd") in (None, []),
            "unprivileged_user": config.get("User") == "65532:65532",
            "network_none": host.get("NetworkMode") == "none" and set(networks).issubset({"none"}),
            "readonly_rootfs": host.get("ReadonlyRootfs") is True,
            "capabilities_dropped": "ALL" in (host.get("CapDrop") or []),
            "no_new_privileges": "no-new-privileges:true" in (host.get("SecurityOpt") or []),
            "pids_bounded": host.get("PidsLimit") == limits.max_pids,
            "memory_bounded": host.get("Memory") == expected_memory and host.get("MemorySwap") == expected_memory,
            "cpu_bounded": host.get("NanoCpus") == expected_nano_cpus,
            "no_mounts": not mounts and not host.get("Binds") and not host.get("Mounts"),
            "not_privileged": host.get("Privileged") is not True,
            "no_sensitive_environment": not any(
                name in env_names or any(name in item for item in env_names)
                for name in _SENSITIVE_ENV_NAMES
            ),
        }
        failed = [name for name, passed in checks.items() if not passed]
        if failed:
            raise AgentSupervisorError("worker Docker isolation inspection failed: " + ",".join(failed))
        return {
            "network_mode": "none",
            "readonly_rootfs": True,
            "cap_drop": ["ALL"],
            "no_new_privileges": True,
            "pids_limit": limits.max_pids,
            "memory_limit_bytes": expected_memory,
            "cpu_limit_nano": expected_nano_cpus,
            "user": "65532:65532",
            "mounts": [],
            "docker_socket_mounted": False,
            "host_home_mounted": False,
            "privileged": False,
            "fixed_entrypoint": list(_FIXED_ENTRYPOINT),
            "image_id": inspected.get("Image"),
            "verified_checks": sorted(checks),
        }

    def execute(self, instance: AgentInstanceSpec, request: AgentWorkerRequest) -> AgentExecution:
        if request.agent_id != instance.agent_id or request.specialist_role != instance.role:
            raise AgentSupervisorError("worker request identity does not match manifest instance")
        if request.profile != instance.execution_profile:
            raise AgentSupervisorError("worker profile does not match manifest instance")
        if request.agent_instance_id == request.agent_id:
            raise AgentSupervisorError("run-scoped worker instance ID must be distinct from stable agent ID")
        catalog = load_agent_catalog()
        definition = catalog.get(instance.role)
        if definition is None:
            raise AgentSupervisorError("specialist role is not registered")
        self._validate_provider(request, definition)
        limits = self._resource_limits(instance)
        image_id = self._resolve_image()

        create_output = self._docker_call(self._create_command(image_id, limits), timeout=30)
        try:
            container_id = create_output.decode("ascii").strip()
        except UnicodeDecodeError:
            raise AgentSupervisorError("Docker returned an invalid container ID") from None
        if not _CONTAINER_ID.fullmatch(container_id):
            raise AgentSupervisorError("Docker did not return a valid worker container ID")

        try:
            before = self._inspect_container(container_id)
            isolation_report = self._validate_container_config(before, image_id=image_id, limits=limits)
            response_bytes = self._docker_call(
                ["start", "--attach", "--interactive", container_id],
                input_bytes=request.to_json(),
                timeout=limits.timeout_seconds,
            )
            after = self._inspect_container(container_id)
            self._validate_container_config(after, image_id=image_id, limits=limits)
            state = after.get("State") or {}
            if state.get("Status") != "exited" or state.get("ExitCode") != 0:
                raise AgentSupervisorError("worker container did not exit successfully")

            worker_result = AgentWorkerResult.from_json(response_bytes)
            expected = {
                "request_id": request.request_id,
                "run_id": request.run_id,
                "agent_id": request.agent_id,
                "agent_instance_id": request.agent_instance_id,
                "specialist_role": request.specialist_role,
                "profile": request.profile,
                "status": "COMPLETED",
            }
            if any(getattr(worker_result, key) != value for key, value in expected.items()):
                raise AgentSupervisorError("worker response identity does not match request")
            isolation_report["container_state"] = "exited"
            isolation_report["worker_pid"] = worker_result.worker_pid
            return AgentExecution(
                worker_result=worker_result,
                container_id=container_id,
                image_id=image_id,
                image_revision=self._source_commit,
                isolation_report=isolation_report,
            )
        except subprocess.TimeoutExpired:
            try:
                self._docker_call(["kill", "--signal", "KILL", container_id], timeout=5)
            except AgentSupervisorError:
                pass
            raise AgentSupervisorError("worker container execution timeout") from None
        finally:
            try:
                self._docker_call(["rm", "--force", container_id], timeout=10)
            except AgentSupervisorError:
                # Never mask the primary result/failure. Cleanup failure is
                # separately observable in the supervisor's host logs.
                pass


def run_agent_worker(
    agent_instance_id: str,
    profile: str,
    request: AgentWorkerRequest,
) -> AgentExecution:
    """Resolve the explicit manifest instance and execute it in a fresh container."""
    from .agent_registry import DEFAULT_AGENT_MANIFEST

    instance = next(
        (
            item for item in DEFAULT_AGENT_MANIFEST
            if item.agent_id == agent_instance_id and item.execution_profile == profile
        ),
        None,
    )
    if instance is None:
        raise AgentSupervisorError("agent instance/profile is not present in the trusted manifest")
    return AgentSupervisor().execute(instance, request)
