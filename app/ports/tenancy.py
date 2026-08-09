# -*- coding: utf-8 -*-
"""TenancyStore — accounts, libraries and memberships (P3.1, §4.1).

⚠⚠ **This is the one store in the package that is NOT library-scoped.** Every
other port here leads with a :class:`LibraryRef` — that is H2's whole shape,
and ``tests/test_store_contract.py``'s isolation suite exists to prove a
foreign record reads as ABSENT. This one cannot: it is the store that ANSWERS
"which libraries are there, and may this caller have them", so scoping it by
the answer would be circular. Its scope is the **account**.

The practical consequence, and the reason it is written at the top of the
file: a bug here does not leak one record between tenants, it hands over a
whole library. So every method that takes an ``account_id`` narrows by it in
the store — never "list them all and filter in the caller", which is the shape
that works until someone reuses the listing somewhere else.

**One port for three entities**, unlike the one-port-per-aggregate split the
rest of this package follows (`BookStore`/`ShelfStore`/`ReadStore`/…). That
split is justified by INDEPENDENT LIFETIMES — a shelf exists before any book
stands on it, a decision outlives the read that produced it. Account, Library
and Membership have no independent lifetime worth separating: a library is
created together with the membership that administers it
(:func:`app.domain.tenancy.new_library`), and the single query the resolver
runs on every request spans all three. Three ports would be three round trips
to answer one question.

May import ``app.domain`` only (H1) — same rule as every other port.
"""
from __future__ import annotations

from typing import Protocol

from app.domain import Account, Library, Membership
from app.domain.book import DomainError


class UnknownAccount(DomainError):
    """A membership names an account that does not exist.

    Refused rather than accepted, because the row it would create is a
    permission granted to nobody — invisible in ``list_libraries`` (there is
    no account to list it for) and visible in ``list_members`` as a member
    whose name cannot be shown. SQLite declares the same rule as a foreign
    key; the check is here as well so both adapters answer identically.
    """


class UnknownLibrary(DomainError):
    """A membership names a library that does not exist."""


class TenancyStore(Protocol):
    """Account-scoped, not library-scoped — see the module note."""

    # --- accounts ---------------------------------------------------------

    def save_account(self, account: Account) -> None:
        """Insert or replace by id."""

    def get_account(self, account_id: str) -> Account | None:
        ...

    # --- libraries --------------------------------------------------------

    def save_library(self, library: Library) -> None:
        """Insert or replace by id.

        Saving a library alone is legal — schema v12's backfill produces
        exactly that for every library id the owner's data already contained
        — but the API never does it: :func:`app.domain.tenancy.new_library`
        returns the library AND its admin membership, and both are written
        together.
        """

    def get_library(self, library_id: str) -> Library | None:
        """By id, regardless of who is asking.

        ⚠ Deliberately NOT membership-checked: the caller that has an account
        in hand asks :meth:`membership` instead. A store method that quietly
        answered ``None`` for a library the caller may not see would make
        "does not exist" and "not yours" indistinguishable *inside the
        server*, which is where they must stay distinct — §4.2's 404-not-403
        rule is about what the API SAYS, not about what the store knows.
        """

    # --- memberships ------------------------------------------------------

    def save_membership(self, membership: Membership) -> None:
        """Insert or replace by ``(account_id, library_id)``.

        Upsert, not append: one membership per pair, so a role change
        overwrites. Raises :class:`UnknownAccount` / :class:`UnknownLibrary`
        if either side is missing.
        """

    def membership(self, account_id: str, library_id: str) -> Membership | None:
        """This account's membership of this library, or ``None``.

        The hot path — ``app.api.deps.current_library`` calls it on every
        request that names a library.
        """

    def delete_membership(self, account_id: str, library_id: str) -> bool:
        """``False`` if there was nothing to remove.

        Never touches a book or a shelf: the person leaves, the collection
        stays (UI_PLAN §5's separation, one level up).
        """

    def list_libraries(self, account_id: str) -> tuple[tuple[Library, Membership], ...]:
        """Every library this account is a member of, with the membership.

        Ordered by :attr:`app.domain.tenancy.Library.sort_key` — the app-bar
        switcher renders this list directly, and an order that varies between
        adapters is an order the user experiences as the list reshuffling
        itself.

        An account that belongs to nothing gets an empty tuple, not an error:
        that is a real state (P4.3's sign-up, before the first library is
        created), and the switcher has to render it.
        """

    def list_members(self, library_id: str) -> tuple[Membership, ...]:
        """Everyone in this library, admins first then by account id.

        Needed by :func:`app.domain.tenancy.set_role` and
        :func:`app.domain.tenancy.remove_member`, which take the WHOLE member
        list because "is there still an admin?" is unanswerable from one row.
        """
