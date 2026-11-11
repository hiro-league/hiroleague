"""Key/value settings stored in the app's database (edited from its Settings page, or kept by the app itself).

Each app names its own keys (its `settings.py`: HA's address, Frigate's); reading and writing them is here.
"""

from sqlmodel import Session

from .models import Setting


def get(session: Session, key: str) -> str | None:
    row = session.get(Setting, key)
    return row.value if row else None


def put(session: Session, key: str, value: str | None) -> None:
    row = session.get(Setting, key)
    if value is None:
        if row:
            session.delete(row)
    elif row:
        row.value = value
    else:
        session.add(Setting(key=key, value=value))
