import uuid


def _instance():
    from app.agent_registry import make_agent_instance_spec

    return make_agent_instance_spec(
        "hermes-runtime-01",
        "Hermes",
        "react",
        capabilities=("tool.safe_expression",),
    )


class RecordingSupervisor:
    def __init__(self, result):
        self.result = result
        self.instance = None
        self.request = None

    def execute(self, instance, request):
        self.instance = instance
        self.request = request
        return self.result


def test_runtime_builds_strict_worker_request_and_delegates_without_fallback():
    from app import agent_runtime
    from app.agent_supervisor import AgentExecution
    assert hasattr(agent_runtime, "run_isolated_agent_instance"), "isolated runtime integration is missing"

    instance = _instance()
    supervisor = RecordingSupervisor(AgentExecution(
        status="COMPLETED",
        container_id="c" * 64,
        image_digest="sha256:" + "b" * 64,
    ))
    run_id = str(uuid.uuid4())
    instance_id = str(uuid.uuid4())

    result = agent_runtime.run_isolated_agent_instance(
        instance,
        "calculate 17 * 23",
        "tool.safe_expression",
        {"expression": "17 * 23"},
        {"proposal": "evaluate the expression"},
        run_id=run_id,
        agent_instance_id=instance_id,
        source_commit="a" * 40,
        supervisor=supervisor,
    )

    assert result.status == "COMPLETED"
    assert supervisor.instance == instance
    assert supervisor.request.schema_version == 1
    assert supervisor.request.run_id == run_id
    assert supervisor.request.agent_instance_id == instance_id
    assert supervisor.request.specialist_role == "Hermes"
    assert supervisor.request.execution_profile == "react"
    assert supervisor.request.allowed_capabilities == ("tool.safe_expression",)
    assert supervisor.request.model_output == {"proposal": "evaluate the expression"}


def test_runtime_blocks_if_source_commit_is_not_trusted(monkeypatch):
    from app import agent_runtime
    from app.agent_supervisor import AgentExecution
    assert hasattr(agent_runtime, "run_isolated_agent_instance"), "isolated runtime integration is missing"

    class NeverCalledSupervisor:
        def execute(self, instance, request):
            raise AssertionError("supervisor must not run without a trusted source commit")

    monkeypatch.setattr(agent_runtime, "_runtime_source_commit", lambda: None)
    result = agent_runtime.run_isolated_agent_instance(
        _instance(),
        "calculate",
        "tool.safe_expression",
        {"expression": "1 + 1"},
        {},
        supervisor=NeverCalledSupervisor(),
    )

    assert isinstance(result, AgentExecution)
    assert result.status == "BLOCKED"
    assert result.reason == "source_commit_not_trusted"


def test_runtime_blocks_capability_outside_instance_allowlist_before_delegation():
    from app import agent_runtime
    from app.agent_supervisor import AgentExecution
    assert hasattr(agent_runtime, "run_isolated_agent_instance"), "isolated runtime integration is missing"

    class NeverCalledSupervisor:
        def execute(self, instance, request):
            raise AssertionError("unauthorized capability must not reach the supervisor")

    result = agent_runtime.run_isolated_agent_instance(
        _instance(),
        "deploy production",
        "production.deploy",
        {"target": "production"},
        {},
        source_commit="a" * 40,
        supervisor=NeverCalledSupervisor(),
    )

    assert isinstance(result, AgentExecution)
    assert result.status == "BLOCKED"
    assert result.reason == "capability_not_in_instance_allowlist"


def test_runtime_preserves_supervisor_block_without_deterministic_fallback():
    from app import agent_runtime
    from app.agent_supervisor import AgentExecution
    assert hasattr(agent_runtime, "run_isolated_agent_instance"), "isolated runtime integration is missing"

    supervisor = RecordingSupervisor(AgentExecution(
        status="BLOCKED",
        reason="worker_image_digest_not_locally_verified",
    ))
    result = agent_runtime.run_isolated_agent_instance(
        _instance(),
        "calculate",
        "tool.safe_expression",
        {"expression": "1 + 1"},
        {},
        source_commit="a" * 40,
        supervisor=supervisor,
    )

    assert result.status == "BLOCKED"
    assert result.reason == "worker_image_digest_not_locally_verified"
