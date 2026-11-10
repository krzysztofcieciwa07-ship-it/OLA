import json

import pytest


def _tool_result():
    from app.providers.contracts import AgentModelOutput, ProviderResult, digest_json

    output = AgentModelOutput(
        status="needs_tool",
        summary="Evaluate the requested arithmetic expression.",
        reasoning="The requested capability is within the specialist allowlist.",
        tool_name="tool.safe_expression",
        tool_arguments_json='{"expression":"17 * 23"}',
        evidence_refs=[],
    )
    return ProviderResult(
        provider="ollama",
        model="qwen2.5:0.5b-instruct",
        model_digest="sha256:" + "a" * 64,
        request_id="ola-proxy:request-001",
        prompt_digest="b" * 64,
        schema_digest="c" * 64,
        raw_response_digest="d" * 64,
        output_digest=digest_json(output.model_dump(mode="json")),
        latency_ms=10,
        output=output,
    )


class _CapturingSupervisor:
    def __init__(self, agent, source_commit):
        self.registry = {agent.agent_id: agent}
        self.expected_source_commit = source_commit
        self.image_digest = "sha256:" + "e" * 64
        self.request = None

    def _inspect_image(self):
        return self.image_digest

    def execute(self, instance, request):
        from app.agent_supervisor import AgentExecution
        from app.agent_worker import run_agent_worker

        self.request = request
        result = run_agent_worker(request).model_copy(update={"worker_pid": 1})
        return AgentExecution(
            status="COMPLETED",
            container_id="f" * 64,
            image_digest=self.image_digest,
            worker_result=result,
            exit_code=0,
        )


def test_model_output_is_the_only_source_of_capability_arguments(monkeypatch):
    from app import agent_runtime
    from app.agent_registry import make_agent_instance_spec

    agent = make_agent_instance_spec(
        "hermes-model-derived-01",
        "Hermes",
        "react",
        capabilities=("tool.safe_expression",),
    )
    source_commit = "a" * 40
    supervisor = _CapturingSupervisor(agent, source_commit)
    records = []

    def append(tenant_id, record_type, payload, **kwargs):
        records.append((record_type, payload))
        return {"id": f"record-{len(records)}"}

    class Gateway:
        def generate(self, **kwargs):
            return _tool_result()

    monkeypatch.setattr(agent_runtime, "append_evidence_atomic", append)
    result = agent_runtime.run_isolated_agent_task(
        "tenant-test",
        agent,
        "Calculate 17 times 23.",
        "tool.safe_expression",
        None,
        provider="ollama",
        provider_gateway=Gateway(),
        supervisor=supervisor,
        source_commit=source_commit,
    )

    assert result["status"] == "COMPLETED"
    assert supervisor.request.capability_input == {"expression": "17 * 23"}
    assert supervisor.request.capability == "tool.safe_expression"
    assert supervisor.request.model_output["output"]["tool_arguments_json"] == (
        '{"expression":"17 * 23"}'
    )
    assert supervisor.request.capability_input != {"expression": "2 + 2"}


def test_worker_output_digest_is_bound_to_fresh_nonce_and_has_signature():
    from app.agent_protocol import AgentWorkerRequest
    from app.agent_registry import make_agent_instance_spec
    from app.agent_worker import run_agent_worker

    agent = make_agent_instance_spec(
        "hermes-attestation-01",
        "Hermes",
        "react",
        capabilities=("tool.safe_expression",),
    )
    request = AgentWorkerRequest(
        schema_version=1,
        run_id="00000000-0000-4000-8000-000000000021",
        agent_id=agent.agent_id,
        agent_instance_id="00000000-0000-4000-8000-000000000022",
        specialist_role=agent.specialist_role,
        execution_profile=agent.execution_profile,
        capability="tool.safe_expression",
        allowed_capabilities=("tool.safe_expression",),
        task="Calculate 17 times 23.",
        capability_input={"expression": "17 * 23"},
        model_output={
            "output": {
                "status": "needs_tool",
                "tool_name": "tool.safe_expression",
                "tool_arguments_json": '{"expression":"17 * 23"}',
            }
        },
        source_commit="a" * 40,
    )

    first = run_agent_worker(request)
    second = run_agent_worker(request)

    assert first.worker_nonce != second.worker_nonce
    assert first.output_digest != second.output_digest
    assert first.worker_public_key
    assert first.worker_signature
    from app.provenance.crypto import verify_worker_signature
    assert verify_worker_signature(first) is True
    assert verify_worker_signature(second) is True


