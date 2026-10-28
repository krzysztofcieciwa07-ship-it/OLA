import pytest

from app.truth_contract import describe_execution_truth


def test_six_deterministic_steps_cannot_certify_factual_truth():
    execution = [{"invocation_type": "local_deterministic_model"} for _ in range(6)]
    truth = describe_execution_truth(execution, "VERIFIED")

    assert truth["evidence_integrity"] == "VERIFIED"
    assert truth["answer_correctness"] == "UNKNOWN"
    assert truth["execution_mode"] == "DETERMINISTIC_SIMULATION"
    assert truth["real_llm_invocations"] == 0


def test_real_model_response_also_requires_an_independent_fact_check():
    truth = describe_execution_truth([{"invocation_type": "real_llm"}], "VERIFIED")

    assert truth["execution_mode"] == "REAL_LLM_PROVENANCE_ONLY"
    assert truth["real_llm_invocations"] == 1
    assert truth["answer_correctness"] == "UNKNOWN"


def test_unclassified_invocation_is_never_silently_certified():
    truth = describe_execution_truth([{"invocation_type": "external_unchecked"}], "BLOCK")

    assert truth["execution_mode"] == "UNCLASSIFIED_EXECUTION"
    assert truth["unclassified_invocations"] == 1
    assert truth["answer_correctness"] == "UNKNOWN"


def test_invalid_execution_shape_is_rejected():
    with pytest.raises(ValueError):
        describe_execution_truth(None, "VERIFIED")


@pytest.mark.parametrize("invalid", [[None], ["model"], [12], [dict(), False]])
def test_invalid_execution_record_fails_closed(invalid):
    with pytest.raises(ValueError, match="records must be objects"):
        describe_execution_truth(invalid, "VERIFIED")
