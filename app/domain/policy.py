# -*- coding: utf-8 -*-
"""The permissions matrix (P3.2, §4.2) — as DATA, with one question it answers.

§4.2's table, transcribed row for row into :data:`POLICY`. The plan's own
wording is the design: *"the matrix as data, one enforcement point,
table-driven test over every (role × capability) cell"*. So this module holds
no control flow worth reading — a capability names a row, a role is in the
row's set or it is not — and changing who may do what is an edit to a table,
not to an ``if`` somewhere in a router.

The one enforcement point is ``app/api/policy.py:require``: every
library-scoped route declares its capability there, and ``tests/test_api.py``
carries the meta-test that a route with NO declaration fails rather than
defaulting to open. This module deliberately knows nothing about routes,
requests or HTTP — the same split as :mod:`app.domain.copy_resolution`'s fire
table, and for the same reason: the rule a silent regression would be most
expensive in should be readable in one screen.

Two §12 questions are settled HERE, as cells, because both are policy and
guessing them elsewhere would produce the wrong schema (plan P3.2):

  - **§12.2 #1 — may a Viewer see the original photos?** ``VIEW_PHOTOS`` is
    Editor+. The photos show the inside of a home, and "viewer" may mean a
    friend browsing what you own; the catalog (titles, authors, lending
    state) is what a Viewer is for. The privacy-preserving cell is also the
    cheap-to-reverse one: loosening later shows photos to people who could
    not see them; tightening later cannot un-show them.
  - **§12.2 #3 — two members reviewing the same read?** Settled as a
    NON-cell: optimistic concurrency, no locking, no per-spine claim. Every
    apply path already recomputes against current library state and is
    idempotent by sighting (P2.7/P2.9), and an answer to a question someone
    else just closed gets a 409 from the duplicates router's own
    re-derivation. That is a property of the write paths, not of this
    matrix — recorded here because P3.2 is where the plan says the question
    gets answered, and the answer is "the schema already holds".

⚠ **Admin here is an admin INSIDE one account's library** (owner,
2026-08-10): the §4.2 role governs one household's collection. It is NOT the
system operator — that is the separate staff console (``app/admin`` /
``app/staff_api``, its own plan), which authenticates and authorizes on its
own axis and never through this matrix.

The open §4.2 sub-question that stays open: a role between Viewer and Editor
that may mark lending but not edit the catalog. Nothing here forecloses it —
it would be a new :class:`app.domain.tenancy.Role` plus one column in this
table — and it is not settled because nobody has asked for it yet.

No I/O, no framework — same rule as the rest of ``app/domain``.
"""
from __future__ import annotations

from enum import Enum

from app.domain.book import DomainError
from app.domain.tenancy import Role


class PolicyUndeclared(DomainError):
    """A capability with no row in :data:`POLICY`.

    Raised, never defaulted — the same stance as
    :func:`app.domain.copy_resolution.fires`: an unrecognised capability
    indistinguishable from a declared-open one is exactly how a new route
    ships unpoliced.
    """


class Capability(str, Enum):
    """§4.2's rows, one enum member per thing a role may or may not do.

    ``str`` mixin for the same serialisation reason as :class:`Role`. The
    names follow the vision's own rows; two of its rows are split where one
    row covers two different routes (``DELETE_PHOTOS`` / ``DELETE_LIBRARY``),
    and two are declared ahead of the pillar that gives them routes
    (``EDIT_MAP`` — pillar 6, ``MANAGE_KEYS`` — pillar 5) so the matrix is
    complete against the vision now, not grown cell by cell.
    """

    #: Browse/search books, see shelves — §4.2 row 1.
    BROWSE = "browse"
    #: See lending state — §4.2 row 2.
    SEE_LENDING = "see_lending"
    #: See the original shelf photographs — §12.2 #1, settled Editor+.
    VIEW_PHOTOS = "view_photos"
    #: Upload photos, start (and stop) a run — §4.2 row 3.
    CAPTURE = "capture"
    #: Approve/reject/replace matches; answer §5.4 questions — §4.2 row 4.
    REVIEW = "review"
    #: Add/remove books manually; edit books and copies — §4.2 row 5.
    EDIT_BOOKS = "edit_books"
    #: Mark lent / returned — §4.2 row 6.
    LEND = "lend"
    #: Edit the physical map — §4.2 row 7 (routes arrive with pillar 6).
    EDIT_MAP = "edit_map"
    #: Invite/remove members, change roles — §4.2 row 8 (routes with P4.3).
    MANAGE_MEMBERS = "manage_members"
    #: Attach BYO API key, see usage/quota — §4.2 row 9 (routes with P5).
    MANAGE_KEYS = "manage_keys"
    #: Rename the library. Not a §4.2 row; grouped with the admin column
    #: because the library's name is the tenant's own identity, and §4.3's
    #: "create a Library, name it" is addressed to the person who owns it.
    MANAGE_LIBRARY = "manage_library"
    #: Delete photos — §4.2's last row, first half. Admin, NOT editor:
    #: deleting a photo destroys the evidence every read of it points at.
    DELETE_PHOTOS = "delete_photos"
    #: Delete the library — §4.2's last row, second half (route with P3.5's
    #: blob purge; the capability exists first so the route cannot ship open).
    DELETE_LIBRARY = "delete_library"


_ANYONE = frozenset({Role.VIEWER, Role.EDITOR, Role.ADMIN})
_EDITORS = frozenset({Role.EDITOR, Role.ADMIN})
_ADMINS = frozenset({Role.ADMIN})

#: §4.2, transcribed. THE data. ``tests/test_domain.py`` holds the
#: table-driven test over every (role × capability) cell — edit that table in
#: the same commit as this one, which is the point: a cell change is a
#: decision, and the test is where it gets written down twice.
POLICY: dict[Capability, frozenset[Role]] = {
    Capability.BROWSE: _ANYONE,
    Capability.SEE_LENDING: _ANYONE,
    Capability.VIEW_PHOTOS: _EDITORS,
    Capability.CAPTURE: _EDITORS,
    Capability.REVIEW: _EDITORS,
    Capability.EDIT_BOOKS: _EDITORS,
    Capability.LEND: _EDITORS,
    Capability.EDIT_MAP: _EDITORS,
    Capability.MANAGE_MEMBERS: _ADMINS,
    Capability.MANAGE_KEYS: _ADMINS,
    Capability.MANAGE_LIBRARY: _ADMINS,
    Capability.DELETE_PHOTOS: _ADMINS,
    Capability.DELETE_LIBRARY: _ADMINS,
}


def allowed(role: Role, capability: Capability) -> bool:
    """May this role exercise this capability? The whole module's API.

    Raises :class:`PolicyUndeclared` for a capability with no row rather than
    answering ``False``: a ``False`` here reads as "denied by policy" when the
    truth is "nobody wrote the policy", and the two must stay distinguishable
    — the second one is a bug.
    """
    grants = POLICY.get(capability)
    if grants is None:
        raise PolicyUndeclared(
            f"no POLICY row for {capability!r} — every capability is declared, "
            "never defaulted (P3.2)"
        )
    return role in grants