def test_ollama_blocks_digest_drift_against_the_deployment_lock():
    import httpx
    from app.providers import OllamaAdapter, ProviderError, AgentModelOutput

    expected_digest = "sha256:" + "b" * 64
    observed_digest = "sha256:" + "a" * 64

    def handler(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={
                "models": [{
                    "name": "qwen2.5:0.5b-instruct",
                    "digest": observed_digest,
                }],
            })
        return httpx.Response(500)

    adapter = OllamaAdapter(
        model="qwen2.5:0.5b-instruct",
        allowed_models=("qwen2.5:0.5b-instruct",),
        base_url="http://127.0.0.1:11434",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    adapter.expected_model_digest = expected_digest

    with pytest.raises(ProviderError) as error:
        adapter.generate(prompt="test", schema=AgentModelOutput.model_json_schema())

    assert error.value.code == "model_digest_mismatch"


def test_supervisor_blocks_rootful_docker_runtime_before_launch(tmp_path):
    import json
    from subprocess import CompletedProcess
    from tests.test_agent_supervisor import (
        IMAGE_DIGEST,
        _request_and_agent,
        _runner_for_inspect,
        _supervisor_module,
    )

    agent, request = _request_and_agent()
    fallback_runner, _ = _runner_for_inspect(agent, request)

    def runner(args, **kwargs):
        if args[1:2] == ["info"]:
            return CompletedProcess(
                args,
                0,
                stdout=json.dumps(["name=seccomp,profile=builtin"]),
                stderr="",
            )
        return fallback_runner(args, **kwargs)

    supervisor = _supervisor_module().AgentSupervisor(
        registry=[agent],
        image_digest=IMAGE_DIGEST,
        expected_source_commit="a" * 40,
        runner=runner,
        temp_dir=str(tmp_path),
    )

    result = supervisor.execute(agent, request)

    assert result.status == "BLOCKED"
    assert result.reason == "container_runtime_not_rootless"


def test_runtime_commits_plan_before_any_agent_start(monkeypatch):
    from app import agent_runtime
    from app.agent_registry import make_agent_instance_spec

    agent = make_agent_instance_spec(
        "hermes-plan-01",
        "Hermes",
        "react",
        capabilities=("tool.safe_expression",),
    )
    source_commit = "a" * 40
    supervisor = _CapturingSupervisor(agent, source_commit)
    records = []

    def append(tenant_id, record_type, payload, **kwargs):
        records.append((record_type, payload))
        return {"id": f"record-{len(records)}"}

    class Gateway:
        def generate(self, **kwargs):
            return _tool_result()

    monkeypatch.setattr(agent_runtime, "append_evidence_atomic", append)
    result = agent_runtime.run_isolated_agent_task(
        "tenant-test",
        agent,
        "Calculate 17 times 23.",
        "tool.safe_expression",
        None,
        provider="ollama",
        provider_gateway=Gateway(),
        supervisor=supervisor,
        source_commit=source_commit,
    )

    types = [record_type for record_type, _ in records]
    assert result["status"] == "COMPLETED"
    assert types.count("plan.committed") == 1
    assert types.index("plan.committed") < types.index("agent.start")
    plan = next(payload for kind, payload in records if kind == "plan.committed")
    assert plan["dag_digest"]
    assert plan["allowlist"] == ["tool.safe_expression"]
    assert plan["required_handoffs"] == []


def test_protocol_canonicalization_matches_rfc8785_number_vector():
    from app.agent_protocol import canonical_json

    value = {
        "numbers": [
            333333333.33333329,
            1e30,
            4.50,
            2e-3,
            0.000000000000000000000000001,
            -0.0,
        ]
    }

    assert canonical_json(value) == (
        '{"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27,0]}'
    )
