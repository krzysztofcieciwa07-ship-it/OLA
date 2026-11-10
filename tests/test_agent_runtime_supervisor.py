import json
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
        {"output": {"status": "needs_tool", "tool_name": "tool.safe_expression", "tool_arguments_json": '{"expression":"17 * 23"}'}},
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
    assert supervisor.request.model_output["output"]["tool_arguments_json"] == '{"expression":"17 * 23"}'


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


def test_runtime_binds_structured_provider_provenance_to_worker_request():
    from app import agent_runtime
    from app.agent_supervisor import AgentExecution
    from app.providers.contracts import AgentModelOutput, ProviderResult, digest_json
    assert hasattr(agent_runtime, "run_isolated_agent_instance")

    output = AgentModelOutput(
        status="complete",
        summary="The task is ready for bounded execution.",
        reasoning="The provider returned a strict structured proposal.",
        tool_name=None,
        tool_arguments_json="",
        evidence_refs=[],
    )
    provider_result = ProviderResult(
        provider="ollama",
        model="qwen2.5:0.5b-instruct",
        model_digest="sha256:" + "a" * 64,
        request_id="ollama-request-1",
        prompt_digest="b" * 64,
        schema_digest="c" * 64,
        raw_response_digest="d" * 64,
        output_digest=digest_json(output.model_dump(mode="json")),
        latency_ms=12,
        output=output,
    )

    class RecordingGateway:
        def __init__(self):
            self.kwargs = None

        def generate(self, **kwargs):
            self.kwargs = kwargs
            return provider_result

    gateway = RecordingGateway()
    supervisor = RecordingSupervisor(AgentExecution(status="COMPLETED"))
    result = agent_runtime.run_isolated_agent_instance(
        _instance(),
        "calculate 17 * 23",
        "tool.safe_expression",
        {"expression": "17 * 23"},
        provider="ollama",
        provider_gateway=gateway,
        source_commit="a" * 40,
        supervisor=supervisor,
    )

    assert result.status == "COMPLETED"
    assert gateway.kwargs["policy"] == "run_policy"
    assert gateway.kwargs["allowed_tools"] == ("tool.safe_expression",)
    assert supervisor.request.model_output["provider"] == "ollama"
    assert supervisor.request.model_output["model_digest"] == "sha256:" + "a" * 64
    assert supervisor.request.model_output["fallback_used"] is False
    assert supervisor.request.model_output["model_output_role"] == "advisory_only"


def test_runtime_does_not_fallback_when_provider_is_missing_or_fails():
    from app import agent_runtime
    from app.agent_supervisor import AgentExecution
    from app.providers.contracts import ProviderError
    assert hasattr(agent_runtime, "run_isolated_agent_instance")

    class NeverCalledSupervisor:
        def execute(self, instance, request):
            raise AssertionError("worker must not run after provider failure")

    missing = agent_runtime.run_isolated_agent_instance(
        _instance(),
        "calculate",
        "tool.safe_expression",
        {"expression": "1 + 1"},
        supervisor=NeverCalledSupervisor(),
        source_commit="a" * 40,
    )
    assert missing.status == "BLOCKED"
    assert missing.reason == "provider_not_configured"

    class FailingGateway:
        def generate(self, **kwargs):
            raise ProviderError("ollama_request_failed", "provider unavailable")

    failed = agent_runtime.run_isolated_agent_instance(
        _instance(),
        "calculate",
        "tool.safe_expression",
        {"expression": "1 + 1"},
        provider="ollama",
        provider_gateway=FailingGateway(),
        supervisor=NeverCalledSupervisor(),
        source_commit="a" * 40,
    )
    assert isinstance(failed, AgentExecution)
    assert failed.status == "BLOCKED"
    assert failed.reason == "provider_ollama_request_failed"


