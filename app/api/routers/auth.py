# -*- coding: utf-8 -*-
"""Sign-in: §3's email magic link (P4.1a).

Three routes, all PRE-AUTH — the closed exemption class beside
``_USER_SCOPED`` in ``tests/test_api.py``: they resolve no principal and no
library, because they are how a caller BECOMES one. Everything else about
them is deliberately narrow:

  - **the answer never says whether an address is known.** Requesting a link
    for a stranger's email and for a member's email return the same 202 —
    an enumeration door on the sign-in route undoes §4.2's 404-never-403
    everywhere else;
  - **rate-limited at two doors** (per address, per source), read from
    `app.domain.auth`'s constants — a guard against loops and abuse, not a
    quota (§1.2's precedent);
  - **the token is minted here, stored hashed, and leaves exactly once** —
    into the Mailer. Not through ``IdGen``: ids are reproducible on purpose
    in tests, and a session credential must never inherit that property by
    someone swapping an adapter.

⚠ In P4.1a these routes are ADDITIVE: the dev principal still answers every
other request, and nothing consumes the session cookie yet. P4.1b points the
resolver at it and deletes the dev identity — the plan
(`planning/LOGIN_PLAN.md`) stages the cutover deliberately.

⚠ The cookie carries no ``Secure`` flag yet: the household flow is plain
HTTP on the LAN until P4.4 puts TLS in front, and a Secure cookie on HTTP
is a cookie the browser silently drops — a login that "worked" and left
you logged out. P4.4 revisits with the deployment.
"""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.api import deps
from app.api.dto import LoginLinkRequest, SessionCreate, UserDTO
from app.domain import User
from app.domain.auth import (
    LINK_RATE_PER_EMAIL,
    LINK_RATE_PER_SOURCE,
    LINK_RATE_WINDOW,
    SESSION_LIFETIME,
    hash_token,
    new_login_token,
    new_session,
    normalize_email,
    rate_window_start,
)
from app.ports import Clock, IdGen
from app.ports.auth import AuthStore, Mailer
from app.ports.tenancy import TenancyStore

router = APIRouter(prefix="/auth", tags=["auth"])


def _source_hash(request: Request) -> str:
    """The requesting client's address, hashed for the rate window.

    Hashed like a token — the address itself has no business persisting.
    Empty when the transport has none (the test client): those requests
    then share one bucket, which only ever errs toward stricter.
    """
    host = request.client.host if request.client else ""
    return hash_token(host)


@router.post("/link", status_code=status.HTTP_202_ACCEPTED)
def request_login_link(
    body: LoginLinkRequest,
    request: Request,
    auth: AuthStore = Depends(deps.get_auth_store),
    mailer: Mailer = Depends(deps.get_mailer),
    clock: Clock = Depends(deps.get_clock),
) -> dict:
    """Mail a sign-in link. **202 whatever the address is** — known member,
    stranger, or future sign-up all read the same, so the route cannot be
    used to enumerate who has an account here."""
    email = normalize_email(body.email)
    if "@" not in email or len(email) < 3:
        # Shape, not validity — see LoginLinkRequest's ⚠. This 422 is for
        # "that is not an email at all", which no mail could ever reach.
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "that does not look like an email address")
    now = clock.now_iso()
    since = rate_window_start(now)
    source = _source_hash(request)
    if (auth.count_recent_login_tokens(email=email, since=since)
            >= LINK_RATE_PER_EMAIL
            or auth.count_recent_login_tokens(source_hash=source, since=since)
            >= LINK_RATE_PER_SOURCE):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"too many sign-in links; try again within "
            f"{int(LINK_RATE_WINDOW.total_seconds() // 60)} minutes",
        )
    token = secrets.token_urlsafe(32)
    auth.save_login_token(new_login_token(token, email, now, source_hash=source))
    mailer.send_login_link(email, token)
    return {"detail": "if that address can sign in here, a link is on its way"}


@router.post("/session", response_model=UserDTO,
             status_code=status.HTTP_201_CREATED)
def redeem_login_link(
    body: SessionCreate,
    response: Response,
    auth: AuthStore = Depends(deps.get_auth_store),
    tenancy: TenancyStore = Depends(deps.get_tenancy_store),
    clock: Clock = Depends(deps.get_clock),
    ids: IdGen = Depends(deps.get_id_gen),
) -> UserDTO:
    """Trade an emailed token for a session cookie.

    Single-use is the STORE's atomic consume — two racing redeems of one
    link mint one session. Expired, consumed and invented tokens are the
    same 401: the caller's remedy is identical (request a new link), and
    distinguishing them tells an attacker which guesses were nearly right.

    A first-ever address mints its User here — the bare identity row. It
    owns nothing and belongs to nowhere until P4.1c's sign-up gives it an
    account and a first library; `list_accounts` answering empty for it is
    a real state the switcher already renders.
    """
    now = clock.now_iso()
    token = auth.consume_login_token(hash_token(body.token), now=now)
    if token is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            "that link is expired or already used — "
                            "request a new one")
    user = tenancy.user_by_email(token.email)
    if user is None:
        user = User(id=ids.new_id(), email=token.email, created_at=now)
        tenancy.save_user(user)
    session_token = secrets.token_urlsafe(32)
    auth.save_session(new_session(session_token, user.id, now))
    response.set_cookie(
        deps.SESSION_COOKIE,
        session_token,
        max_age=int(SESSION_LIFETIME.total_seconds()),
        httponly=True,       # a script that can read the cookie can BE you
        samesite="lax",      # the link lands via navigation; Lax lets it in
        path="/",
    )
    return UserDTO(id=user.id, display_name=user.display_name)


@router.delete("/session", status_code=status.HTTP_204_NO_CONTENT)
def sign_out(
    request: Request,
    response: Response,
    auth: AuthStore = Depends(deps.get_auth_store),
    clock: Clock = Depends(deps.get_clock),
) -> None:
    """Revoke the cookie's session — a tombstone, not a delete.

    204 whether or not a live session was presented: sign-out is a state to
    arrive at, not an action to fail. The cookie is cleared either way.
    """
    raw = request.cookies.get(deps.SESSION_COOKIE)
    if raw:
        auth.revoke_session(hash_token(raw), at=clock.now_iso())
    response.delete_cookie(deps.SESSION_COOKIE, path="/")