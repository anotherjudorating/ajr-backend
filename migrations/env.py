from logging.config import fileConfig

from alembic import context
from sqlalchemy import text
from sqlmodel import SQLModel

import ajr.core.models  # noqa: F401  (registers the tables)
from ajr.core.db import engine
from ajr.core.models import SCHEMA

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def only_our_schema(name, type_, parent_names):
    """Supabase has many schemas of its own (auth, storage, ...): leave them alone."""
    if type_ == "schema":
        return name == SCHEMA
    return True


with engine.connect() as connection:
    # Alembic keeps its version table in our schema, so the schema must exist first.
    connection.execute(text(f"create schema if not exists {SCHEMA}"))
    connection.commit()

    context.configure(
        connection=connection,
        target_metadata=SQLModel.metadata,
        include_schemas=True,
        include_name=only_our_schema,
        version_table_schema=SCHEMA,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()
