#!/usr/bin/env python3
"""Prune expired secure-bridge nonces using a separate PostgreSQL maintenance role.

Set OLA_DATABASE_MIGRATION_URL to the PostgreSQL URL for a migration/maintenance
principal. The online API runtime must not receive DELETE privilege on the nonce
ledger merely to perform retention cleanup.
"""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine

from app.database import database_url_from_env
from app.secure_bridge import prune_expired_nonces


def main() -> int:
    raw_url = os.getenv("OLA_DATABASE_MIGRATION_URL", "").strip()
    if not raw_url:
        raise SystemExit("OLA_DATABASE_MIGRATION_URL is required")
    url = database_url_from_env({"OLA_DATABASE_URL": raw_url})
    if not url.startswith("postgresql+psycopg://"):
        raise SystemExit("maintenance URL must use PostgreSQL with Psycopg 3")

    maintenance_engine = create_engine(url, pool_pre_ping=True)
    try:
        pruned = prune_expired_nonces(maintenance_engine)
    finally:
        maintenance_engine.dispose()
    print(f"OLA_SECURE_BRIDGE_EXPIRED_NONCES_PRUNED={pruned}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
