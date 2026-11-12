"""The tables every app has, defined once: settings, the copy of the core's family list (CorePerson, Role), who
has opened the app (AppUser) and their browsers' sessions (WebSession). An app's own `models.py` imports them, so they are on SQLModel's metadata
with the app's own tables and its Alembic migrations see them all.

The kit ships no migrations: each app's migrations already made these tables, and a change to one here needs a
migration in every app.
"""

from sqlmodel import Field, SQLModel


class Setting(SQLModel, table=True):
    """One key/value setting (settings.py)."""

    key: str = Field(primary_key=True)
    value: str
