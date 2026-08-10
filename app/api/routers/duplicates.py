# -*- coding: utf-8 -*-
"""/api/v1/duplicates — the durable "duplicates to resolve" queue (P2.6, §5.4).

THIN by rule (H3): the fire/never-fire table, the default answer and the two
cheap wins all live in ``app.domain.copy_resolution``; the queue bookkeeping
(open on skip, close on answer) lives in ``app.reconcile_apply``. This module
is the HTTP shape over both, plus the one piece of orchestration that has
nowhere else to live — re-deriving which `ClaimOutcome` a queued question
was raised from before it can be answered, the same "recompute, never cache"
idiom ``reads.py``'s own diff endpoints already follow.

Not nested under ``/shelves/{shelf_id}`` like reads are: a queued question is
about a BOOK, and the Books tab's "duplicates to resolve" filter (this
item's other half, ``GET /books?duplicates=true``) needs to list them across
the WHOLE library in one call — nesting under one shelf would make that a
fan-out.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import (
    get_book_store,
    get_clock,
    get_decision_store,
    get_duplicate_queue,
    get_id_gen,
    get_read_store,
    get_shelf_store,
)
from app.api.dto import BookDTO, DuplicateAnswerIn, DuplicateQuestionDTO
from app.api.policy import require
from app.api.routers.reads import diff_for
from app.domain import (
    DEFAULT_RESOLUTION,
    Capability,
    DecisionKind,
    LibraryRef,
    build_prompt,
)
from app.ports import Clock, IdGen
from app.ports.decisions import DecisionStore
from app.ports.duplicates import DuplicateQueue
from app.ports.store import BookStore, ReadStore, ShelfStore
from app.reconcile_apply import Answer, AnswerKind, UnresolvedAnswer, apply_diff

router = APIRouter(prefix="/duplicates", tags=["duplicates"])

# §5.4's queue only ever concerns the ambiguous-location prompt (already
# listed / another copy / wrong book) — the review-tier "is this a real
# book?" question (confirm/reject) has no standing queue, so this map is
# deliberately narrower than reads.py's `_ANSWER_KINDS`.
_ANSWER_KINDS = {
    "already_listed": AnswerKind.ALREADY_LISTED,
    "another_copy": AnswerKind.ANOTHER_COPY,
    "wrong_book": AnswerKind.WRONG_BOOK,
}
_DEFAULT_ANSWER_KIND = {
    DecisionKind.ALREADY_LISTED: AnswerKind.ALREADY_LISTED,
    DecisionKind.ANOTHER_COPY: AnswerKind.ANOTHER_COPY,
}[DEFAULT_RESOLUTION]


def _find_open(duplicates: DuplicateQueue, library: LibraryRef, question_id: str):
    """By the minted id every route addresses one question with.

    A linear scan of the OPEN set, not an indexed lookup — deliberate: the
    queue is expected to hold at most a handful of genuinely ambiguous
    claims at once (that is the whole point of §5.4's "must fire rarely"
    requirement), never library-scale. Revisit if that assumption is ever
    measured wrong, the same "measure before adding an index" stance
    ``app.domain.search`` documents for its own linear scan.
    """
    for q in duplicates.list_open_questions(library):
        if q.id == question_id:
            return q
    return None


def _load_question(duplicates: DuplicateQueue, library: LibraryRef, question_id: str):
    question = _find_open(duplicates, library, question_id)
    if question is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such open question")
    return question


def _resolve_outcome(
    question, library: LibraryRef, shelves: ShelfStore, reads: ReadStore,
    books: BookStore, decisions: DecisionStore, duplicates: DuplicateQueue,
):
    """Re-derive the EXACT `ClaimOutcome` this question was raised from.

    The queue stores a pointer ``(shelf_id, read_id, book_key)``, never a
    frozen snapshot — same "recompute against current reality" idiom
    ``reads.py``'s own diff endpoints follow. If it no longer resolves to an
    open ``ambiguous_location`` outcome at that key (the book was deleted,
    the read's claims changed underfoot, or — most likely — someone else
    already answered it a moment ago), the question is STALE: it is dropped
    from the queue right here rather than left to confuse the next listing,
    and the caller gets a 409 rather than a silently wrong write.
    """
    read, diff = diff_for(question.shelf_id, question.read_id, library,
                          shelves, reads, books, decisions)
    for outcome in diff.needs_decision:
        if outcome.reason == "ambiguous_location" and outcome.book_key == question.book_key:
            return read, diff, outcome
    duplicates.delete_question(library, question.shelf_id, question.depth,
                               question.book_key)
    raise HTTPException(
        status.HTTP_409_CONFLICT,
        f"question {question.id} is no longer open — it may already have "
        "been answered, or the book or read it concerned changed",
    )


@router.get("", response_model=list[DuplicateQuestionDTO])
def list_open_questions(
    library: LibraryRef = Depends(require(Capability.BROWSE)),
    books: BookStore = Depends(get_book_store),
    duplicates: DuplicateQueue = Depends(get_duplicate_queue),
) -> list[DuplicateQuestionDTO]:
    """Every open §5.4 ask across the whole library — what the Books tab's
    "duplicates to resolve" filter (``GET /books?duplicates=true``) narrows
    to, and what this screen answers or skips from."""
    out: list[DuplicateQuestionDTO] = []
    for q in duplicates.list_open_questions(library):
        book = books.get(library, q.existing_book_id)
        if book is None:
            # The book this question was about no longer exists — nothing
            # left to ask about it. SKIPPED here, not deleted: this is a GET
            # on a BROWSE capability, and a Viewer's listing must never write
            # (P3.2's data-integrity review caught the earlier inline
            # cleanup). The stale row costs nothing to skip and is deleted by
            # the REVIEW-gated paths that already do it — `_resolve_outcome`
            # removes it the moment anyone tries to answer or skip it.
            continue
        out.append(DuplicateQuestionDTO.of(q, book=book, prompt=build_prompt(book)))
    return out


@router.post("/{question_id}/answer", response_model=BookDTO)
def answer_question(
    question_id: str,
    body: DuplicateAnswerIn,
    library: LibraryRef = Depends(require(Capability.REVIEW)),
    shelves: ShelfStore = Depends(get_shelf_store),
    reads: ReadStore = Depends(get_read_store),
    books: BookStore = Depends(get_book_store),
    decisions: DecisionStore = Depends(get_decision_store),
    duplicates: DuplicateQueue = Depends(get_duplicate_queue),
    clock: Clock = Depends(get_clock),
    ids: IdGen = Depends(get_id_gen),
) -> BookDTO:
    """A human's real answer — already listed / another copy / wrong book —
    to one queued question. Closes the queue row in the SAME write as the
    `Decision` it creates (``app.reconcile_apply``'s bookkeeping)."""
    question = _load_question(duplicates, library, question_id)
    kind = _ANSWER_KINDS.get(body.kind)
    if kind is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"unknown answer kind {body.kind!r}; expected one of "
            f"{sorted(_ANSWER_KINDS)}",
        )
    read, diff, outcome = _resolve_outcome(question, library, shelves, reads,
                                           books, decisions, duplicates)
    answer = Answer(claim_id=outcome.claim.id, kind=kind, copy_id=body.copy_id)
    try:
        apply_diff(diff, library=library, books=books, shelves=shelves,
                  decisions=decisions, duplicates=duplicates, clock=clock,
                  ids=ids, captured_at=read.finished_at, answers=(answer,))
    except UnresolvedAnswer as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    book = books.get(library, question.existing_book_id)
    if book is None:
        # WRONG_BOOK writes no book; existing_book_id still names the one
        # this question was ABOUT, and it is untouched either way.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such book")
    return BookDTO.of(book)


