# -*- coding: utf-8 -*-
"""H4 ring — ``app.reconcile_apply``: turning a `Diff` into writes (P2.5).

Not a domain ring (`reconcile()` itself lives in ``tests/test_domain.py`` and
needs no store) — this module exercises the layer ABOVE it: real
``MemoryBookStore``/``MemoryShelfStore``/``MemoryDecisionStore`` instances, a
stub `Clock`/`IdGen`, and the actual persisted result. What matters here is
that the RULE `reconcile()` already decided is executed correctly and nothing
more — a wrong write here would be the silent-data-loss bug the plan calls
this item out for.
"""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.adapters.memory_store import (
    MemoryBookStore,
    MemoryDecisionStore,
    MemoryDuplicateQueue,
    MemoryShelfStore,
)
from app.domain import (
    DEFAULT_RESOLUTION,
    Claim,
    Provenance,
    ClaimTier,
    DecisionKind,
    LibraryRef,
    RetractAction,
    Status,
    UnknownCopy,
    approve,
    new_book,
    new_shelf,
    pick_default_copy,
    reconcile,
)
from app.domain.book import DomainError
from app.reconcile_apply import (
    Answer,
    AnswerKind,
    UnresolvedAnswer,
    apply_diff,
    retract_finding,
)

LIB = LibraryRef("lib-1", "Lib")
WHEN = "2026-08-07T12:00:00+00:00"


class StubClock:
    def now_iso(self) -> str:
        return WHEN


class SeqIdGen:
    def __init__(self) -> None:
        self._n = 0

    def new_id(self) -> str:
        self._n += 1
        return f"id-{self._n}"


