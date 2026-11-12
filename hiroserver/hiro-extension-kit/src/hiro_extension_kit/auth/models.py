"""The family tables of the kit's sign-in: the copy of the core's family list (CorePerson, Role), who has opened the
app (AppUser) and their browsers' sessions (WebSession). An app that uses the kit's sign-in, family copy and route
check (auth/, family.py) imports this module in its models.py, so its migrations see them (NetHiro, TrainHiro).
HomeHiro keeps its own for now: its users have more (HA person links, My room) and come in one more way.
"""

from datetime import datetime

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


class CorePerson(SQLModel, table=True):
    """A person in HiroLeague's family list: the app's copy of the core's `people.list`, replaced by each sync
    (family.py). The core owns them; the app changes them only by asking it. Kept while the core lists them."""

    id: str = Field(primary_key=True)  # the core's person_id
    name: str
    calls_them: str = ""  # what Hiro calls them ("" = their name)
    whatsapp: str = ""  # digits with the country code ("" = none)
    role_id: str  # the core's role id (a Role row once synced)
    synced_at: datetime


class Role(SQLModel, table=True):
    """What a group of users may do in the app (auth/): the rights it has, per feature (auth/access.py). "owner" is
    built in and always has everything. The whole role comes from HiroLeague's family list (family.py): its name, its
    line, and the rights the owner grants it in the app there; this row is the app's copy."""

    id: str = Field(primary_key=True)  # the core's role id ("owner", "adult", "kid", a slug)
    name: str = Field(unique=True)
    says: str = ""  # one line on what it is for, shown when picking a role
    built_in: bool = False
    core: bool = False  # seen in the core's list (every row the app keeps is: a role the core drops is removed)
    rights: list[str] = Field(default_factory=list, sa_column=Column(JSON))  # Phase 9a: "<feature>.<right>" keys
    created_at: datetime
    updated_at: datetime


class AppUser(SQLModel, table=True):
    """Someone who has opened the app: a person in HiroLeague's family list, with their role. They come in signed in
    at HiroLeague (auth/api.py `/api/auth/hiro`; Phase 8's one sign-in)."""

    id: str = Field(primary_key=True)  # the core's person id
    name: str  # their name in the family list, as last seen
    # A cache: their role in HiroLeague's family list (family.py `recompute_roles`); None while the app's copy doesn't
    # have it yet.
    role_id: str | None = Field(default=None, foreign_key="role.id", index=True)
    denied: bool = False  # the owner chose No access
    first_seen: datetime
    last_seen: datetime
    last_way: str = ""  # "web" (signed in at HiroLeague)
    last_device: str = ""  # "iPhone", "Windows PC"...


class WebSession(SQLModel, table=True):
    """A browser signed in at the app's address, through HiroLeague's sign-in (auth/sessions.py, Phase 8). Only the
    token's hash is kept; the token itself is in the browser's cookie. Kept until it goes unused for SESSION_DAYS or
    the user signs out; expired ones are deleted at the next sign-in."""

    id: str = Field(primary_key=True)  # sha256 of the token
    user_id: str = Field(foreign_key="appuser.id", index=True)
    device: str = ""  # "Windows PC", "iPhone"...
    created_at: datetime
    last_used: datetime
    expires_at: datetime
