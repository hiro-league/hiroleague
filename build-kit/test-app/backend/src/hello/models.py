"""Hello's one table, beside the kit's (Setting): a greeting, so an upgrade has a database to copy and migrate."""

import hiro_extension_kit.models  # noqa: F401  (the kit's Setting table: Alembic sees it)
from sqlmodel import Field, SQLModel


class Greeting(SQLModel, table=True):
    id: int = Field(default=None, primary_key=True)
    words: str
