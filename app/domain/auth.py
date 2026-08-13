# -*- coding: utf-8 -*-
"""Sessions and login tokens — the pure rules of §3's magic link (P4.1a).

VISION §3, the decided spec in six words: **rate-limited, single-use,
expiring**. This module holds every number and every rule; the stores
enforce single-use atomically, the routes enforce the rate, and both read
the policy from here so there is exactly one copy of each (CLAUDE.md §6).

⚠ NOT in ``tenancy.py`` on purpose. ``test_a_role_says_who_you_are_and_never_
what_you_may_do`` keeps authorization vocabulary out of that module; a
session is AUTHENTICATION — who is asking — and it lives one module over for
the same hygiene in the other direction: nothing here knows what a Role is.

**Secrets are stored HASHED, always.** A session cookie and a login link
both carry the raw token exactly once, to the client; the database holds
``sha256(token)``. A leaked database then contains nothing that logs anyone
in — CLAUDE.md's credential hygiene, applied to tokens we mint rather than
keys we hold.

Timestamps are ISO-8601 UTC strings, the ``Clock`` port's own format;
comparisons are lexical, which is correct for one fixed format and is the
same convention every other aggregate uses.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

#: 90-day rolling sessions (owner, 2026-08-13): a household app on personal
#: phones — short lifetimes punish the capture flow. Revocation is the
#: server-side answer to a lost phone, not a short expiry.
SESSION_LIFETIME = timedelta(days=90)

#: "Rolling" without a write per request: a session is REFRESHED (expiry
#: pushed back out to the full lifetime) only once the remaining life dips
#: under this. One write a month per device, not one per tap.
SESSION_REFRESH_BELOW = timedelta(days=60)

#: A login link is an emailed credential; it outlives a coffee break, never
#: an afternoon inbox.
TOKEN_LIFETIME = timedelta(minutes=15)

#: §3's "rate-limited", the two doors: per address (an attacker guessing
#: emails burns this) and per source (one machine hammering many addresses
#: burns this). Windows are an hour, like §1.2's run-rate cap — a guard
#: against loops and abuse, not a quota.
LINK_RATE_PER_EMAIL = 5
LINK_RATE_PER_SOURCE = 15
LINK_RATE_WINDOW = timedelta(hours=1)


def hash_token(token: str) -> str:
    """What the database holds instead of the token. One way, one place."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def normalize_email(email: str) -> str:
    """One address, one spelling: trimmed, lowercased.

    Case-folding the whole address (not just the domain) technically drops a
    distinction RFC 5321 allows — and every real mail provider ignores. The
    alternative is `Moshe@` and `moshe@` becoming two users of one inbox,
    which is a duplicate identity for a standards point nobody exercises.
    """
    return email.strip().lower()


def _at(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


@dataclass(frozen=True)
class Session:
    """One signed-in device. The cookie carries the raw token; this carries
    its hash. ``revoked_at`` is a tombstone, never a delete — "when did this
    device stop being trusted" is an answer worth keeping."""

    token_hash: str
    user_id: str
    created_at: str
    expires_at: str
    revoked_at: str | None = None

    def live(self, now: str) -> bool:
        return self.revoked_at is None and now < self.expires_at


@dataclass(frozen=True)
class LoginToken:
    """One emailed link. ``source_hash`` is the requesting client's hashed
    address, kept for the per-source rate window — never the address itself,
    which has no business persisting."""

    token_hash: str
    email: str
    created_at: str
    expires_at: str
    source_hash: str = ""
    consumed_at: str | None = None


def new_session(token: str, user_id: str, now: str) -> Session:
    return Session(
        token_hash=hash_token(token),
        user_id=user_id,
        created_at=now,
        expires_at=_iso(_at(now) + SESSION_LIFETIME),
    )


def refreshed(session: Session, now: str) -> Session | None:
    """The rolling rule: the same session with its expiry pushed back out,
    or ``None`` when no write is due — not-yet-worn sessions and dead ones
    both answer ``None``, because neither should touch the store."""
    if not session.live(now):
        return None
    if _at(session.expires_at) - _at(now) >= SESSION_REFRESH_BELOW:
        return None
    return replace(session, expires_at=_iso(_at(now) + SESSION_LIFETIME))


def rate_window_start(now: str) -> str:
    """Where §3's rate window opens, for the store's counting query."""
    return _iso(_at(now) - LINK_RATE_WINDOW)


def new_login_token(token: str, email: str, now: str,
                    source_hash: str = "") -> LoginToken:
    return LoginToken(
        token_hash=hash_token(token),
        email=normalize_email(email),
        created_at=now,
        expires_at=_iso(_at(now) + TOKEN_LIFETIME),
        source_hash=source_hash,
    )
