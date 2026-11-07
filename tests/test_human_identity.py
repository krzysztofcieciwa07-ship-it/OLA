"""Human identity schema foundation tests (red-first)."""
from sqlalchemy import inspect

from app.database import engine


def test_human_identity_schema_contains_core_tables():
    required = {
        "human_principals",
        "human_identity_links",
        "tenant_identity_configs",
        "tenant_memberships",
        "human_identity_enforcement",
    }
    present = set(inspect(engine).get_table_names())
    missing = sorted(required - present)
    assert not missing, f"Human Identity schema is missing tables: {missing}"