def _raises(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc as e:
        return e
    raise AssertionError(f"expected {exc.__name__}, nothing raised")


READ_START = "2026-08-07T11:00:00+00:00"


def _read_for_retract():
    """The read a retraction is scoped to. Its start time is what lets
    `plan_retraction` tell a record this read created from one it merely
    reconfirmed — see `app/domain/retract.py`."""
    from app.domain import Read, ReadStatus

    return Read(id="r1", library_id=LIB.id, shelf_id="sh1", depth=1,
                capture_ids=("cap1",), mode="llmpage",
                status=ReadStatus.DONE, started_at=READ_START,
                finished_at=WHEN)


def _rig(depth_count: int = 1):
    shelves = MemoryShelfStore()
    shelf = new_shelf(id="sh1", library_id=LIB.id, depth_count=depth_count)
    shelves.save_shelf(LIB, shelf)
    return shelf, shelves, MemoryBookStore(), MemoryDecisionStore(), StubClock(), SeqIdGen()


def _claim(n: int = 1, **kw) -> Claim:
    args = dict(id=f"cl{n}", spine_id=f"sp{n}", capture_id="cap1",
                title="מלכי הכופרים", author="פול קארני",
                tier=ClaimTier.AUTO, score=90.0)
    args.update(kw)
    return Claim(**args)


def test_a_hand_added_finding_is_persisted_at_manual_with_no_approval_step():
    """The ONLY thing `added` still means after the 2026-08-09 reversal: a
    book the owner typed onto a photo. It enters at MANUAL — a person's word,
    not a read's — and it enters immediately, because asking someone to
    approve what they just typed is the ceremony that teaches people to click
    through prompts (§5.4's own warning, one screen over)."""
    shelf, shelves, books, decisions, clock, ids = _rig()
    typed = _claim(tier=ClaimTier.MANUAL, score=0.0)
    diff = reconcile(shelf, 1, [typed], {}, [], read_id="r1")
    result = apply_diff(diff, library=LIB, books=books, shelves=shelves,
                        decisions=decisions, clock=clock, ids=ids)

    assert len(result.books_saved) == 1
    saved = result.books_saved[0]
    assert saved.title == "מלכי הכופרים" and saved.status is Status.MANUAL
    assert saved.copies[0].location == ("sh1", 1)
    assert saved.copies[0].provenance[0].sighting == ("r1", "sp1")
    assert books.count(LIB) == 1


def test_a_machine_claim_writes_nothing_until_it_is_confirmed():
    """The reversal itself, at the layer that actually writes: applying a
    read whose claims are all unconfirmed must leave the library untouched.
    Reversing this is what put fourteen unasked-for books in the owner's
    library."""
    shelf, shelves, books, decisions, clock, ids = _rig()
    diff = reconcile(shelf, 1, [_claim()], {}, [], read_id="r1")
    result = apply_diff(diff, library=LIB, books=books, shelves=shelves,
                        decisions=decisions, clock=clock, ids=ids)

    assert result.books_saved == () and books.count(LIB) == 0

    confirmed = apply_diff(diff, library=LIB, books=books, shelves=shelves,
                           decisions=decisions, clock=clock, ids=ids,
                           answers=(Answer(claim_id="cl1",
                                           kind=AnswerKind.CONFIRM),))
    assert books.count(LIB) == 1
    saved = confirmed.books_saved[0]
    # A human said yes — APPROVED, never the AUTO rung a read alone produces.
    assert saved.status is Status.APPROVED
    assert saved.copies[0].provenance[0].sighting == ("r1", "sp1")


def test_confirming_as_corrected_files_the_typed_title_not_the_read_one():
    """One human act, one write: the reader recognised the book but spelled
    it wrong, and approving-then-editing would be two records of one
    decision. The CLAIM keeps the engine's text — it is evidence."""
    shelf, shelves, books, decisions, clock, ids = _rig()
    diff = reconcile(shelf, 1, [_claim(title="מלכי הכופריט")], {}, [],
                     read_id="r1")
    apply_diff(diff, library=LIB, books=books, shelves=shelves,
               decisions=decisions, clock=clock, ids=ids,
               answers=(Answer(claim_id="cl1", kind=AnswerKind.CONFIRM,
                               title="מלכי הכופרים", author="פול קארני"),))

    saved = books.list(LIB).items[0]
    assert saved.title == "מלכי הכופרים" and saved.author == "פול קארני"
    assert diff.needs_decision[0].claim.title == "מלכי הכופריט",         "the claim was rewritten; it is the engine's record, not the book's"


def test_an_unchanged_outcome_still_appends_provenance():
    """§5.6 row 1 says "no new record" — it does NOT say "no write". The
    sighting must land even though nothing about the record's shape changes."""
    shelf, shelves, books, decisions, clock, ids = _rig()
    here = new_book(id="b1", library_id=LIB.id, title="מלכי הכופרים",
                    author="פול קארני", copy_id="c1", shelf_id="sh1", depth=1)
    books.save(LIB, here)

    diff = reconcile(shelf, 1, [_claim()], {here.key: here}, [], read_id="r1")
    result = apply_diff(diff, library=LIB, books=books, shelves=shelves,
                        decisions=decisions, clock=clock, ids=ids)

    assert books.count(LIB) == 1, "unchanged must not create a second record"
    got = books.get(LIB, "b1")
    assert [p.sighting for p in got.copies[0].provenance] == [("r1", "sp1")]


def test_an_already_listed_answer_relinks_and_records_a_replayable_decision():
    shelf, shelves, books, decisions, clock, ids = _rig()
    elsewhere = new_book(id="b1", library_id=LIB.id, title="מלכי הכופרים",
                         author="פול קארני", copy_id="c1", shelf_id="sh9", depth=1)
    books.save(LIB, elsewhere)

    diff = reconcile(shelf, 1, [_claim()], {elsewhere.key: elsewhere}, [],
                     read_id="r1")
    apply_diff(diff, library=LIB, books=books, shelves=shelves,
              decisions=decisions, clock=clock, ids=ids,
              answers=(Answer(claim_id="cl1", kind=AnswerKind.ALREADY_LISTED),))

    got = books.get(LIB, "b1")
    assert got.copy_count == 1, "already-listed must not create a copy"
    assert got.copies[0].location == ("sh1", 1), "the copy was not relinked"

    stored = decisions.get_decision(LIB, "sh1", 1, elsewhere.key)
    assert stored is not None and stored.kind is DecisionKind.ALREADY_LISTED
    assert stored.copy_id == "c1"


def test_a_stored_already_listed_decision_is_never_asked_again():
    """The decision recorded above must make the NEXT read of this exact
    (shelf, depth, book_key) resolve on its own — this is what makes the
    `corrected` bucket real rather than theoretical."""
    shelf, shelves, books, decisions, clock, ids = _rig()
    elsewhere = new_book(id="b1", library_id=LIB.id, title="מלכי הכופרים",
                         author="פול קארני", copy_id="c1", shelf_id="sh9", depth=1)
    books.save(LIB, elsewhere)
    diff1 = reconcile(shelf, 1, [_claim(1)], {elsewhere.key: elsewhere}, [],
                      read_id="r1")
    apply_diff(diff1, library=LIB, books=books, shelves=shelves,
              decisions=decisions, clock=clock, ids=ids,
              answers=(Answer(claim_id="cl1", kind=AnswerKind.ALREADY_LISTED),))

    library_books = {b.key: b for b in books.list(LIB, limit=1000).items}
    stored = decisions.list_decisions(LIB, "sh1", 1)
    diff2 = reconcile(shelf, 1, [_claim(2)], library_books, stored, read_id="r2")

    assert not diff2.needs_decision, "the SAME question was asked twice"
    assert len(diff2.unchanged) == 1, (
        "a second read at the now-relinked location should be unchanged, "
        "not corrected again — the copy really is here now"
    )


def test_an_another_copy_answer_creates_a_manual_copy_with_provenance():
    shelf, shelves, books, decisions, clock, ids = _rig()
    elsewhere = new_book(id="b1", library_id=LIB.id, title="מלכי הכופרים",
                         author="פול קארני", copy_id="c1", shelf_id="sh9", depth=1)
    books.save(LIB, elsewhere)

    diff = reconcile(shelf, 1, [_claim()], {elsewhere.key: elsewhere}, [],
                     read_id="r1")
    apply_diff(diff, library=LIB, books=books, shelves=shelves,
              decisions=decisions, clock=clock, ids=ids,
              answers=(Answer(claim_id="cl1", kind=AnswerKind.ANOTHER_COPY),))

    got = books.get(LIB, "b1")
    assert got.copy_count == 2, "another-copy must create a NEW copy"
    original = got.copy("c1")
    new = next(c for c in got.copies if c.id != "c1")
    assert original.location == ("sh9", 1), "the original copy must not move"
    assert new.location == ("sh1", 1)
    assert new.status is Status.MANUAL
    assert [p.sighting for p in new.provenance] == [("r1", "sp1")], (
        "a copy created from a read's evidence must carry that evidence"
    )


def test_a_wrong_book_answer_writes_no_book_but_records_the_decision():
    shelf, shelves, books, decisions, clock, ids = _rig()
    elsewhere = new_book(id="b1", library_id=LIB.id, title="מלכי הכופרים",
                         author="פול קארני", copy_id="c1", shelf_id="sh9", depth=1)
    books.save(LIB, elsewhere)

    diff = reconcile(shelf, 1, [_claim()], {elsewhere.key: elsewhere}, [],
                     read_id="r1")
    result = apply_diff(diff, library=LIB, books=books, shelves=shelves,
                        decisions=decisions, clock=clock, ids=ids,
                        answers=(Answer(claim_id="cl1", kind=AnswerKind.WRONG_BOOK),))

    assert result.books_saved == ()
    assert books.get(LIB, "b1").copy_count == 1, "the existing book must be untouched"
    stored = decisions.get_decision(LIB, "sh1", 1, elsewhere.key)
    assert stored.kind is DecisionKind.WRONG_BOOK


def test_a_confirm_answer_creates_the_book_at_approved_not_auto():
    """A human confirming a REVIEW-tier claim IS an approval — stronger
    evidence than a read alone, so the new book must not land at the same
    rung an unattended AUTO claim would."""
    shelf, shelves, books, decisions, clock, ids = _rig()
    diff = reconcile(shelf, 1, [_claim(tier=ClaimTier.REVIEW, score=55.0)],
                     {}, [], read_id="r1")
    apply_diff(diff, library=LIB, books=books, shelves=shelves,
              decisions=decisions, clock=clock, ids=ids,
              answers=(Answer(claim_id="cl1", kind=AnswerKind.CONFIRM),))

    assert books.count(LIB) == 1
    got = next(iter(books.list(LIB).items))
    assert got.status is Status.APPROVED


def test_a_reject_answer_persists_a_decision_and_stops_the_re_add():
    shelf, shelves, books, decisions, clock, ids = _rig()
    diff1 = reconcile(shelf, 1, [_claim(tier=ClaimTier.REVIEW, score=40.0)],
                      {}, [], read_id="r1")
    apply_diff(diff1, library=LIB, books=books, shelves=shelves,
              decisions=decisions, clock=clock, ids=ids,
              answers=(Answer(claim_id="cl1", kind=AnswerKind.REJECT),))
    assert books.count(LIB) == 0

    stored = decisions.list_decisions(LIB, "sh1", 1)
    diff2 = reconcile(shelf, 1, [_claim(2, tier=ClaimTier.REVIEW, score=40.0)],
                      {}, stored, read_id="r2")
    assert not diff2.needs_decision and not diff2.added
    assert len(diff2.rejected) == 1


def test_answering_a_claim_that_is_not_open_is_a_domain_error():
    shelf, shelves, books, decisions, clock, ids = _rig()
    # A hand-typed claim is `added` — already settled, never a question.
    diff = reconcile(shelf, 1, [_claim(tier=ClaimTier.MANUAL)], {}, [],
                     read_id="r1")
    _raises(UnresolvedAnswer, apply_diff, diff, library=LIB, books=books,
           shelves=shelves, decisions=decisions, clock=clock, ids=ids,
           answers=(Answer(claim_id="cl1", kind=AnswerKind.CONFIRM),))


def test_answering_an_ambiguous_claim_with_confirm_is_refused():
    """§5.4's three answers and the review-claim's confirm/reject are
    DIFFERENT vocabularies, on purpose — mixing them would let a client
    silently misapply the wrong action to the wrong kind of claim."""
    shelf, shelves, books, decisions, clock, ids = _rig()
    elsewhere = new_book(id="b1", library_id=LIB.id, title="מלכי הכופרים",
                         author="פול קארני", copy_id="c1", shelf_id="sh9", depth=1)
    books.save(LIB, elsewhere)
    diff = reconcile(shelf, 1, [_claim()], {elsewhere.key: elsewhere}, [],
                     read_id="r1")
    _raises(UnresolvedAnswer, apply_diff, diff, library=LIB, books=books,
           shelves=shelves, decisions=decisions, clock=clock, ids=ids,
           answers=(Answer(claim_id="cl1", kind=AnswerKind.CONFIRM),))


def test_already_listed_with_several_copies_requires_naming_one():
    shelf, shelves, books, decisions, clock, ids = _rig()
    from app.domain import add_copy

    multi = add_copy(
        new_book(id="b1", library_id=LIB.id, title="מלכי הכופרים",
                 author="פול קארני", copy_id="c1", shelf_id="sh9", depth=1),
        copy_id="c1b", shelf_id="sh8", depth=1,
    )
    books.save(LIB, multi)
    diff = reconcile(shelf, 1, [_claim()], {multi.key: multi}, [], read_id="r1")

    _raises(UnresolvedAnswer, apply_diff, diff, library=LIB, books=books,
           shelves=shelves, decisions=decisions, clock=clock, ids=ids,
           answers=(Answer(claim_id="cl1", kind=AnswerKind.ALREADY_LISTED),))

    # …but naming one resolves it cleanly.
    apply_diff(diff, library=LIB, books=books, shelves=shelves,
              decisions=decisions, clock=clock, ids=ids,
              answers=(Answer(claim_id="cl1", kind=AnswerKind.ALREADY_LISTED,
                              copy_id="c1b"),))
    got = books.get(LIB, "b1")
    assert got.copy("c1b").location == ("sh1", 1)
    assert got.copy("c1").location == ("sh9", 1), "the untouched copy must not move"


def test_naming_a_copy_that_is_not_this_books_is_refused():
    shelf, shelves, books, decisions, clock, ids = _rig()
    elsewhere = new_book(id="b1", library_id=LIB.id, title="מלכי הכופרים",
                         author="פול קארני", copy_id="c1", shelf_id="sh9", depth=1)
    books.save(LIB, elsewhere)
    diff = reconcile(shelf, 1, [_claim()], {elsewhere.key: elsewhere}, [],
                     read_id="r1")
    _raises(UnknownCopy, apply_diff, diff, library=LIB, books=books,
           shelves=shelves, decisions=decisions, clock=clock, ids=ids,
           answers=(Answer(claim_id="cl1", kind=AnswerKind.ALREADY_LISTED,
                           copy_id="not-a-real-copy"),))


def test_not_seen_entries_are_never_written_anywhere():
    """P2.5 explicitly does not persist not_seen streaks (P2.8's job) — this
    asserts apply_diff() really does nothing with them, not merely that it
    doesn't crash."""
    shelf, shelves, books, decisions, clock, ids = _rig()
    here = new_book(id="b1", library_id=LIB.id, title="לא נקרא", author="",
                    copy_id="c1", shelf_id="sh1", depth=1)
    books.save(LIB, here)
    diff = reconcile(shelf, 1, [], {here.key: here}, [], read_id="r1")
    result = apply_diff(diff, library=LIB, books=books, shelves=shelves,
                        decisions=decisions, clock=clock, ids=ids)

    assert result.books_saved == () and result.decisions_saved == ()
    unchanged = books.get(LIB, "b1")
    assert unchanged == here, "a not-seen book must be left byte-for-byte alone"


def test_apply_refuses_when_the_shelf_no_longer_exists():
    """Defense in depth: a shelf deleted between computing the diff and
    applying it must not silently write claims about a place that no longer
    has an identity."""
    shelf, shelves, books, decisions, clock, ids = _rig()
    diff = reconcile(shelf, 1, [_claim()], {}, [], read_id="r1")
    empty_shelves = MemoryShelfStore()  # the shelf was never saved here
    _raises(DomainError, apply_diff, diff, library=LIB, books=books,
           shelves=empty_shelves, decisions=decisions, clock=clock, ids=ids)


# --- P2.6: the durable duplicates queue (§5.4) ------------------------------
#
# `duplicates=None` (every test above) must keep working unchanged — every
# test in this section is what proves the OPPOSITE: passing a real
# DuplicateQueue actually keeps it in step with what apply_diff writes.

def test_an_unanswered_ambiguous_claim_opens_a_duplicate_question():
    shelf, shelves, books, decisions, clock, ids = _rig()
    duplicates = MemoryDuplicateQueue()
    elsewhere = new_book(id="b1", library_id=LIB.id, title="מלכי הכופרים",
                         author="פול קארני", copy_id="c1", shelf_id="sh9", depth=1)
    books.save(LIB, elsewhere)

    diff = reconcile(shelf, 1, [_claim()], {elsewhere.key: elsewhere}, [],
                     read_id="r1")
    apply_diff(diff, library=LIB, books=books, shelves=shelves,
              decisions=decisions, duplicates=duplicates, clock=clock, ids=ids)

    open_qs = duplicates.list_open_questions(LIB)
    assert len(open_qs) == 1
    q = open_qs[0]
    assert q.shelf_id == "sh1" and q.depth == 1 and q.book_key == elsewhere.key
    assert q.existing_book_id == "b1"
    assert books.get(LIB, "b1").copy_count == 1, (
        "an unanswered claim must write NOTHING to the book — only the queue"
    )


def test_answering_a_queued_claim_closes_the_question_in_the_same_write():
    shelf, shelves, books, decisions, clock, ids = _rig()
    duplicates = MemoryDuplicateQueue()
    elsewhere = new_book(id="b1", library_id=LIB.id, title="מלכי הכופרים",
                         author="פול קארני", copy_id="c1", shelf_id="sh9", depth=1)
    books.save(LIB, elsewhere)
    diff = reconcile(shelf, 1, [_claim()], {elsewhere.key: elsewhere}, [],
                     read_id="r1")
    apply_diff(diff, library=LIB, books=books, shelves=shelves,
              decisions=decisions, duplicates=duplicates, clock=clock, ids=ids)
    assert len(duplicates.list_open_questions(LIB)) == 1

    apply_diff(diff, library=LIB, books=books, shelves=shelves,
              decisions=decisions, duplicates=duplicates, clock=clock, ids=ids,
              answers=(Answer(claim_id="cl1", kind=AnswerKind.ALREADY_LISTED),))
    assert duplicates.list_open_questions(LIB) == (), (
        "answering the claim must close the queue row, not leave it stale"
    )


def test_a_wrong_book_answer_also_closes_the_open_question():
    """WRONG_BOOK writes no book, but it DOES answer the question — the
    queue row must close exactly as it would for the other two answers."""
    shelf, shelves, books, decisions, clock, ids = _rig()
    duplicates = MemoryDuplicateQueue()
    elsewhere = new_book(id="b1", library_id=LIB.id, title="מלכי הכופרים",
                         author="פול קארני", copy_id="c1", shelf_id="sh9", depth=1)
    books.save(LIB, elsewhere)
    diff = reconcile(shelf, 1, [_claim()], {elsewhere.key: elsewhere}, [],
                     read_id="r1")
    apply_diff(diff, library=LIB, books=books, shelves=shelves,
              decisions=decisions, duplicates=duplicates, clock=clock, ids=ids)
    assert len(duplicates.list_open_questions(LIB)) == 1

    apply_diff(diff, library=LIB, books=books, shelves=shelves,
              decisions=decisions, duplicates=duplicates, clock=clock, ids=ids,
              answers=(Answer(claim_id="cl1", kind=AnswerKind.WRONG_BOOK),))
    assert duplicates.list_open_questions(LIB) == ()


def test_a_repeat_unanswered_claim_refreshes_the_same_row_not_a_second_one():
    """A later read of the same (shelf, depth) that ALSO leaves the question
    unanswered must not pile up a second row — `open_or_refresh` (the domain
    rule) keeps this to one, and this is the proof the real pipeline calls
    it rather than a bare upsert-by-accident that happens to look similar."""
    shelf, shelves, books, decisions, clock, ids = _rig()
    duplicates = MemoryDuplicateQueue()
    elsewhere = new_book(id="b1", library_id=LIB.id, title="מלכי הכופרים",
                         author="פול קארני", copy_id="c1", shelf_id="sh9", depth=1)
    books.save(LIB, elsewhere)

    diff1 = reconcile(shelf, 1, [_claim(1)], {elsewhere.key: elsewhere}, [],
                      read_id="r1")
    apply_diff(diff1, library=LIB, books=books, shelves=shelves,
              decisions=decisions, duplicates=duplicates, clock=clock, ids=ids)
    first_id = duplicates.list_open_questions(LIB)[0].id

    diff2 = reconcile(shelf, 1, [_claim(2)], {elsewhere.key: elsewhere}, [],
                      read_id="r2")
    apply_diff(diff2, library=LIB, books=books, shelves=shelves,
              decisions=decisions, duplicates=duplicates, clock=clock, ids=ids)

    open_qs = duplicates.list_open_questions(LIB)
    assert len(open_qs) == 1, "a repeat unanswered claim opened a SECOND row"
    assert open_qs[0].id == first_id, "the row's id must survive a refresh"
    assert open_qs[0].read_id == "r2", "but its content should be the latest"


def test_the_skip_default_relinks_rather_than_creating_a_second_copy():
    """§5.4, verbatim: 'default when the question is skipped or the run is
    never reviewed: already listed copy -- one copy, relinked.' The
    end-to-end, MUTATION-CHECKABLE proof: this simulates exactly what
    ``POST /duplicates/{id}/skip`` does (app/api/routers/duplicates.py) —
    resolve with DEFAULT_RESOLUTION against the SAME candidate
    pick_default_copy would preselect. Reversing DEFAULT_RESOLUTION to
    ANOTHER_COPY makes this fail with copy_count == 2: a phantom copy is
    exactly what that reversal invents, and §5.1 says a default may never
    create one on its own.
    """
    shelf, shelves, books, decisions, clock, ids = _rig()
    duplicates = MemoryDuplicateQueue()
    elsewhere = new_book(id="b1", library_id=LIB.id, title="מלכי הכופרים",
                         author="פול קארני", copy_id="c1", shelf_id="sh9", depth=1)
    books.save(LIB, elsewhere)
    diff = reconcile(shelf, 1, [_claim()], {elsewhere.key: elsewhere}, [],
                     read_id="r1")
    apply_diff(diff, library=LIB, books=books, shelves=shelves,
              decisions=decisions, duplicates=duplicates, clock=clock, ids=ids)
    assert books.get(LIB, "b1").copy_count == 1
    assert len(duplicates.list_open_questions(LIB)) == 1

    kind_of = {DecisionKind.ALREADY_LISTED: AnswerKind.ALREADY_LISTED,
              DecisionKind.ANOTHER_COPY: AnswerKind.ANOTHER_COPY}
    candidate = pick_default_copy(elsewhere)
    default_answer = Answer(claim_id="cl1", kind=kind_of[DEFAULT_RESOLUTION],
                            copy_id=candidate.id)
    apply_diff(diff, library=LIB, books=books, shelves=shelves,
              decisions=decisions, duplicates=duplicates, clock=clock, ids=ids,
              answers=(default_answer,))

    got = books.get(LIB, "b1")
    assert got.copy_count == 1, (
        "the default resolution created a second copy — this is the "
        "phantom-copy regression §5.1/§5.4 exist to prevent"
    )
    assert got.copies[0].location == ("sh1", 1), "the copy was not relinked"
    assert duplicates.list_open_questions(LIB) == ()


def test_duplicates_none_skips_the_queue_bookkeeping_entirely():
    """Every test above this section already exercises `duplicates=None`
    implicitly; this one names the contract directly, so a future reader
    does not have to infer it from absence."""
    shelf, shelves, books, decisions, clock, ids = _rig()
    elsewhere = new_book(id="b1", library_id=LIB.id, title="מלכי הכופרים",
                         author="פול קארני", copy_id="c1", shelf_id="sh9", depth=1)
    books.save(LIB, elsewhere)
    diff = reconcile(shelf, 1, [_claim()], {elsewhere.key: elsewhere}, [],
                     read_id="r1")
    # Must not raise, and must not implicitly require a queue.
    apply_diff(diff, library=LIB, books=books, shelves=shelves,
              decisions=decisions, clock=clock, ids=ids)
    assert books.get(LIB, "b1").copy_count == 1


# --- retracting a settled finding (P2.10, §12.2 #10) ------------------------

def _applied(claim=None, *, depth_count: int = 1, existing=None):
    """Run one claim all the way through apply, the way a settled read does
    (P2.9's automatic apply), and hand back the rig plus the freshly
    recomputed outcome the workspace's ✕ would act on."""
    shelf, shelves, books, decisions, clock, ids = _rig(depth_count)
    if existing is not None:
        books.save(LIB, existing)
    claim = claim or _claim()
    library_books = {b.key: b for b in books.list(LIB, limit=100).items}
    diff = reconcile(shelf, 1, [claim], library_books, [], read_id="r1")
    # CONFIRM every still-open finding: since 2026-08-09 a machine claim
    # writes nothing until a human approves it, and a retraction is only
    # meaningful against a finding that actually landed.
    apply_diff(diff, library=LIB, books=books, shelves=shelves,
               decisions=decisions, clock=clock, ids=ids,
               answers=tuple(Answer(claim_id=o.claim.id, kind=AnswerKind.CONFIRM)
                             for o in diff.needs_decision
                             if o.reason == "new_book_unconfirmed"))

    fresh_books = {b.key: b for b in books.list(LIB, limit=100).items}
    fresh = reconcile(shelf, 1, [claim], fresh_books,
                      decisions.list_decisions(LIB, "sh1", 1), read_id="r1")
    outcome = next(o for group in (fresh.unchanged, fresh.added, fresh.corrected,
                                   fresh.needs_decision)
                   for o in group)
    return outcome, shelves, books, decisions, clock, ids


def test_retracting_an_auto_finding_deletes_the_phantom_and_records_the_no():
    """The workspace's ✕ on a book only a read ever claimed: gone from the
    library, AND suppressed here — CLAUDE.md's phantom, and §5.6's "a
    rejected book must not be re-added by a later run", in one act."""
    outcome, shelves, books, decisions, clock, ids = _applied()
    assert books.count(LIB) == 1

    result = retract_finding(outcome, library=LIB, shelf_id="sh1", depth=1,
                            read=_read_for_retract(), books=books, decisions=decisions, clock=clock)

    assert result.action is RetractAction.DELETE_BOOK
    assert books.count(LIB) == 0
    stored = decisions.get_decision(LIB, "sh1", 1, outcome.book_key)
    assert stored is not None and stored.kind is DecisionKind.REJECTED


def test_a_retracted_finding_is_not_re_added_by_the_next_read():
    """The whole point of writing the decision. Without it the identical
    claim reconciles as `added` again and the phantom comes back."""
    outcome, shelves, books, decisions, clock, ids = _applied()
    retract_finding(outcome, library=LIB, shelf_id="sh1", depth=1,
                    read=_read_for_retract(), books=books, decisions=decisions, clock=clock)

    shelf = shelves.get_shelf(LIB, "sh1")
    again = reconcile(shelf, 1, [_claim()], {},
                      decisions.list_decisions(LIB, "sh1", 1), read_id="r2")
    assert not again.added
    assert [o.reason for o in again.rejected] == ["rejected"]
    apply_diff(again, library=LIB, books=books, shelves=shelves,
               decisions=decisions, clock=clock, ids=ids)
    assert books.count(LIB) == 0, "the retracted book came back on a re-read"


def test_retracting_keeps_a_book_that_existed_before_this_read():
    """UI_PLAN §5's separation, at the layer that writes: *remove from shelf*
    is not *delete from library*. A book an earlier read (or P1.3's import)
    put in the library has a life of its own — one ✕ on one photo's finding
    must take it off this shelf and no more."""
    shelf, shelves, books, decisions, clock, ids = _rig()
    older = new_book(id="b1", library_id=LIB.id, title="מלכי הכופרים",
                     author="פול קארני", copy_id="c1", shelf_id="sh1", depth=1,
                     provenance=(Provenance(run_id="an-older-read",
                                            spine_id="sp9", shelf_id="sh1",
                                            depth=1),))
    books.save(LIB, older)
    diff = reconcile(shelf, 1, [_claim()], {older.key: older}, [], read_id="r1")
    outcome = diff.unchanged[0]

    result = retract_finding(outcome, library=LIB, shelf_id="sh1", depth=1,
                            read=_read_for_retract(), books=books, decisions=decisions,
                            clock=clock)

    assert result.action is RetractAction.REMOVE_FROM_SHELF
    still_here = books.get(LIB, "b1")
    assert still_here is not None, "a book older than this read was deleted"
    assert still_here.copies[0].location is None
    assert still_here.copies[0].provenance, "its history was destroyed too"


def test_retracting_an_ambiguous_claim_records_wrong_book_and_closes_the_queue():
    """§5.4's third answer, reached from the workspace instead of the prompt —
    it must land on the same standing decision AND clear the durable question,
    or the queue keeps asking something already answered."""
    shelf, shelves, books, decisions, clock, ids = _rig()
    duplicates = MemoryDuplicateQueue()
    elsewhere = new_book(id="b1", library_id=LIB.id, title="מלכי הכופרים",
                         author="פול קארני", copy_id="c1", shelf_id="sh9", depth=1)
    books.save(LIB, elsewhere)
    diff = reconcile(shelf, 1, [_claim()], {elsewhere.key: elsewhere}, [],
                     read_id="r1")
    apply_diff(diff, library=LIB, books=books, shelves=shelves,
               decisions=decisions, duplicates=duplicates, clock=clock, ids=ids)
    assert len(duplicates.list_open_questions(LIB)) == 1

    outcome = diff.needs_decision[0]
    result = retract_finding(outcome, library=LIB, shelf_id="sh1", depth=1,
                            read=_read_for_retract(), books=books, decisions=decisions, clock=clock,
                            duplicates=duplicates)

    assert result.action is RetractAction.NOTHING, \
        "the book stands on another shelf — this row has nothing to remove"
    assert decisions.get_decision(LIB, "sh1", 1, outcome.book_key).kind \
        is DecisionKind.WRONG_BOOK
    assert duplicates.list_open_questions(LIB) == ()
    assert books.get(LIB, "b1").copies[0].location == ("sh9", 1), \
        "retracting here touched the copy standing somewhere else"


def test_undoing_a_retraction_lets_the_same_claim_apply_again():
    """The workspace's ↩ — clearing the standing decision (`DecisionStore`'s
    own "undo of a mis-click") and re-applying is what puts the book back;
    the API route composes exactly these two steps."""
    outcome, shelves, books, decisions, clock, ids = _applied()
    retract_finding(outcome, library=LIB, shelf_id="sh1", depth=1,
                    read=_read_for_retract(), books=books, decisions=decisions, clock=clock)
    assert books.count(LIB) == 0

    assert decisions.delete_decision(LIB, "sh1", 1, outcome.book_key) is True
    shelf = shelves.get_shelf(LIB, "sh1")
    again = reconcile(shelf, 1, [_claim()], {}, [], read_id="r1")
    # The claim is a question again — undoing a rejection restores the
    # FINDING, not the book; approving it is still a human's act.
    assert len(again.needs_decision) == 1
    apply_diff(again, library=LIB, books=books, shelves=shelves,
               decisions=decisions, clock=clock, ids=ids,
               answers=(Answer(claim_id="cl1", kind=AnswerKind.CONFIRM),))
    assert books.count(LIB) == 1


if __name__ == "__main__":
    import subprocess

    raise SystemExit(subprocess.call(
        [sys.executable, str(Path(__file__).parent / "run_all.py"), __file__]
    ))