@router.post("/{question_id}/skip", response_model=BookDTO)
def skip_question(
    question_id: str,
    library: LibraryRef = Depends(require(Capability.REVIEW)),
    shelves: ShelfStore = Depends(get_shelf_store),
    reads: ReadStore = Depends(get_read_store),
    books: BookStore = Depends(get_book_store),
    decisions: DecisionStore = Depends(get_decision_store),
    duplicates: DuplicateQueue = Depends(get_duplicate_queue),
    clock: Clock = Depends(get_clock),
    ids: IdGen = Depends(get_id_gen),
) -> BookDTO:
    """*"Not now — use the safe default."* §5.4, verbatim: *"Default when the
    question is skipped or the run is never reviewed: already listed copy —
    one copy, relinked."* Distinct from simply NOT answering during
    ``POST .../reads/{id}/apply`` (which leaves the question open in this
    same queue for later) — this is the explicit "stop asking about this
    one" action, and it always resolves to
    :data:`app.domain.copy_resolution.DEFAULT_RESOLUTION`, never to creating
    a copy: reversing that default is exactly the mistake that invents a
    phantom object nobody asked for.
    """
    question = _load_question(duplicates, library, question_id)
    read, diff, outcome = _resolve_outcome(question, library, shelves, reads,
                                           books, decisions, duplicates)
    candidate = build_prompt(outcome.existing_book).candidate_copy_id
    answer = Answer(claim_id=outcome.claim.id, kind=_DEFAULT_ANSWER_KIND,
                    copy_id=candidate)
    apply_diff(diff, library=library, books=books, shelves=shelves,
              decisions=decisions, duplicates=duplicates, clock=clock,
              ids=ids, captured_at=read.finished_at, answers=(answer,))

    book = books.get(library, question.existing_book_id)
    if book is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such book")
    return BookDTO.of(book)
