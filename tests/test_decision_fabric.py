from app.decision_fabric import DecisionFabric, DecisionPolicy


class FakeProvider:
    name = "fake"

    def __init__(self, body):
        self.body = body

    def evaluate(self, *, state, questions, model):
        return {"body": self.body, "request_id": "req-test-1"}


def test_decision_fabric_preserves_typed_answers_and_hashes():
    provider = FakeProvider(
        {
            "model": "jev-1.13.0",
            "answers": {
                "route": {
                    "type": "choice",
                    "choice": "audit",
                    "probabilities": {"audit": 0.92, "block": 0.08},
                    "confidence": 0.92,
                },
                "needs_human": {"type": "noul", "noul": 0.91},
            },
        }
    )
    fabric = DecisionFabric(provider=provider)
    result = fabric.evaluate(
        state={"task": "audit evidence"},
        questions={
            "route": {
                "type": "choice",
                "instructions": "Which route?",
                "criteria": {"audit": "Evidence audit", "block": "Unsafe"},
            },
            "needs_human": {
                "type": "noul",
                "instructions": "Does this require human review?",
            },
        },
    )
    assert result.status == "READY"
    assert result.model == "jev-1.13.0"
    assert result.request_sha256
    assert result.response_sha256
    assert result.request_id == "req-test-1"
    assert fabric.classify(result) == {"route": "ACCEPT", "needs_human": "YES"}


def test_decision_policy_does_not_treat_uncertainty_as_yes():
    policy = DecisionPolicy(noul_yes_threshold=0.80, noul_no_threshold=0.20)
    assert policy.classify({"type": "noul", "noul": 0.50}) == "REVIEW"
    assert policy.classify({"type": "noul", "noul": 0.79}) == "REVIEW"
    assert policy.classify({"type": "noul", "noul": 0.20}) == "NO"


def test_decision_fabric_blocks_on_missing_provider():
    class Broken:
        name = "broken"

        def evaluate(self, **kwargs):
            raise RuntimeError("missing credential")

    result = DecisionFabric(provider=Broken()).evaluate(
        state={"task": "x"},
        questions={"ok": {"type": "noul", "instructions": "Is it safe?"}},
    )
    assert result.status == "BLOCK"
    assert "unavailable" in result.reason
    assert DecisionFabric(provider=Broken()).classify(result) == {}


def test_decision_fabric_blocks_mismatched_answers():
    provider = FakeProvider({"model": "jev-1.13.0", "answers": {"other": {"type": "noul", "noul": 1.0}}})
    result = DecisionFabric(provider=provider).evaluate(
        state={},
        questions={"expected": {"type": "noul", "instructions": "Is it valid?"}},
    )
    assert result.status == "BLOCK"
    assert "does not match" in result.reason
