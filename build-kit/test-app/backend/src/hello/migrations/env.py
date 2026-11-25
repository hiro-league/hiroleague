"""Alembic environment: uses the app's engine and SQLModel metadata."""

from alembic import context
from sqlmodel import SQLModel

from hello import models  # noqa: F401  (registers the tables; first: the package tells the kit which app this is)
from hiro_extension_kit.db import engine

with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=SQLModel.metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()
