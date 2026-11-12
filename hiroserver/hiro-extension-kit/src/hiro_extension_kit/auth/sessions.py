"""Browsers signed in at the app's address (Phase 8: through HiroLeague's sign-in, api.py): a random token in an
HttpOnly cookie, its hash in `websession`. The user is a core person (AppUser.id).

A session lasts until it goes unused for SESSION_DAYS, or its user signs out. Retention: expired
sessions are deleted at each sign-in (`purge`).
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, col, delete, select

from .. import identity
from ..models import WebSession

COOKIE = f"{identity.app().name}_session"  # nethiro_session
SESSION_DAYS = 90
TOUCH_EVERY = timedelta(hours=1)  # how often last_used (and so the expiry) moves on


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def start(session: Session, user_id: str, device: str) -> str:
    """A new session for this user; the token to put in the cookie."""
    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    session.add(WebSession(id=_hash(token), user_id=user_id, device=device, created_at=now, last_used=now,
                           expires_at=now + timedelta(days=SESSION_DAYS)))
    session.commit()
    return token


def user_of(session: Session, token: str) -> str | None:
    """The user a cookie's token signs in, or None (unknown, or expired)."""
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
    return s.user_id


def end(session: Session, token: str) -> None:
    if token:
        session.exec(delete(WebSession).where(col(WebSession.id) == _hash(token)))
        session.commit()


def purge(session: Session) -> int:
    """Delete the expired sessions; how many."""
    old = session.exec(select(WebSession).where(col(WebSession.expires_at) <= datetime.now(UTC))).all()
    for s in old:
        session.delete(s)
    session.commit()
    return len(old)
