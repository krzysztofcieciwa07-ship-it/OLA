#!/usr/bin/env python3
"""Run the paid-order worker with an isolated PostgreSQL claim credential.

SQLite retains its local polling path. PostgreSQL uses OLA_DATABASE_WORKER_URL
to call only ola_claim_checkout_jobs(), then dispatches opaque claim coordinates
to the tenant-scoped runtime API over HTTPS.
"""
import argparse
import json
import logging
import os
from pathlib import Path
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, or_, select, text

from app.database import (
    SessionLocal,
    database_url_from_env,
    engine as runtime_engine,
    prepare_runtime_schema,
)
from app.models import CheckoutExecutionJob
from app.paid_order_execution import execute_paid_order_job, PaidOrderExecutionRejected

LOG = logging.getLogger("ola.paid-order-worker")


def pending_job_ids(*, now: int | None = None, stale_after_seconds: int = 900, limit: int = 20):
    """Legacy SQLite-only poller; PostgreSQL must use the isolated claim function."""
    if runtime_engine.dialect.name == "postgresql":
        raise RuntimeError("PostgreSQL worker polling requires OLA_DATABASE_WORKER_URL")
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


def claim_postgres_jobs(worker_engine, *, limit: int = 20, stale_after_seconds: int = 900):
    """Claim a bounded batch without granting the worker direct table access."""
    with worker_engine.begin() as conn:
        result = conn.execute(
            text("""
                SELECT job_id, tenant_id, claim_token
                FROM ola_claim_checkout_jobs(:limit, :stale_after)
            """),
            {"limit": limit, "stale_after": stale_after_seconds},
        )
        rows = result.all() if hasattr(result, "all") else list(result)
    claims = []
    for row in rows:
        claim = {
            "job_id": row.job_id,
            "tenant_id": row.tenant_id,
            "claim_token": row.claim_token,
        }
        if any(not isinstance(value, str) or not value for value in claim.values()):
            raise RuntimeError("PostgreSQL claim function returned incomplete claim coordinates")
        claims.append(claim)
    return claims


def _validate_dispatch_config(api_url: str, worker_token: str) -> None:
    if not isinstance(api_url, str) or not api_url.strip():
        raise ValueError("OLA_EXECUTION_API_URL is required")
    parsed = urlsplit(api_url)
    if (parsed.scheme != "https" or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment):
        raise ValueError("OLA_EXECUTION_API_URL must be an absolute HTTPS URL without embedded credentials")
    if (not isinstance(worker_token, str) or len(worker_token) < 32
            or not worker_token.isascii()
            or any(ord(char) < 33 or ord(char) > 126 for char in worker_token)):
        raise ValueError("OLA_EXECUTION_WORKER_TOKEN must be at least 32 printable ASCII characters")


