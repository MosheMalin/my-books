# -*- coding: utf-8 -*-
"""Book and Copy — the entities and the rules that must not be reversible.

Target shape from VISION §5.2. Three splits are doing the work:

  1. **bibliographic vs user-owned** — publisher/year/cover live once globally
     (``shared_book_id``, pillar 7); ratings and tags live per library;
  2. **book-level vs copy-level user fields** — a rating/note/read-status
     describes the *book* (you don't rate your second copy differently); tags,
     condition, acquisition, location and lending describe the *object*;
  3. **provenance sits on the Copy**, append-only. A book seen on two shelves
     across two runs produces two provenance entries, and a *human* decides
     whether that is one copy that moved or two copies owned.

Everything here is frozen and every operation returns a NEW object. That is
not style: "append provenance, never overwrite" (§5.2) and "a re-read must
never demote a confirmed book" (§5.6) are both far harder to violate when the
old value physically cannot be reassigned.

No I/O, no framework, no store. The only import out of this package is
``normalize()`` via ``app.domain.text`` — see that module for why.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum

from app.domain.text import author_sort_key, book_key, normalize


class DomainError(Exception):
    """Base for rule violations. Callers map these to HTTP in app/api."""


class UnknownCopy(DomainError):
    """A copy id that does not belong to this book."""


class AmbiguousCopy(DomainError):
    """A read matched a known book but cannot say WHICH physical copy.

    Not a failure — this is §5.4's prompt firing. The domain refuses to guess
    because guessing in either direction is destructive: silently relinking
    moves a book that didn't move, and silently creating invents a phantom.
    P2.4 owns the UI that answers it; the default answer is "already listed".
    """


class CopyAlreadyLentOut(DomainError):
    """Lending an object that is already out. You lend a copy to ONE person
    at a time — a second `lend` on top of the first would silently overwrite
    who has it, which is exactly the record "who has my books" (§5.2) exists
    to answer correctly. Return it first."""


class CopyNotLentOut(DomainError):
    """Marking returned a copy that was never lent, or already is. There is
    nothing to close, and closing it anyway would fabricate a `returned_at`
    for a loan that does not exist."""


# --- status ladder --------------------------------------------------------

class Status(str, Enum):
    """auto < approved < manual.

    ``auto``      the pipeline claimed it at AUTO tier and nobody has looked;
    ``approved``  a human confirmed the claim;
    ``manual``    a human typed or corrected it.

    Ordering matters because it is the whole content of "a human decision
    outranks an auto one" (`booksnap/library.py::add_book`, VISION §5.6).
    """

    AUTO = "auto"
    APPROVED = "approved"
    MANUAL = "manual"

    @property
    def rank(self) -> int:
        return _LADDER.index(self)

    def outranks(self, other: "Status") -> bool:
        return self.rank > other.rank

    @staticmethod
    def merge(current: "Status", incoming: "Status") -> "Status":
        """The re-read rule: take the higher rung, NEVER the incoming one.

        This is the single line that stops a worse re-read from demoting a
        book the owner already approved (§5.6). Measured recall is 0.78-0.83,
        so a re-read failing to confirm something is weak evidence — treating
        it as authoritative would silently undo human work.
        """
        return current if current.rank >= incoming.rank else incoming


_LADDER: tuple[Status, ...] = (Status.AUTO, Status.APPROVED, Status.MANUAL)


# --- value objects --------------------------------------------------------

@dataclass(frozen=True)
class Provenance:
    """One sighting of one physical copy. Append-only; never edited.

    ``shelf_id`` and ``captured_at`` are optional because P1.3 imports 251
    real books whose recorded evidence is only ``{run_id, spine_id}`` — the
    shape `booksnap/library.py` has been writing all along. Losing those books
    to a stricter type would be the wrong trade.
    """

    run_id: str
    spine_id: str
    shelf_id: str | None = None
    captured_at: str | None = None

    @property
    def sighting(self) -> tuple[str, str]:
        """Identity of the sighting, for idempotent appends."""
        return (self.run_id, self.spine_id)


@dataclass(frozen=True)
class Lending:
    """Per COPY, never per book — you lend an object, not a work.

    The field exists from P1.1 because it is part of the record split above;
    the lend/return transitions are P1.7's.
    """

    lent_to: str
    lent_at: str
    due_at: str | None = None
    returned_at: str | None = None

    @property
    def is_out(self) -> bool:
        return self.returned_at is None


@dataclass(frozen=True)
class CopyFields:
    """User fields describing the physical object."""

    tags: tuple[str, ...] = ()
    condition: str = ""
    acquired_at: str | None = None


@dataclass(frozen=True)
class WorkFields:
    """User fields describing the work. Rating a second copy makes no sense."""

    rating: int | None = None
    notes: str = ""
    read_status: str | None = None


# --- entities -------------------------------------------------------------

@dataclass(frozen=True)
class Copy:
    """One physical object.

    NEVER constructed by a read. ``tests/test_domain.py`` walks this module's
    AST and fails if a ``Copy(...)`` appears outside the two functions a human
    action reaches: :func:`new_book` and :func:`add_copy` (§5.1).
    """

    id: str
    book_id: str
    status: Status = Status.AUTO
    label: str = ""
    shelf_id: str | None = None
    provenance: tuple[Provenance, ...] = ()
    fields: CopyFields = field(default_factory=CopyFields)
    lending: Lending | None = None

    @property
    def last_seen(self) -> Provenance | None:
        return self.provenance[-1] if self.provenance else None


@dataclass(frozen=True)
class Book:
    """One ``{title, author}`` per library (§5.1) — no ISBN, no edition.

    An ISBN is not legible from a spine photo in the general case, so edition
    modelling would be effort spent on a field that stays empty. Copies exist
    because *lending* needs them, not because identity resolution does.
    """

    id: str
    library_id: str
    title: str
    author: str = ""
    copies: tuple[Copy, ...] = ()
    shared_book_id: str | None = None
    work: WorkFields = field(default_factory=WorkFields)
    added_at: str | None = None

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise DomainError("a book must have a title")
        if not self.library_id:
            raise DomainError("a book must belong to a library (H2)")
        # §5.2: "copies: [Copy, ...] <- at least one". Removing the last copy
        # is deleting the book, which is a store operation and a different,
        # separately-confirmed user action (UI_PLAN §5).
        if not self.copies:
            raise DomainError("a book must have at least one copy")

    # --- derived ---------------------------------------------------------

    @property
    def normalized_title(self) -> str:
        return normalize(self.title)

    @property
    def normalized_author(self) -> str:
        return normalize(self.author)

    @property
    def author_sort(self) -> str:
        """Surname-first key — what "sort by author" actually means (§6).

        Separate from :attr:`normalized_author`, which is IDENTITY: it is the
        author filter's key and half of the search haystack, so reordering it
        would silently change which books an author chip matches.
        """
        return author_sort_key(self.author)

    @property
    def key(self) -> str:
        """Identity within the library. Changes when the title is edited —
        which is why re-keying is the store's job, not the entity's."""
        return book_key(self.title, self.author)

    @property
    def status(self) -> Status:
        """The book's standing = the strongest claim any of its copies has.

        Derived rather than stored so it cannot disagree with the copies. The
        UI's status filter (§6) reads this.
        """
        return max((c.status for c in self.copies), key=lambda s: s.rank)

    @property
    def copy_count(self) -> int:
        return len(self.copies)

    def copy(self, copy_id: str) -> Copy:
        for c in self.copies:
            if c.id == copy_id:
                return c
        raise UnknownCopy(f"{copy_id} is not a copy of book {self.id}")


# --- operations -----------------------------------------------------------
#
# Two of these create a Copy, and both are reachable only from a deliberate
# human action. Everything a READ can call is below them and cannot.

def new_book(
    *,
    id: str,
    library_id: str,
    title: str,
    copy_id: str,
    author: str = "",
    status: Status = Status.AUTO,
    shelf_id: str | None = None,
    provenance: tuple[Provenance, ...] = (),
    label: str = "",
    added_at: str | None = None,
) -> Book:
    """A book entering the library, with its first and only copy.

    Default is exactly one copy, so a user who never thinks about copies never
    sees the concept — the list shows books, and the count appears only when
    it exceeds one (§5.1).
    """
    first = Copy(
        id=copy_id,
        book_id=id,
        status=status,
        label=label,
        shelf_id=shelf_id,
        provenance=tuple(provenance),
    )
    return Book(
        id=id,
        library_id=library_id,
        title=title,
        author=author,
        copies=(first,),
        added_at=added_at,
    )


def add_copy(
    book: Book,
    *,
    copy_id: str,
    label: str = "",
    shelf_id: str | None = None,
    status: Status = Status.MANUAL,
    fields: CopyFields = CopyFields(),
) -> Book:
    """*"I have another copy"* — THE ONLY path that creates a second copy.

    Status defaults to ``manual`` because a person declaring a duplicate is
    the strongest evidence the system ever gets; no re-read can produce this.
    """
    extra = Copy(
        id=copy_id,
        book_id=book.id,
        status=status,
        label=label,
        shelf_id=shelf_id,
        fields=fields,
    )
    return replace(book, copies=book.copies + (extra,))


def observe(
    book: Book,
    prov: Provenance,
    *,
    status: Status = Status.AUTO,
    copy_id: str | None = None,
) -> Book:
    """A read saw this book again. Appends evidence; creates nothing.

    Resolution order, straight out of §5.4's fire/never-fire table:

      1. an explicit ``copy_id`` — the user already answered the prompt;
      2. a copy already standing on ``prov.shelf_id`` — same shelf, same copy,
         never ask;
      3. the book's ONLY copy, if it has never been located — adopt it (this
         is also the path P1.3's legacy import takes, where sightings carry no
         shelf at all);
      4. otherwise :class:`AmbiguousCopy` — a different shelf, or more than
         one candidate. The domain refuses to guess; P2.4 asks.

    Appending is idempotent per ``(run_id, spine_id)``, so replaying a read
    does not inflate a copy's history. That is idempotency, not overwriting —
    an existing entry is never modified or dropped.
    """
    target = _resolve_copy(book, prov, copy_id)

    seen = {p.sighting for p in target.provenance}
    provenance = target.provenance
    if prov.sighting not in seen:
        provenance = provenance + (prov,)

    updated = replace(
        target,
        provenance=provenance,
        status=Status.merge(target.status, status),
        # Adopting an unshelved copy is the only relink a read may perform;
        # moving a copy that already stands somewhere is the §5.4 prompt.
        shelf_id=target.shelf_id if target.shelf_id is not None else prov.shelf_id,
    )
    return _with_copy(book, updated)


def approve(book: Book, *, copy_id: str | None = None) -> Book:
    """A human confirmed the claim. Never lowers an already-``manual`` copy."""
    targets = (book.copy(copy_id),) if copy_id else book.copies
    out = book
    for c in targets:
        out = _with_copy(out, replace(c, status=Status.merge(c.status, Status.APPROVED)))
    return out


def edit(book: Book, *, title: str | None = None, author: str | None = None) -> Book:
    """Fix the title/author by hand. The book becomes ``manual``.

    Every copy is raised, because title and author are BOOK-level: a person
    has vouched for this record's identity, and the copies are all copies of
    that identity (UI_PLAN §5).

    Note the key changes when the title does — the store re-keys, not the
    entity, which has no idea other books exist.
    """
    out = replace(
        book,
        title=book.title if title is None else title,
        author=book.author if author is None else author,
    )
    for c in out.copies:
        out = _with_copy(out, replace(c, status=Status.merge(c.status, Status.MANUAL)))
    return out


def remove_from_shelf(book: Book, copy_id: str) -> Book:
    """*Remove from shelf* — NOT *delete from library* (UI_PLAN §5).

    The book may simply have moved (§5.6). The copy keeps its id, its label,
    its tags, its lending state and its whole provenance history; it just no
    longer claims a location. Deleting from the library is a different,
    separately-confirmed action, and it lives in the store because it removes
    a row rather than changing one.
    """
    return _with_copy(book, replace(book.copy(copy_id), shelf_id=None))


def edit_copy(
    book: Book,
    copy_id: str,
    *,
    label: str | None = None,
    tags: tuple[str, ...] | None = None,
    condition: str | None = None,
) -> Book:
    """Fix a copy's own label/tags/condition (§5.2 — object-level, unlike
    :func:`set_work_fields`). Unlike :func:`edit`, this does NOT touch status:
    describing the physical object ("paperback", "torn cover") is not a claim
    about the book's identity, so it must not read as confirming one."""
    copy = book.copy(copy_id)
    new_label = copy.label if label is None else label
    new_fields = copy.fields
    if tags is not None:
        new_fields = replace(new_fields, tags=tags)
    if condition is not None:
        new_fields = replace(new_fields, condition=condition)
    return _with_copy(book, replace(copy, label=new_label, fields=new_fields))


