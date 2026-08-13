# -*- coding: utf-8 -*-
"""Google and Apple sign-in — the pure rules (P4.2, VISION §3).

The **authorization-code flow with PKCE**, and nothing else. No implicit
flow, no password, no provider SDK: three redirects and one back-channel
POST, all of which are ours to state exactly.

**One person is one User, anchored on the VERIFIED email.** A provider that
says "this address is confirmed mine" is answering the same question the
magic link answers — so signing in with Google to an address that already
signed in by link lands on the SAME user, and no account is duplicated. An
UNVERIFIED address is refused outright: it would let anyone who can type
your address into their own provider account walk into your library.

**Why no JWT signature check.** OIDC Core §3.1.3.7 permits exactly this
omission for the code flow, and only for it: the ID Token arrives over a
TLS connection WE opened to the provider's own token endpoint, with a URL
this module pins, so TLS server authentication has already established who
said it. There is no attacker-supplied token to verify — the thing an
attacker CAN supply is the redirect back, which is why the state below is
single-use and server-side. If a future flow ever accepts an ID Token from
the front channel, this reasoning evaporates and a JWKS check becomes
mandatory.

⚠ Everything an attacker can hand us gets checked: the state (single-use,
unexpired, and BOUND TO THE BROWSER that started the flow), the nonce
(bound to that state), the issuer, the audience, the expiry and the
email's verified flag.

⚠⚠ The browser binding is the one that was missing, and "single-use and
server-side" is not a substitute for it — that was this module's own
first claim, and it was wrong. Single-use stops a REPLAY; nothing stopped
FIXATION: an attacker began a flow as themselves, kept the code and
state, and handed the victim the finished callback URL, whose browser was
then issued a session for the ATTACKER's account (measured end to end,
P4.2's security review — including the escalation where a victim with a
pending invite spent it against that session and gave the attacker a
standing membership in their own household). See `OAuthState.belongs_to`.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass
from datetime import timedelta

from app.domain.auth import (
    _at,
    _iso,
    hash_token,
    normalize_email,
    valid_email_shape,
)

#: A person clicking through a provider's consent screen — generous
#: enough for a password manager and a second factor, short enough that a
#: link left in a browser tab is not a standing door.
STATE_LIFETIME = timedelta(minutes=15)


class OAuthError(Exception):
    """The provider's answer cannot be trusted, or is not usable.

    One exception for every rejection on purpose: which check failed is a
    fact for the server log, never for the wire (the same reasoning that
    makes expired, consumed and invented links one 401).
    """


@dataclass(frozen=True)
class Provider:
    """One identity provider, as DATA — the endpoints are theirs, not ours.

    ``issuer`` is what their ID Token must claim; a mismatch means the
    answer came from somewhere else and is refused.
    """

    key: str
    issuer: str
    authorize_endpoint: str
    token_endpoint: str
    scopes: str
    #: Apple posts the callback cross-site (``response_mode=form_post``),
    #: which is why the state cannot live in a SameSite=Lax cookie and is
    #: server-side instead. Recorded here because it is the constraint
    #: that shaped the storage decision.
    form_post: bool = False


GOOGLE = Provider(
    key="google",
    issuer="https://accounts.google.com",
    authorize_endpoint="https://accounts.google.com/o/oauth2/v2/auth",
    token_endpoint="https://oauth2.googleapis.com/token",
    scopes="openid email",
)

APPLE = Provider(
    key="apple",
    issuer="https://appleid.apple.com",
    authorize_endpoint="https://appleid.apple.com/auth/authorize",
    token_endpoint="https://appleid.apple.com/auth/token",
    scopes="openid email",
    form_post=True,
)

PROVIDERS = {p.key: p for p in (GOOGLE, APPLE)}


@dataclass(frozen=True)
class OAuthState:
    """One in-flight sign-in. Single-use, like every other credential here.

    Server-side rather than a cookie because Apple's ``form_post`` reply is
    a cross-site POST, which a ``SameSite=Lax`` cookie does not accompany —
    the state would simply be absent exactly when it is needed.
    """

    state_hash: str
    provider: str
    nonce: str
    verifier: str
    created_at: str
    expires_at: str
    consumed_at: str | None = None
    #: Where to send the person afterwards. Carried through the flow so a
    #: shared invite link survives a detour through Google.
    next_hash: str = ""
    #: The hash of a secret handed to the STARTING browser as a cookie.
    #: Single-use stops a replay; this is what stops FIXATION — without
    #: it, an attacker who begins a flow can hand a victim the finished
    #: callback and log that victim into the attacker's account (measured,
    #: P4.2's security review). Empty means unbound, which
    #: :meth:`belongs_to` refuses.
    binding_hash: str = ""

    def live(self, now: str) -> bool:
        return self.consumed_at is None and now < self.expires_at

    def belongs_to(self, binding: str) -> bool:
        """Whether the browser presenting the callback is the one that
        started the flow. Fails CLOSED on an unbound row."""
        if not self.binding_hash or not binding:
            return False
        return secrets.compare_digest(self.binding_hash, hash_token(binding))


@dataclass(frozen=True)
class VerifiedIdentity:
    """What a provider told us, once every check has passed."""

    email: str
    subject: str
    provider: str


def new_state(state: str, provider: str, nonce: str, verifier: str,
              now: str, next_hash: str = "", binding: str = "") -> OAuthState:
    return OAuthState(
        state_hash=hash_token(state),
        provider=provider,
        nonce=nonce,
        verifier=verifier,
        created_at=now,
        expires_at=_iso(_at(now) + STATE_LIFETIME),
        next_hash=next_hash,
        binding_hash=hash_token(binding) if binding else "",
    )


def pkce_challenge(verifier: str) -> str:
    """S256, never ``plain``.

    PKCE binds the code to the client that asked for it. ``plain`` puts
    the verifier in the front-channel request, which is the one part of
    this flow that travels through the user's browser and their history.
    """
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def identity_from_claims(claims: dict, provider: Provider,
                         client_id: str, nonce: str,
                         now: float | None = None) -> VerifiedIdentity:
    """Every check an attacker-influenced answer has to survive.

    Order matters only for what the log says; each is independently
    sufficient to refuse. The email's VERIFIED flag is the load-bearing
    one: without it, anyone who types your address into a provider account
    they control signs in as you.

    ⚠ ``exp`` is checked HERE, not in the adapter. It lived there, and the
    port's contract says this function IS the checklist — so a provider
    written to that contract accepted an indefinitely stale token
    (measured at review). One list, one place.
    """
    expiry = claims.get("exp")
    if not isinstance(expiry, (int, float)) or isinstance(expiry, bool):
        raise OAuthError("the id_token has no expiry")
    moment = time.time() if now is None else now
    if moment > float(expiry):
        raise OAuthError("the id_token has expired")

    if claims.get("iss") != provider.issuer:
        raise OAuthError(f"issuer {claims.get('iss')!r} is not {provider.issuer}")

    audience = claims.get("aud")
    audiences = audience if isinstance(audience, list) else [audience]
    if client_id not in audiences:
        raise OAuthError("this token was issued for a different client")

    if not nonce or claims.get("nonce") != nonce:
        # Binds the token to the request WE started — the replay guard for
        # an id_token captured from some other sign-in.
        raise OAuthError("nonce does not match the request that started this")

    email = normalize_email(str(claims.get("email") or ""))
    if not email:
        raise OAuthError("the provider returned no email address")
    if not valid_email_shape(email):
        # The same door the magic link uses. Neither Google nor Apple
        # emits a CRLF address — but this token's signature is unchecked
        # BY DESIGN, so "the provider would not" is the only thing
        # standing here, and it stops standing the day a third provider
        # is configured (P4.2's security review).
        raise OAuthError("the provider returned an unusable email address")

    verified = claims.get("email_verified")
    # Apple sends the flag as a JSON string ("true"), Google as a bool.
    if verified not in (True, "true"):
        raise OAuthError(f"{email} is not verified with this provider")

    subject = str(claims.get("sub") or "")
    if not subject:
        raise OAuthError("the provider returned no subject")

    return VerifiedIdentity(email=email, subject=subject,
                            provider=provider.key)
