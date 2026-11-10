import pytest

from app.hashchain import PUBLIC_PRODUCER, TRUSTED_PRODUCER, sealed_payload_json


@pytest.mark.parametrize("record_type", [
    "firewall.request.received",
    "firewall.decision.made",
    "firewall.approval.granted",
    "firewall.execution.start",
    "firewall.execution.end",
    "ledger.checkpoint",
])
def test_public_tenant_producer_cannot_forge_firewall_lifecycle(record_type):
    with pytest.raises(ValueError, match="public producer"):
        sealed_payload_json(record_type, {"decision": "ALLOW"}, producer=PUBLIC_PRODUCER)


def test_trusted_runtime_can_write_firewall_lifecycle():
    payload = sealed_payload_json(
        "firewall.decision.made", {"decision": "BLOCK"}, producer=TRUSTED_PRODUCER
    )
    assert '"producer":"ola_runtime"' in payload
