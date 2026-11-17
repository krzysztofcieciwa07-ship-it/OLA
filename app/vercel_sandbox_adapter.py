"""Bounded Vercel Sandbox adapter for the existing NINA WorkflowEngine.

The adapter executes a fixed Python interpreter invocation inside a fresh
Firecracker sandbox. It does not create runs or write evidence; the existing
WorkflowEngine and Evidence V4 writer own those responsibilities.
"""
from datetime import timedelta
import hashlib


MAX_SOURCE_BYTES = 100_000
MAX_OUTPUT_BYTES = 8_192
MAX_TIMEOUT_SECONDS = 60
RUNTIME_IMAGE = "vercel/sandbox/python:3.14"


class SandboxAdapterError(ValueError):
    """The requested sandbox operation violates the adapter contract."""


class _BoundedTextSink:
    """Retain at most N UTF-8 bytes while allowing the remote process to drain."""

    encoding = "utf-8"
    errors = "replace"

    def __init__(self, limit_bytes):
        self._limit = limit_bytes
        self._buffer = bytearray()
        self.truncated = False

    def write(self, value):
        if not isinstance(value, str):
            raise TypeError("sandbox output must be text")
        encoded = value.encode("utf-8")
        remaining = self._limit - len(self._buffer)
        if remaining > 0:
            self._buffer.extend(encoded[:remaining])
        if len(encoded) > max(remaining, 0):
            self.truncated = True
        return len(value)

    def flush(self):
        return None

    def writable(self):
        return True

    def bytes(self):
        return bytes(self._buffer)

    def text(self):
        return self.bytes().decode("utf-8", errors="replace")

    def sha256(self):
        return hashlib.sha256(self.bytes()).hexdigest()


def execute_python_source(
    source,
    *,
    sdk=None,
    timeout_seconds=30,
    output_limit_bytes=MAX_OUTPUT_BYTES,
):
    """Execute Python source in a one-shot, network-isolated Vercel Sandbox.

    The SDK session is opened inside the calling thread. This matters because
    WorkflowEngine dispatches registered nodes through ThreadPoolExecutor.
    """
    if not isinstance(source, str) or not source.strip():
        raise SandboxAdapterError("Python source must be a non-empty string")
    source_bytes = source.encode("utf-8")
    if len(source_bytes) > MAX_SOURCE_BYTES:
        raise SandboxAdapterError("Python source exceeds the configured limit")
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= MAX_TIMEOUT_SECONDS:
        raise SandboxAdapterError("timeout must be an integer from 1 to 60 seconds")
    if type(output_limit_bytes) is not int or not 1 <= output_limit_bytes <= MAX_OUTPUT_BYTES:
        raise SandboxAdapterError("output limit must be an integer from 1 to 8192 bytes")

    if sdk is None or client is None:
        from vercel.sandbox import sync as sandbox_sdk

        sdk = sdk or sandbox_sdk
        client = client or sandbox_sdk.SyncSandboxClient.create()

    stdout = _BoundedTextSink(output_limit_bytes)
    stderr = _BoundedTextSink(output_limit_bytes)
    timeout = timedelta(seconds=timeout_seconds)

    try:
        with client.create_sandbox(
            image=RUNTIME_IMAGE,
            execution_time_limit=timeout,
            persistent=False,
            resources=sdk.SandboxResources(vcpus=1),
            network_policy=sdk.NetworkPolicy.deny_all(),
            destroy=True,
        ) as sandbox:
            sandbox_name = getattr(sandbox, "name", None)
            if not isinstance(sandbox_name, str) or not sandbox_name:
                raise SandboxAdapterError("Vercel Sandbox did not return a sandbox identity")
            completed = sandbox.run_process(
                "python3",
                ["-c", source],
                kill_after=timeout,
                stdout=stdout,
                stderr=stderr,
                check=False,
            )
            exit_code = getattr(completed, "returncode", None)
            if type(exit_code) is not int:
                raise SandboxAdapterError("Vercel Sandbox returned no valid process exit code")
    finally:
        client.close()

    return {
        "executor": "vercel_sandbox",
        "operation": "python_exec",
        "runtime": "python3.14",
        "sandbox_name": sandbox_name,
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "exit_code": exit_code,
        "stdout": stdout.text(),
        "stderr": stderr.text(),
        "stdout_sha256": stdout.sha256(),
        "stderr_sha256": stderr.sha256(),
        "stdout_truncated": stdout.truncated,
        "stderr_truncated": stderr.truncated,
    }


def _unique_json_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON member")
        value[key] = item
    return value


def execute_sandbox_task(task_json):
    """Validate the NINA node task envelope before dispatching source code."""
    import json

    try:
        task = json.loads(task_json, object_pairs_hook=_unique_json_object)
    except (TypeError, ValueError):
        raise SandboxAdapterError("sandbox task must be strict JSON") from None
    if not isinstance(task, dict) or set(task) != {"operation", "source"}:
        raise SandboxAdapterError("sandbox task fields are invalid")
    if task.get("operation") != "python_exec":
        raise SandboxAdapterError("sandbox operation is not allowlisted")
    if not isinstance(task.get("source"), str):
        raise SandboxAdapterError("sandbox source must be a string")
    return execute_python_source(task["source"])
