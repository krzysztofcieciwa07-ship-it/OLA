"""Bounded Vercel Sandbox adapter for the existing NINA WorkflowEngine.

The adapter executes a fixed Python interpreter invocation inside a fresh
Firecracker sandbox. It does not create runs or write evidence; the existing
WorkflowEngine and Evidence V4 writer own those responsibilities.
"""
import hashlib
from datetime import timedelta
from threading import BoundedSemaphore


MAX_SOURCE_BYTES = 100_000
MAX_OUTPUT_BYTES = 8_192
MAX_TIMEOUT_SECONDS = 60
# Admission control is process-local; multi-process deployments multiply this cap.
MAX_CONCURRENT_SANDBOXES_PER_PROCESS = 4
RUNTIME_IMAGE = "vercel/sandbox/python@sha256:e678419c0a4463c1f892b44f6f115c3bd8f5ac3f7817841dd5709947e4ed53e8"
_SANDBOX_SLOTS = BoundedSemaphore(MAX_CONCURRENT_SANDBOXES_PER_PROCESS)


def _is_digest_pinned_image(image):
    if not isinstance(image, str):
        return False
    prefix, marker, digest = image.rpartition("@sha256:")
    return bool(prefix) and bool(marker) and len(digest) == 64 and all(
        char in "0123456789abcdef" for char in digest
    )


class SandboxAdapterError(ValueError):
    """The requested sandbox operation violates the adapter contract."""


class SandboxOutputLimitExceeded(SandboxAdapterError):
    """Remote output exceeded its budget; the ephemeral sandbox is destroyed."""


class _BoundedTextSink:
    """Retain at most N UTF-8 bytes and abort immediately on overflow."""


    encoding = "utf-8"
    errors = "replace"

    def __init__(self, limit_bytes, on_overflow=None):
        self._limit = limit_bytes
        self._buffer = bytearray()
        self._on_overflow = on_overflow
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
            if self._on_overflow is not None:
                self._on_overflow()
            raise SandboxOutputLimitExceeded("sandbox output budget exceeded")
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
    client=None,
    timeout_seconds=30,
    output_limit_bytes=MAX_OUTPUT_BYTES,
):
    """Execute Python source in a one-shot, network-isolated Vercel Sandbox.

    A standalone SDK client is created and closed inside the calling thread.
    This matters because WorkflowEngine dispatches nodes through ThreadPoolExecutor.
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

    if not _SANDBOX_SLOTS.acquire(blocking=False):
        raise SandboxAdapterError("sandbox concurrency limit reached")

    try:
        if sdk is None and client is None:
            from vercel.sandbox import sync as sandbox_sdk

            sdk = sandbox_sdk
            client = sandbox_sdk.SyncSandboxClient.create()
        elif sdk is None or client is None:
            raise SandboxAdapterError("SDK and client test injections must be supplied together")

        process_ref = {}

        def abort_process():
            process = process_ref.get("process")
            if process is not None:
                try:
                    process.kill()
                finally:
                    raise SandboxOutputLimitExceeded("sandbox output budget exceeded")

        def capture_process(process):
            process_ref["process"] = process

        stdout = _BoundedTextSink(output_limit_bytes, on_overflow=abort_process)
        stderr = _BoundedTextSink(output_limit_bytes, on_overflow=abort_process)
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
                image = getattr(sandbox, "image", None)
                if image != RUNTIME_IMAGE or not _is_digest_pinned_image(image):
                    raise SandboxAdapterError("Vercel Sandbox did not return the expected digest-pinned image")
                completed = sandbox.run_process(
                    "python3",
                    ["-c", source],
                    kill_after=timeout,
                    stdout=stdout,
                    stderr=stderr,
                    check=False,
                    on_start=capture_process,
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
            "image": image,
            "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
            "exit_code": exit_code,
            "stdout": stdout.text(),
            "stderr": stderr.text(),
            "stdout_sha256": stdout.sha256(),
            "stderr_sha256": stderr.sha256(),
            "stdout_truncated": stdout.truncated,
            "stderr_truncated": stderr.truncated,
        }
    finally:
        _SANDBOX_SLOTS.release()


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
