"""Anonymous-session service: token issuing, hashing, lookup, expiry.

Tokens are cryptographically random and never stored -- only their SHA-256
hash. HTTP concerns (cookies, status codes) stay in routes/dependencies.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum

from sqlalchemy import select
from sqlalchemy.orm import Session

from saudi_plot_api.database import utcnow
from saudi_plot_api.models import (
    SESSION_STATUS_ACTIVE,
    SESSION_STATUS_EXPIRED,
    AnonymousSession,
)

_TOKEN_BYTES = 32


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass
class IssuedSession:
    session: AnonymousSession
    token: str  # returned once, to be set as a cookie; never persisted


def create_session(db: Session, ttl_seconds: int) -> IssuedSession:
    token = secrets.token_urlsafe(_TOKEN_BYTES)
    now = utcnow()
    session = AnonymousSession(
        token_hash=hash_token(token),
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(seconds=ttl_seconds),
        status=SESSION_STATUS_ACTIVE,
    )
    db.add(session)
    db.commit()
    return IssuedSession(session=session, token=token)


class SessionResolution(Enum):
    OK = "ok"
    MISSING = "missing"
    EXPIRED = "expired"


def resolve_session(db: Session, token: str) -> tuple[AnonymousSession | None, SessionResolution]:
    """Look up a session by its raw token and enforce status/expiry.

    A valid session gets its ``last_seen_at`` refreshed. An expired one is
    marked ``expired`` in place so the state is visible in the database.
    """
    row = db.execute(
        select(AnonymousSession).where(AnonymousSession.token_hash == hash_token(token))
    ).scalar_one_or_none()
    if row is None:
        return None, SessionResolution.MISSING

    now = utcnow()
    if row.status != SESSION_STATUS_ACTIVE or row.expires_at <= now:
        if row.status == SESSION_STATUS_ACTIVE:
            row.status = SESSION_STATUS_EXPIRED
            db.commit()
        return None, SessionResolution.EXPIRED

    row.last_seen_at = now
    db.commit()
    return row, SessionResolution.OK
