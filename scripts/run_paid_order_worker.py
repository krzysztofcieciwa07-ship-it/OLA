#!/usr/bin/env python3
"""Run the durable paid-order outbox worker inside the OLA trust boundary.

The worker is intentionally single-attempt: QUEUED jobs execute once; a stale
RUNNING job is marked INTERRUPTED and never replayed automatically. A human
must reconcile any ambiguous result before a future, separately authorized run.
"""
import argparse
import logging
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import or_, select

from app.database import SessionLocal, prepare_runtime_schema
from app.models import CheckoutExecutionJob
from app.paid_order_execution import execute_paid_order_job, PaidOrderExecutionRejected

LOG = logging.getLogger("ola.paid-order-worker")


def pending_job_ids(*, now: int | None = None, stale_after_seconds: int = 900, limit: int = 20):
    current = int(time.time()) if now is None else int(now)
    stale_before = current - stale_after_seconds
    with SessionLocal() as db:
        rows = db.scalars(
            select(CheckoutExecutionJob)
            .where(or_(
                CheckoutExecutionJob.status == "QUEUED",
                (CheckoutExecutionJob.status == "RUNNING") &
                ((CheckoutExecutionJob.started_at <= stale_before) | (CheckoutExecutionJob.started_at.is_(None))),
            ))
            .order_by(CheckoutExecutionJob.created_at.asc())
            .limit(limit)
        ).all()
        return [row.id for row in rows]


def run_once(*, now: int | None = None, stale_after_seconds: int = 900) -> int:
    job_ids = pending_job_ids(now=now, stale_after_seconds=stale_after_seconds)
    exit_code = 0
    for job_id in job_ids:
        try:
            result = execute_paid_order_job(job_id, now=now, stale_after_seconds=stale_after_seconds)
            status = result.get("status")
            LOG.info("job=%s status=%s run_id=%s", job_id, status, result.get("run_id"))
            if status in {"EXECUTED_BLOCKED", "FAILED", "INTERRUPTED", "BLOCKED"}:
                exit_code = 1
        except PaidOrderExecutionRejected as exc:
            LOG.warning("job=%s rejected status=%s reason=%s", job_id, exc.code, str(exc))
            exit_code = 1
        except Exception:
            LOG.exception("job=%s worker failure", job_id)
            exit_code = 1
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="process the current batch and exit")
    parser.add_argument("--poll-seconds", type=float, default=float(os.getenv("OLA_EXECUTION_WORKER_POLL_SECONDS", "5")))
    parser.add_argument("--stale-after-seconds", type=int, default=int(os.getenv("OLA_EXECUTION_WORKER_STALE_SECONDS", "900")))
    args = parser.parse_args()
    if args.poll_seconds < 1 or args.stale_after_seconds < 60:
        parser.error("poll interval must be >=1s and stale timeout >=60s")

    logging.basicConfig(level=os.getenv("OLA_LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    prepare_runtime_schema()
    LOG.info("paid-order worker started; poll=%ss stale_after=%ss", args.poll_seconds, args.stale_after_seconds)
    if args.once:
        return run_once(stale_after_seconds=args.stale_after_seconds)
    while True:
        run_once(stale_after_seconds=args.stale_after_seconds)
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