def test_runtime_constructs_only_requested_provider_and_blocks_if_it_is_unconfigured(monkeypatch):
    from app import agent_runtime
    assert hasattr(agent_runtime, "run_isolated_agent_instance")
    monkeypatch.delenv("OLA_OLLAMA_MODEL", raising=False)
    monkeypatch.delenv("OLA_OLLAMA_ALLOWED_MODELS", raising=False)

    class NeverCalledSupervisor:
        def execute(self, instance, request):
            raise AssertionError("worker must not run without a configured provider")

    result = agent_runtime.run_isolated_agent_instance(
        _instance(),
        "calculate",
        "tool.safe_expression",
        {"expression": "1 + 1"},
        provider="ollama",
        source_commit="a" * 40,
        supervisor=NeverCalledSupervisor(),
    )

    assert result.status == "BLOCKED"
    assert result.reason == "provider_model_not_allowlisted"


def _lifecycle_provider_result():
    from app.providers.contracts import AgentModelOutput, ProviderResult, digest_json

    output = AgentModelOutput(
        status="needs_tool",
        summary="The plan is ready.",
        reasoning="Structured output was validated.",
        tool_name="tool.safe_expression",
        tool_arguments_json='{"expression":"17 * 23"}',
        evidence_refs=[],
    )
    return ProviderResult(
        provider="ollama",
        model="qwen2.5:0.5b-instruct",
        model_digest="sha256:" + "a" * 64,
        request_id="ollama-request-lifecycle",
        prompt_digest="b" * 64,
        schema_digest="c" * 64,
        raw_response_digest="d" * 64,
        output_digest=digest_json(output.model_dump(mode="json")),
        latency_ms=7,
        output=output,
    )


class _LifecycleGateway:
    def __init__(self, result=None, error=None):
        self.result = result or _lifecycle_provider_result()
        self.error = error
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.result


class _LifecycleSupervisor:
    def __init__(self, agent, source_commit, *, valid_worker=True):
        from app.agent_supervisor import AgentExecution

        self.registry = {agent.agent_id: agent}
        self.expected_source_commit = source_commit
        self.image_digest = "sha256:" + "e" * 64
        self.valid_worker = valid_worker
        self.execution_type = AgentExecution

    def _inspect_image(self):
        return self.image_digest

    def execute(self, instance, request):
        from app.agent_supervisor import AgentExecution
        from app.agent_worker import run_agent_worker

        if self.valid_worker:
            from unittest.mock import patch
            with patch("app.agent_worker.os.getpid", return_value=1):
                worker_result = run_agent_worker(request)
        else:
            worker_result = None
        return AgentExecution(
            status="COMPLETED",
            container_id="f" * 64,
            image_digest=self.image_digest,
            worker_result=worker_result,
            exit_code=0,
        )


def test_isolated_agent_task_writes_full_lifecycle_without_plaintext(monkeypatch):
    from app import agent_runtime

    agent = _instance()
    source_commit = "a" * 40
    gateway = _LifecycleGateway()
    supervisor = _LifecycleSupervisor(agent, source_commit)
    records = []

    def append(tenant_id, record_type, payload, **kwargs):
        records.append((record_type, payload))
        return {"id": f"evidence-{len(records)}"}

    monkeypatch.setattr(agent_runtime, "append_evidence_atomic", append)
    result = agent_runtime.run_isolated_agent_task(
        "tenant-test",
        agent,
        "calculate 17 * 23",
        "tool.safe_expression",
        {"expression": "17 * 23"},
        provider="ollama",
        provider_gateway=gateway,
        supervisor=supervisor,
        source_commit=source_commit,
    )

    assert result["status"] == "COMPLETED"
    assert [item[0] for item in records] == [
        "execution.run.start",
        "agent.provider.response",
        "agent.worker.start",
        "agent.worker.end",
        "execution.run.end",
    ]
    payloads = [item[1] for item in records]
    assert all(payload["run_id"] == result["run_id"] for payload in payloads)
    assert payloads[0]["task_digest"] == __import__("hashlib").sha256(
        b"calculate 17 * 23"
    ).hexdigest()
    serialized_payloads = json.dumps(payloads)
    assert "calculate 17 * 23" not in serialized_payloads
    assert "17 * 23" not in serialized_payloads
    assert payloads[1]["fallback_used"] is False
    assert payloads[1]["model_output_role"] == "advisory_only"
    assert payloads[1]["model_output_digest"] == payloads[3]["model_output_digest"]
    assert payloads[3]["worker_pid"] == 1
    assert payloads[3]["exit_code"] == 0
    assert payloads[3]["container_id"] == payloads[4]["container_id"]
    assert payloads[3]["output_digest"] == payloads[4]["output_digest"]


