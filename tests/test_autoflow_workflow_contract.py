from pathlib import Path
import re
import textwrap


ROOT = Path(__file__).resolve().parents[1]


def workflow(name: str) -> str:
    return (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


def trigger_block(source: str, next_section: str) -> str:
    match = re.search(
        rf"(?ms)^on:\\n(?P<body>.*?)(?=^{re.escape(next_section)}:)",
        source,
    )
    assert match is not None, "workflow trigger block is missing"
    return match.group("body")


def test_nina_ollama_workflow_is_reusable_not_a_second_pr_or_main_push_trigger():
    source = workflow("nina-igor-ollama.yml")
    triggers = trigger_block(source, "permissions")

    assert re.search(r"(?m)^  workflow_call:", triggers)
    assert re.search(r"(?m)^  workflow_dispatch:", triggers)
    assert not re.search(r"(?m)^  pull_request:", triggers)
    push = re.search(r"(?ms)^  push:\\n(?P<body>.*)$", triggers)
    assert push is not None
    assert "- feat/evidence-graph-v0.1" in push.group("body")
    assert "- main" not in push.group("body")


def test_12h_flow_is_the_single_full_flow_for_pr_and_main_push():
    source = workflow("ola-12h-autoflow.yml")
    triggers = trigger_block(source, "concurrency")

    assert re.search(r"(?m)^  schedule:", triggers)
    assert re.search(r"(?m)^  workflow_dispatch:", triggers)
    assert re.search(r"(?m)^  pull_request:", triggers)
    assert re.search(r"(?m)^  push:", triggers)
    assert "paths:" not in triggers


def test_12h_concurrency_isolates_prs_from_main_evidence_runs():
    source = workflow("ola-12h-autoflow.yml")
    group = re.search(r"(?m)^  group: (.+)$", source)
    assert group is not None
    assert "github.event.pull_request.number" in group.group(1)
    assert "github.ref" in group.group(1)
    assert re.search(r"(?m)^  cancel-in-progress: false$", source)


def test_final_gate_verifies_nested_nina_igor_and_aggregator_in_12h_run():
    source = workflow("final-production-gate.yml")
    required = re.search(r"required_exact\\s*=\\s*\\[(.*?)\\]", source, re.S)
    assert required is not None
    assert "OLA 12h Autonomous Evidence Flow" in required.group(1)
    assert "NINA IGOR Ollama Full Flow" not in required.group(1)
    assert 'autoflow_run = exact.get("OLA 12h Autonomous Evidence Flow")' in source
    assert 'real_ollama_flow / nina-igor-ollama-full-flow' in source
    assert 'real_ollama_flow / igor-independent-ollama / igor-ollama' in source
    assert '"OLA 12h Evidence Aggregator": "classify"' in source
    assert "jobs_by_name.setdefault(job.get(\\"name\\"), job)" in source


def test_final_gate_embedded_python_is_syntactically_valid():
    source = workflow("final-production-gate.yml")
    marker = "if python - <<'PY'"
    start = source.index(marker)
    newline = chr(10)
    body_start = source.index(newline, start) + 1
    body_end = source.index(newline + "          PY", body_start)
    body = source[body_start:body_end]
    compile(
        textwrap.dedent(body),
        "final-production-gate.yml::<embedded-python>",
        "exec",
    )
