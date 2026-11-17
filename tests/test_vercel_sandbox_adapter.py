from datetime import timedelta
from threading import BoundedSemaphore
from types import SimpleNamespace

import pytest

import app.vercel_sandbox_adapter as adapter_module
from app.vercel_sandbox_adapter import (
    SandboxAdapterError,
    SandboxOutputLimitExceeded,
    execute_python_source,
)


class FakeNetworkPolicy:
    @classmethod
    def deny_all(cls):
        return "deny-all"


class FakeResources:
    def __init__(self, *, vcpus, memory):
        self.vcpus = vcpus
        self.memory = memory


class FakeSandbox:
    name = "sandbox-test-123"
    image = "vercel/sandbox/python@sha256:e678419c0a4463c1f892b44f6f115c3bd8f5ac3f7817841dd5709947e4ed53e8"
    region = "fra1"
    network_policy = SimpleNamespace(mode="deny-all")
    persistent = False
    vcpus = 1
    memory = 2048
    failover_regions = ()
    execution_time_limit = timedelta(seconds=30)

    def __init__(self, stdout="42\n", stderr=""):
        self.stdout_value = stdout
        self.stderr_value = stderr
        self.calls = []
        self.exited = False
        self.process = SimpleNamespace(killed=False)

        def kill_process():
            self.process.killed = True

        self.process.kill = kill_process

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.exited = True

    def run_process(self, command, args, **kwargs):
        self.calls.append((command, args, kwargs))
        if kwargs.get("on_start") is not None:
            kwargs["on_start"](self.process)
        kwargs["stdout"].write(self.stdout_value)
        kwargs["stderr"].write(self.stderr_value)
        return SimpleNamespace(returncode=0)


class FakeSDK:
    NetworkPolicy = FakeNetworkPolicy
    SandboxResources = FakeResources

    def __init__(self, box):
        self.box = box
        self.create_options = None
        self.closed = False

    def create_sandbox(self, **kwargs):
        self.create_options = kwargs
        return self.box

    def close(self):
        self.closed = True


def test_adapter_uses_ephemeral_deny_all_sandbox_and_fixed_python_argv():
    source = "print(6 * 7)"
    box = FakeSandbox()
    sdk = FakeSDK(box)

    result = execute_python_source(
        source,
        sdk=sdk,
        client=sdk,
        timeout_seconds=12,
    )

    assert result["executor"] == "vercel_sandbox"
    assert result["operation"] == "python_exec"
    assert result["runtime"] == "python3.14"
    assert result["sandbox_name"] == box.name
    assert result["image"] == box.image
    assert result["region"] == "fra1"
    assert result["failover_regions"] == []
    assert result["network_policy"] == "deny-all"
    assert result["persistent"] is False
    assert result["destroy_on_exit"] is True
    assert result["resources"] == {"vcpus": 1, "memory_mb": 2048}
    assert result["timeout_seconds"] == 12
    assert result["output_limit_bytes_per_stream"] == 8192
    assert result["source_bytes"] == len(source.encode("utf-8"))
    assert result["exit_code"] == 0
    assert result["stdout"] == "42\n"
    assert result["source_sha256"]
    assert result["stdout_sha256"]
    assert result["stderr_sha256"]
    assert result["stdout_truncated"] is False
    assert result["stderr_truncated"] is False

    options = sdk.create_options
    assert options["image"] == "vercel/sandbox/python@sha256:e678419c0a4463c1f892b44f6f115c3bd8f5ac3f7817841dd5709947e4ed53e8"
    assert options["persistent"] is False
    assert options["network_policy"] == "deny-all"
    assert options["resources"].vcpus == 1
    assert options["resources"].memory == 2048
    assert options["execution_time_limit"] == timedelta(seconds=12)
    assert "env" not in options

    command, args, kwargs = box.calls[0]
    assert command == "python3"
    assert args == ["-c", source]
    assert kwargs["check"] is False
    assert kwargs["kill_after"] == timedelta(seconds=12)
    assert kwargs["stdout"] is not None and kwargs["stderr"] is not None
    assert box.exited is True
    assert sdk.closed is True
    assert box.process.killed is False
    assert options["destroy"] is True


def test_adapter_requires_provider_confirmed_region_before_execution():
    box = FakeSandbox()
    box.region = None
    sdk = FakeSDK(box)

    with pytest.raises(SandboxAdapterError, match="EU region"):
        execute_python_source("print(1)", sdk=sdk, client=sdk)

    assert box.process_calls == []


def test_adapter_rejects_unpinned_resolved_image_before_execution():
    box = FakeSandbox()
    box.image = "vercel/sandbox/python:3.14"
    sdk = FakeSDK(box)

    with pytest.raises(SandboxAdapterError, match="digest-pinned image"):
        execute_python_source("print(42)", sdk=sdk, client=sdk)

    assert box.calls == []
    assert sdk.closed is True


def test_adapter_rejects_unexpected_digest_pinned_image_before_execution():
    box = FakeSandbox()
    box.image = "vercel/sandbox/python@sha256:" + "b" * 64
    sdk = FakeSDK(box)

    with pytest.raises(SandboxAdapterError, match="expected digest-pinned image"):
        execute_python_source("print(42)", sdk=sdk, client=sdk)

    assert box.calls == []
    assert sdk.closed is True


