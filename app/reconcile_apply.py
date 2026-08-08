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

One thing this module explicitly does NOT do, matching `reconcile()`'s own
documented boundary: it does not persist ``not_seen`` anywhere.
Streak-counting across several reads is P2.8's, which has the read archive
to count from.

**The durable "duplicates to resolve" queue (P2.6, §5.4).** An unanswered
``needs_decision`` claim reasoned ``ambiguous_location`` — the ONE situation
:func:`app.domain.copy_resolution.fires` says §5.4's prompt should actually
ask about — is opened (or refreshed) in the :class:`~app.ports.duplicates.DuplicateQueue`
so a human can answer it later from the Books tab without re-running
anything; the moment an answer resolves it (this call or a later one, via
this same function or the queue's own "use the default" action), the
matching row is deleted. ``duplicates=None`` skips this bookkeeping entirely
— every REAL call site (the API layer) always provides one; tests that only
care about the write itself, not the queue, may omit it.

**Retracting a finding (P2.10, §12.2 #10).** :func:`retract_finding` is the
second entry point here, and it is deliberately NOT an extra
:class:`AnswerKind` on :func:`apply_diff`: an answer RESOLVES a question that
is still open, while a retraction RETRACTS something already settled and
written — often days later, from the image workspace, long after the read
auto-applied. Routing it through ``answers`` would also mean the unconditional
``unchanged`` loop above re-``observe()``-ing the very claim being retracted in
the same call, which reads as a bug however it is ordered. Same split as the
rest of this module: `app.domain.retract.plan_retraction` decides, this
persists.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.domain import (
    Book,
    Decision,
    Read,
    DecisionKind,
    Diff,
    FireDecision,
    LibraryRef,
    Provenance,
    RetractAction,
    Status,
    add_copy,
    fires,
    new_book,
    observe,
    open_or_refresh,
    plan_retraction,
    relink_copy,
    remove_from_shelf,
)
from app.domain.book import DomainError
from app.ports import Clock, IdGen
from app.ports.decisions import DecisionStore
from app.ports.duplicates import DuplicateQueue
from app.ports.store import BookStore, ShelfStore


class AnswerKind(str, Enum):
    """A human's response to one still-open (``needs_decision``) claim.

    ``CONFIRM`` only fits a claim reasoned ``new_book_unconfirmed`` (no prior
    record anywhere in the library): a human looking at it and saying "yes,
    real book" is itself an approval — stronger evidence than a read alone
    ever produces — so the book is created at :attr:`Status.APPROVED`, not
    ``AUTO``. Since 2026-08-09 that covers AUTO-tier claims too, not only
    REVIEW ones: nothing enters the library unapproved (see
    `app.domain.reconcile`'s own note on the reversal), which makes this the
    ONLY door a machine-read book ever comes through.

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

    ``title``/``author`` are only meaningful with :attr:`AnswerKind.CONFIRM`
    and mean *"yes — as corrected"*: the reader got the book right enough to
    recognise but spelled it wrong, and approving it as-read only to
    immediately edit the record would be two writes and two audit entries for
    one human act. The CLAIM is left exactly as the engine produced it (it is
    evidence, and `Claim` is frozen for that reason) — the correction lands on
    the `Book`, which is the thing being asserted about.
    """

    claim_id: str
    kind: AnswerKind
    copy_id: str | None = None
    title: str | None = None
    author: str | None = None


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
    duplicates: DuplicateQueue | None = None,
    captured_at: str | None = None,
    answers: tuple[Answer, ...] = (),
) -> AppliedResult:
    """Persist a reconciled diff, plus any freshly-supplied human answers.

    ``captured_at`` becomes every fresh :class:`Provenance`'s timestamp;
    defaults to ``clock.now_iso()`` when the caller has no better value (a
    `Read` normally does — ``read.finished_at`` — and should pass it).

    ``duplicates`` keeps the P2.6 queue in step (see the module docstring);
    pass ``None`` to skip that bookkeeping entirely.
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
        # Since 2026-08-09 `reconcile()` puts exactly one thing here: a book
        # the OWNER typed onto a photo (`manual_add`). A machine-read book is
        # never `added` unconditionally any more — it waits for a CONFIRM
        # answer below. Hence MANUAL, not AUTO: the only evidence this record
        # has is a person, and §5.1's ladder says that outranks every read.
        book = new_book(
            id=ids.new_id(), library_id=library.id, title=outcome.claim.title,
            author=outcome.claim.author, copy_id=ids.new_id(),
            status=Status.MANUAL, shelf_id=diff.shelf_id, depth=diff.depth,
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

    if duplicates is not None:
        _sync_duplicate_queue(diff, answers, duplicates, library=library,
                              when=when, ids=ids)

    return AppliedResult(books_saved=tuple(saved),
                         decisions_saved=tuple(saved_decisions))


# --- retracting a settled finding (P2.10) ------------------------------------

@dataclass(frozen=True)
class RetractedResult:
    """What a retraction actually did — the API turns this into its response,
    and the tests assert on it rather than re-reading the store."""

    action: RetractAction
    decision: Decision
    book: Book | None = None
    """The saved book when it survived (``REMOVE_FROM_SHELF``); ``None`` when
    it was deleted or there was never one."""
    deleted_book_id: str | None = None


def retract_finding(
    outcome,
    *,
    library: LibraryRef,
    shelf_id: str,
    depth: int,
    read: Read,
    books: BookStore,
    decisions: DecisionStore,
    clock: Clock,
    duplicates: DuplicateQueue | None = None,
    when: str | None = None,
) -> RetractedResult:
    """*"No — this finding is wrong"*, on a claim that has already been
    applied (P2.10's ✕; see the module docstring for why it is not an
    :class:`Answer`).

    Two writes, and the ORDER of importance is the opposite of the obvious
    one: the :class:`Decision` is the part that must always happen (§5.6 — a
    rejected book must not be re-added by a later run, and the very next read
    of this row would otherwise put it straight back), while what happens to
    the library record depends on
    :func:`app.domain.retract.plan_retraction`'s rule — a record this very
    read created is deleted, anything with a life of its own is merely taken
    off this shelf.

    ``outcome`` is a live :class:`~app.domain.reconcile.ClaimOutcome` from a
    freshly recomputed diff, never a stored snapshot, for the same reason
    P2.6's queue stores a pointer: the book may have been edited, gained a
    copy, or moved since the read.
    """
    stamp = when or clock.now_iso()
    plan = plan_retraction(
        outcome.existing_book, shelf_id, depth, read=read,
        # §5.4's ambiguous case is the one where the key names a book the
        # library already holds SOMEWHERE ELSE — the same question the
        # three-way prompt's "wrong book" answers, so it records the same
        # decision kind. Everything else is a plain "not a real book here".
        claimed_elsewhere=outcome.reason == "ambiguous_location",
    )
    decision = Decision(library_id=library.id, shelf_id=shelf_id, depth=depth,
                        book_key=outcome.book_key, kind=plan.decision_kind,
                        decided_at=stamp)
    decisions.save_decision(library, decision)

    saved: Book | None = None
    deleted_id: str | None = None
    if plan.action is RetractAction.DELETE_BOOK:
        books.delete(library, outcome.existing_book.id)
        deleted_id = outcome.existing_book.id
    elif plan.action is RetractAction.REMOVE_FROM_SHELF:
        saved = remove_from_shelf(outcome.existing_book, plan.copy_id)
        books.save(library, saved)

    if duplicates is not None:
        # A retraction ANSWERS §5.4's question if one was open at this key —
        # the same "an answer and its queue row are two states of one fact"
        # bookkeeping `_sync_duplicate_queue` does, here for the one act that
        # does not go through `apply_diff`.
        duplicates.delete_question(library, shelf_id, depth, outcome.book_key)

    return RetractedResult(action=plan.action, decision=decision, book=saved,
                           deleted_book_id=deleted_id)


# --- the P2.6 queue ----------------------------------------------------------

def _sync_duplicate_queue(
    diff: Diff,
    answers: tuple[Answer, ...],
    duplicates: DuplicateQueue,
    *,
    library: LibraryRef,
    when: str,
    ids: IdGen,
) -> None:
    """Keep the durable queue in step with what THIS call resolved.

    Every still-open ``ambiguous_location`` claim (the one reason
    :func:`fires` marks ASK — see the module docstring) with no matching
    answer is opened or refreshed; one that WAS answered this call is
    closed immediately, in the SAME write as the `Decision` that answered it,
    so a queue row can never outlive its own answer even by one request.

    Also sweeps ``corrected``/``rejected`` outcomes reasoned
    ``relinked_by_decision``, ``new_copy_by_decision`` or ``wrong_book`` —
    every one of those means a `Decision` now exists at that key (a REPLAY of
    an earlier answer, or a fresh WRONG_BOOK), so no open row may survive at
    it either, however that came to be. Defensive rather than load-bearing in
    the common flow: the row was normally already deleted the first time the
    decision was created.
    """
    answered_claim_ids = {a.claim_id for a in answers}

    for outcome in diff.needs_decision:
        if outcome.reason != "ambiguous_location":
            continue  # new_book_unconfirmed -- a different question (§5.4
                      # never applies), never a candidate for this queue.
        assert fires(outcome.reason) is FireDecision.ASK, (
            "FIRE_TABLE and reconcile()'s own classification have drifted "
            f"apart for reason {outcome.reason!r}"
        )
        if outcome.claim.id in answered_claim_ids:
            duplicates.delete_question(library, diff.shelf_id, diff.depth,
                                       outcome.book_key)
            continue
        existing = duplicates.get_question(library, diff.shelf_id, diff.depth,
                                           outcome.book_key)
        question = open_or_refresh(
            existing, new_id=ids.new_id(), library_id=library.id,
            shelf_id=diff.shelf_id, depth=diff.depth, book_key=outcome.book_key,
            read_id=diff.read_id, spine_id=outcome.claim.spine_id,
            claim_title=outcome.claim.title, claim_author=outcome.claim.author,
            existing_book_id=outcome.existing_book.id, when=when,
            captured_at=when,
        )
        duplicates.save_question(library, question)

    for outcome in (*diff.corrected, *diff.rejected):
        if outcome.reason in ("relinked_by_decision", "new_copy_by_decision",
                              "wrong_book"):
            duplicates.delete_question(library, diff.shelf_id, diff.depth,
                                       outcome.book_key)


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
    if outcome.reason == "new_book_unconfirmed":
        if answer.kind is AnswerKind.CONFIRM:
            title = (answer.title or outcome.claim.title).strip()
            if not title:
                raise UnresolvedAnswer(
                    f"claim {outcome.claim.id!r} has no title to confirm; "
                    "send one with the answer"
                )
            book = new_book(
                id=ids.new_id(), library_id=library.id, title=title,
                author=(answer.author if answer.author is not None
                        else outcome.claim.author),
                copy_id=ids.new_id(),
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
            f"{answer.kind.value!r} does not answer an unconfirmed new-book "
            f"claim (claim {outcome.claim.id!r}) — expected confirm or reject"
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
