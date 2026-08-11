# -*- coding: utf-8 -*-
"""User, Library, Membership — the tenancy entities (P3.1, §4.1).

Until P3.1 the tenant key was the whole model: :class:`LibraryRef`, a string
with a label, handed to every store method and minted by a hardcoded dev
adapter. That was correct for one library and says nothing about the two
questions pillar 3 exists to answer — *whose* library is this, and *which* of
them is this request about.

§4.1's shape, kept deliberately narrow here:

  | | what it is | where |
  |---|---|---|
  | **User** | a person, one identity | here (no credentials — pillar 4) |
  | **Library** | a collection, and today still the tenancy boundary | here |
  | **Membership** | User × Library × Role | here |
  | **Place** | a location inside a library — a room, or a whole site (home, office, the parents') | pillar 6 |

(*Place* is the settled noun, 2026-08-10; *PhysicalLibrary* is its retired
synonym and must not appear in code — VISION §4.1.)

⚠ **This module is mid-move, and the half you are reading is P3.7a.** VISION
§4.1's 2026-08-11 revision makes the ACCOUNT the tenant and demotes a Library
to a logical partition inside one. This item does only the rename that frees
the word: the person used to be called ``Account`` and is now a
:class:`User`, so that P3.7b can introduce ``Account`` meaning *the customer*
without two classes fighting over one noun. **Nothing about the boundary has
moved yet** — a `Membership` still names a library, and `current_library`
still resolves through it. Every sentence below that calls a Library the
tenancy boundary is true today and scheduled to change at P3.7b; see
`planning/TENANCY_BOUNDARY_PLAN.md`.

⚠ **Library is not Place**, and collapsing them is the mistake §4.1
calls out by name. A Library is a permission boundary — "the Malin family
collection". A place you keep books is an ADDRESS inside it, and the whole
of plan §1.1's argument is that addresses arrive with the map. So there is no
place, no room and no bookcase in this module, for the same reason
:mod:`app.domain.shelf` has none.

⚠ **A Role carries no permissions here.** §4.2's matrix is P3.2's item, as
*data* with one enforcement point — so this module stores which role someone
has and answers no question about what it lets them do. A ``can()`` helper
added here would be the second enforcement point before the first one exists,
and ``tests/test_domain.py`` asserts its absence structurally rather than
trusting the comment.

No I/O, no framework, no store — same rule as the rest of ``app/domain``.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from app.domain.book import DomainError
from app.domain.library import LibraryRef


class LibraryNeedsAName(DomainError):
    """A library is created with a label, and the label may not be blank.

    Note the deliberate asymmetry with :class:`app.domain.shelf.Shelf`, whose
    label is optional *because identity is free* and an unnamed shelf is shown
    by its own photograph. A library has no photograph. It is the thing the
    app-bar switcher lists, and two blank rows in that list are two libraries
    the owner cannot tell apart — §4.3's own onboarding sketch says "create a
    Library, **name it**".
    """


class UnknownMember(DomainError):
    """No membership for that user in that library."""


class NoAdminLeft(DomainError):
    """The last admin cannot be demoted or removed.

    §4.2 puts "invite/remove members, change roles" in the admin column alone,
    so a library whose last admin steps down is a library nobody can ever
    invite anyone to, rename, or delete — an unadministrable tenant that only
    a database edit can rescue. Refusing costs one check; the alternative
    surfaces months later as a support request nobody can answer.
    """


class Role(str, Enum):
    """§4.2's three roles, as identity only — see the module note.

    ``str`` mixin so a role serialises as its own value in JSON and in a
    SQLite column without an adapter converting it, the same choice
    :class:`app.domain.book.Status` makes.
    """

    VIEWER = "viewer"
    EDITOR = "editor"
    ADMIN = "admin"


@dataclass(frozen=True)
class User:
    """A person, one identity (§4.1).

    Named ``Account`` until P3.7a. The rename is not cosmetic: the owner's
    word — and the operator console's — for a CUSTOMER is "account", and while
    this class held that noun the console had to document the mismatch instead
    of using it (ADMIN_CONSOLE_PLAN revision 4). A person is a user; the
    customer arrives at P3.7b.

    ``email`` is optional and unused until P4.1: there is no login yet, and a
    dev-trusted principal has no address to give. It is here because the
    user is the record a magic link authenticates *to*, and adding the
    column then would mean migrating the one row that matters.
    """

    id: str
    display_name: str = ""
    email: str | None = None
    created_at: str | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise DomainError("a user needs an id")


@dataclass(frozen=True)
class Library:
    """The tenancy boundary (§4.1) — the entity behind :class:`LibraryRef`.

    Two types for one thing, on purpose. ``LibraryRef`` is the *key*: it
    travels through every store method and every persisted record, and it is
    deliberately tiny so that signature stays readable. ``Library`` is the
    *record*: it has a lifetime, it gets renamed, it is listed in a switcher.
    :attr:`ref` is the one-way door between them, so nothing downstream has to
    know which one it was handed.

    ⚠ ``label`` is validated in :func:`new_library`, not here. Rows backfilled
    by schema v12 — every library id that already existed in the owner's data
    before P3.1 — have no label to recover, so the ENTITY must be able to
    represent one and the CONSTRUCTOR must refuse to mint another. Same split
    as ``Book``/``new_book``.
    """

    id: str
    label: str = ""
    created_at: str | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise DomainError("a library needs an id")

    @property
    def ref(self) -> LibraryRef:
        """The physical scope key every store method takes."""
        return LibraryRef(id=self.id, label=self.label)

    @property
    def sort_key(self) -> tuple[str, str, str]:
        """Named libraries alphabetically, then the nameless ones oldest-first.

        The same shape as :attr:`app.domain.shelf.Shelf.sort_key`, and here it
        covers exactly one case: the v12 backfill, whose rows have no label.
        A switcher whose order varies between adapters is an order the user
        experiences as the list reshuffling itself, so the rule lives here and
        both adapters mirror it. ``id`` last, so the order is total.
        """
        return (self.label.strip(), self.created_at or "", self.id)


@dataclass(frozen=True)
class Membership:
    """User × Library × Role (§4.1). One per pair — see :func:`set_role`."""

    user_id: str
    library_id: str
    role: Role = Role.VIEWER
    joined_at: str | None = None

    def __post_init__(self) -> None:
        if not self.user_id:
            raise DomainError("a membership needs a user")
        if not self.library_id:
            raise DomainError("a membership needs a library")

    @property
    def is_admin(self) -> bool:
        return self.role is Role.ADMIN


# --- operations -----------------------------------------------------------

def new_library(
    *,
    id: str,
    label: str,
    owner: User,
    created_at: str | None = None,
) -> tuple[Library, Membership]:
    """Create a library **and** the admin membership that administers it.

    Returning both from one call is the rule, not a convenience: a library
    saved without a membership is invisible to the person who just made it
    (nothing lists it, because listing is by user) and unadministrable by
    anyone else. Two separate operations would make that state reachable from
    a caller that simply forgot the second one — which is exactly the shape of
    bug :class:`NoAdminLeft` exists to prevent at the other end of the
    lifetime.
    """
    name = label.strip()
    if not name:
        raise LibraryNeedsAName("a library is created with a name (§4.3)")
    library = Library(id=id, label=name, created_at=created_at)
    membership = Membership(
        user_id=owner.id,
        library_id=library.id,
        role=Role.ADMIN,
        joined_at=created_at,
    )
    return library, membership


def rename_library(library: Library, label: str) -> Library:
    """Rename, with the same non-blank rule creation has.

    A library that can be renamed to '' is a library that can be hidden from
    its own switcher, which is :class:`LibraryNeedsAName`'s whole argument
    arriving one edit later.
    """
    name = label.strip()
    if not name:
        raise LibraryNeedsAName("a library keeps a name (§4.3)")
    return replace(library, label=name)


def set_role(
    members: tuple[Membership, ...], user_id: str, role: Role,
) -> tuple[Membership, ...]:
    """Change one member's role within a library's full member list.

    Takes the WHOLE list rather than the one membership because the rule being
    enforced is about the list — "is there still an admin?" is unanswerable
    from a single row. Same reasoning as :func:`app.domain.book.observe`
    taking the whole book to decide about one copy.
    """
    current = _find(members, user_id)
    if current.role is Role.ADMIN and role is not Role.ADMIN:
        _refuse_if_last_admin(members, user_id)
    return tuple(
        replace(m, role=role) if m.user_id == user_id else m
        for m in members
    )


def remove_member(
    members: tuple[Membership, ...], user_id: str,
) -> tuple[Membership, ...]:
    """Remove one member from a library's full member list.

    Removing a member never touches a book. §4.2's admin capability is
    "invite/remove members", and UI_PLAN §5's separation applies here too: the
    person leaves, the collection stays.
    """
    current = _find(members, user_id)
    if current.is_admin:
        _refuse_if_last_admin(members, user_id)
    return tuple(m for m in members if m.user_id != user_id)


def _find(members: tuple[Membership, ...], user_id: str) -> Membership:
    for m in members:
        if m.user_id == user_id:
            return m
    raise UnknownMember(f"{user_id!r} is not a member of this library")


def _refuse_if_last_admin(
    members: tuple[Membership, ...], user_id: str,
) -> None:
    others = [m for m in members if m.user_id != user_id and m.is_admin]
    if not others:
        raise NoAdminLeft(
            "a library keeps at least one admin (§4.2) — promote someone else "
            "first"
        )
