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
import re
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
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("worker claim batch limit must be between 1 and 100")
    if type(stale_after_seconds) is not int or not 60 <= stale_after_seconds <= 86400:
        raise ValueError("worker claim lease must be between 60 and 86400 seconds")
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


def verify_worker_database_identity(
    worker_engine,
    expected_role: str,
    runtime_role: str = "ola_runtime",
) -> None:
    """Fail closed unless the worker DSN and claim-function owner are isolated."""
    role_pattern = r"[A-Za-z_][A-Za-z0-9_$]{0,62}"
    if not isinstance(expected_role, str) or re.fullmatch(role_pattern, expected_role) is None:
        raise RuntimeError("OLA_DATABASE_WORKER_ROLE is invalid")
    if not isinstance(runtime_role, str) or re.fullmatch(role_pattern, runtime_role) is None:
        raise RuntimeError("OLA_DATABASE_RUNTIME_ROLE is invalid")
    if runtime_role == expected_role:
        raise RuntimeError("OLA_DATABASE_RUNTIME_ROLE and OLA_DATABASE_WORKER_ROLE must be distinct")

    protected_tables = [
        "tenants",
        "api_keys",
        "evidence_records",
        "stripe_events",
        "checkout_orders",
        "checkout_order_controls",
        "checkout_execution_jobs",
        "checkout_report_reviews",
        "ola_schema_migrations",
    ]
    with worker_engine.connect() as conn:
        identity = conn.execute(
            text("""
                SELECT
                    current_user AS role_name,
                    session_user AS session_role,
                    r.rolsuper,
                    r.rolbypassrls,
                    r.rolinherit,
                    r.rolcreatedb,
                    r.rolcreaterole,
                    r.rolreplication,
                    r.rolcanlogin,
                    EXISTS (
                        SELECT 1
                        FROM pg_auth_members AS memberships
                        WHERE memberships.member = pg_catalog.to_regrole(current_user::text)::oid
                           OR memberships.roleid = pg_catalog.to_regrole(current_user::text)::oid
                    ) AS has_role_membership,
                    has_schema_privilege(current_user, current_schema(), 'USAGE') AS schema_usage,
                    has_schema_privilege(current_user, current_schema(), 'CREATE') AS schema_create,
                    EXISTS (
                        SELECT 1
                        FROM pg_namespace AS n
                        CROSS JOIN LATERAL aclexplode(
                            COALESCE(n.nspacl, acldefault('n', n.nspowner))
                        ) AS acl
                        WHERE n.nspname = current_schema()
                          AND acl.grantee = 0
                    ) AS schema_public_acl,
                    EXISTS (
                        SELECT 1
                        FROM pg_namespace AS n
                        CROSS JOIN LATERAL aclexplode(
                            COALESCE(n.nspacl, acldefault('n', n.nspowner))
                        ) AS acl
                        WHERE n.nspname = current_schema()
                          AND acl.grantee = pg_catalog.to_regrole(current_user::text)::oid
                          AND acl.is_grantable
                    ) AS schema_grant_option,
                    COALESCE((
                        SELECT array_agg(DISTINCT pg_get_userbyid(acl.grantee)::text)
                        FROM pg_namespace AS n
                        CROSS JOIN LATERAL aclexplode(
                            COALESCE(n.nspacl, acldefault('n', n.nspowner))
                        ) AS acl
                        WHERE n.nspname = current_schema()
                          AND acl.grantee <> 0
                          AND acl.grantee <> n.nspowner
                          AND acl.grantee NOT IN (
                              pg_catalog.to_regrole(current_user::text)::oid,
                              pg_catalog.to_regrole(:runtime_role)::oid
                          )
                    ), ARRAY[]::text[]) AS extra_schema_grantees,
                    COALESCE(has_function_privilege(
                        current_user,
                        to_regprocedure(format(
                            '%I.ola_claim_checkout_jobs(integer,integer)',
                            current_schema()
                        )),
                        'EXECUTE'
                    ), false) AS claim_execute,
                    COALESCE(has_function_privilege(
                        current_user,
                        to_regprocedure(format(
                            '%I.ola_authenticate_api_key(text)',
                            current_schema()
                        )),
                        'EXECUTE'
                    ), false) AS auth_execute,
                    COALESCE((
                        SELECT p.prosecdef
                        FROM pg_proc AS p
                        WHERE p.oid = to_regprocedure(format(
                            '%I.ola_claim_checkout_jobs(integer,integer)',
                            current_schema()
                        ))
                    ), false) AS claim_security_definer,
                    COALESCE((
                        SELECT p.proconfig @> ARRAY['search_path=pg_catalog']::text[]
                        FROM pg_proc AS p
                        WHERE p.oid = to_regprocedure(format(
                            '%I.ola_claim_checkout_jobs(integer,integer)',
                            current_schema()
                        ))
                    ), false) AS claim_search_path_fixed,
                    (
                        SELECT pg_get_userbyid(p.proowner)::text
                        FROM pg_proc AS p
                        WHERE p.oid = to_regprocedure(format(
                            '%I.ola_claim_checkout_jobs(integer,integer)',
                            current_schema()
                        ))
                    ) AS claim_owner,
                    EXISTS (
                        SELECT 1
                        FROM pg_proc AS p
                        CROSS JOIN LATERAL aclexplode(
                            COALESCE(p.proacl, acldefault('f', p.proowner))
                        ) AS acl
                        WHERE p.oid = to_regprocedure(format(
                            '%I.ola_claim_checkout_jobs(integer,integer)',
                            current_schema()
                        ))
                          AND acl.grantee = 0
                          AND acl.privilege_type = 'EXECUTE'
                    ) AS claim_public_execute,
                    EXISTS (
                        SELECT 1
                        FROM pg_proc AS p
                        CROSS JOIN LATERAL aclexplode(
                            COALESCE(p.proacl, acldefault('f', p.proowner))
                        ) AS acl
                        WHERE p.oid = to_regprocedure(format(
                            '%I.ola_claim_checkout_jobs(integer,integer)',
                            current_schema()
                        ))
                          AND acl.privilege_type = 'EXECUTE'
                          AND acl.grantee <> p.proowner
                          AND acl.is_grantable
                    ) AS claim_execute_grant_option,
                    COALESCE((
                        SELECT array_agg(DISTINCT pg_get_userbyid(acl.grantee)::text)
                        FROM pg_proc AS p
                        CROSS JOIN LATERAL aclexplode(
                            COALESCE(p.proacl, acldefault('f', p.proowner))
                        ) AS acl
                        WHERE p.oid = to_regprocedure(format(
                            '%I.ola_claim_checkout_jobs(integer,integer)',
                            current_schema()
                        ))
                          AND acl.privilege_type = 'EXECUTE'
                          AND acl.grantee <> 0
                          AND acl.grantee <> p.proowner
                          AND acl.grantee <> pg_catalog.to_regrole(current_user::text)::oid
                    ), ARRAY[]::text[]) AS claim_extra_execute_grantees,
                    COALESCE((
                        SELECT bool_or(has_table_privilege(
                            current_user,
                            format('%I.%I', current_schema(), scoped.table_name),
                            privilege.privilege
                        ))
                        FROM unnest(CAST(:table_names AS text[])) AS scoped(table_name)
                        CROSS JOIN unnest(ARRAY[
                            'SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE',
                            'REFERENCES', 'TRIGGER', 'MAINTAIN'
                        ]) AS privilege(privilege)
                    ), false) AS has_direct_table_privileges
                FROM pg_roles AS r
                WHERE r.rolname = current_user
            """),
            {
                "table_names": protected_tables,
                "runtime_role": runtime_role,
            },
        ).mappings().one_or_none()

    if identity is None or identity["role_name"] != expected_role:
        actual = None if identity is None else identity["role_name"]
        raise RuntimeError(
            f"PostgreSQL worker DSN identity mismatch: expected {expected_role}, got {actual}"
        )
    if identity["session_role"] != expected_role:
        raise RuntimeError(
            "PostgreSQL worker DSN session identity mismatch: "
            f"expected {expected_role}, got {identity['session_role']}"
        )

    if identity["auth_execute"]:
        raise RuntimeError("PostgreSQL worker role must not execute the API-key authentication function")
    if (
        not identity["claim_execute"]
        or not identity["claim_security_definer"]
        or not identity["claim_search_path_fixed"]
        or identity["claim_owner"] in {None, expected_role, runtime_role}
        or identity["claim_public_execute"]
        or identity["claim_execute_grant_option"]
        or identity["claim_extra_execute_grantees"]
    ):
        raise RuntimeError(
            "PostgreSQL worker claim function ACL/SECURITY DEFINER configuration is not least-privilege"
        )

    forbidden_flags = (
        "rolsuper", "rolbypassrls", "rolinherit",
        "rolcreatedb", "rolcreaterole", "rolreplication",
    )
    if any(bool(identity[name]) for name in forbidden_flags) or not identity["rolcanlogin"]:
        raise RuntimeError(
            "PostgreSQL worker role must be LOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS "
            "NOCREATEDB NOCREATEROLE NOREPLICATION"
        )
    if identity["has_role_membership"]:
        raise RuntimeError("PostgreSQL worker role must not participate in any role membership")
    if not identity["schema_usage"] or identity["schema_create"]:
        raise RuntimeError("PostgreSQL worker role requires schema USAGE and must not have schema CREATE")
    if (
        identity["schema_public_acl"]
        or identity["schema_grant_option"]
        or identity["extra_schema_grantees"]
    ):
        raise RuntimeError("PostgreSQL worker schema ACL is not least-privilege")
    if not identity["claim_execute"]:
        raise RuntimeError("PostgreSQL worker role cannot execute ola_claim_checkout_jobs")
    if identity["has_direct_table_privileges"]:
        raise RuntimeError("PostgreSQL worker role must not have direct privileges on tenant-owned tables")


