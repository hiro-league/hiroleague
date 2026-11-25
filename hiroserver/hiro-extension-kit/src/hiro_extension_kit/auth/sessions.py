"""Browsers signed in at the app's address (Phase 8: through HiroLeague's sign-in, api.py): a random token in an
HttpOnly cookie, its hash in `websession`. The user is a core person (AppUser.id).

A session lasts until it goes unused for SESSION_DAYS, or its user signs out. Retention: expired
sessions are deleted at each sign-in (`purge`). Each keeps the person's proof the core gave at sign-in (`core_token`,
Permissions phase 8), sent with what the app asks the core for them.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, col, delete, select

from .. import identity
from .models import WebSession

COOKIE = f"{identity.app().name}_session"  # nethiro_session
SESSION_DAYS = 90
TOUCH_EVERY = timedelta(hours=1)  # how often last_used (and so the expiry) moves on


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def start(session: Session, user_id: str, device: str, core_token: str | None = None) -> str:
    """A new session for this user, with their proof from the core (None: it gave none); the token to put in the
    cookie."""
    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    session.add(WebSession(id=_hash(token), user_id=user_id, device=device, created_at=now, last_used=now,
                           expires_at=now + timedelta(days=SESSION_DAYS), core_token=core_token))
    session.commit()
    return token


def of(session: Session, token: str) -> WebSession | None:
    """The session a cookie's token signs in, or None (unknown, or expired); its use moves the expiry on."""
    if not token:
        return None
    s = session.get(WebSession, _hash(token))
    now = datetime.now(UTC)
    if s is None or s.expires_at <= now:
        return None
    if now - s.last_used >= TOUCH_EVERY:
        s.last_used, s.expires_at = now, now + timedelta(days=SESSION_DAYS)
        session.add(s)
        session.commit()
    return s


def user_of(session: Session, token: str) -> str | None:
    """The user a cookie's token signs in, or None (unknown, or expired)."""
    s = of(session, token)
    return s.user_id if s else None


def end(session: Session, token: str) -> str | None:
    """End the session a cookie's token signs in; the core's proof it kept (None: none), for the core to end too."""
    if not token:
        return None
    s = session.get(WebSession, _hash(token))
    core_token = s.core_token if s else None
    session.exec(delete(WebSession).where(col(WebSession.id) == _hash(token)))
    session.commit()
    return core_token


def purge(session: Session) -> int:
    """Delete the expired sessions; how many."""
    old = session.exec(select(WebSession).where(col(WebSession.expires_at) <= datetime.now(UTC))).all()
    for s in old:
        session.delete(s)
    session.commit()
    return len(old)