def lend(
    book: Book,
    copy_id: str,
    *,
    lent_to: str,
    lent_at: str,
    due_at: str | None = None,
) -> Book:
    """*"Lend it out"* (UI_PLAN §5). One borrower at a time per copy — a copy
    already out must be returned before it can be lent again, or the earlier
    borrower's name is silently lost from "who has my books" (§5.2)."""
    copy = book.copy(copy_id)
    if copy.lending is not None and copy.lending.is_out:
        raise CopyAlreadyLentOut(
            f"copy {copy_id} is already lent to {copy.lending.lent_to!r}; "
            "mark it returned first"
        )
    return _with_copy(book, replace(
        copy, lending=Lending(lent_to=lent_to, lent_at=lent_at, due_at=due_at),
    ))


def return_copy(book: Book, copy_id: str, *, returned_at: str) -> Book:
    """*"Mark returned"*. The lending record is kept, not cleared — it is the
    copy's history of who has borrowed it, same reasoning as provenance being
    append-only rather than overwritten."""
    copy = book.copy(copy_id)
    if copy.lending is None or not copy.lending.is_out:
        raise CopyNotLentOut(f"copy {copy_id} is not currently lent out")
    return _with_copy(book, replace(
        copy, lending=replace(copy.lending, returned_at=returned_at),
    ))


