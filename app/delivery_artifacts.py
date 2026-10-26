"""Operator-side staging of a reserved delivery artifact.

Never dispatch from this module. All paths and payment state fail closed
until the authenticated provider recheck and external recipient delivery are built.
"""


def stage_delivery(tenant_id, session_id, reservation_id, filename,
                   recipient_sha256, *, dry_run=True):
    return {"status": "BLOCKED", "delivery_sent": False}
