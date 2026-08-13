# -*- coding: utf-8 -*-
"""Account, User, Library, Membership — the tenancy entities (§4.1).

Until P3.1 the tenant key was the whole model: :class:`LibraryRef`, a string
with a label, handed to every store method and minted by a hardcoded dev
adapter. That was correct for one library and says nothing about the two
questions pillar 3 exists to answer — *whose* library is this, and *which* of
them is this request about.

§4.1's shape after the 2026-08-11 revision, kept deliberately narrow here:

  | | what it is | where |
  |---|---|---|
  | **Account** | the customer — **the tenancy boundary** | here |
  | **User** | a person, one identity | here (no credentials — pillar 4) |
  | **Library** | a collection inside an account; logical, not a boundary | here |
  | **Membership** | User × **Account** × Role | here |
  | **Place** | a location inside a library — a room, or a whole site (home, office, the parents') | pillar 6 |

(*Place* is the settled noun, 2026-08-10; *PhysicalLibrary* is its retired
synonym and must not appear in code — VISION §4.1.)

⚠⚠ **A Library is not the boundary, and `library_id` is still the only
enforced scope.** Those two sentences sound contradictory and are the whole
design (§4.1, P3.7b). Every store method still leads with a
:class:`LibraryRef`, every row still carries `library_id`, and the contract
suite still proves a foreign record reads as ABSENT — that machinery is
untouched, and is now defence in depth INSIDE the boundary rather than the
boundary itself. What moved is *authorization*: a membership names an
ACCOUNT, and :func:`app.api.deps.current_library` asks whether the library a
request named is owned by an account the caller belongs to. One narrowing in
SQL, one decision at the door. Adding a second enforced scope to the data is
the mistake this shape exists to avoid.

⚠ **Library is not Place** either, and collapsing those is the mistake §4.1
calls out by name. A place you keep books is an ADDRESS, and the whole of plan
§1.1's argument is that addresses arrive with the map. So there is no place,
no room and no bookcase in this module, for the same reason
:mod:`app.domain.shelf` has none. Note what the revision does NOT do: it does
not make a Library into a room. Splitting one collection across two libraries
still costs search, dedup and §5.4 silently — the difference is that the cost
is now guidance rather than a boundary.

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
    """No membership for that user in that account."""


class NoAdminLeft(DomainError):
    """The last admin cannot be demoted or removed.

    §4.2 puts "invite/remove members, change roles" in the admin column alone,
    so an account whose last admin steps down is an account nobody can ever
    invite anyone to, rename, or delete — an unadministrable tenant that only
    a database edit can rescue. Refusing costs one check; the alternative
    surfaces months later as a support request nobody can answer.

    ⚠ This is an ACCOUNT-level rule since P3.7b, and that is a widening, not a
    move: it used to protect one library, and now it protects every library
    the customer owns. A demotion that was legal when the person administered
    only `lib-2` is now refused if they are the account's last admin.
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
class Account:
    """The customer, and **the tenancy boundary** (§4.1, 2026-08-11).

    One household, one shop, one school. Everything else here hangs off
    exactly one of these, and a user of account A must not be able to learn
    that account B exists.

    ⚠ ``label`` may be blank, and unlike :class:`Library` there is no
    constructor refusing to mint a nameless one. The reason is the same shape
    as v12's argument for libraries and points the other way: an account is
    NOT chosen from a switcher — it is resolved from who is asking, and today
    nobody ever types its name. Schema v14 derives one from the admin's
    display name where there is one and leaves it empty otherwise, rather than
    inventing a string of ours. When P4.1 gives sign-up a name field, the rule
    it needs is :func:`app.domain.tenancy.new_library`'s, one level up.
    """

    id: str
    label: str = ""
    created_at: str | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise DomainError("an account needs an id")


