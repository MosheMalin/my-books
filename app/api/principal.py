# -*- coding: utf-8 -*-
"""The session principal — who is asking, read from the cookie (P4.1b).

This is the module that ended the dev-trusted era. ``app/main.py`` binds
:func:`session_principal` as the app's principal provider; every request to
a principal-dependent route resolves its caller HERE, from the
``booksnap_session`` cookie, against the AuthStore. No cookie, a revoked
session, an expired one — all the same 401, with the one remedy in the
detail: sign in.

⚠ A separate module from ``deps.py`` for the same reason ``policy.py`` is:
H2's structural test walks ``deps.py`` and fails on any function that
resolves a library, and identity is a different concern with its own test
surface. Nothing here may name a library — the Principal port itself lost
that property at P4.1b (see ``app.ports.Principal``).

**The rolling refresh lives here**, because this is the one place every
authenticated request passes: when a live session's remaining life dips
under the threshold (`app.domain.auth.refreshed`), the row is rewritten
with its expiry pushed out — one write a month per device, not one per
request. A failure to refresh must never fail the request: the session IS
live, and the refresh is bookkeeping.
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status

from app.api import deps
from app.domain.auth import hash_token, refreshed
from app.ports import Clock, Principal
from app.ports.auth import AuthStore

_SIGN_IN = "not signed in — request a sign-in link and follow it"


@dataclass(frozen=True)
class SessionPrincipal:
    """Implements ``app.ports.Principal``: an id, nothing else."""

    id: str


def session_principal(
    request: Request,
    auth: AuthStore = Depends(deps.get_auth_store),
    clock: Clock = Depends(deps.get_clock),
) -> Principal:
    """The cookie's session, or 401.

    Missing, invented, revoked and expired cookies are ONE answer — the
    remedy is identical, and distinguishing them on the wire tells an
    attacker which stolen cookies were nearly fresh.
    """
    raw = request.cookies.get(deps.SESSION_COOKIE)
    if not raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, _SIGN_IN)
    now = clock.now_iso()
    session = auth.get_session(hash_token(raw))
    if session is None or not session.live(now):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, _SIGN_IN)
    rolled = refreshed(session, now)
    if rolled is not None:
        auth.save_session(rolled)
    return SessionPrincipal(id=session.user_id)
