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


def test_enabled_human_identity_enforcement_cannot_be_disabled_or_deleted():
    import uuid

    import pytest
    from sqlalchemy import delete, insert, update
    from sqlalchemy.exc import SQLAlchemyError

    from app.models import HumanIdentityEnforcement

    table = HumanIdentityEnforcement.__table__
    row_id = str(uuid.uuid4())
    with engine.begin() as connection:
        connection.execute(insert(table).values(id=row_id, required=True))

    with pytest.raises(SQLAlchemyError):
        with engine.begin() as connection:
            connection.execute(
                update(table).where(table.c.id == row_id).values(required=False)
            )

    with pytest.raises(SQLAlchemyError):
        with engine.begin() as connection:
            connection.execute(delete(table).where(table.c.id == row_id))
