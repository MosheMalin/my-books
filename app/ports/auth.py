# -*- coding: utf-8 -*-
"""AuthStore and Mailer — the two ports P4.1a adds.

**AuthStore holds credentials-shaped rows, so its contract is sharper than
the other stores':**

  - everything it stores is a HASH (`app.domain.auth.hash_token`); a raw
    token must never reach a store method. There is nothing to enforce that
    mechanically — the argument is a string either way — so the rule is
    stated here, where every implementer reads it;
  - ``consume_login_token`` is the single-use rule, and it must be ATOMIC:
    two concurrent redeems of one link get one session between them. The
    sqlite adapter does it with one guarded UPDATE, the memory adapter with
    a plain dict under the GIL — the contract suite races them both;
  - like :class:`app.ports.tenancy.TenancyStore`, this store is NOT
    library-scoped: it answers who is asking, which exists before any
    library is named. It is user-scoped, and nothing in it may name a
    library or a role.

**Mailer is a port for the same reason the Reader is** (CLAUDE.md: the
credential preflight lives on the port): whether mail can be sent, and how,
is an adapter's business — the dev adapter prints the link to the server
log, the production adapter (P4.4) speaks to a provider. A route never
reads mail configuration out of the environment.
"""
from __future__ import annotations

from typing import Protocol

from app.domain.auth import LoginToken, Session


class AuthStore(Protocol):
    """Sessions and login tokens. All arguments hashed; see the module note."""

    # --- sessions ---------------------------------------------------------

    def save_session(self, session: Session) -> None:
        """Insert or replace by ``token_hash`` — the refresh rule rewrites
        the same row with a later expiry."""

    def get_session(self, token_hash: str) -> Session | None:
        """The row, live or not — the CALLER applies ``Session.live``,
        because "expired" and "revoked" may render differently one day and
        the store should not have an opinion."""

    def revoke_session(self, token_hash: str, *, at: str) -> bool:
        """Tombstone a session. ``False`` when there was nothing to revoke.
        Idempotent: revoking twice keeps the FIRST timestamp — when trust
        ended is a fact, not the latest logout's opinion."""

    # --- login tokens -----------------------------------------------------

    def save_login_token(self, token: LoginToken) -> None:
        """Insert. Token hashes are unique by construction (256 bits)."""

    def consume_login_token(self, token_hash: str, *, now: str) -> LoginToken | None:
        """The single-use gate. Returns the token and marks it consumed in
        one atomic step IF it exists, is unconsumed, and ``now`` is before
        its expiry — else ``None``, with nothing changed. A second redeem
        of the same link gets ``None``, whoever raced it got the token."""

    def count_recent_login_tokens(self, *, email: str | None = None,
                                  source_hash: str | None = None,
                                  since: str) -> int:
        """How many links were minted since ``since`` for this address or
        from this source — §3's rate windows. Exactly one of the two
        filters is given per call."""


class Mailer(Protocol):
    """Outbound mail, magic links only — a wider interface is speculative."""

    def send_login_link(self, email: str, token: str) -> None:
        """Deliver a sign-in link carrying ``token`` to ``email``.

        The adapter composes the URL (the deployment knows its own address;
        the route does not) and MUST treat the token as a credential: into
        the message, never into a log — except the dev adapter, whose whole
        purpose is printing the link for a developer with no mailbox.
        """
