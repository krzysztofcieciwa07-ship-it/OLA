"""Describe exactly what an OLA execution proves.

Cryptographic integrity of a trace is not verification of the answer in it.
No inference provider, including a real LLM, may promote its own output to a
fact without an independent task-level verifier.
"""


def describe_execution_truth(execution, evidence_status):
    if not isinstance(execution, list):
        raise ValueError("execution must be a list")
    if any(not isinstance(item, dict) for item in execution):
        raise ValueError("execution records must be objects")

    types = [item.get("invocation_type") for item in execution]
    real_calls = sum(kind == "real_llm" for kind in types)
    deterministic_calls = sum(kind == "local_deterministic_model" for kind in types)
    unclassified_calls = len(types) - real_calls - deterministic_calls

    if not types:
        mode = "NO_MODEL_EXECUTION"
    elif unclassified_calls:
        mode = "UNCLASSIFIED_EXECUTION"
    elif real_calls == len(types):
        mode = "REAL_LLM_PROVENANCE_ONLY"
    elif deterministic_calls == len(types):
        mode = "DETERMINISTIC_SIMULATION"
    else:
        mode = "MIXED_EXECUTION"

    return {
        "evidence_integrity": evidence_status,
        "evidence_scope": "record_integrity_and_execution_trace_only",
        "answer_correctness": "UNKNOWN",
        "independent_fact_checks": 0,
        "real_llm_invocations": real_calls,
        "deterministic_invocations": deterministic_calls,
        "unclassified_invocations": unclassified_calls,
        "execution_mode": mode,
        "reason": (
            "No independent task-level fact verifier was run; "
            "a valid hash chain or model response does not establish factual truth."
        ),
    }