def dispatch_claim_to_api(
    api_url: str,
    worker_token: str,
    claim: dict,
    *,
    stale_after_seconds: int = 900,
) -> dict:
    """Dispatch one claim; tenant and token are headers, never query parameters."""
    _validate_dispatch_config(api_url, worker_token)
    if not isinstance(stale_after_seconds, int) or not 60 <= stale_after_seconds <= 86400:
        raise ValueError("worker claim lease must be between 60 and 86400 seconds")
    if not isinstance(claim, dict) or set(claim) != {"job_id", "tenant_id", "claim_token"}:
        raise ValueError("worker claim must contain only job_id, tenant_id, and claim_token")
    for field in ("job_id", "tenant_id", "claim_token"):
        value = claim[field]
        if (not isinstance(value, str) or not value or len(value) > 256
                or not value.isascii()
                or any(ord(char) < 33 or ord(char) > 126 for char in value)):
            raise ValueError(f"worker claim {field} is invalid")
    if len(claim["tenant_id"]) > 128 or not 16 <= len(claim["claim_token"]) <= 128:
        raise ValueError("worker claim tenant ID or claim token length is invalid")

    endpoint = (
        api_url.rstrip("/")
        + "/internal/checkout-execution/"
        + quote(claim["job_id"], safe="")
        + "/run"
    )
    request = Request(
        endpoint,
        data=b"{}",
        headers={
            "Content-Type": "application/json",
            "X-OLA-Worker-Token": worker_token,
            "X-OLA-Tenant-ID": claim["tenant_id"],
            "X-OLA-Claim-Token": claim["claim_token"],
            "X-OLA-Claim-Stale-After": str(stale_after_seconds),
        },
        method="POST",
    )
    class RejectRedirects(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    try:
        opener = build_opener(RejectRedirects)
        with opener.open(request, timeout=20) as response:
            body = response.read()
            if not 200 <= response.status < 300:
                raise RuntimeError(f"runtime API rejected claim with HTTP {response.status}")
    except HTTPError as exc:
        raise RuntimeError(f"runtime API rejected claim with HTTP {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError("runtime API dispatch failed") from exc
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("runtime API returned a non-JSON response") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("runtime API returned a non-object response")
    return payload


def _failed_execution_status(status) -> bool:
    return status in {"EXECUTED_BLOCKED", "FAILED", "INTERRUPTED", "BLOCKED"}


def run_once(
    *,
    now: int | None = None,
    stale_after_seconds: int = 900,
    worker_engine=None,
    api_url: str | None = None,
    worker_token: str | None = None,
    limit: int = 20,
) -> int:
    if worker_engine is not None:
        _validate_dispatch_config(api_url, worker_token)
        claims = claim_postgres_jobs(
            worker_engine, limit=limit, stale_after_seconds=stale_after_seconds,
        )
        exit_code = 0
        for claim in claims:
            try:
                result = dispatch_claim_to_api(
                    api_url, worker_token, claim,
                    stale_after_seconds=stale_after_seconds,
                )
                status = result.get("status")
                LOG.info(
                    "job=%s tenant=%s status=%s run_id=%s",
                    claim["job_id"], claim["tenant_id"], status, result.get("run_id"),
                )
                if status != "ACCEPTED" or _failed_execution_status(status):
                    LOG.error(
                        "job=%s runtime API returned unexpected acceptance status=%s",
                        claim["job_id"], status,
                    )
                    exit_code = 1
            except Exception:
                LOG.exception("job=%s PostgreSQL claim dispatch failed", claim.get("job_id"))
                exit_code = 1
        return exit_code

    if runtime_engine.dialect.name == "postgresql":
        raise RuntimeError("PostgreSQL worker cannot poll with the shared runtime database credential")
    job_ids = pending_job_ids(now=now, stale_after_seconds=stale_after_seconds, limit=limit)
    exit_code = 0
    for job_id in job_ids:
        try:
            result = execute_paid_order_job(job_id, now=now, stale_after_seconds=stale_after_seconds)
            status = result.get("status")
            LOG.info("job=%s status=%s run_id=%s", job_id, status, result.get("run_id"))
            if _failed_execution_status(status):
                exit_code = 1
        except PaidOrderExecutionRejected as exc:
            LOG.warning("job=%s rejected status=%s reason=%s", job_id, exc.code, str(exc))
            exit_code = 1
        except Exception:
            LOG.exception("job=%s worker failure", job_id)
            exit_code = 1
    return exit_code


def _run_loop(args, *, worker_engine=None, api_url=None, worker_token=None) -> int:
    if args.once:
        return run_once(
            stale_after_seconds=args.stale_after_seconds,
            worker_engine=worker_engine,
            api_url=api_url,
            worker_token=worker_token,
        )
    while True:
        run_once(
            stale_after_seconds=args.stale_after_seconds,
            worker_engine=worker_engine,
            api_url=api_url,
            worker_token=worker_token,
        )
        time.sleep(args.poll_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="process the current batch and exit")
    parser.add_argument("--poll-seconds", type=float, default=float(os.getenv("OLA_EXECUTION_WORKER_POLL_SECONDS", "5")))
    parser.add_argument("--stale-after-seconds", type=int, default=int(os.getenv("OLA_EXECUTION_WORKER_STALE_SECONDS", "900")))
    args = parser.parse_args()
    if args.poll_seconds < 1 or args.stale_after_seconds < 60:
        parser.error("poll interval must be >=1s and stale timeout >=60s")

    logging.basicConfig(level=os.getenv("OLA_LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    worker_url = os.getenv("OLA_DATABASE_WORKER_URL", "").strip()
    api_url = os.getenv("OLA_EXECUTION_API_URL", "").strip()
    worker_token = os.getenv("OLA_EXECUTION_WORKER_TOKEN", "")

    if worker_url:
        try:
            normalized_url = database_url_from_env({"OLA_DATABASE_URL": worker_url})
        except ValueError as exc:
            parser.error(str(exc))
        if not normalized_url.startswith("postgresql+psycopg://"):
            parser.error("OLA_DATABASE_WORKER_URL must use PostgreSQL with Psycopg 3")
        try:
            _validate_dispatch_config(api_url, worker_token)
        except ValueError as exc:
            parser.error(str(exc))
        worker_engine = create_engine(normalized_url, pool_pre_ping=True)
        try:
            LOG.info(
                "isolated PostgreSQL worker started; poll=%ss stale_after=%ss",
                args.poll_seconds, args.stale_after_seconds,
            )
            return _run_loop(
                args, worker_engine=worker_engine, api_url=api_url, worker_token=worker_token,
            )
        finally:
            worker_engine.dispose()

    if runtime_engine.dialect.name == "postgresql":
        raise SystemExit(
            "PostgreSQL worker requires OLA_DATABASE_WORKER_URL, "
            "OLA_EXECUTION_API_URL, and OLA_EXECUTION_WORKER_TOKEN; shared runtime polling is disabled"
        )

    prepare_runtime_schema()
    LOG.info("SQLite paid-order worker started; poll=%ss stale_after=%ss", args.poll_seconds, args.stale_after_seconds)
    return _run_loop(args)


if __name__ == "__main__":
    raise SystemExit(main())
