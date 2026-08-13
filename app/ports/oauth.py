# -*- coding: utf-8 -*-
"""The provider port and the in-flight state store (P4.2).

``IdentityProvider`` is the seam that keeps Google's and Apple's
differences out of the routes — different secret schemes, different
response modes, one interface — and keeps the tests off the network. The
API ring drives a stub; ``app/main.py`` binds the real one.

``OAuthStateStore`` gets its own port rather than joining ``AuthStore``
for the reason the tenancy port already states about lifetimes: an
in-flight sign-in lives for minutes and is consumed once, which is a
different object from a 90-day session. Same credential contract as every
other store here: what is stored is a HASH, and consuming is atomic.
"""
from __future__ import annotations

from typing import Protocol

from app.domain.oauth import OAuthState, VerifiedIdentity


class IdentityProvider(Protocol):
    """One configured provider — Google or Apple."""

    @property
    def key(self) -> str:
        """``"google"`` / ``"apple"`` — matches `app.domain.oauth.PROVIDERS`."""

    def authorize_url(self, *, state: str, nonce: str, challenge: str) -> str:
        """Where to send the person's browser. Front-channel, so it carries
        only values that are safe in a URL bar and a history entry."""

    def exchange(self, *, code: str, verifier: str, nonce: str) -> VerifiedIdentity:
        """Trade the code for an identity, back-channel.

        Raises :class:`app.domain.oauth.OAuthError` for anything that does
        not check out. Implementations must apply
        :func:`app.domain.oauth.identity_from_claims` rather than reading
        claims themselves — that function IS the checklist, and a second
        copy of it is a copy that will drift.
        """


class OAuthStateStore(Protocol):
    """In-flight sign-ins, keyed by the hash of the state parameter."""

    def save_state(self, state: OAuthState) -> None:
        """Insert. Hashes are unique by construction (256 bits)."""

    def consume_state(self, state_hash: str, *, now: str) -> OAuthState | None:
        """The single-use gate, atomic: returns the state and marks it
        consumed IF it is live, else ``None`` with nothing changed. A
        replayed callback therefore gets nothing, which is the CSRF
        property this parameter exists for."""

    def purge_states(self, *, before: str) -> int:
        """Drop states whose expiry is behind ``before``; returns how many.
        Swept on the way past like login tokens and invites — an expired
        state opens nothing and answers nothing."""
