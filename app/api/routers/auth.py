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

Since P4.1b the session cookie these routes mint is the ONLY identity:
the resolver reads it per request (`app.api.principal`), and the dev
principal is deleted, not parked.

⚠ The cookie's ``Secure`` flag is a per-DEPLOYMENT fact
(`deps.get_session_secure`), not a constant: on plain HTTP a Secure cookie
is silently dropped — a login that "worked" and left you logged out — so
the LAN dev flow runs without it and the TLS deployment (P4.4's compose
file, which is what puts TLS in front) sets BOOKSNAP_SESSION_SECURE=1.
"""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse

from app import API_PREFIX
from app.api import deps
from app.api.dto import (
    LoginLinkRequest,
    ProvidersDTO,
    SessionCreate,
    UserDTO,
)
from app.domain import User
from app.domain.auth import (
    LINK_RATE_PER_EMAIL,
    LINK_RATE_PER_EMAIL_WIDE,
    LINK_RATE_PER_SOURCE,
    LINK_RATE_WINDOW,
    SESSION_LIFETIME,
    hash_token,
    new_login_token,
    new_session,
    normalize_email,
    rate_window_start,
    valid_email_shape,
)
from app.domain.oauth import (
    PROVIDERS,
    STATE_LIFETIME,
    OAuthError,
    new_state,
    pkce_challenge,
)
from app.ports import Clock, IdGen
from app.ports.auth import AuthStore, Mailer
from app.ports.oauth import IdentityProvider, OAuthStateStore
from app.ports.tenancy import EmailTaken, TenancyStore

router = APIRouter(prefix="/auth", tags=["auth"])

#: Where a refused provider sign-in lands. The client reads it and shows
#: one sentence — the person clicked a button, so a JSON error page would
#: be the product answering a human in a language it reserves for
#: machines.
OAUTH_FAILED = "#/login?error=provider"

#: A `next` is one of this client's own routes; anything longer is not
#: one. Capped because `/start` is an unauthenticated write.
_MAX_NEXT = 200


def _failed() -> RedirectResponse:
    """One answer for every refusal, and the binding cookie cleared with
    it — a flow that ended has no second attempt."""
    answer = RedirectResponse(f"/{OAUTH_FAILED}",
                              status_code=status.HTTP_303_SEE_OTHER)
    answer.delete_cookie(deps.OAUTH_COOKIE, path=f"{API_PREFIX}/auth/oauth")
    return answer


def _source_hash(request: Request) -> str:
    """The requesting client's address, hashed for the rate window.

    Honestly: an UNSALTED hash of an IP is a rate-limit key, not
    anonymisation — the IPv4 space brute-forces in minutes. It is stored
    this way because the counter needs a deterministic lookup, and it
    stops being stored at all once the row ages past the window (the
    purge in the route below). Whatever string the transport presents is
    one bucket — Starlette's test client presents the literal host
    "testclient", a transport with no peer at all presents "" — and a
    shared bucket only ever errs toward stricter.

    ⚠ P4.4: this reads the DIRECT peer. Behind the TLS reverse proxy that
    item adds, every caller becomes 127.0.0.1 and the per-source door
    turns into a whole-service cap (15 requests lock everyone out for an
    hour — measured at review). The fix belongs to the deployment: run
    uvicorn with --proxy-headers --forwarded-allow-ips=<proxy>, never an
    unconditional X-Forwarded-For read here (that hands the bypass back).
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
    if not valid_email_shape(email):
        # Shape, not validity — see LoginLinkRequest's ⚠. This 422 refuses
        # what no mail could reach AND what must not ride into the Mailer
        # (CRLF into a real message is header injection; the review
        # measured a forged Bcc landing verbatim).
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "that does not look like an email address")
    now = clock.now_iso()
    since = rate_window_start(now)
    source = _source_hash(request)
    # Expired tokens serve no redeem and no rate window; what they DO hold
    # is an address in cleartext, forever, for anyone who ever typed one.
    # Each request sweeps — no cron to forget, cost one indexed DELETE.
    auth.purge_login_tokens(before=since)
    # The narrow door is the (address × source) PAIR — see the constants'
    # comment for why address-alone was a lockout an attacker could aim.
    if (auth.count_recent_login_tokens(email=email, source_hash=source,
                                       since=since) >= LINK_RATE_PER_EMAIL
            or auth.count_recent_login_tokens(source_hash=source, since=since)
            >= LINK_RATE_PER_SOURCE
            or auth.count_recent_login_tokens(email=email, since=since)
            >= LINK_RATE_PER_EMAIL_WIDE):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"too many sign-in links; try again in "
            f"{int(LINK_RATE_WINDOW.total_seconds() // 60)} minutes",
        )
    token = secrets.token_urlsafe(32)
    auth.save_login_token(new_login_token(token, email, now, source_hash=source))
    mailer.send_login_link(email, token)
    # `delivery` is a fact about the transport, identical for every
    # address — the anti-enumeration answer above it is untouched.
    return {"detail": "if that address can sign in here, a link is on its way",
            "delivery": mailer.delivery}