@dataclass(frozen=True)
class User:
    """A person, one identity (§4.1).

    Named ``Account`` until P3.7a, when the word moved up to the customer.

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
    """A collection inside an account — the entity behind :class:`LibraryRef`.

    Two types for one thing, on purpose. ``LibraryRef`` is the *key*: it
    travels through every store method and every persisted record, and it is
    deliberately tiny so that signature stays readable. ``Library`` is the
    *record*: it has a lifetime, it gets renamed, it is listed in a switcher.
    :attr:`ref` is the one-way door between them, so nothing downstream has to
    know which one it was handed.

    ⚠ :attr:`account_id` is REQUIRED, and it is the only new field of P3.7b's
    whole data change. It is not a second enforced scope — no store method
    narrows by it and no other table gained it. It exists so
    ``deps.current_library`` can answer "who owns this?" in one lookup, which
    is the entire boundary.

    ⚠ ``label`` is validated in :func:`new_library`, not here. Rows backfilled
    by schema v12 — every library id that already existed in the owner's data
    before P3.1 — have no label to recover, so the ENTITY must be able to
    represent one and the CONSTRUCTOR must refuse to mint another. Same split
    as ``Book``/``new_book``.
    """

    id: str
    account_id: str
    label: str = ""
    created_at: str | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise DomainError("a library needs an id")
        if not self.account_id:
            raise DomainError("a library belongs to an account (§4.1)")

    @property
    def ref(self) -> LibraryRef:
        """The physical scope key every store method takes.

        ⚠ Deliberately does NOT carry the account. The ref is what every row
        is written against, and putting the owner in it would either duplicate
        a fact the `libraries` row already holds or invite a store method to
        narrow by it — which is the second enforced scope §4.1 refuses.
        """
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
    """User × Account × Role (§4.1). One per pair — see :func:`set_role`.

    ⚠ Named an ACCOUNT since P3.7b, not a library. A role is therefore held
    across every library the account owns; a user restricted to one library of
    an account is not expressible, and that is accepted (owner, 2026-08-11) —
    nobody has asked for it, and the shape that would allow it is a library
    scope on this row, added when someone does rather than left here dead.
    """

    user_id: str
    account_id: str
    role: Role = Role.VIEWER
    joined_at: str | None = None

    def __post_init__(self) -> None:
        if not self.user_id:
            raise DomainError("a membership needs a user")
        if not self.account_id:
            raise DomainError("a membership needs an account")

    @property
    def is_admin(self) -> bool:
        return self.role is Role.ADMIN


# --- operations -----------------------------------------------------------

#: How many libraries one account may hold (owner, 2026-08-13, P4.1c) — a
#: policy number checked at create time on the ACCOUNT, never a second
#: scope on the data (VISION §4.1). It exists as a retry-loop and abuse
#: guard, like §1.2's run-rate cap, not as a product limit: one library is
#: the normal case, a second is the rare separate collection, and five is
#: generous for both. Raising it is a one-line decision with this comment
#: to argue with.
LIBRARIES_PER_ACCOUNT = 5


def new_account(
    *,
    id: str,
    owner: User,
    label: str = "",
    created_at: str | None = None,
) -> tuple[Account, Membership]:
    """Create an account **and** the admin membership that administers it.

    Returning both from one call is the rule that :func:`new_library` used to
    carry, moved up to the level that now owns it: an account saved without a
    membership is invisible to the person who just made it (nothing lists it,
    because listing is by user) and unadministrable by anyone else. Two
    separate operations would make that state reachable from a caller that
    simply forgot the second one — which is exactly the shape of bug
    :class:`NoAdminLeft` prevents at the other end of the lifetime.
    """
    account = Account(id=id, label=label.strip(), created_at=created_at)
    membership = Membership(
        user_id=owner.id,
        account_id=account.id,
        role=Role.ADMIN,
        joined_at=created_at,
    )
    return account, membership


def new_library(
    *,
    id: str,
    label: str,
    account: Account,
    created_at: str | None = None,
) -> Library:
    """Create a library inside an account.

    ⚠ Returns a Library and NOTHING else — P3.7b's most load-bearing deletion.
    Until then this call also minted an admin membership, because a library
    WAS the boundary and one without a member was unreachable. Now access
    comes from the account, so minting a membership here would either
    duplicate the account's own or, worse, invent a second grant that
    ``current_library`` never consults. Creating a library is no longer a
    permission event.
    """
    name = label.strip()
    if not name:
        raise LibraryNeedsAName("a library is created with a name (§4.3)")
    return Library(id=id, account_id=account.id, label=name,
                   created_at=created_at)


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
    """Change one member's role within an account's full member list.

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
    """Remove one member from an account's full member list.

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
    raise UnknownMember(f"{user_id!r} is not a member of this account")


def _refuse_if_last_admin(
    members: tuple[Membership, ...], user_id: str,
) -> None:
    others = [m for m in members if m.user_id != user_id and m.is_admin]
    if not others:
        raise NoAdminLeft(
            "an account keeps at least one admin (§4.2) — promote someone "
            "else first"
        )