def set_work_fields(book: Book, **changes: object) -> Book:
    """Rating / notes / read status — book-level, never per copy (§5.2)."""
    return replace(book, work=replace(book.work, **changes))  # type: ignore[arg-type]


# --- internals ------------------------------------------------------------

def _with_copy(book: Book, updated: Copy) -> Book:
    """Replace one copy in place, preserving order. Order is meaningful:
    copy #1 is the original, and the UI lists them as the owner acquired
    them."""
    book.copy(updated.id)  # raises UnknownCopy if it isn't ours
    return replace(
        book,
        copies=tuple(updated if c.id == updated.id else c for c in book.copies),
    )


def _resolve_copy(book: Book, prov: Provenance, copy_id: str | None) -> Copy:
    if copy_id is not None:
        return book.copy(copy_id)

    if prov.shelf_id is not None:
        on_shelf = [c for c in book.copies if c.shelf_id == prov.shelf_id]
        if len(on_shelf) == 1:
            return on_shelf[0]
        if len(on_shelf) > 1:
            raise AmbiguousCopy(
                f"book {book.id} has {len(on_shelf)} copies on shelf "
                f"{prov.shelf_id}; ask which one (§5.4)"
            )

    # Only a book with a SINGLE, never-located copy is adopted silently. Once
    # there are several, §5.4 says the user picks — and its own suggested
    # default ("the copy with no shelf assigned") is a UI default to be shown,
    # not a decision the domain may take on its own.
    if book.copy_count == 1 and book.copies[0].shelf_id is None:
        return book.copies[0]

    raise AmbiguousCopy(
        f"book {book.id} was seen on shelf {prov.shelf_id!r} but its "
        f"{book.copy_count} copy/copies are elsewhere; ask which one (§5.4)"
    )