@router.post("/session", response_model=UserDTO,
             status_code=status.HTTP_201_CREATED)
def redeem_login_link(
    body: SessionCreate,
    response: Response,
    auth: AuthStore = Depends(deps.get_auth_store),
    tenancy: TenancyStore = Depends(deps.get_tenancy_store),
    clock: Clock = Depends(deps.get_clock),
    ids: IdGen = Depends(deps.get_id_gen),
    secure: bool = Depends(deps.get_session_secure),
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
        try:
            user = User(id=ids.new_id(), email=token.email, created_at=now)
            tenancy.save_user(user)
        except EmailTaken:
            # Two redeems for one never-seen address raced the read above
            # (two links opened at once, a mail client prefetching while
            # the human taps). The loser's answer is the winner's user —
            # one address, one identity, whoever wrote the row.
            user = tenancy.user_by_email(token.email)
            if user is None:  # pragma: no cover — the row just refused us
                raise
    session_token = secrets.token_urlsafe(32)
    auth.save_session(new_session(session_token, user.id, now))
    response.set_cookie(
        deps.SESSION_COOKIE,
        session_token,
        max_age=int(SESSION_LIFETIME.total_seconds()),
        httponly=True,       # a script that can read the cookie can BE you
        samesite="lax",      # the link lands via navigation; Lax lets it in
        secure=secure,       # see the module note: per-deployment, not fixed
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

# --- Google and Apple (P4.2, VISION §3) -----------------------------------


def _form_post(key: str) -> bool:
    """Whether this provider posts its callback cross-site.

    Read from the domain's registry, not off the adapter: the
    response mode is a fact about Apple, and `IdentityProvider`
    promises only `key`/`authorize_url`/`exchange`.
    """
    known = PROVIDERS.get(key)
    return bool(known and known.form_post)


def _provider(key: str, providers: dict) -> IdentityProvider:
    configured = providers.get(key)
    if configured is None:
        # Not "unknown provider": whether Apple is configured is a fact
        # about this deployment, and the client asks `/auth/providers`
        # rather than guessing.
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"{key!r} sign-in is not configured here")
    return configured


@router.get("/providers", response_model=ProvidersDTO,
            summary="Which sign-in providers are configured")
def list_providers(
    providers: dict = Depends(deps.get_identity_providers),
) -> ProvidersDTO:
    """So the login screen can offer exactly the buttons that WORK.

    A dangling "Sign in with Apple" on a deployment with no Apple key is
    the absent-not-disabled rule broken at the first screen anyone sees.
    """
    return ProvidersDTO(providers=sorted(providers))


@router.get("/oauth/{provider}/start",
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            summary="Begin a provider sign-in")
def start_oauth(
    provider: str,
    request: Request,
    next: str = "",
    auth: AuthStore = Depends(deps.get_auth_store),
    states: OAuthStateStore = Depends(deps.get_oauth_state_store),
    providers: dict = Depends(deps.get_identity_providers),
    clock: Clock = Depends(deps.get_clock),
    secure: bool = Depends(deps.get_session_secure),
) -> RedirectResponse:
    """Mint the state, the nonce and the PKCE verifier, then redirect.

    All three are `secrets`, never `IdGen`: they are credentials, and the
    test id generator is reproducible on purpose (the same rule the
    session token carries).
    """
    chosen = _provider(provider, providers)
    now = clock.now_iso()
    states.purge_states(before=now)

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(16)
    verifier = secrets.token_urlsafe(64)
    binding = secrets.token_urlsafe(32)
    # `next` is a HASH fragment of our own client, never a URL: an open
    # redirect is the classic hole in exactly this parameter, so nothing
    # that could name another origin is accepted — and the QUERY is
    # dropped, because a client that put an invite token there would have
    # us store a live grant in cleartext (measured at review; the client
    # no longer sends one, and this is why it could not matter if it did).
    # Capped, because this is an unauthenticated write.
    safe_next = next.split("?")[0][:_MAX_NEXT] if (
        next.startswith("#/") and "//" not in next) else ""
    states.save_state(new_state(state, chosen.key, nonce, verifier, now,
                                next_hash=safe_next, binding=binding))

    answer = RedirectResponse(
        chosen.authorize_url(state=state, nonce=nonce,
                             challenge=pkce_challenge(verifier)),
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    )
    # ⚠ THE anti-fixation cookie. Without it, an attacker starts a flow as
    # themselves, keeps code+state, and hands the victim the finished
    # callback URL — the victim's browser is then issued a session for the
    # ATTACKER's user, and everything they catalogue next lands in the
    # attacker's library (measured end to end at review, including the
    # escalation to a standing membership through a pending invite).
    #
    # SameSite: Apple's callback is a cross-site POST, which `lax` does
    # not accompany — so a form_post provider needs `none`, which needs
    # `Secure`, which Apple's own HTTPS-only redirect requirement
    # guarantees. Google's is a top-level GET, where `lax` is enough and
    # is the tighter choice.
    answer.set_cookie(
        deps.OAUTH_COOKIE,
        binding,
        max_age=int(STATE_LIFETIME.total_seconds()),
        httponly=True,
        samesite="none" if _form_post(chosen.key) else "lax",
        secure=secure or _form_post(chosen.key),
        path=f"{API_PREFIX}/auth/oauth",
    )
    return answer


@router.get("/oauth/{provider}/callback", include_in_schema=False)
def oauth_callback_get(
    provider: str,
    request: Request,
    response: Response,
    code: str = "",
    state: str = "",
    auth: AuthStore = Depends(deps.get_auth_store),
    tenancy: TenancyStore = Depends(deps.get_tenancy_store),
    states: OAuthStateStore = Depends(deps.get_oauth_state_store),
    providers: dict = Depends(deps.get_identity_providers),
    clock: Clock = Depends(deps.get_clock),
    ids: IdGen = Depends(deps.get_id_gen),
    secure: bool = Depends(deps.get_session_secure),
) -> RedirectResponse:
    """Google's redirect back: a top-level GET."""
    return _finish_oauth(provider, code, state,
                         request.cookies.get(deps.OAUTH_COOKIE, ""),
                         auth, tenancy, states, providers, clock, ids, secure)


@router.post("/oauth/{provider}/callback", include_in_schema=False)
async def oauth_callback_post(
    provider: str,
    request: Request,
    response: Response,
    auth: AuthStore = Depends(deps.get_auth_store),
    tenancy: TenancyStore = Depends(deps.get_tenancy_store),
    states: OAuthStateStore = Depends(deps.get_oauth_state_store),
    providers: dict = Depends(deps.get_identity_providers),
    clock: Clock = Depends(deps.get_clock),
    ids: IdGen = Depends(deps.get_id_gen),
    secure: bool = Depends(deps.get_session_secure),
) -> RedirectResponse:
    """Apple's redirect back: a cross-site form POST.

    ⚠ This is the route that decides where the flow's state may live. A
    cross-site POST carries no SameSite=Lax cookie, so the state is
    server-side — and the single-use consume below is what makes this
    unauthenticated POST safe to expose at all.
    """
    form = await request.form()
    return _finish_oauth(provider, str(form.get("code") or ""),
                         str(form.get("state") or ""),
                         request.cookies.get(deps.OAUTH_COOKIE, ""),
                         auth, tenancy, states, providers, clock, ids, secure)


def _finish_oauth(provider: str, code: str, state: str, binding: str,
                  auth: AuthStore, tenancy: TenancyStore,
                  states: OAuthStateStore, providers: dict, clock: Clock,
                  ids: IdGen, secure: bool) -> RedirectResponse:
    """One implementation for both response modes.

    Every refusal lands the person back on the login screen with one
    honest sentence, rather than a JSON error in a browser they arrived
    at by clicking a button — this is the only route in the product whose
    caller is a REDIRECT, not the client's own fetch.
    """
    chosen = _provider(provider, providers)
    now = clock.now_iso()
    in_flight = states.consume_state(hash_token(state), now=now) if state else None
    if (in_flight is None or in_flight.provider != chosen.key or not code
            or not in_flight.belongs_to(binding)):
        # Replayed, forged, expired, for a different provider, or — the
        # one this list was missing — presented by a browser that did not
        # start it. One answer for all of them, like every other
        # credential refusal here.
        return _failed()
    try:
        identity = chosen.exchange(code=code, verifier=in_flight.verifier,
                                   nonce=in_flight.nonce)
    except OAuthError:
        return _failed()

    # THE anchor: a verified address is a verified address, whoever
    # confirmed it. Signing in with Google to the address that has been
    # using magic links lands on the SAME user (§4.1 — one person, one
    # identity), and no second account is minted.
    user = tenancy.user_by_email(identity.email)
    if user is None:
        try:
            user = User(id=ids.new_id(), email=identity.email, created_at=now)
            tenancy.save_user(user)
        except EmailTaken:                       # raced another sign-in
            user = tenancy.user_by_email(identity.email)
            if user is None:  # pragma: no cover
                raise

    session_token = secrets.token_urlsafe(32)
    auth.save_session(new_session(session_token, user.id, now))
    landing = RedirectResponse(f"/{in_flight.next_hash or ''}",
                               status_code=status.HTTP_303_SEE_OTHER)
    # The flow is over: the binding cookie has no second use.
    landing.delete_cookie(deps.OAUTH_COOKIE, path=f"{API_PREFIX}/auth/oauth")
    landing.set_cookie(
        deps.SESSION_COOKIE,
        session_token,
        max_age=int(SESSION_LIFETIME.total_seconds()),
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )
    return landing
