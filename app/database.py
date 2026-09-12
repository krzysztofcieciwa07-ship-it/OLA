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
