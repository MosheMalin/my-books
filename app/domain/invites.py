# -*- coding: utf-8 -*-
"""Invites — how a user joins an ACCOUNT (P4.3, VISION §4.1 "invite once").

An invite is a share-link, not a mail: the admin mints one and hands the
link over their own channel (the family chat is the household's real
transport), the invitee signs in like anyone else and accepts. Joining is
to the ACCOUNT — the invitee gets every library that customer owns, at the
role the invite carries, which is §4.1's whole point ("a user joins the
ACCOUNT and gets what that account owns, instead of N membership rows that
drift apart").

Token discipline is the magic link's, exactly: the raw token exists in the
link and nowhere else; stores hold ``hash_token`` of it; single-use is the
store's atomic consume. The one deliberate difference is the lifetime — a
login link is an emailed credential (minutes); an invite waits for a
relative to get around to it (days).

⚠ The ROLE rides inside the invite, chosen by the admin at mint time. An
invite must never grant more than its minter could — enforced trivially,
because only an admin may mint (§4.2's MANAGE_MEMBERS row) and admin is
the ceiling.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from app.domain.auth import _at, _iso, hash_token
from app.domain.tenancy import Role

#: Long enough for "אמא, תלחצי על הקישור" to take a weekend; short enough
#: that a link forgotten in a chat scroll is not a standing door. Days,
#: not minutes, on purpose — see the module note.
INVITE_LIFETIME = timedelta(days=7)


@dataclass(frozen=True)
class Invite:
    """One outstanding (or spent) way into an account.

    ``consumed_by`` records WHO accepted — the membership row itself says
    that too, but the membership can later be removed and "who used this
    link" is a fact about the link.
    """

    token_hash: str
    account_id: str
    role: Role
    created_by: str
    created_at: str
    expires_at: str
    consumed_at: str | None = None
    consumed_by: str | None = None

    def live(self, now: str) -> bool:
        return self.consumed_at is None and now < self.expires_at


def new_invite(token: str, account_id: str, role: Role, created_by: str,
               now: str) -> Invite:
    return Invite(
        token_hash=hash_token(token),
        account_id=account_id,
        role=role,
        created_by=created_by,
        created_at=now,
        expires_at=_iso(_at(now) + INVITE_LIFETIME),
    )