def test_isolated_agent_task_blocks_provider_failure_and_records_terminal_state(monkeypatch):
    from app import agent_runtime
    from app.providers.contracts import ProviderError

    agent = _instance()
    source_commit = "a" * 40
    gateway = _LifecycleGateway(error=ProviderError("ollama_request_failed", "offline"))
    supervisor = _LifecycleSupervisor(agent, source_commit)
    records = []

    def append(tenant_id, record_type, payload, **kwargs):
        records.append((record_type, payload))
        return {"id": f"evidence-{len(records)}"}

    monkeypatch.setattr(agent_runtime, "append_evidence_atomic", append)
    result = agent_runtime.run_isolated_agent_task(
        "tenant-test",
        agent,
        "calculate",
        "tool.safe_expression",
        {"expression": "1 + 1"},
        provider="ollama",
        provider_gateway=gateway,
        supervisor=supervisor,
        source_commit=source_commit,
    )

    assert result["status"] == "BLOCKED"
    assert result["reason"] == "provider_ollama_request_failed"
    assert [item[0] for item in records] == [
        "execution.run.start",
        "execution.run.error",
        "execution.run.end",
    ]
    assert records[-1][1]["status"] == "BLOCKED"


def test_isolated_agent_task_never_claims_completion_if_worker_proof_is_missing(monkeypatch):
    from app import agent_runtime

    agent = _instance()
    source_commit = "a" * 40
    gateway = _LifecycleGateway()
    supervisor = _LifecycleSupervisor(agent, source_commit, valid_worker=False)
    records = []

    def append(tenant_id, record_type, payload, **kwargs):
        records.append((record_type, payload))
        return {"id": f"evidence-{len(records)}"}

    monkeypatch.setattr(agent_runtime, "append_evidence_atomic", append)
    result = agent_runtime.run_isolated_agent_task(
        "tenant-test",
        agent,
        "calculate",
        "tool.safe_expression",
        {"expression": "1 + 1"},
        provider="ollama",
        provider_gateway=gateway,
        supervisor=supervisor,
        source_commit=source_commit,
    )

    assert result["status"] == "BLOCKED"
    assert result["execution"].reason == "worker_execution_proof_invalid"
    assert records[-1][0] == "execution.run.end"
    assert records[-1][1]["status"] == "BLOCKED"


def test_isolated_agent_task_returns_finalization_pending_when_worker_end_cannot_be_recorded(monkeypatch):
    from app import agent_runtime

    agent = _instance()
    source_commit = "a" * 40
    gateway = _LifecycleGateway()
    supervisor = _LifecycleSupervisor(agent, source_commit)
    records = []

    def append(tenant_id, record_type, payload, **kwargs):
        if record_type == "agent.worker.end":
            raise RuntimeError("ledger unavailable")
        records.append((record_type, payload))
        return {"id": f"evidence-{len(records)}"}

    monkeypatch.setattr(agent_runtime, "append_evidence_atomic", append)
    result = agent_runtime.run_isolated_agent_task(
        "tenant-test",
        agent,
        "calculate",
        "tool.safe_expression",
        {"expression": "1 + 1"},
        provider="ollama",
        provider_gateway=gateway,
        supervisor=supervisor,
        source_commit=source_commit,
    )

    assert result["status"] == "FINALIZATION_PENDING"
    assert records[-1][0] == "execution.run.end"
    assert records[-1][1]["status"] == "FINALIZATION_PENDING"
