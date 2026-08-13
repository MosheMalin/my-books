# -*- coding: utf-8 -*-
"""InviteStore — outstanding ways into an account (P4.3).

Its own port, unlike the four tenancy entities that share one: an invite
HAS an independent lifetime (minted, waits days, consumed or expires or is
revoked), which is exactly the split criterion the tenancy port's own
docstring states. Account-scoped like its subject.

Same credential contract as the AuthStore: every stored token is a HASH,
single-use is the store's atomic consume, and a raced accept resolves to
one winner. Revocation is a DELETE here, not a tombstone — an invite that
never minted anything leaves nothing behind worth explaining; the
membership it creates is the durable record.
"""
from __future__ import annotations

from typing import Protocol

from app.domain.invites import Invite


class InviteStore(Protocol):
    """Invites, keyed by token hash, listed by account."""

    def save_invite(self, invite: Invite) -> None:
        """Insert. Hashes are unique by construction (256 bits); a
        duplicate raises rather than re-arming anything.

        ⚠ Referential integrity (the account and creator existing) is the
        SQLITE adapter's own defence-in-depth, not part of this contract —
        the memory adapter holds no tenancy and cannot check. The route
        passes ids it just resolved, so the FK firing means a programmer
        error, not a request."""

    def get_invite(self, token_hash: str) -> Invite | None:
        ...

    def list_open_invites(self, account_id: str, *, now: str) -> tuple[Invite, ...]:
        """Unconsumed, unexpired invites of this account, oldest first —
        what the admin's screen shows beside a revoke button. Metadata
        only, by construction: nothing stored can reproduce the link."""

    def consume_invite(self, token_hash: str, *, by: str, now: str) -> Invite | None:
        """The single-use gate, same shape as the login token's: returns
        the invite and marks it consumed atomically IF it is live, else
        ``None`` with nothing changed."""

    def revoke_invite(self, account_id: str, token_hash: str) -> bool:
        """Delete an invite of THIS account. ``False`` when there was
        nothing to delete. The account id narrows it — one admin must not
        be able to revoke another customer's invite by guessing hashes."""
