# -*- coding: utf-8 -*-
"""Retracting a finding — the rule behind the workspace's ✕ (P2.10, §12.2 #10).

The Capture tab is a WORKSPACE, not a pipeline: an image is durable, its runs
hang off it, and each finding can be approved, edited or removed long after the
read that produced it settled. *Approve* and *edit* already had domain
operations (`app.domain.book.approve` / `edit`); **remove** did not, and it is
the only one of the three that has a rule worth arguing about, because it sits
exactly between two rules this codebase takes seriously and that point in
opposite directions:

  - **precision is the expensive metric** (CLAUDE.md): *"a missing book is
    noticed, a phantom one silently rots in the catalog"*. A finding a human
    has just called wrong, left standing in the library, is that phantom;
  - **remove-from-shelf is not delete-from-library** (UI_PLAN §5, owner's
    call): the destructive one is a separate, confirmed action, because a book
    that has simply MOVED must not be destroyed by a shelf-scoped judgement.

:func:`plan_retraction` is where those two meet, and the line it draws is:

> the library record is deleted only when **this read created it** — one copy,
> standing here, and every sighting on that copy comes from this very read.
> Anything with a life of its own keeps the book and only takes it off this
> shelf.

So retracting a finding undoes exactly what that finding did, and a book that
existed before this photo — an import, an earlier read, a hand-added copy —
survives a ✕ on one photo's finding; it just stops claiming this row.

⚠ **This is the SECOND version of the rule** (both same-day, 2026-08-09). The
first asked *"has a human vouched for this book?"* and deleted only records
still at :attr:`Status.AUTO`. That proxy stopped meaning anything hours later,
when the owner's *"nothing enters the library unapproved"* landed: every
machine-read book is now created by a CONFIRM answer and so arrives at
:attr:`Status.APPROVED`, which would have made the delete branch unreachable
and left every ✕ silently leaving an unshelved record behind. Asking who
CREATED the record answers the real question directly instead of by proxy, and
it does not drift when the status ladder's usage changes again.

Separately and ALWAYS, a retraction records a standing
:class:`~app.domain.reconcile.Decision` at this (shelf, depth, book_key): §5.6
is explicit that a rejected book must not be re-added by a later run, and
without the decision the very next read would put the phantom straight back.
That is why this returns a decision KIND even in the ``NOTHING`` case — there
may be no copy left here to remove, and the answer *"not this book, not here"*
still has to survive.

Pure: no store, no clock, no ids — :mod:`app.reconcile_apply` executes what
this decides, the same split P2.5 already documents between
`app.domain.reconcile` and that module.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.domain.book import Book
from app.domain.read import Read
from app.domain.reconcile import DecisionKind


class RetractAction(str, Enum):
    """What removing this finding does to the library record.

    ``DELETE_BOOK``        the book exists only because of reads, and only
                            here — nothing survives the retraction;
    ``REMOVE_FROM_SHELF``  the copy standing here stops claiming this row; the
                            book (and its other copies, its lending, its
                            history) stays;
    ``NOTHING``            no copy of this book stands at this (shelf, depth)
                            at all — the finding was never applied, or its copy
                            has since been moved or removed. Only the decision
                            is recorded.
    """

    DELETE_BOOK = "delete_book"
    REMOVE_FROM_SHELF = "remove_from_shelf"
    NOTHING = "nothing"


@dataclass(frozen=True)
class Retraction:
    """What :func:`plan_retraction` decided, for `app.reconcile_apply` to
    execute. ``copy_id`` names the copy standing at the retracted location —
    ``None`` exactly when :attr:`RetractAction.NOTHING`."""

    action: RetractAction
    decision_kind: DecisionKind
    copy_id: str | None = None


def deletion_sites(book: Book) -> tuple[tuple[str, int], ...]:
    """Where a *delete from the library* has to record its "no" (owner,
    2026-08-10).

    Deleting a book is the strongest statement the product offers about a
    record, and until now it recorded nothing anywhere — so the finding that
    produced the book reverted to an ordinary unanswered question, and **the
    next read of that shelf would put the book straight back**. That is the
    §5.6 rule ("a rejected book must not be re-added by a later run") going
    unenforced for the one action that most obviously means rejection.

    It is also what the owner asked for from the other end: a deleted book's
    finding should read as *removed* — struck through, with its undo — rather
    than as a question nobody has answered yet. Both come from the same
    write, because `reconcile()` already puts a claim in ``rejected`` exactly
    when a standing decision suppresses it.

    Returns the DISTINCT ``(shelf_id, depth)`` locations the book's copies
    stand at, in a stable order. Empty when nothing is located — the 251
    imported books have no shelf, and a deletion there suppresses nothing
    because there is no row for a future read to re-find it on.

    ⚠ Locations, not "the shelf": a book with copies on two rows was seen on
    two rows, and a decision is scoped to one (shelf, depth) by §5.7 #1. One
    decision per site is the only answer that suppresses everywhere it was
    actually claimed.

    Pure, like everything else in this module — the caller writes.
    """
    sites: list[tuple[str, int]] = []
    for copy in book.copies:
        here = copy.location
        if here is not None and here not in sites:
            sites.append(here)
    return tuple(sites)


def plan_retraction(
    book: Book | None,
    shelf_id: str,
    depth: int,
    *,
    read: Read,
    claimed_elsewhere: bool = False,
) -> Retraction:
    """Decide what removing this finding costs the library.

    :param book: the book this finding resolved to, or ``None`` when the
        finding never became one (a claim nobody confirmed, or one a standing
        decision already suppresses). ``None`` is an ordinary case, not an
        error: the answer *"no, not here"* is still worth recording, and
        recording it is the whole point (§5.6).
    :param shelf_id: the shelf the finding was read from.
    :param depth: the row front-to-back (§5.7 #1 — a retraction is scoped to
        the row that was photographed, exactly like the read and the decision).
    :param read: the read this finding belongs to. This is what makes "did
        this finding create the record?" answerable rather than guessed at,
        and it takes BOTH of the read's facts — its id (every
        :class:`~app.domain.book.Provenance` entry names the read that
        produced it) and when it started (``Book.added_at`` says when the
        record joined the library).
    :param claimed_elsewhere: True when this key is a book the library already
        held somewhere ELSE before this read — §5.4's ambiguous case. It only
        picks which decision kind is recorded (``WRONG_BOOK`` vs ``REJECTED``,
        which suppress identically but say which question was answered — see
        :class:`~app.domain.reconcile.DecisionKind`), never what happens to the
        record.
    """
    kind = DecisionKind.WRONG_BOOK if claimed_elsewhere else DecisionKind.REJECTED
    if book is None:
        return Retraction(action=RetractAction.NOTHING, decision_kind=kind)

    here = (shelf_id, depth)
    copy_here = next((c for c in book.copies if c.location == here), None)
    if copy_here is None:
        return Retraction(action=RetractAction.NOTHING, decision_kind=kind)

    # This read is the record's whole history: one copy, standing here,
    # nothing but this read has ever vouched for it, and the record itself
    # joined the library no earlier than this read began. Deleting it undoes
    # exactly what the finding did and leaves nothing behind.
    #
    # All three clauses are load-bearing, and the LAST one is the least
    # obvious: a book that already existed and that this read merely
    # RECONFIRMED gets its first-ever sighting from this read (`observe()`
    # appends one), so provenance alone cannot tell "created here" from
    # "found here" — it says the same thing about both. ``added_at`` can, and
    # it is the fact that literally answers the question. A record with no
    # ``added_at`` at all reads as OLDER, never as newer: the safe direction
    # is always to keep the book.
    #
    # `copy_here.provenance` must be non-empty for the second clause to mean
    # anything — a copy with NO sightings was declared by a human through
    # *"I have another copy"* (`add_copy`'s own default), and `all()` over an
    # empty tuple would quietly report that as "all from this read".
    made_here = (
        book.copy_count == 1
        and bool(copy_here.provenance)
        and all(p.run_id == read.id for p in copy_here.provenance)
        and book.added_at is not None
        and read.started_at is not None
        and book.added_at >= read.started_at
    )
    if made_here:
        return Retraction(action=RetractAction.DELETE_BOOK, decision_kind=kind,
                          copy_id=copy_here.id)
    return Retraction(action=RetractAction.REMOVE_FROM_SHELF,
                      decision_kind=kind, copy_id=copy_here.id)