def test_adapter_aborts_and_destroys_sandbox_when_output_limit_is_exceeded():
    box = FakeSandbox(stdout="x" * 20, stderr="y" * 20)
    sdk = FakeSDK(box)

    with pytest.raises(SandboxOutputLimitExceeded, match="output budget"):
        execute_python_source(
            "print('x')",
            sdk=sdk,
            client=sdk,
            output_limit_bytes=5,
        )

    assert box.exited is True
    assert sdk.closed is True
    assert box.process.killed is True


@pytest.mark.parametrize(
    "source, timeout, output_limit",
    [
        ("", 10, 100),
        ("print(1)", True, 100),
        ("print(1)", 0, 100),
        ("print(1)", 61, 100),
        ("print(1)", 10, 0),
        ("print(1)", 10, 8193),
    ],
)
def test_adapter_rejects_invalid_bounds_before_provider_call(source, timeout, output_limit):
    sdk = FakeSDK(FakeSandbox())
    with pytest.raises(SandboxAdapterError):
        execute_python_source(
            source,
            sdk=sdk,
            client=sdk,
            timeout_seconds=timeout,
            output_limit_bytes=output_limit,
        )
    assert sdk.create_options is None


def test_adapter_rejects_source_over_limit_before_provider_call():
    sdk = FakeSDK(FakeSandbox())
    with pytest.raises(SandboxAdapterError):
        execute_python_source(
            "x" * 100_001,
            sdk=sdk,
            client=sdk,
        )
    assert sdk.create_options is None


def test_pinned_vercel_sdk_exposes_standalone_sync_sandbox_client():
    import inspect

    import vercel.sandbox as sdk
    from vercel.sandbox.sync import SandboxServiceOptions, SyncSandboxClient

    create_parameters = set(inspect.signature(SyncSandboxClient.create_sandbox).parameters)
    assert {"image", "execution_time_limit", "persistent", "resources",
            "network_policy", "destroy"} <= create_parameters
    options = SandboxServiceOptions(region="fra1")
    client = SyncSandboxClient.create(options=options)
    try:
        assert sdk.NetworkPolicy.deny_all() is not None
        assert sdk.SandboxResources(vcpus=1, memory=2048) is not None
    finally:
        client.close()


def test_default_adapter_uses_official_sdk_policy_and_resource_types(monkeypatch):
    import vercel.sandbox as sdk
    from vercel.sandbox.sync import SyncSandboxClient

    fake_client = FakeSDK(FakeSandbox())
    captured = {}
    def fake_create(*, options):
        captured["options"] = options
        return fake_client
    monkeypatch.setattr(SyncSandboxClient, "create", fake_create)

    result = execute_python_source("print(42)")

    assert result["executor"] == "vercel_sandbox"
    assert captured["options"].region == "fra1"
    assert fake_client.create_options["region"] == "fra1"
    assert fake_client.create_options["failover_regions"] == []
    assert fake_client.create_options["destroy"] is True
    assert isinstance(fake_client.create_options["network_policy"], sdk.NetworkPolicy)
    assert isinstance(fake_client.create_options["resources"], sdk.SandboxResources)
    assert fake_client.create_options["resources"].memory == 2048
    assert result["region"] == "fra1"
    assert fake_client.closed is True



@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_adapter_aborts_sandbox_when_output_budget_is_exceeded(stream):
    box = FakeSandbox(
        stdout="x" * 8193 if stream == "stdout" else "",
        stderr="y" * 8193 if stream == "stderr" else "",
    )
    sdk = FakeSDK(box)

    with pytest.raises(SandboxOutputLimitExceeded, match="output budget"):
        execute_python_source("print('large')", sdk=sdk, client=sdk)

    # Exiting the ephemeral sandbox context destroys the remote process.
    assert box.exited is True
    assert sdk.closed is True
    assert box.process.killed is True


def test_adapter_rejects_new_sandbox_when_global_capacity_is_exhausted(monkeypatch):
    class BusySlots:
        def acquire(self, blocking=False):
            return False

    monkeypatch.setattr(adapter_module, "_SANDBOX_SLOTS", BusySlots())
    sdk = FakeSDK(FakeSandbox())

    with pytest.raises(SandboxAdapterError, match="concurrency limit"):
        execute_python_source("print(42)", sdk=sdk, client=sdk)

    assert sdk.create_options is None
    assert sdk.closed is False



def test_adapter_releases_global_slot_after_output_abort(monkeypatch):
    slots = BoundedSemaphore(1)
    monkeypatch.setattr(adapter_module, "_SANDBOX_SLOTS", slots)
    sdk = FakeSDK(FakeSandbox(stdout="x" * 20))

    with pytest.raises(SandboxOutputLimitExceeded):
        execute_python_source(
            "print('large')",
            sdk=sdk,
            client=sdk,
            output_limit_bytes=5,
        )

    assert slots.acquire(blocking=False) is True
    slots.release()