def _validate_dispatch_config(api_url: str, worker_token: str) -> None:
    if not isinstance(api_url, str) or not api_url.strip():
        raise ValueError("OLA_EXECUTION_API_URL is required")
    parsed = urlsplit(api_url)
    if (parsed.scheme != "https" or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment):
        raise ValueError("OLA_EXECUTION_API_URL must be an absolute HTTPS URL without embedded credentials")
    if (not isinstance(worker_token, str) or not 32 <= len(worker_token) <= 256
            or not worker_token.isascii()
            or any(ord(char) < 33 or ord(char) > 126 for char in worker_token)):
        raise ValueError("OLA_EXECUTION_WORKER_TOKEN must be between 32 and 256 printable ASCII characters")


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
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("worker claim batch limit must be between 1 and 100")
        if type(stale_after_seconds) is not int or not 60 <= stale_after_seconds <= 86400:
            raise ValueError("worker claim lease must be between 60 and 86400 seconds")
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
    if args.poll_seconds < 1 or not 60 <= args.stale_after_seconds <= 86400:
        parser.error("poll interval must be >=1s and stale timeout must be between 60s and 86400s")

    logging.basicConfig(level=os.getenv("OLA_LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    worker_url = os.getenv("OLA_DATABASE_WORKER_URL", "").strip()
    api_url = os.getenv("OLA_EXECUTION_API_URL", "").strip()
    worker_token = os.getenv("OLA_EXECUTION_WORKER_TOKEN", "")
    worker_role = os.getenv("OLA_DATABASE_WORKER_ROLE", "ola_worker").strip()
    runtime_role = os.getenv("OLA_DATABASE_RUNTIME_ROLE", "ola_runtime").strip()

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
            verify_worker_database_identity(
                worker_engine, worker_role, runtime_role=runtime_role,
            )
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
