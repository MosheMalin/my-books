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
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.adapters.memory_store import (
    MemoryBookStore,
    MemoryDecisionStore,
    MemoryShelfStore,
)
from app.domain import (
    Claim,
    ClaimTier,
    DecisionKind,
    LibraryRef,
    Status,
    UnknownCopy,
    new_book,
    new_shelf,
    reconcile,
)
from app.domain.book import DomainError
from app.reconcile_apply import Answer, AnswerKind, UnresolvedAnswer, apply_diff

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


def test_an_added_outcome_is_persisted_as_a_new_book():
    shelf, shelves, books, decisions, clock, ids = _rig()
    diff = reconcile(shelf, 1, [_claim()], {}, [], read_id="r1")
    result = apply_diff(diff, library=LIB, books=books, shelves=shelves,
                        decisions=decisions, clock=clock, ids=ids)

    assert len(result.books_saved) == 1
    saved = result.books_saved[0]
    assert saved.title == "מלכי הכופרים" and saved.status is Status.AUTO
    assert saved.copies[0].location == ("sh1", 1)
    assert saved.copies[0].provenance[0].sighting == ("r1", "sp1")
    assert books.count(LIB) == 1


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
    diff = reconcile(shelf, 1, [_claim()], {}, [], read_id="r1")  # this is `added`, not open
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


if __name__ == "__main__":
    import subprocess

    raise SystemExit(subprocess.call(
        [sys.executable, str(Path(__file__).parent / "run_all.py"), __file__]
    ))
