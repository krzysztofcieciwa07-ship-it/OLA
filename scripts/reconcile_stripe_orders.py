"""Inspect or safely reconcile one paid order without ever rerunning execution.

Usage:
  python -m scripts.reconcile_stripe_orders cs_test_...              # read-only
  python -m scripts.reconcile_stripe_orders cs_test_... --apply      # proof-gated

--apply can only restore PENDING_INDEPENDENT_VERIFICATION after full local
hash-chain and agent evidence validation. It cannot approve or deliver work.
"""

import argparse
import json
import os
import sys

from app.stripe_recovery import reconcile_checkout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout_session_id", help="Stripe Checkout Session ID (cs_...)")
    parser.add_argument("--apply", action="store_true", help="Atomically record proven local recovery")
    args = parser.parse_args()
    if args.apply and not os.getenv("OLA_EG_DB_PATH"):
        print("Stripe recovery blocked: explicitly set OLA_EG_DB_PATH before --apply",
              file=sys.stderr)
        return 2
    try:
        result = reconcile_checkout(args.checkout_session_id, apply=args.apply)
    except Exception as exc:
        print(f"Stripe recovery failed closed: {exc.__class__.__name__}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] in {
        "RECOVERABLE_PENDING_REVIEW", "RECORDED_PENDING_REVIEW",
    } else 2


if __name__ == "__main__":
    raise SystemExit(main())
