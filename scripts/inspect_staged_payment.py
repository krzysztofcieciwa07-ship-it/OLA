"""Read-only provider snapshot for an operator-staged OLA artifact.

No entitlement, delivery, refund, charge or irreversible side effect.
"""
import argparse
import json
import sys

from app.payment_recheck import inspect_staged_payment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--reservation-id", required=True)
    parser.add_argument("--filename", required=True)
    parser.add_argument("--recipient-sha256", required=True)
    args = parser.parse_args()
    status = inspect_staged_payment(
        args.tenant_id, args.session_id, args.reservation_id,
        args.filename, args.recipient_sha256,
    )
    print(json.dumps(status, sort_keys=True))
    return 0 if status["status"] == "PROVIDER_SNAPSHOT_CLEAR_MANUAL_REVIEW" else 2


if __name__ == "__main__":
    sys.exit(main())
