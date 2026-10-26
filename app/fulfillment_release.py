"""Operator-only signed delivery reservation (not a customer delivery endpoint).

Intentionally fail-closed scaffold for behavioral RED tests. Implementation
follows the test evidence in this stacked PR.
"""


def reserve_delivery(manifest, signatures, *, igor_public_key, owner_public_key):
    return {"status": "BLOCKED", "reason": "delivery gate not implemented"}
