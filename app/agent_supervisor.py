import json
import os
import re
import subprocess
import tempfile
import time
import uuid
from collections.abc import Sequence
from types import MappingProxyType
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Any

from .agent_protocol import (
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    AgentWorkerRequest,
    AgentWorkerResult,
    digest_json,
)
from .provenance.crypto import verify_worker_signature
from .agent_registry import (
    AgentInstanceSpec,
    DEFAULT_AGENT_MANIFEST,
    build_agent_registry,
    load_agent_manifest,
)


_IMAGE_DIGEST_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
_CONTAINER_ID_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_SECRET_ENV_MARKERS = ("key", "secret", "token", "password", "credential")
_FIXED_ENTRYPOINT = ["python", "-m", "app.agent_worker"]


@dataclass(frozen=True, slots=True)
class AgentExecution:
    status: str
    container_id: str | None = None
    image_digest: str | None = None
    worker_result: AgentWorkerResult | None = None
    reason: str | None = None
    exit_code: int | None = None
    supervisor_started_at: float | None = None
    supervisor_finished_at: float | None = None


class AgentSupervisor:
    """Launch one-shot, network-isolated Docker workers with a fixed image and entrypoint."""

    def __init__(
        self,
        *,
        registry: Sequence[AgentInstanceSpec] | None = None,
        image_digest: str | None = None,
        expected_source_commit: str | None = None,
        docker_binary: str = "docker",
        timeout_seconds: int = 120,
        memory_mb: int = 512,
        cpu_millis: int = 1000,
        pids_limit: int = 32,
        runner: Callable[..., Any] | None = None,
        temp_dir: str | None = None,
        runtime_preflight: Callable[[], bool] | None = None,
    ):
        if registry is None:
            manifest_path = os.getenv("OLA_AGENT_MANIFEST_PATH")
            registry = load_agent_manifest(manifest_path) if manifest_path else DEFAULT_AGENT_MANIFEST
        validated_registry = build_agent_registry(registry)
        self.registry = MappingProxyType({agent.agent_id: agent for agent in validated_registry})
        self.image_digest = (
            image_digest if image_digest is not None
            else os.getenv("OLA_AGENT_WORKER_IMAGE_DIGEST")
        )
        self.expected_source_commit = (
            expected_source_commit if expected_source_commit is not None
            else os.getenv("OLA_SOURCE_COMMIT")
        )
        self.docker_binary = docker_binary
        self.timeout_seconds = timeout_seconds
        self.memory_mb = memory_mb
        self.cpu_millis = cpu_millis
        self.pids_limit = pids_limit
        self.runner = runner or subprocess.run
        self.temp_dir = temp_dir
        self.runtime_preflight = runtime_preflight
        if any(type(value) is not int or value <= 0 for value in (
            timeout_seconds, memory_mb, cpu_millis, pids_limit
        )):
            raise ValueError("supervisor resource limits must be positive integers")

    @staticmethod
    def _blocked(reason: str, image_digest: str | None = None,
                 container_id: str | None = None) -> AgentExecution:
        return AgentExecution(
            status="BLOCKED",
            container_id=container_id,
            image_digest=image_digest,
            reason=reason,
        )

    def _call(self, args: list[str], **kwargs):
        return self.runner(args, **kwargs)

    def _verify_rootless_runtime(self) -> bool:
        """Require rootless Docker or Podman; a rootful daemon is host-root authority."""
        if self.runtime_preflight is not None:
            try:
                return self.runtime_preflight() is True
            except Exception:
                return False

        runtime_name = Path(self.docker_binary).name.lower()
        try:
            if "podman" in runtime_name:
                result = self._call(
                    [self.docker_binary, "info", "--format", "json"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                if result.returncode != 0:
                    return False
                info = json.loads(result.stdout)
                host = info.get("host") or {}
                security = host.get("security") or {}
                return security.get("rootless") is True

            result = self._call(
                [self.docker_binary, "info", "--format", "{{json .SecurityOptions}}"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if result.returncode != 0:
                return False
            options = json.loads(result.stdout)
            return (
                isinstance(options, list)
                and any("rootless" in str(option).lower() for option in options)
            )
        except (OSError, subprocess.SubprocessError, ValueError, TypeError):
            return False

    def _inspect_image(self) -> bool:
        if not isinstance(self.image_digest, str) or _IMAGE_DIGEST_PATTERN.fullmatch(self.image_digest) is None:
            return False
        try:
            result = self._call(
                [self.docker_binary, "image", "inspect", "--format", "{{.Id}}", self.image_digest],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except Exception:
            return False
        return result.returncode == 0 and result.stdout.strip() == self.image_digest

    @staticmethod
    def _verify_container(
        inspect: dict[str, Any],
        *,
        container_id: str,
        image_digest: str,
        memory_mb: int,
        cpu_millis: int,
        pids_limit: int,
        source_commit: str,
    ) -> str | None:
        if inspect.get("Id") != container_id:
            return "container_identity_mismatch"
        if inspect.get("Image") != image_digest:
            return "worker_image_mismatch"

        state = inspect.get("State") or {}
        if state.get("Status") != "exited" or state.get("ExitCode") != 0:
            return "worker_exit_not_clean"

        config = inspect.get("Config") or {}
        host = inspect.get("HostConfig") or {}
        if config.get("Entrypoint") != _FIXED_ENTRYPOINT or config.get("Cmd") not in (None, []):
            return "worker_entrypoint_not_fixed"
        if config.get("User") != "65532:65532":
            return "worker_user_not_unprivileged"
        if config.get("Volumes"):
            return "worker_declared_volumes_not_allowed"
        labels = config.get("Labels") or {}
        if labels.get("org.opencontainers.image.revision") != source_commit:
            return "worker_source_revision_mismatch"
        for env_item in config.get("Env") or []:
            env_name = str(env_item).split("=", 1)[0].lower()
            if any(marker in env_name for marker in _SECRET_ENV_MARKERS):
                return "worker_secret_environment_not_allowed"

        if host.get("NetworkMode") != "none":
            return "worker_network_not_isolated"
        if host.get("ReadonlyRootfs") is not True:
            return "worker_rootfs_not_read_only"
        if host.get("Privileged") is not False:
            return "worker_privileged_mode_not_allowed"
        if "ALL" not in (host.get("CapDrop") or []) or host.get("CapAdd"):
            return "worker_capabilities_not_dropped"
        if "no-new-privileges:true" not in (host.get("SecurityOpt") or []):
            return "worker_no_new_privileges_missing"
        if host.get("PidsLimit") != pids_limit:
            return "worker_pid_limit_mismatch"
        if host.get("Memory") != memory_mb * 1024 * 1024:
            return "worker_memory_limit_mismatch"
        if host.get("NanoCpus") != cpu_millis * 1_000_000:
            return "worker_cpu_limit_mismatch"
        if host.get("MemorySwap") not in (None, memory_mb * 1024 * 1024):
            return "worker_swap_limit_mismatch"

        tmpfs = host.get("Tmpfs") or {}
        tmpfs_options = str(tmpfs.get("/tmp", ""))
        if not all(flag in tmpfs_options for flag in ("noexec", "nosuid", "nodev")):
            return "worker_tmpfs_not_hardened"

        if host.get("Binds") or host.get("Mounts"):
            return "worker_host_mounts_not_allowed"
        if host.get("Devices") or host.get("DeviceRequests"):
            return "worker_device_access_not_allowed"
        if host.get("PortBindings"):
            return "worker_port_bindings_not_allowed"
        if host.get("PidMode") == "host" or host.get("IpcMode") == "host":
            return "worker_host_namespace_not_allowed"

        mounts = inspect.get("Mounts") or []
        if any(
            mount.get("Type") != "tmpfs" or mount.get("Destination") != "/tmp"
            for mount in mounts
        ):
            return "worker_external_mount_not_allowed"
        return None

    def execute(self, instance: AgentInstanceSpec, request: AgentWorkerRequest) -> AgentExecution:
        try:
            instance = build_agent_registry([instance])[0]
            request = AgentWorkerRequest.model_validate_json(request.model_dump_json())
        except Exception:
            return self._blocked("invalid_worker_contract", self.image_digest)
        registered_instance = self.registry.get(instance.agent_id)
        if registered_instance is None or registered_instance != instance:
            return self._blocked("agent_not_registered", self.image_digest)
        if (
            not isinstance(self.expected_source_commit, str)
            or re.fullmatch(r"[a-f0-9]{40}", self.expected_source_commit) is None
            or request.source_commit != self.expected_source_commit
        ):
            return self._blocked("source_commit_not_trusted", self.image_digest)
        if instance.availability_status != "enabled":
            return self._blocked("agent_instance_disabled", self.image_digest)
        if (
            request.agent_id != instance.agent_id
            or request.specialist_role != instance.specialist_role
            or request.execution_profile != instance.execution_profile
            or not set(request.allowed_capabilities).issubset(instance.capabilities)
            or request.capability not in instance.capabilities
        ):
            return self._blocked("worker_request_identity_or_policy_mismatch", self.image_digest)

        request_bytes = len(request.model_dump_json().encode("utf-8"))
        if request_bytes > min(MAX_REQUEST_BYTES, instance.resource_limits.max_input_bytes):
            return self._blocked("worker_request_too_large", self.image_digest)
        if not self._verify_rootless_runtime():
            return self._blocked("container_runtime_not_rootless", self.image_digest)
        if not self._inspect_image():
            return self._blocked("worker_image_digest_not_locally_verified", self.image_digest)

        memory_mb = min(self.memory_mb, instance.resource_limits.memory_mb)
        cpu_millis = min(self.cpu_millis, instance.resource_limits.cpu_millis)
        pids_limit = min(self.pids_limit, instance.resource_limits.max_processes)
        timeout_seconds = min(self.timeout_seconds, instance.resource_limits.timeout_seconds)

        try:
            cid_fd, cidfile = tempfile.mkstemp(
                prefix="ola-worker-", suffix=".cid", dir=self.temp_dir
            )
            os.close(cid_fd)
            os.unlink(cidfile)
        except Exception:
            return self._blocked("worker_cidfile_unavailable", self.image_digest)
        container_name = f"ola-worker-{uuid.uuid4().hex}"
        run_attempted = False
        supervisor_started_at = None
        supervisor_finished_at = None
        container_id = None
        execution = self._blocked("worker_not_started", self.image_digest)
        cleanup_ok = True

        command = [
            self.docker_binary, "run", "-i",
            "--name", container_name,
            "--cidfile", cidfile,
            "--pull=never",
            "--network", "none",
            "--read-only",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges:true",
            "--pids-limit", str(pids_limit),
            "--memory", f"{memory_mb}m",
            "--memory-swap", f"{memory_mb}m",
            "--cpus", f"{cpu_millis / 1000:g}",
            "--user", "65532:65532",
            "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=16m",
            self.image_digest,
        ]

        try:
            run_attempted = True
            supervisor_started_at = time.time()
            try:
                worker_process = self._call(
                    command,
                    input=request.model_dump_json(),
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                    check=False,
                )
            except (subprocess.TimeoutExpired, TimeoutError):
                execution = AgentExecution(
                    status="FAILED",
                    image_digest=self.image_digest,
                    reason="worker_timeout",
                )
                worker_process = None
            except Exception:
                execution = self._blocked("worker_launch_failed", self.image_digest)
                worker_process = None

            try:
                candidate_id = Path(cidfile).read_text(encoding="ascii").strip()
                if _CONTAINER_ID_PATTERN.fullmatch(candidate_id):
                    container_id = candidate_id
            except OSError:
                container_id = None

            if worker_process is None:
                if container_id:
                    execution = AgentExecution(
                        status="FAILED",
                        container_id=container_id,
                        image_digest=self.image_digest,
                        reason="worker_timeout_or_launch_failure",
                    )
            elif container_id is None:
                execution = self._blocked("worker_container_identity_missing", self.image_digest)
            else:
                try:
                    inspect_process = self._call(
                        [
                            self.docker_binary, "inspect", "--type", "container",
                            "--format", "{{json .}}", container_id,
                        ],
                        capture_output=True,
                        text=True,
                        timeout=10,
                        check=False,
                    )
                except Exception:
                    inspect_process = None

                if inspect_process is None or inspect_process.returncode != 0:
                    execution = self._blocked(
                        "worker_container_inspection_failed", self.image_digest, container_id
                    )
                else:
                    try:
                        inspect = json.loads(inspect_process.stdout)
                    except (TypeError, ValueError):
                        inspect = None
                    if not isinstance(inspect, dict):
                        execution = self._blocked(
                            "worker_container_inspection_invalid", self.image_digest, container_id
                        )
                    else:
                        policy_failure = self._verify_container(
                            inspect,
                            container_id=container_id,
                            image_digest=self.image_digest,
                            memory_mb=memory_mb,
                            cpu_millis=cpu_millis,
                            pids_limit=pids_limit,
                            source_commit=request.source_commit,
                        )
                        if policy_failure:
                            execution = self._blocked(
                                policy_failure, self.image_digest, container_id
                            )
                        elif worker_process.returncode != 0:
                            execution = AgentExecution(
                                status="FAILED",
                                container_id=container_id,
                                image_digest=self.image_digest,
                                reason="worker_nonzero_exit",
                            )
                        else:
                            try:
                                worker_result = AgentWorkerResult.model_validate_json(
                                    worker_process.stdout
                                )
                            except Exception:
                                worker_result = None
                            if worker_result is None:
                                execution = self._blocked(
                                    "worker_response_invalid", self.image_digest, container_id
                                )
                            elif (
                                worker_result.status != "COMPLETED"
                                or worker_result.run_id != request.run_id
                                or worker_result.agent_id != request.agent_id
                                or worker_result.agent_instance_id != request.agent_instance_id
                                or worker_result.specialist_role != request.specialist_role
                                or worker_result.execution_profile != request.execution_profile
                                or worker_result.capability != request.capability
                                or worker_result.source_commit != request.source_commit
                            ):
                                execution = self._blocked(
                                    "worker_response_identity_or_status_mismatch",
                                    self.image_digest,
                                    container_id,
                                )
                            elif worker_result.worker_pid != 1:
                                execution = self._blocked(
                                    "worker_process_identity_invalid", self.image_digest, container_id
                                )
                            elif (
                                worker_result.request_digest != digest_json(request.model_dump(mode="json"))
                                or worker_result.input_digest != digest_json({
                                    "task": request.task,
                                    "capability_input": request.capability_input,
                                })
                                or worker_result.capability_input_digest != digest_json(request.capability_input)
                                or worker_result.model_output_digest != digest_json(request.model_output)
                                or not verify_worker_signature(
                                    worker_result,
                                    expected_request_digest=digest_json(request.model_dump(mode="json")),
                                    expected_model_output_digest=digest_json(request.model_output),
                                    expected_capability_input_digest=digest_json(request.capability_input),
                                )
                            ):
                                execution = self._blocked(
                                    "worker_result_digest_mismatch", self.image_digest, container_id
                                )
                            elif len(worker_process.stdout.encode("utf-8")) > min(
                                MAX_RESPONSE_BYTES, instance.resource_limits.max_output_bytes
                            ):
                                execution = self._blocked(
                                    "worker_response_too_large", self.image_digest, container_id
                                )
                            else:
                                execution = AgentExecution(
                                    status="COMPLETED",
                                    container_id=container_id,
                                    image_digest=self.image_digest,
                                    worker_result=worker_result,
                                    exit_code=worker_process.returncode,
                                )
        finally:
            if run_attempted:
                cleanup_target = container_id or container_name
                try:
                    cleanup = self._call(
                        [self.docker_binary, "rm", "-f", cleanup_target],
                        capture_output=True,
                        text=True,
                        timeout=10,
                        check=False,
                    )
                    cleanup_ok = cleanup.returncode == 0
                except Exception:
                    cleanup_ok = False
            try:
                Path(cidfile).unlink(missing_ok=True)
            except OSError:
                cleanup_ok = False

        supervisor_finished_at = time.time()
        if not cleanup_ok:
            blocked = self._blocked("worker_container_cleanup_failed", self.image_digest, container_id)
            return replace(
                blocked,
                supervisor_started_at=supervisor_started_at,
                supervisor_finished_at=supervisor_finished_at,
            )
        return replace(
            execution,
            supervisor_started_at=supervisor_started_at,
            supervisor_finished_at=supervisor_finished_at,
        )
