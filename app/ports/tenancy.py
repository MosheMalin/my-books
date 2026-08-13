# -*- coding: utf-8 -*-
"""TenancyStore — accounts, users, libraries and memberships (§4.1).

⚠⚠ **This is the one store in the package that is NOT library-scoped.** Every
other port here leads with a :class:`LibraryRef` — that is H2's whole shape,
and ``tests/test_store_contract.py``'s isolation suite exists to prove a
foreign record reads as ABSENT. This one cannot: it is the store that ANSWERS
"which libraries are there, and may this caller have them", so scoping it by
the answer would be circular. Its scope is the **account**, which since P3.7b
is also the tenancy boundary itself.

The practical consequence, and the reason it is written at the top of the
file: a bug here does not leak one record between tenants, it hands over a
whole customer. So every method that takes an id narrows by it in the store —
never "list them all and filter in the caller", which is the shape that works
until someone reuses the listing somewhere else.

**One port for four entities**, unlike the one-port-per-aggregate split the
rest of this package follows (`BookStore`/`ShelfStore`/`ReadStore`/…). That
split is justified by INDEPENDENT LIFETIMES — a shelf exists before any book
stands on it, a decision outlives the read that produced it. Account, User,
Library and Membership have no independent lifetime worth separating: an
account is created together with the membership that administers it
(:func:`app.domain.tenancy.new_account`), and the single question the resolver
asks on every request — *is this library owned by an account you belong to* —
spans three of them. Separate ports would be separate round trips to answer
one question.

May import ``app.domain`` only (H1) — same rule as every other port.
"""
from __future__ import annotations

from typing import Protocol

from app.domain import Account, Library, Membership, User
from app.domain.book import DomainError


class UnknownUser(DomainError):
    """A membership names a user that does not exist.

    Refused rather than accepted, because the row it would create is a
    permission granted to nobody — invisible in ``list_accounts`` (there is
    no user to list it for) and visible in ``list_members`` as a member
    whose name cannot be shown. SQLite declares the same rule as a foreign
    key; the check is here as well so both adapters answer identically.
    """


class UnknownAccount(DomainError):
    """A membership, or a library, names an account that does not exist.

    ⚠ The library half is the one that matters. A library saved against an
    account nobody owns is unreachable by every caller — ``current_library``
    resolves through the owning account — but it still holds books, still
    occupies blob storage, and still counts on the operator's dashboard.
    That is the "phantom" shape §4.1 refuses at the book level, one layer up.
    """


class EmailTaken(DomainError):
    """``save_user`` would give two users one address (P4.1b).

    The address IS the identity anchor (the magic link resolves users by it
    and by nothing else), so two users sharing one is two people one login
    cannot tell apart. Raised as a domain error rather than leaking the
    sqlite ``IntegrityError``, because the api layer may not import
    adapters — and because the MEMORY store must refuse identically, or the
    contract suite tests the one adapter that cannot fail (P4.1a's
    data-integrity review measured exactly that divergence).
    """


class TenancyStore(Protocol):
    """Account-scoped, not library-scoped — see the module note."""

    # --- users ------------------------------------------------------------

    def save_user(self, user: User) -> None:
        """Insert or replace by id."""

    def get_user(self, user_id: str) -> User | None:
        ...

    def user_by_email(self, email: str) -> User | None:
        """The user this address authenticates to, or ``None`` (P4.1a).

        EXACT match: callers pass an address already through
        :func:`app.domain.auth.normalize_email` — the store compares bytes,
        because a second normalization here would be a second copy of the
        rule, and the two would drift.
        """

    # --- accounts ---------------------------------------------------------

    def save_account(self, account: Account) -> None:
        """Insert or replace by id.

        Saving an account alone is legal — schema v14's backfill produces
        exactly that for a library nobody was a member of — but the API never
        does it: :func:`app.domain.tenancy.new_account` returns the account
        AND its admin membership, and both are written together.
        """

    def get_account(self, account_id: str) -> Account | None:
        ...

    # --- libraries --------------------------------------------------------

    def save_library(self, library: Library) -> None:
        """Insert or replace by id. Raises :class:`UnknownAccount` if the
        library names an owner that does not exist."""

    def get_library(self, library_id: str) -> Library | None:
        """By id, regardless of who is asking.

        ⚠ Deliberately NOT membership-checked, and this is the method the
        whole boundary turns on: the caller that has a user in hand reads
        :attr:`app.domain.tenancy.Library.account_id` off the result and asks
        :meth:`membership` about THAT. A store method that quietly answered
        ``None`` for a library the caller may not see would make "does not
        exist" and "not yours" indistinguishable *inside the server*, which is
        where they must stay distinct — §4.2's 404-not-403 rule is about what
        the API SAYS, not about what the store knows.
        """

    def list_libraries(self, account_id: str) -> tuple[Library, ...]:
        """Every library this account OWNS, in
        :attr:`app.domain.tenancy.Library.sort_key` order.

        ⚠ By ownership, not by membership — that is the P3.7b change in one
        signature. It used to return ``(Library, Membership)`` pairs because a
        role was held per library; a role is now held per account, so the
        pairing would have repeated one row N times.
        """

    # --- memberships ------------------------------------------------------

    def save_membership(self, membership: Membership) -> None:
        """Insert or replace by ``(user_id, account_id)``.

        Upsert, not append: one membership per pair, so a role change
        overwrites. Raises :class:`UnknownUser` / :class:`UnknownAccount`
        if either side is missing.
        """

    def membership(self, user_id: str, account_id: str) -> Membership | None:
        """This user's membership of this account, or ``None``.

        The hot path — ``app.api.deps.current_library`` calls it on every
        request that names a library, with the account read off that library.
        """

    def delete_membership(self, user_id: str, account_id: str) -> bool:
        """``False`` if there was nothing to remove.

        Never touches a book or a shelf: the person leaves, the collection
        stays (UI_PLAN §5's separation, one level up).
        """

    def list_accounts(self, user_id: str) -> tuple[tuple[Account, Membership], ...]:
        """Every account this user belongs to, with the membership.

        Ordered by account id, which is arbitrary but TOTAL — the client
        orders what it renders by :attr:`Library.sort_key`, so no screen
        depends on this one, and an order that varies between adapters is an
        order somebody eventually reads as the list reshuffling itself.

        A user that belongs to nothing gets an empty tuple, not an error:
        that is a real state (P4.3's sign-up, before the first account is
        created), and the switcher has to render it.
        """

    def list_members(self, account_id: str) -> tuple[Membership, ...]:
        """Everyone in this account, admins first then by user id.

        Needed by :func:`app.domain.tenancy.set_role` and
        :func:`app.domain.tenancy.remove_member`, which take the WHOLE member
        list because "is there still an admin?" is unanswerable from one row.
        """
