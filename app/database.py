import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

DB_PATH = os.getenv("OLA_EG_DB_PATH", "ola.db")
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()


def install_append_only_triggers():
    with engine.begin() as conn:
        conn.exec_driver_sql("""
        CREATE TRIGGER IF NOT EXISTS evidence_no_update
        BEFORE UPDATE ON evidence_records
        BEGIN SELECT RAISE(ABORT, 'evidence_records is append-only'); END;
        """)
        conn.exec_driver_sql("""
        CREATE TRIGGER IF NOT EXISTS evidence_no_delete
        BEFORE DELETE ON evidence_records
        BEGIN SELECT RAISE(ABORT, 'evidence_records is append-only'); END;
        """)

def ensure_evidence_hash_schema():
    """Additive, idempotent SQLite change; never rewrite or rehash old evidence.

    Legacy rows retain hash_version=1; only newly appended rows use v2.
    Caller must retain an external trusted backup/anchor before production GO.
    """
    with engine.connect() as connection:
        # Writers from multiple workers must not race to ALTER the same table.
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            cols = {row[1] for row in connection.exec_driver_sql(
                "PRAGMA table_info(evidence_records)"
            ).fetchall()}
            if not cols:
                raise RuntimeError("evidence_records table must exist")
            if "hash_version" not in cols:
                connection.exec_driver_sql(
                    "ALTER TABLE evidence_records "
                    "ADD COLUMN hash_version INTEGER NOT NULL DEFAULT 1"
                )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise


def ensure_api_key_access_schema():
    """Add authority and revocation metadata without reissuing legacy keys.

    Existing keys retain Core authority. Only explicit new issuance produces a
    review-only credential; key order/count never assigns a reviewer role.
    """
    with engine.connect() as connection:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            columns = {row[1] for row in connection.exec_driver_sql(
                "PRAGMA table_info(api_keys)"
            ).fetchall()}
            if not columns:
                raise RuntimeError("api_keys table must exist")
            if "access_scope" not in columns:
                connection.exec_driver_sql(
                    "ALTER TABLE api_keys ADD COLUMN access_scope TEXT "
                    "NOT NULL DEFAULT 'OLA_CORE' "
                    "CHECK (access_scope IN ('OLA_CORE','REVIEW_RESULT'))"
                )
            invalid = connection.exec_driver_sql(
                "SELECT COUNT(*) FROM api_keys WHERE access_scope IS NULL "
                "OR access_scope NOT IN ('OLA_CORE','REVIEW_RESULT')"
            ).scalar_one()
            if invalid:
                raise RuntimeError("api_keys contains an unsupported access scope")
            if "revoked_at" not in columns:
                connection.exec_driver_sql(
                    "ALTER TABLE api_keys ADD COLUMN revoked_at INTEGER"
                )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
