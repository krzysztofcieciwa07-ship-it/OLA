#!/usr/bin/env python3
"""Apply the additive OLA PostgreSQL schema using a dedicated migration role.

Set OLA_DATABASE_MIGRATION_URL to a PostgreSQL URL whose role owns the OLA
schema. The API and worker must use OLA_DATABASE_URL with a separate runtime
role. This script is an explicit deployment step; application startup never
runs PostgreSQL DDL.
"""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine

from app.database import database_url_from_env, migrate_postgres_schema


def main() -> int:
    raw_url = os.getenv("OLA_DATABASE_MIGRATION_URL", "").strip()
    if not raw_url:
        raise SystemExit("OLA_DATABASE_MIGRATION_URL is required")
    url = database_url_from_env({"OLA_DATABASE_URL": raw_url})
    if not url.startswith("postgresql+psycopg://"):
        raise SystemExit("migration URL must use PostgreSQL with Psycopg 3")
    runtime_role = os.getenv("OLA_DATABASE_RUNTIME_ROLE", "ola_runtime").strip()
    worker_role = os.getenv("OLA_DATABASE_WORKER_ROLE", "ola_worker").strip()
    if not runtime_role or not worker_role or runtime_role == worker_role:
        raise SystemExit("OLA_DATABASE_RUNTIME_ROLE and a distinct OLA_DATABASE_WORKER_ROLE are required")
    migration_engine = create_engine(url, pool_pre_ping=True)
    try:
        migrate_postgres_schema(
            migration_engine, runtime_role=runtime_role, worker_role=worker_role,
        )
    finally:
        migration_engine.dispose()
    print("OLA_POSTGRES_SCHEMA=VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
