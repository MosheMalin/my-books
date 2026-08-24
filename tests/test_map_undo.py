# -*- coding: utf-8 -*-
"""The undo journal (P6.4b, MAP_PLAN §3.15).

One test per reversible sentence of the decision, in the shape
``test_domain.py`` uses — not coverage of the module. The three sentences the
owner settled on 2026-08-24 are the three this file exists to hold in place:

  - an undo proves the world is unchanged with a FINGERPRINT taken at undo
    time, and **there is no expiry** — age is not evidence;
  - the journal RECORDS every destructive edit and only the HEAD is undoable.
    Undoing does not expose the edit before it, and there is no redo;
  - the grain of an entry is the OPERATION, not the request — which is what
    makes deleting a bookcase (two calls) one undo.

Each is mutation-checked: reverse the rule, watch the named test fail.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.adapters.memory_store import (  # noqa: E402
    MemoryBookStore,
    MemoryMapStore,
    MemoryMapUndoStore,
    MemoryShelfStore,
)
from app.domain import (  # noqa: E402
    LibraryRef,
    Rect,
    ShelfAddress,
    new_bookcase,
    new_book,
    new_floor,
    new_place,
    new_section,
    new_site,
    with_column_count,
    with_gaps,
)
from app.map_edit import (  # noqa: E402
    apply_gaps,
    apply_slot_change,
    clear_bookcase_slots,
    clear_section_slots,
    draw_bookcase,
    remove_record,
)
from app.map_undo import Journal, UndoRefused, offer, undo  # noqa: E402

LIB = LibraryRef("lib-1", "הבית")
OTHER = LibraryRef("lib-2", "הדירה")


class StubClock:
    """A clock that MOVES, unlike ``test_map_edit``'s.

    Two entries recorded at the same instant make "which is the head?"
    depend on an id tiebreak, and a journal test that cannot order its own
    entries is testing the tiebreak instead of the rule.
    """

    def __init__(self, start: int = 0) -> None:
        self._n = start

    def now_iso(self) -> str:
        self._n += 1
        return f"2026-08-24T10:{self._n:02d}:00+00:00"


class SeqIdGen:
    def __init__(self, prefix: str = "id") -> None:
        self._n = 0
        self._prefix = prefix

    def new_id(self) -> str:
        self._n += 1
        return f"{self._prefix}-{self._n}"


def _world():
    shelves = MemoryShelfStore()
    maps = MemoryMapStore()
    books = MemoryBookStore()
    maps.bind_shelves(shelves)
    shelves.bind_map(maps)
    shelves.bind_books(books)
    for lib in (LIB, OTHER):
        maps.save_site(lib, new_site(id=f"st-{lib.id}", library_id=lib.id,
                                     name="הבית"))
        maps.save_floor(lib, new_floor(id=f"fl-{lib.id}", library_id=lib.id,
                                       site_id=f"st-{lib.id}", name="קרקע"))
        maps.save_place(lib, new_place(id=f"pl-{lib.id}", library_id=lib.id,
                                       floor_id=f"fl-{lib.id}",
                                       rect=Rect(0, 0, 12, 9), name="סלון"))
    journal = Journal(store=MemoryMapUndoStore(), ids=SeqIdGen("u"),
                      clock=StubClock())
    return maps, shelves, books, journal


def _draw(maps, shelves, *, lib=LIB, case_id="bc", columns=2, levels=3):
    case = new_bookcase(id=case_id, library_id=lib.id, floor_id=f"fl-{lib.id}",
                        rect=Rect(0, 0, 4, 1), place_id=f"pl-{lib.id}")
    return draw_bookcase(maps, shelves, lib, case, ids=SeqIdGen(case_id),
                         clock=StubClock(), columns=columns, levels=levels,
                         depth=1)


def _shelve_a_book(books, shelf_id, *, lib=LIB, n=1, depth=1):
    books.save(lib, new_book(id=f"b{n}", library_id=lib.id, title="ספר",
                             author="סופר", copy_id=f"c{n}",
                             shelf_id=shelf_id, depth=depth))


def _at(shelves, section_id, col, level, *, lib=LIB):
    return shelves.get_shelf_at(lib, ShelfAddress(section_id, col, level))


def _raises(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc as e:
        return e
    raise AssertionError(f"expected {exc.__name__}, nothing raised")


# --- what gets recorded ---------------------------------------------------

def test_removing_a_column_records_the_shelves_it_destroyed():
    """§3.15's first named edit. The inverse is the ROWS, not the request: the
    entry has to carry each lost shelf whole, because an id cannot be put
    back."""
    maps, shelves, books, journal = _world()
    drawn = _draw(maps, shelves)
    section = drawn.sections[0]
    doomed = _at(shelves, section.id, 2, 1)
    shelves.save_shelf(LIB, doomed.__class__(**{**doomed.__dict__,
                                                "label": "מדף ימני"}))

    apply_slot_change(maps, shelves, books, LIB,
                      with_column_count(maps.get_section(LIB, section.id), 1),
                      journal=journal, ids=SeqIdGen("new"), clock=StubClock())

    entry = journal.store.recent(LIB, limit=1)[0]
    assert entry.kind == "remove_column"
    kept = {s.id: s for s in entry.restore.shelves}
    assert doomed.id in kept, "the destroyed shelf is not in its own inverse"
    assert kept[doomed.id].label == "מדף ימני"
    assert kept[doomed.id].address == ShelfAddress(section.id, 2, 1)
    assert entry.restore.sections[0].column_levels == (3, 3), (
        "the section's shape before the edit was not remembered")


def test_an_edit_that_destroyed_nothing_records_nothing():
    """A one-deep journal has ONE slot, so an entry for a no-op edit is not
    merely noise — it evicts the real undo standing behind it."""
    maps, shelves, books, journal = _world()
    drawn = _draw(maps, shelves, columns=2, levels=3)
    section = maps.get_section(LIB, drawn.sections[0].id)
    # Grow, rather than shrink: nothing is lost, so nothing is undoable.
    apply_slot_change(maps, shelves, books, LIB, with_column_count(section, 3),
                      journal=journal, ids=SeqIdGen("new"), clock=StubClock())
    assert journal.store.recent(LIB, limit=5) == ()


def test_every_destructive_map_edit_records_one(  # noqa: C901
):
    """All FIVE of them — the four §3.15 named plus the gaps P6.3.2 added.

    ⚠ A hardcoded list, so it does NOT catch a sixth destructive edit added
    later — an earlier version of this docstring claimed it did. What the
    required ``journal`` argument buys is that a new destructive function
    cannot be written without being handed somewhere to record its inverse;
    remembering to CALL ``_record`` is still a thing a person does. This
    checks the five that exist, from the outside.
    """
    seen = {}

    maps, shelves, books, journal = _world()
    drawn = _draw(maps, shelves, columns=2, levels=3)
    section_id = drawn.sections[0].id
    apply_slot_change(
        maps, shelves, books, LIB,
        with_column_count(maps.get_section(LIB, section_id), 1),
        journal=journal, ids=SeqIdGen("a"), clock=StubClock())
    seen["remove_column"] = journal.store.recent(LIB)[0].kind

    maps, shelves, books, journal = _world()
    drawn = _draw(maps, shelves, columns=2, levels=3)
    section = maps.get_section(LIB, drawn.sections[0].id)
    apply_gaps(maps, shelves, books, LIB,
               with_gaps(section, [(2, 2)], gap=True),
               journal=journal, ids=SeqIdGen("b"), clock=StubClock())
    seen["gaps"] = journal.store.recent(LIB)[0].kind

    maps, shelves, books, journal = _world()
    drawn = _draw(maps, shelves)
    clear_bookcase_slots(maps, shelves, books, LIB, drawn.bookcase.id,
                         journal=journal)
    seen["clear_bookcase"] = journal.store.recent(LIB)[0].kind

    maps, shelves, books, journal = _world()
    drawn = _draw(maps, shelves)
    clear_section_slots(maps, shelves, books, LIB, drawn.sections[0].id,
                        journal=journal)
    seen["clear_section"] = journal.store.recent(LIB)[0].kind

    maps, shelves, books, journal = _world()
    # A site with nothing under it — RESTRICT refuses any other kind.
    maps.save_site(LIB, new_site(id="st-spare", library_id=LIB.id, name="גג"))
    remove_record(maps, shelves, LIB, "site", "st-spare", journal=journal)
    seen["delete_site"] = journal.store.recent(LIB)[0].kind

    assert seen == {
        "remove_column": "remove_column",
        "gaps": "gaps",
        "clear_bookcase": "clear_bookcase",
        "clear_section": "clear_section",
        "delete_site": "delete_site",
    }, f"a destructive map edit recorded nothing: {seen}"


# --- what an undo puts back ------------------------------------------------

def test_undoing_a_removed_column_puts_the_shelves_back_where_they_stood():
    """The whole promise, end to end: the shelf returns with its id, its label
    and its address — not a fresh shelf in the same slot, which is what the
    client's own redraw would produce and what §3.15 calls a guessed
    inverse."""
    maps, shelves, books, journal = _world()
    drawn = _draw(maps, shelves)
    section = drawn.sections[0]
    doomed = _at(shelves, section.id, 2, 1)
    apply_slot_change(maps, shelves, books, LIB,
                      with_column_count(maps.get_section(LIB, section.id), 1),
                      journal=journal, ids=SeqIdGen("new"), clock=StubClock())
    assert shelves.get_shelf(LIB, doomed.id) is None, "not destroyed to begin with"

    undo(journal, maps, shelves, books, LIB)

    back = shelves.get_shelf(LIB, doomed.id)
    assert back is not None, "the undo did not put the shelf back"
    assert back.address == ShelfAddress(section.id, 2, 1)
    assert maps.get_section(LIB, section.id).column_levels == (3, 3)


def test_an_occupied_shelf_comes_back_to_its_slot_with_its_books():
    """The case that makes recording beat deriving. A detached shelf keeps its
    books (``_release``'s rule); the undo must return its ADDRESS without
    touching the books, so nothing about the copy moves in either
    direction."""
    maps, shelves, books, journal = _world()
    drawn = _draw(maps, shelves)
    section = drawn.sections[0]
    occupied = _at(shelves, section.id, 2, 1)
    _shelve_a_book(books, occupied.id)

    apply_slot_change(maps, shelves, books, LIB,
                      with_column_count(maps.get_section(LIB, section.id), 1),
                      journal=journal, ids=SeqIdGen("new"), clock=StubClock())
    assert shelves.get_shelf(LIB, occupied.id).address is None, (
        "an occupied shelf should have been detached, not deleted")

    undo(journal, maps, shelves, books, LIB)

    assert _at(shelves, section.id, 2, 1).id == occupied.id
    assert books.get(LIB, "b1").copies[0].shelf_id == occupied.id, (
        "the undo moved a book, which is exactly what §3.15 forbids")


def test_switching_a_cell_back_on_records_nothing():
    """§3.15 is about DESTRUCTIVE edits, and un-gapping destroys nothing.

    It matters because the journal is one deep: an entry for an additive edit
    does not merely add noise, it evicts the real undo standing behind it. The
    drawing's own history (``app/web/src/map/core/history.ts``) is what takes
    an addition back.
    """
    maps, shelves, books, journal = _world()
    drawn = _draw(maps, shelves, columns=2, levels=3)
    section = maps.get_section(LIB, drawn.sections[0].id)
    apply_gaps(maps, shelves, books, LIB, with_gaps(section, [(2, 2)], gap=True),
               journal=journal, ids=SeqIdGen("g"), clock=StubClock())
    assert journal.store.recent(LIB)[0].kind == "gaps"

    gapped = maps.get_section(LIB, section.id)
    apply_gaps(maps, shelves, books, LIB, with_gaps(gapped, [(2, 2)], gap=False),
               journal=journal, ids=SeqIdGen("h"), clock=StubClock())
    assert len(journal.store.recent(LIB, limit=9)) == 1, (
        "restoring a cell recorded an undo of its own")
    # …and the head is still the destructive edit, still undoable.
    assert journal.store.recent(LIB)[0].kind == "gaps"


def test_an_undo_removes_a_shelf_the_same_edit_minted_while_healing():
    """``MapRestore.created`` — the half a bag of old rows cannot express.

    Reachable on an ordinary REMOVAL, not only in theory: ``_fill`` is passed
    the section's whole address set, so a removal also mints a shelf for any
    slot a concurrent edit left empty (its own ⚠ says so). If the undo put the
    old shape back and left that shelf standing, the section would describe
    fewer slots than there are shelves addressed to it — the *"shelf nothing
    can render"* ``apply_slot_change`` orders its writes to avoid.
    """
    maps, shelves, books, journal = _world()
    drawn = _draw(maps, shelves, columns=2, levels=3)
    section_id = drawn.sections[0].id
    doomed = _at(shelves, section_id, 2, 1)

    # A slot loses its shelf out of band — the lost update `_fill` heals.
    orphaned_slot = _at(shelves, section_id, 1, 2)
    shelves.delete_shelf(LIB, orphaned_slot.id)

    apply_slot_change(maps, shelves, books, LIB,
                      with_column_count(maps.get_section(LIB, section_id), 1),
                      journal=journal, ids=SeqIdGen("new"), clock=StubClock())
    minted = _at(shelves, section_id, 1, 2)
    assert minted is not None and minted.id != orphaned_slot.id, (
        "the edit did not heal the empty slot, so this test proves nothing")
    entry = journal.store.recent(LIB)[0]
    assert minted.id in entry.restore.created

    undo(journal, maps, shelves, books, LIB)

    assert shelves.get_shelf(LIB, doomed.id) is not None, "the column is back"
    assert shelves.get_shelf(LIB, minted.id) is None, (
        "the undo left standing a shelf the edit itself had minted")


def test_an_undo_refuses_to_remove_a_minted_shelf_that_has_gained_a_book():
    """The fingerprint watches the shelf ROW, and shelving a book does not
    change that row — so this refusal comes from ``delete_shelf`` itself, and
    it has to, or an undo destroys a book's only recorded location."""
    maps, shelves, books, journal = _world()
    drawn = _draw(maps, shelves, columns=2, levels=3)
    section_id = drawn.sections[0].id
    orphaned_slot = _at(shelves, section_id, 1, 2)
    shelves.delete_shelf(LIB, orphaned_slot.id)
    apply_slot_change(maps, shelves, books, LIB,
                      with_column_count(maps.get_section(LIB, section_id), 1),
                      journal=journal, ids=SeqIdGen("new"), clock=StubClock())
    minted = _at(shelves, section_id, 1, 2)
    _shelve_a_book(books, minted.id, n=7)

    refusal = _raises(UndoRefused, undo, journal, maps, shelves, books, LIB)
    assert f"shelves:{minted.id}" in refusal.changed
    assert shelves.get_shelf(LIB, minted.id) is not None
    assert books.get(LIB, "b7") is not None, "the undo destroyed a book"


# --- the fingerprint -------------------------------------------------------

def test_an_undo_refuses_when_the_world_moved_and_names_what_moved():
    """§3.15: *"An undo that cannot prove the world is still as it left it
    refuses, and says why."* The refusal names the target, because *"something
    changed"* is the answer the decision explicitly rules out."""
    maps, shelves, books, journal = _world()
    drawn = _draw(maps, shelves)
    section = drawn.sections[0]
    apply_slot_change(maps, shelves, books, LIB,
                      with_column_count(maps.get_section(LIB, section.id), 1),
                      journal=journal, ids=SeqIdGen("new"), clock=StubClock())

    # Somebody edits the same section afterwards.
    survivor = _at(shelves, section.id, 1, 1)
    shelves.save_shelf(LIB, survivor.__class__(
        **{**survivor.__dict__, "label": "אחר כך"}))
    later = maps.get_section(LIB, section.id)
    apply_gaps(maps, shelves, books, LIB, with_gaps(later, [(1, 3)], gap=True),
               journal=Journal(store=MemoryMapUndoStore(), ids=SeqIdGen("z"),
                               clock=StubClock()),
               ids=SeqIdGen("y"), clock=StubClock())

    refusal = _raises(UndoRefused, undo, journal, maps, shelves, books, LIB)
    assert refusal.changed, "refused without saying what moved"
    assert any(t.startswith("sections:") or t.startswith("slots:")
               for t in refusal.changed), refusal.changed
    assert maps.get_section(LIB, section.id).column_levels == (3,), (
        "a refused undo wrote anyway")


def test_a_slot_taken_by_another_shelf_refuses_rather_than_colliding():
    """The load-bearing half of the fingerprint's scope. Without the section's
    SLOT MAP in it, every row check passes and the replay then violates
    ``shelves_by_slot`` at the store — a 500 where a refusal was owed."""
    maps, shelves, books, journal = _world()
    drawn = _draw(maps, shelves)
    section = drawn.sections[0]
    doomed = _at(shelves, section.id, 2, 1)
    apply_slot_change(maps, shelves, books, LIB,
                      with_column_count(maps.get_section(LIB, section.id), 1),
                      journal=journal, ids=SeqIdGen("new"), clock=StubClock())

    # The column comes back by some other route and a DIFFERENT shelf takes
    # the slot — an unaddressed shelf bound there by hand is P6.4c's own
    # feature, so this is not a contrived state.
    widened = with_column_count(maps.get_section(LIB, section.id), 2)
    apply_slot_change(maps, shelves, books, LIB, widened,
                      journal=Journal(store=MemoryMapUndoStore(),
                                      ids=SeqIdGen("z"), clock=StubClock()),
                      ids=SeqIdGen("other"), clock=StubClock())
    intruder = _at(shelves, section.id, 2, 1)
    assert intruder is not None and intruder.id != doomed.id

    refusal = _raises(UndoRefused, undo, journal, maps, shelves, books, LIB)
    assert f"slots:{section.id}" in refusal.changed
    assert _at(shelves, section.id, 2, 1).id == intruder.id


def test_age_alone_never_invalidates_an_undo():
    """The owner's decision of 2026-08-24, against the recommendation: there
    is NO expiry, because a mis-tap noticed a week later is still a mis-tap.

    Mutation guard as much as a test — an age check added anywhere on the undo
    path (a ``recorded_at`` comparison, a 24h floor) fails here and nowhere
    else, because every other test undoes within the same simulated minute.
    """
    maps, shelves, books, journal = _world()
    drawn = _draw(maps, shelves)
    section = drawn.sections[0]
    doomed = _at(shelves, section.id, 2, 1)
    apply_slot_change(maps, shelves, books, LIB,
                      with_column_count(maps.get_section(LIB, section.id), 1),
                      journal=journal, ids=SeqIdGen("new"), clock=StubClock())

    # Re-date the entry to a year ago. Nothing else changes — the world is
    # exactly as the edit left it, which is the only question that may matter.
    from dataclasses import replace
    stale = replace(journal.store.recent(LIB)[0],
                    recorded_at="2025-08-24T10:00:00+00:00")
    journal.store.record(LIB, stale)

    assert offer(journal, maps, shelves, LIB).available, (
        "an untouched year-old entry was refused; age is not evidence")
    undo(journal, maps, shelves, books, LIB)
    assert shelves.get_shelf(LIB, doomed.id) is not None


# --- record all, undo the head --------------------------------------------

def test_the_journal_keeps_every_edit_but_only_the_head_is_undoable():
    """*Record all, undo the head* (owner). Undoing does NOT expose the edit
    before it — that is the n-deep stack this item deliberately is not, and
    the difference is only visible with two entries on the table."""
    maps, shelves, books, journal = _world()
    drawn = _draw(maps, shelves, columns=3, levels=3)
    section_id = drawn.sections[0].id

    first_victim = _at(shelves, section_id, 3, 1)
    apply_slot_change(maps, shelves, books, LIB,
                      with_column_count(maps.get_section(LIB, section_id), 2),
                      journal=journal, ids=SeqIdGen("a"), clock=StubClock())
    second_victim = _at(shelves, section_id, 2, 1)
    apply_slot_change(maps, shelves, books, LIB,
                      with_column_count(maps.get_section(LIB, section_id), 1),
                      journal=journal, ids=SeqIdGen("b"), clock=StubClock())

    assert len(journal.store.recent(LIB, limit=9)) == 2, (
        "the journal is a record of what happened, not a single slot")

    undo(journal, maps, shelves, books, LIB)
    assert shelves.get_shelf(LIB, second_victim.id) is not None

    # …and that is all. The first removal stays done.
    assert not offer(journal, maps, shelves, LIB).available
    assert offer(journal, maps, shelves, LIB).reason == "already_undone"
    _raises(UndoRefused, undo, journal, maps, shelves, books, LIB)
    assert shelves.get_shelf(LIB, first_victim.id) is None, (
        "undoing the head exposed the edit before it — that is a stack")


def test_there_is_no_redo():
    """An entry is replayed once. ``undone_at`` is what says so, and the row
    is kept rather than deleted because the journal is also the record that
    the undo itself happened."""
    maps, shelves, books, journal = _world()
    drawn = _draw(maps, shelves)
    section_id = drawn.sections[0].id
    apply_slot_change(maps, shelves, books, LIB,
                      with_column_count(maps.get_section(LIB, section_id), 1),
                      journal=journal, ids=SeqIdGen("a"), clock=StubClock())
    undo(journal, maps, shelves, books, LIB)

    head = journal.store.recent(LIB)[0]
    assert head.undone_at, "the entry does not record that it was replayed"
    assert not head.is_live
    refusal = _raises(UndoRefused, undo, journal, maps, shelves, books, LIB)
    assert "redo" in str(refusal)


def test_nothing_recorded_and_already_undone_are_different_sentences():
    """Both are ``available: false``, and a screen that showed one message for
    both would tell an owner who just pressed undo that nothing ever
    happened."""
    maps, shelves, books, journal = _world()
    assert offer(journal, maps, shelves, LIB).reason == "nothing_recorded"

    drawn = _draw(maps, shelves)
    apply_slot_change(
        maps, shelves, books, LIB,
        with_column_count(maps.get_section(LIB, drawn.sections[0].id), 1),
        journal=journal, ids=SeqIdGen("a"), clock=StubClock())
    undo(journal, maps, shelves, books, LIB)
    assert offer(journal, maps, shelves, LIB).reason == "already_undone"


# --- the grain of an entry is the operation --------------------------------

def test_clearing_then_deleting_a_bookcase_is_ONE_undo():
    """The client issues that as two requests (``DELETE .../slots`` then
    ``DELETE .../bookcases/{id}``), so a journal at one entry per request
    answers a press of undo by restoring an EMPTY bookcase.

    Coalescing by tag is the same mechanism ``app/web/src/map/core/history.ts``
    already uses on the client, where fourteen keystrokes of a room name are
    one undo.
    """
    maps, shelves, books, journal = _world()
    drawn = _draw(maps, shelves)
    case_id = drawn.bookcase.id
    section_id = drawn.sections[0].id
    standing = {s.id for s in shelves.list_shelves_in_section(LIB, section_id)}
    assert len(standing) == 6

    clear_bookcase_slots(maps, shelves, books, LIB, case_id, journal=journal)
    remove_record(maps, shelves, LIB, "bookcase", case_id, journal=journal)

    assert len(journal.store.recent(LIB, limit=9)) == 1, (
        "two requests, one operation — the journal recorded two undos")

    undo(journal, maps, shelves, books, LIB)

    assert maps.get_bookcase(LIB, case_id) is not None, "the case did not return"
    assert maps.get_section(LIB, section_id) is not None, (
        "the case came back with no sections — an unaddressable shell")
    back = {s.id for s in shelves.list_shelves_in_section(LIB, section_id)}
    assert back == standing, "the case came back empty; its shelves did not"


def test_two_different_bookcases_never_coalesce():
    """The tag is the thing being edited, so the merge cannot reach across
    two removals that merely happened in a row."""
    maps, shelves, books, journal = _world()
    first = _draw(maps, shelves, case_id="bc1")
    second = _draw(maps, shelves, case_id="bc2")

    clear_bookcase_slots(maps, shelves, books, LIB, first.bookcase.id,
                         journal=journal)
    clear_bookcase_slots(maps, shelves, books, LIB, second.bookcase.id,
                         journal=journal)

    assert len(journal.store.recent(LIB, limit=9)) == 2
    undo(journal, maps, shelves, books, LIB)
    assert shelves.list_shelves_in_section(LIB, second.sections[0].id)
    assert not shelves.list_shelves_in_section(LIB, first.sections[0].id), (
        "one undo took back two bookcases' worth of clearing")


# --- tenancy ---------------------------------------------------------------

def test_a_journal_is_scoped_to_its_library():
    """H2, and the same 404-not-403 shape as every other aggregate: another
    library's edits are not merely unreachable, they are absent."""
    maps, shelves, books, journal = _world()
    drawn = _draw(maps, shelves, lib=OTHER, case_id="bc-other")
    clear_bookcase_slots(maps, shelves, books, OTHER, drawn.bookcase.id,
                         journal=journal)

    assert journal.store.recent(OTHER, limit=9), "the edit recorded nothing"
    assert journal.store.recent(LIB, limit=9) == ()
    assert offer(journal, maps, shelves, LIB).reason == "nothing_recorded"
    _raises(UndoRefused, undo, journal, maps, shelves, books, LIB)


def test_undoing_a_site_removal_brings_its_storeys_back():
    """Deleting a site takes its EMPTY storeys with it — so the inverse has to
    carry them, or the undo restores a site with no floor at all.

    That state is not merely incomplete, it is one the model calls
    impossible: ``delete_floor`` refuses to leave a site with none, so nothing
    else in the product can produce it. Measured by a data-integrity review,
    which found the undo reporting success with the storeys' names, order and
    ids unrecoverable.
    """
    maps, shelves, books, journal = _world()
    maps.save_site(LIB, new_site(id="st-p", library_id=LIB.id, name="ההורים"))
    for n, name in ((1, "מרתף"), (2, "קרקע")):
        maps.save_floor(LIB, new_floor(id=f"fl-p{n}", library_id=LIB.id,
                                       site_id="st-p", name=name, order=n))

    assert remove_record(maps, shelves, LIB, "site", "st-p", journal=journal)
    undo(journal, maps, shelves, books, LIB)

    assert maps.get_site(LIB, "st-p") is not None
    back = {f.id: f for f in maps.load_map(LIB).floors if f.site_id == "st-p"}
    assert set(back) == {"fl-p1", "fl-p2"}, "the storeys did not come back"
    assert back["fl-p1"].name == "מרתף" and back["fl-p2"].order == 2


def test_undoing_a_room_removal_puts_its_bookcases_back_in_it():
    """Deleting a room NULLs the ``place_id`` of every case that stood in it —
    *"deleting a container never destroys what it held"*. That is true of the
    delete and was false of its inverse: the room came back empty, and every
    case had to be dragged into it by hand before a book's location named a
    room again.
    """
    maps, shelves, books, journal = _world()
    drawn = _draw(maps, shelves)
    assert maps.get_bookcase(LIB, drawn.bookcase.id).place_id == f"pl-{LIB.id}"

    assert remove_record(maps, shelves, LIB, "place", f"pl-{LIB.id}",
                         journal=journal)
    assert maps.get_bookcase(LIB, drawn.bookcase.id).place_id is None

    undo(journal, maps, shelves, books, LIB)

    assert maps.get_place(LIB, f"pl-{LIB.id}") is not None
    assert maps.get_bookcase(LIB, drawn.bookcase.id).place_id == f"pl-{LIB.id}", (
        "the room came back without the bookcases that stood in it")


class FrozenClock:
    """A clock that does NOT move — the production shape, made explicit.

    ``SystemClock`` has second resolution, so every request of one client
    flush shares a timestamp. This is that, taken to its limit, so the tests
    below cannot pass by accident of timing.
    """

    def now_iso(self) -> str:
        return "2026-08-24T10:00:00+00:00"


def test_two_operations_in_one_second_still_undo_the_later_one():
    """The measured failure: 165 of 500 undid the WRONG bookcase.

    `recorded_at` ties when two edits land in one second — the ordinary case,
    since deleting a bookcase is two requests and the client flushes a whole
    diff at once — and the tie broke on a uuid4, which has no order. The
    store's own `seq` is what answers "which came last" now, so this passes
    with a clock that never moves at all.
    """
    maps, shelves, books, journal = _world()
    journal = Journal(store=journal.store, ids=SeqIdGen("u"),
                      clock=FrozenClock())
    first = _draw(maps, shelves, case_id="bc1")
    second = _draw(maps, shelves, case_id="bc2")

    clear_bookcase_slots(maps, shelves, books, LIB, first.bookcase.id,
                         journal=journal)
    clear_bookcase_slots(maps, shelves, books, LIB, second.bookcase.id,
                         journal=journal)

    undo(journal, maps, shelves, books, LIB)

    assert shelves.list_shelves_in_section(LIB, second.sections[0].id), (
        "undo took back the FIRST bookcase's clearing, not the last one")
    assert not shelves.list_shelves_in_section(LIB, first.sections[0].id)


def test_an_interleaved_removal_still_coalesces_into_one_undo():
    """The other measured failure: 83 of 500 restored an EMPTY bookcase.

    Two bookcases removed in one flush interleave, so when the second case's
    DELETE records, the newest entry is the FIRST case's clearing. Looking at
    "whatever is newest" therefore refused to coalesce, and the two halves of
    one removal became two entries — undo then restored a case with no
    shelves. `partner_for` searches by TAG, so an interleave cannot confuse
    it.
    """
    maps, shelves, books, journal = _world()
    journal = Journal(store=journal.store, ids=SeqIdGen("u"),
                      clock=FrozenClock())
    first = _draw(maps, shelves, case_id="bc1")
    second = _draw(maps, shelves, case_id="bc2")
    standing = {s.id for s in
                shelves.list_shelves_in_section(LIB, second.sections[0].id)}

    # Interleaved exactly as a flush of two removals arrives.
    clear_bookcase_slots(maps, shelves, books, LIB, second.bookcase.id,
                         journal=journal)
    clear_bookcase_slots(maps, shelves, books, LIB, first.bookcase.id,
                         journal=journal)
    remove_record(maps, shelves, LIB, "bookcase", second.bookcase.id,
                  journal=journal)

    undo(journal, maps, shelves, books, LIB)

    assert maps.get_bookcase(LIB, second.bookcase.id) is not None
    back = {s.id for s in
            shelves.list_shelves_in_section(LIB, second.sections[0].id)}
    assert back == standing, (
        "the case came back empty — its clearing did not coalesce into the "
        "delete, because another case's entry sat between them")


def _relabel(shelves, shelf, text):
    from dataclasses import replace
    shelves.save_shelf(LIB, replace(shelf, label=text))


def test_a_label_typed_on_the_detached_shelf_refuses_the_undo():
    """`digest_row` digests EVERY field, and this is the case that made it
    specific: the undo writes the remembered row back whole, so a label typed
    on the detached shelf since would be silently discarded.

    Nothing else enforces it — the slot map is unchanged, because a detached
    shelf stands nowhere — so with the row digest reduced to a presence check
    this undo sails through and destroys the name.
    """
    maps, shelves, books, journal = _world()
    drawn = _draw(maps, shelves)
    section = drawn.sections[0]
    occupied = _at(shelves, section.id, 2, 1)
    _shelve_a_book(books, occupied.id)
    apply_slot_change(maps, shelves, books, LIB,
                      with_column_count(maps.get_section(LIB, section.id), 1),
                      journal=journal, ids=SeqIdGen("new"), clock=StubClock())

    _relabel(shelves, shelves.get_shelf(LIB, occupied.id), "ספרי הילדים")

    refusal = _raises(UndoRefused, undo, journal, maps, shelves, books, LIB)
    assert f"shelves:{occupied.id}" in refusal.changed
    assert shelves.get_shelf(LIB, occupied.id).label == "ספרי הילדים"


def test_a_label_typed_on_an_untouched_shelf_leaves_the_undo_available():
    """`digest_slots` is deliberately NOT the whole row, and that is the rule
    keeping the journal usable in a library somebody is actually using.

    Reverse it — digest the labels too — and any rename anywhere in the
    section kills the undo. Nothing else says so.
    """
    maps, shelves, books, journal = _world()
    drawn = _draw(maps, shelves)
    section = drawn.sections[0]
    bystander = _at(shelves, section.id, 1, 1)
    apply_slot_change(maps, shelves, books, LIB,
                      with_column_count(maps.get_section(LIB, section.id), 1),
                      journal=journal, ids=SeqIdGen("new"), clock=StubClock())

    _relabel(shelves, shelves.get_shelf(LIB, bystander.id), "שירה")

    assert offer(journal, maps, shelves, LIB).available, (
        "renaming a shelf the undo does not touch made it unavailable")
    undo(journal, maps, shelves, books, LIB)
    assert shelves.get_shelf(LIB, bystander.id).label == "שירה"


def test_a_cleared_bookcase_refuses_when_one_of_its_slots_is_taken():
    """The slot map must be watched for the CLEAR edits too, and they reach it
    by a different route: their restore carries shelves and no section, so
    `sections_touched` has to derive the section from the shelves' addresses.

    Drop that half and a deleted shelf digests to ABSENT both times, every row
    check passes, and `save_shelves` then violates `shelves_by_slot` — the
    "500 where a refusal was owed" this module exists to prevent.
    """
    maps, shelves, books, journal = _world()
    drawn = _draw(maps, shelves)
    section_id = drawn.sections[0].id
    clear_bookcase_slots(maps, shelves, books, LIB, drawn.bookcase.id,
                         journal=journal)
    # Something else fills the emptied slots again.
    shrunk = maps.get_section(LIB, section_id)
    apply_slot_change(maps, shelves, books, LIB, with_column_count(shrunk, 2),
                      journal=Journal(store=MemoryMapUndoStore(),
                                      ids=SeqIdGen("z"), clock=StubClock()),
                      ids=SeqIdGen("other"), clock=StubClock())

    refusal = _raises(UndoRefused, undo, journal, maps, shelves, books, LIB)
    assert f"slots:{section_id}" in refusal.changed


def test_an_undo_refuses_when_the_parent_it_needs_has_gone():
    """A restored row needs somewhere to hang. Delete a bookcase, then the
    storey it stood on, then press undo: the rows being restored are
    unchanged, so a row-only fingerprint reports `available` and the replay
    then raises `UnknownParent` out of a route that had just promised it.
    """
    maps, shelves, books, journal = _world()
    maps.save_floor(LIB, new_floor(id="fl-attic", library_id=LIB.id,
                                   site_id=f"st-{LIB.id}", name="עלייה"))
    case = new_bookcase(id="bc-attic", library_id=LIB.id, floor_id="fl-attic",
                        rect=Rect(0, 0, 4, 1))
    draw_bookcase(maps, shelves, LIB, case, ids=SeqIdGen("bc-attic"),
                  clock=StubClock(), columns=1, levels=2, depth=1)

    clear_bookcase_slots(maps, shelves, books, LIB, "bc-attic", journal=journal)
    remove_record(maps, shelves, LIB, "bookcase", "bc-attic", journal=journal)

    # The now-empty storey is tidied away afterwards, through its own route.
    other = Journal(store=MemoryMapUndoStore(), ids=SeqIdGen("z"),
                    clock=StubClock())
    assert remove_record(maps, shelves, LIB, "floor", "fl-attic",
                         journal=other)

    assert not offer(journal, maps, shelves, LIB).available, (
        "the offer promised an undo whose parent has gone")
    refusal = _raises(UndoRefused, undo, journal, maps, shelves, books, LIB)
    assert "exists:floors:fl-attic" in refusal.changed, refusal.changed


def test_an_undo_refuses_when_another_section_has_taken_its_ordinal():
    """`sections_by_bookcase` is unique over `(library, bookcase, ordinal)`,
    and adding a section is ADDITIVE so it records nothing of its own. Two
    ordinary gestures — remove the hutch, add another — left the offer
    promising an undo that raised `DuplicateSectionOrdinal`; and because the
    entry was never marked undone, it kept promising it.
    """
    maps, shelves, books, journal = _world()
    drawn = _draw(maps, shelves)
    maps.save_section(LIB, new_section(
        id="se-hutch", library_id=LIB.id, bookcase_id=drawn.bookcase.id,
        ordinal=2, columns=1, default_levels=2))

    assert remove_record(maps, shelves, LIB, "section", "se-hutch",
                         journal=journal)
    maps.save_section(LIB, new_section(
        id="se-new", library_id=LIB.id, bookcase_id=drawn.bookcase.id,
        ordinal=2, columns=1, default_levels=2))

    assert not offer(journal, maps, shelves, LIB).available
    refusal = _raises(UndoRefused, undo, journal, maps, shelves, books, LIB)
    assert f"ordinals:{drawn.bookcase.id}" in refusal.changed


def test_the_offer_reports_the_refusal_before_it_is_pressed():
    """`offer` runs the same check as `undo`, so the control is honest BEFORE
    it is pressed. Without it the GET promises an undo the POST then refuses,
    which is the shape that teaches people to distrust the control."""
    maps, shelves, books, journal = _world()
    drawn = _draw(maps, shelves)
    section = drawn.sections[0]
    occupied = _at(shelves, section.id, 2, 1)
    _shelve_a_book(books, occupied.id)
    apply_slot_change(maps, shelves, books, LIB,
                      with_column_count(maps.get_section(LIB, section.id), 1),
                      journal=journal, ids=SeqIdGen("new"), clock=StubClock())
    _relabel(shelves, shelves.get_shelf(LIB, occupied.id), "אחר כך")

    said = offer(journal, maps, shelves, LIB)
    assert not said.available and said.reason == "world_moved"
    assert f"shelves:{occupied.id}" in said.changed


def test_clearing_then_deleting_a_section_is_also_one_undo():
    """The other half of `CONTINUES`, and a real production path:
    `app/web/src/map/push.ts` issues `DELETE .../slots` then
    `DELETE .../sections/{id}`. Only the bookcase pair was covered."""
    from app.map_edit import _fill

    maps, shelves, books, journal = _world()
    drawn = _draw(maps, shelves)
    hutch = new_section(id="se-hutch", library_id=LIB.id,
                        bookcase_id=drawn.bookcase.id, ordinal=2, columns=1,
                        default_levels=2)
    maps.save_section(LIB, hutch)
    _fill(shelves, LIB, hutch, hutch.addresses, ids=SeqIdGen("h"),
          clock=StubClock())
    standing = {s.id for s in shelves.list_shelves_in_section(LIB, "se-hutch")}
    assert standing

    clear_section_slots(maps, shelves, books, LIB, "se-hutch", journal=journal)
    remove_record(maps, shelves, LIB, "section", "se-hutch", journal=journal)
    assert len(journal.store.recent(LIB, limit=9)) == 1, (
        "two requests, one operation — the journal recorded two undos")

    undo(journal, maps, shelves, books, LIB)

    assert maps.get_section(LIB, "se-hutch") is not None
    back = {s.id for s in shelves.list_shelves_in_section(LIB, "se-hutch")}
    assert back == standing


def test_an_already_undone_entry_is_never_revived_by_a_later_half():
    """`coalesces_with` requires the head to be LIVE. Without that guard a
    `delete_bookcase` arriving after its own clearing was undone would absorb
    the undone entry — and `absorbed` clears `undone_at` — so an entry
    replayed once becomes replayable again, which the item says cannot
    happen."""
    maps, shelves, books, journal = _world()
    drawn = _draw(maps, shelves)
    clear_bookcase_slots(maps, shelves, books, LIB, drawn.bookcase.id,
                         journal=journal)
    undo(journal, maps, shelves, books, LIB)
    assert not journal.store.recent(LIB)[0].is_live

    clear_bookcase_slots(maps, shelves, books, LIB, drawn.bookcase.id,
                         journal=journal)
    remove_record(maps, shelves, LIB, "bookcase", drawn.bookcase.id,
                  journal=journal)
    entries = journal.store.recent(LIB, limit=9)
    assert [e.is_live for e in entries].count(False) == 1, (
        "an undone entry was revived by a later half of another operation")
