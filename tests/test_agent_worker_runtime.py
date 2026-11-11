import os

import pytest


def _run_builder_worker(task="Calculate 17 * 23"):
    from app.agent_worker import run_agent_worker

    return run_agent_worker(
        agent_id="builder-primary",
        role="Builder",
        execution_profile="codeact",
        task=task,
        context={"previous_output": {}, "upstream_agents": []},
    )


def test_worker_executes_registered_capability_in_a_distinct_os_process():
    result = _run_builder_worker()

    assert result["status"] == "COMPLETED"
    assert result["execution_boundary"] == "subprocess"
    assert result["agent_id"] == "builder-primary"
    assert result["specialist_role"] == "Builder"
    assert result["execution_profile"] == "codeact"
    assert isinstance(result["worker_pid"], int)
    assert result["worker_pid"] != os.getpid()
    assert result["worker_parent_pid"] == os.getpid()
    assert result["result"]["tool_output"] == "391"
    assert result["result"]["action_result_source"] == "registered_capability"


def test_worker_rejects_profile_not_allowed_for_specialist_before_launch(monkeypatch):
    import app.agent_worker as worker_module

    def forbidden(*args, **kwargs):
        raise AssertionError("unapproved worker must not be launched")

    monkeypatch.setattr(worker_module.subprocess, "run", forbidden, raising=False)

    with pytest.raises(ValueError, match="not allowed"):
        worker_module.run_agent_worker(
            agent_id="sales-primary",
            role="Sales",
            execution_profile="codeact",
            task="Calculate 1 + 1",
            context={"previous_output": {}, "upstream_agents": []},
        )


def test_worker_rejects_oversized_input_before_launch(monkeypatch):
    import app.agent_worker as worker_module

    def forbidden(*args, **kwargs):
        raise AssertionError("oversized worker request must not be launched")

    monkeypatch.setattr(worker_module.subprocess, "run", forbidden, raising=False)

    with pytest.raises(ValueError, match="input limit"):
        worker_module.run_agent_worker(
            agent_id="builder-primary",
            role="Builder",
            execution_profile="codeact",
            task="x" * 4097,
            context={"previous_output": {}, "upstream_agents": []},
        )


def test_worker_request_does_not_inherit_openai_credentials(monkeypatch):
    import app.agent_worker as worker_module

    captured = {}

    class Completed:
        returncode = 0
        stdout = b"{}"
        stderr = b""

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs["env"]
        return Completed()

    monkeypatch.setattr(worker_module.subprocess, "run", fake_run, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-cross-worker-boundary")
    with pytest.raises(RuntimeError):
        worker_module.run_agent_worker(
            agent_id="builder-primary",
            role="Builder",
            execution_profile="codeact",
            task="Calculate 1 + 1",
            context={"previous_output": {}, "upstream_agents": []},
        )

    assert "OPENAI_API_KEY" not in captured["env"]
    assert captured["command"][-1] == "app.agent_worker"
