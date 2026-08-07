# -*- coding: utf-8 -*-
"""Applying a diff — persistence only, no rules (P2.5).

``app.domain.reconcile`` decides WHAT a claim means; this module decides
nothing — it turns each :class:`~app.domain.reconcile.ClaimOutcome` into the
domain operation the RULE already named (``new_book``/``observe``/
``add_copy``, all pure) and writes the result through the ports. That split is
the plan's own phrasing: "keep the RULES in the pure function; this part only
persists."

Lives directly under ``app/`` — a sibling of ``domain``/``ports``/``adapters``/
``api`` rather than inside any of them — because it needs BOTH `app.domain`
(the rules and their entities) AND `app.ports` (`BookStore`, `ShelfStore`,
`DecisionStore`, `Clock`, `IdGen`) to do its job, and neither `app/domain`
(H1: pure, no ports) nor `app/api` (the plan says explicitly: not there — the
API layer's job is HTTP shape, not orchestration across four ports) is the
right home. It may import ``app.domain`` and ``app.ports``; it must NOT import
``app.adapters`` (H1's spirit — the day a Postgres adapter exists, this module
must not care) and it is imported BY ``app.api`` routes, never the reverse.

Two things this module explicitly does NOT do, matching `reconcile()`'s own
documented boundaries:

  - it does not persist ``not_seen`` anywhere. Streak-counting across several
    reads is P2.8's, which has the read archive to count from;
  - it does not make an unanswered ``needs_decision`` durable beyond this
    call. The "duplicates to resolve" queue that survives across sessions is
    P2.6's item — here, an entry with no matching :class:`Answer` is simply
    left open, and the caller sees it again next time it asks for the diff.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.domain import (
    Book,
    Decision,
    DecisionKind,
    Diff,
    LibraryRef,
    Provenance,
    Status,
    add_copy,
    new_book,
    observe,
    relink_copy,
)
from app.domain.book import DomainError
from app.ports import Clock, IdGen
from app.ports.decisions import DecisionStore
from app.ports.store import BookStore, ShelfStore


class AnswerKind(str, Enum):
    """A human's response to one still-open (``needs_decision``) claim.

    ``CONFIRM`` only fits a claim reasoned ``review_tier_new_book`` (no prior
    record anywhere in the library, read at REVIEW confidence): a human
    looking at it and saying "yes, real book" is itself an approval —
    stronger evidence than a read alone ever produces — so the book is
    created at :attr:`Status.APPROVED`, not ``AUTO``.

    ``REJECT`` fits either origin and means the same thing operationally:
    suppress this claim, here, forever, until the decision is cleared (§5.6).
    It is recorded as a :class:`DecisionKind.REJECTED` /
    :class:`DecisionKind.WRONG_BOOK` decision depending on which origin it
    answers, so the audit trail says which question was actually asked.

    ``ALREADY_LISTED`` / ``ANOTHER_COPY`` / ``WRONG_BOOK`` only fit a claim
    reasoned ``ambiguous_location`` — §5.4's three-way prompt.
    """

    CONFIRM = "confirm"
    REJECT = "reject"
    ALREADY_LISTED = "already_listed"
    ANOTHER_COPY = "another_copy"
    WRONG_BOOK = "wrong_book"


@dataclass(frozen=True)
class Answer:
    """One human response to one still-open claim, by claim id.

    ``copy_id`` is only meaningful with :attr:`AnswerKind.ALREADY_LISTED`,
    and only REQUIRED when the book has more than one copy not already
    standing somewhere else it disambiguates on its own (§5.4: "if the
    library already holds several copies, the user picks which one").
    """

    claim_id: str
    kind: AnswerKind
    copy_id: str | None = None


class UnresolvedAnswer(DomainError):
    """An :class:`Answer` named a claim that is not open in this diff, or
    paired a kind with a claim it does not fit (e.g. ``CONFIRM`` for an
    ambiguous-location claim). Mapped to a 400 by the API — this is a client
    bug, not a state conflict."""


@dataclass(frozen=True)
class AppliedResult:
    """What actually got written, for the caller to report or assert on."""

    books_saved: tuple[Book, ...] = ()
    decisions_saved: tuple[Decision, ...] = ()


def apply_diff(
    diff: Diff,
    *,
    library: LibraryRef,
    books: BookStore,
    shelves: ShelfStore,
    decisions: DecisionStore,
    clock: Clock,
    ids: IdGen,
    captured_at: str | None = None,
    answers: tuple[Answer, ...] = (),
) -> AppliedResult:
    """Persist a reconciled diff, plus any freshly-supplied human answers.

    ``captured_at`` becomes every fresh :class:`Provenance`'s timestamp;
    defaults to ``clock.now_iso()`` when the caller has no better value (a
    `Read` normally does — ``read.finished_at`` — and should pass it).
    """
    shelf = shelves.get_shelf(library, diff.shelf_id)
    if shelf is None:
        raise DomainError(
            f"shelf {diff.shelf_id!r} no longer exists; nothing to apply"
        )
    shelf.check_depth(diff.depth)
    when = captured_at or clock.now_iso()

    saved: list[Book] = []
    saved_decisions: list[Decision] = []

    def _prov(claim) -> Provenance:
        return Provenance(run_id=diff.read_id, spine_id=claim.spine_id,
                          shelf_id=diff.shelf_id, depth=diff.depth,
                          captured_at=when)

    # --- what `reconcile()` already decided, with no human input needed ---

    for outcome in diff.added:
        book = new_book(
            id=ids.new_id(), library_id=library.id, title=outcome.claim.title,
            author=outcome.claim.author, copy_id=ids.new_id(),
            status=Status.AUTO, shelf_id=diff.shelf_id, depth=diff.depth,
            provenance=(_prov(outcome.claim),), added_at=when,
        )
        books.save(library, book)
        saved.append(book)

    for outcome in diff.unchanged:
        book = observe(outcome.existing_book, _prov(outcome.claim),
                       status=Status.AUTO, copy_id=outcome.existing_copy_id)
        books.save(library, book)
        saved.append(book)

    for outcome in diff.corrected:
        book = _apply_corrected(outcome, when=when, prov=_prov(outcome.claim),
                                ids=ids, shelf_id=diff.shelf_id, depth=diff.depth)
        books.save(library, book)
        saved.append(book)

    # --- fresh human answers to claims `reconcile()` left open -------------

    open_by_id = {o.claim.id: o for o in diff.needs_decision}
    for answer in answers:
        outcome = open_by_id.get(answer.claim_id)
        if outcome is None:
            raise UnresolvedAnswer(
                f"claim {answer.claim_id!r} is not an open decision in this "
                f"diff (read {diff.read_id!r})"
            )
        book, decision = _apply_answer(
            outcome, answer, library=library, shelf_id=diff.shelf_id,
            depth=diff.depth, when=when, prov=_prov(outcome.claim), ids=ids,
        )
        if book is not None:
            books.save(library, book)
            saved.append(book)
        if decision is not None:
            decisions.save_decision(library, decision)
            saved_decisions.append(decision)

    return AppliedResult(books_saved=tuple(saved),
                         decisions_saved=tuple(saved_decisions))


# --- per-outcome execution ---------------------------------------------------

def _apply_corrected(outcome, *, when: str, prov: Provenance, ids: IdGen,
                     shelf_id: str, depth: int) -> Book:
    """A ``corrected`` outcome always carries the standing :class:`Decision`
    that produced it (``reconcile()`` never emits ``corrected`` without
    one) — this only re-dispatches on ITS kind, the same two branches
    :func:`_apply_answer` uses for a FRESH answer of the same shape."""
    decision = outcome.decision
    if decision.kind is DecisionKind.ALREADY_LISTED:
        # A relocation, not an ordinary sighting — `observe()` would refuse to
        # move a copy that already stands somewhere (by design); this claim's
        # LOCATION already disagrees with the copy's recorded one, which is
        # exactly what an ALREADY_LISTED decision means (§5.4).
        return relink_copy(outcome.existing_book, outcome.existing_copy_id,
                           prov, status=Status.AUTO)
    if decision.kind is DecisionKind.ANOTHER_COPY:
        return add_copy(outcome.existing_book, copy_id=ids.new_id(),
                        shelf_id=shelf_id, depth=depth, status=Status.MANUAL,
                        provenance=(prov,))
    raise DomainError(f"unexpected decision kind on a corrected outcome: "
                      f"{decision.kind!r}")


def _apply_answer(outcome, answer: Answer, *, library: LibraryRef,
                  shelf_id: str, depth: int, when: str, prov: Provenance,
                  ids: IdGen) -> tuple[Book | None, Decision | None]:
    if outcome.reason == "review_tier_new_book":
        if answer.kind is AnswerKind.CONFIRM:
            book = new_book(
                id=ids.new_id(), library_id=library.id, title=outcome.claim.title,
                author=outcome.claim.author, copy_id=ids.new_id(),
                # A human confirming a REVIEW-tier claim IS an approval — it
                # would be dishonest to file it at the same rung a read alone
                # produces (Status.AUTO).
                status=Status.APPROVED, shelf_id=shelf_id, depth=depth,
                provenance=(prov,), added_at=when,
            )
            return book, None
        if answer.kind is AnswerKind.REJECT:
            decision = Decision(library_id=library.id, shelf_id=shelf_id,
                                depth=depth, book_key=outcome.book_key,
                                kind=DecisionKind.REJECTED, decided_at=when)
            return None, decision
        raise UnresolvedAnswer(
            f"{answer.kind.value!r} does not answer a new-book review claim "
            f"(claim {outcome.claim.id!r}) — expected confirm or reject"
        )

    if outcome.reason == "ambiguous_location":
        if answer.kind is AnswerKind.ALREADY_LISTED:
            copy_id = _resolve_copy_id(outcome.existing_book, answer.copy_id)
            decision = Decision(library_id=library.id, shelf_id=shelf_id,
                                depth=depth, book_key=outcome.book_key,
                                kind=DecisionKind.ALREADY_LISTED,
                                copy_id=copy_id, decided_at=when)
            book = relink_copy(outcome.existing_book, copy_id, prov,
                              status=Status.AUTO)
            return book, decision
        if answer.kind is AnswerKind.ANOTHER_COPY:
            decision = Decision(library_id=library.id, shelf_id=shelf_id,
                                depth=depth, book_key=outcome.book_key,
                                kind=DecisionKind.ANOTHER_COPY, decided_at=when)
            book = add_copy(outcome.existing_book, copy_id=ids.new_id(),
                            shelf_id=shelf_id, depth=depth, status=Status.MANUAL,
                            provenance=(prov,))
            return book, decision
        if answer.kind is AnswerKind.WRONG_BOOK:
            decision = Decision(library_id=library.id, shelf_id=shelf_id,
                                depth=depth, book_key=outcome.book_key,
                                kind=DecisionKind.WRONG_BOOK, decided_at=when)
            return None, decision
        raise UnresolvedAnswer(
            f"{answer.kind.value!r} does not answer an ambiguous-location "
            f"claim (claim {outcome.claim.id!r}) — expected already_listed, "
            "another_copy or wrong_book"
        )

    raise UnresolvedAnswer(
        f"claim {outcome.claim.id!r} is not a kind of open decision this "
        f"module knows how to answer ({outcome.reason!r})"
    )


def _resolve_copy_id(book: Book, given: str | None) -> str:
    if given is not None:
        book.copy(given)  # raises UnknownCopy if it is not really this book's
        return given
    if book.copy_count == 1:
        return book.copies[0].id
    raise UnresolvedAnswer(
        f"book {book.id!r} has {book.copy_count} copies; an 'already listed' "
        "answer must name which one (§5.4)"
    )
