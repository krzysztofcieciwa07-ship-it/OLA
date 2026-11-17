from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.vercel_sandbox_adapter import SandboxAdapterError, execute_python_source


class FakeNetworkPolicy:
    @classmethod
    def deny_all(cls):
        return "deny-all"


class FakeResources:
    def __init__(self, *, vcpus):
        self.vcpus = vcpus


class FakeSandbox:
    name = "sandbox-test-123"

    def __init__(self, stdout="42\n", stderr=""):
        self.stdout_value = stdout
        self.stderr_value = stderr
        self.calls = []
        self.exited = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.exited = True

    def run_process(self, command, args, **kwargs):
        self.calls.append((command, args, kwargs))
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
    assert result["exit_code"] == 0
    assert result["stdout"] == "42\n"
    assert result["source_sha256"]
    assert result["stdout_sha256"]
    assert result["stderr_sha256"]
    assert result["stdout_truncated"] is False
    assert result["stderr_truncated"] is False

    options = sdk.create_options
    assert options["image"] == "vercel/sandbox/python:3.14"
    assert options["persistent"] is False
    assert options["network_policy"] == "deny-all"
    assert options["resources"].vcpus == 1
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
    assert options["destroy"] is True


def test_adapter_caps_retained_output_and_marks_truncation():
    box = FakeSandbox(stdout="x" * 20, stderr="y" * 20)
    sdk = FakeSDK(box)
    result = execute_python_source(
        "print('x')",
        sdk=sdk,
        client=sdk,
        output_limit_bytes=5,
    )
    assert result["stdout"] == "xxxxx"
    assert result["stderr"] == "yyyyy"
    assert result["stdout_truncated"] is True
    assert result["stderr_truncated"] is True


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
