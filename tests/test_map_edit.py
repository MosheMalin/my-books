# -*- coding: utf-8 -*-
"""H4 ring — ``app.map_edit``: a drawing, turned into shelves (P6.1).

The layer above ``app.domain.place``: real ``MemoryMapStore``/
``MemoryShelfStore``/``MemoryBookStore`` instances, a stub ``Clock``/``IdGen``,
and the actual persisted result. Every case here is one sentence of
``planning/MAP_PLAN.md`` §3 that a later reader could plausibly "fix" — and
this is the module where "fixing" it would silently lose a book's only
recorded location, which is why MAP_PLAN §2 flagged this item as the risky one
before any of it was written.

Three of these exist because a review MEASURED the bug, not because it was
imagined: the shelf with books and no photograph, the depth clamp, and the
half-applied shrink.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.adapters.memory_store import (
    MemoryMapUndoStore,
    MemoryBookStore,
    MemoryMapStore,
    MemoryShelfStore,
)
from app.domain import (
    LibraryRef,
    NotEmpty,
    Rect,
    Section,
    ShelfAddress,
    new_bookcase,
    new_book,
    new_capture,
    new_floor,
    new_place,
    new_section,
    new_shelf,
    new_site,
    with_column_count,
    with_default_depth,
)
from app.map_undo import Journal
from app.map_edit import (
    apply_depth_default,
    apply_slot_change,
    attach_case_to_room,
    clear_bookcase_slots,
    clear_section_slots,
    deepest_occupied_depths,
    draw_bookcase,
)

LIB = LibraryRef("lib-1", "הבית")
WHEN = "2026-08-16T12:00:00+00:00"


class StubClock:
    def now_iso(self) -> str:
        return WHEN


class SeqIdGen:
    def __init__(self) -> None:
        self._n = 0

    def new_id(self) -> str:
        self._n += 1
        return f"id-{self._n}"


def _journal(ids=None, clock=None) -> Journal:
    """A throwaway undo journal for a test that is not about the journal.

    P6.4b made ``journal`` a REQUIRED argument of every destructive function
    here, which is the invariant: a destructive edit cannot be written without
    somewhere to record its inverse. The tests that ARE about the journal live
    in ``test_map_undo.py`` and build their own.
    """
    return Journal(store=MemoryMapUndoStore(),
                   ids=ids if ids is not None else SeqIdGen(),
                   clock=clock if clock is not None else StubClock())


def _raises(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc as e:
        return e
    raise AssertionError(f"expected {exc.__name__}, nothing raised")


def _world():
    """A library with one site, one floor and one room — the state the editor
    is in the moment before a bookcase is drawn.

    ⚠ BOTH bindings. A review found this helper wiring only one of them, which
    silently disabled the shelf store's parent check for the whole ring; the
    stores now refuse to answer rather than answering weakly, which is how the
    gap surfaced.
    """
    shelves = MemoryShelfStore()
    maps = MemoryMapStore()
    books = MemoryBookStore()
    maps.bind_shelves(shelves)
    shelves.bind_map(maps)
    shelves.bind_books(books)
    maps.save_site(LIB, new_site(id="st", library_id=LIB.id, name="הבית"))
    maps.save_floor(LIB, new_floor(id="fl", library_id=LIB.id, site_id="st",
                                   name="קומת קרקע"))
    maps.save_place(LIB, new_place(id="pl", library_id=LIB.id, floor_id="fl",
                                   rect=Rect(0, 0, 12, 9), name="סלון"))
    return maps, shelves, books


def _case(**kw):
    return new_bookcase(id="bc", library_id=LIB.id, floor_id="fl",
                        rect=Rect(0, 0, 4, 1), place_id="pl", **kw)


def _shelve_a_book(books, shelf_id: str, *, depth: int = 1, n: int = 1):
    books.save(LIB, new_book(id=f"b{n}", library_id=LIB.id, title="ספר",
                             author="סופר", copy_id=f"c{n}",
                             shelf_id=shelf_id, depth=depth))


def test_drawing_a_bookcase_creates_a_real_empty_shelf_per_slot():
    """MAP_PLAN §3.1, the sentence the whole item turns on: *a drawn slot IS a
    Shelf* — created empty, carrying an address, and not a second concept with
    a mapping table beside it. Draw 2 columns of 5 and ten shelves exist that
    were never photographed."""
    maps, shelves, _ = _world()
    drawn = draw_bookcase(maps, shelves, LIB, _case(), ids=SeqIdGen(),
                          clock=StubClock(), columns=2, levels=5, depth=1)
    assert drawn.shelves == 10
    standing = shelves.list_shelves_in_section(LIB, drawn.sections[0].id)
    assert len(standing) == 10
    assert all(s.is_addressed and s.label == "" for s in standing)
    assert standing[0].created_at == WHEN
    assert {(s.address.col, s.address.level) for s in standing} == {
        (c, lvl) for c in (1, 2) for lvl in range(1, 6)}


def test_a_drawn_shelf_takes_the_sections_depth_as_a_copy():
    """§3.3: the default is copied at creation. Deepening the section
    afterwards must not reach back — if it did, SHALLOWING it would delete the
    location of every book in the back row, and the two are the same code
    path."""
    maps, shelves, _ = _world()
    drawn = draw_bookcase(maps, shelves, LIB, _case(), ids=SeqIdGen(),
                          clock=StubClock(), columns=1, levels=2, depth=2)
    section = drawn.sections[0]
    assert all(s.depth_count == 2
               for s in shelves.list_shelves_in_section(LIB, section.id))
    maps.save_section(LIB, with_default_depth(section, 1))
    assert all(s.depth_count == 2
               for s in shelves.list_shelves_in_section(LIB, section.id)), (
        "editing the section's default reached back into existing shelves"
    )


def test_filling_slots_is_idempotent_so_a_retry_mints_no_twin():
    """The slot is the identity, so a retried request finds the shelf already
    standing there.

    ⚠ The retry has to replay the SAME computed change — a client whose
    response was dropped sends the same request again, and the server computes
    it from the section IT last saw. Recomputing from the stored section would
    make this test pass while proving nothing, because the second change is
    then empty. Without the guard the second pass tries to mint three more
    shelves at occupied slots and the unique index turns a retry into a 500.
    """
    maps, shelves, books = _world()
    ids = SeqIdGen()
    drawn = draw_bookcase(maps, shelves, LIB, _case(), ids=ids,
                          clock=StubClock(), columns=1, levels=3, depth=1)
    section = drawn.sections[0]
    change = with_column_count(section, 2)      # the request, computed once

    first = apply_slot_change(maps, shelves, books, LIB, change, journal=_journal(), ids=ids,
                              clock=StubClock())
    assert first.total == 0
    assert len(shelves.list_shelves_in_section(LIB, section.id)) == 6

    again = apply_slot_change(maps, shelves, books, LIB, change, journal=_journal(), ids=ids,
                              clock=StubClock())
    assert again.total == 0
    assert len(shelves.list_shelves_in_section(LIB, section.id)) == 6, (
        "the retry minted a second shelf for a slot that already had one"
    )


def test_growing_a_section_adds_shelves_and_shrinking_removes_the_empty_ones():
    """The drawing and the shelves move together, in one call — a caller that
    updated the grid and forgot the shelves would leave a bookcase whose
    columns exist on screen and nowhere else."""
    maps, shelves, books = _world()
    ids = SeqIdGen()
    drawn = draw_bookcase(maps, shelves, LIB, _case(), ids=ids,
                          clock=StubClock(), columns=1, levels=2, depth=1)
    section = drawn.sections[0]
    apply_slot_change(maps, shelves, books, LIB, with_column_count(section, 3),
                      journal=_journal(), ids=ids, clock=StubClock())
    assert len(shelves.list_shelves_in_section(LIB, section.id)) == 6
    assert maps.get_section(LIB, section.id).column_levels == (2, 2, 2)

    back = apply_slot_change(
        maps, shelves, books, LIB,
        with_column_count(maps.get_section(LIB, section.id), 1),
        journal=_journal(), ids=ids, clock=StubClock())
    assert len(back.deleted) == 4 and back.detached == ()
    assert len(shelves.list_shelves_in_section(LIB, section.id)) == 2


def test_shrinking_a_section_detaches_an_occupied_shelf_instead_of_deleting_it():
    """§3.1 and §5.6 together, and the reason this item is the risky one: the
    shelf holding the photographs SURVIVES, unaddressed. Its books keep their
    shelf; what they lose is a location the owner has just erased from the
    drawing."""
    maps, shelves, books = _world()
    ids = SeqIdGen()
    drawn = draw_bookcase(maps, shelves, LIB, _case(), ids=ids,
                          clock=StubClock(), columns=2, levels=1, depth=1)
    section = drawn.sections[0]
    photographed = shelves.get_shelf_at(LIB, ShelfAddress(section.id, 2, 1))
    shelves.save_shelf(LIB, new_shelf(id=photographed.id, library_id=LIB.id,
                                      label="מדף עם ספרים", depth_count=1,
                                      address=photographed.address))
    _shelve_a_book(books, photographed.id)

    removal = apply_slot_change(maps, shelves, books, LIB,
                                with_column_count(section, 1), journal=_journal(), ids=ids,
                                clock=StubClock())
    assert removal.detached == (photographed.id,)
    assert removal.deleted == ()
    survivor = shelves.get_shelf(LIB, photographed.id)
    assert survivor is not None, "a shelf with books on it was deleted"
    assert survivor.address is None
    assert survivor.label == "מדף עם ספרים", "the survivor lost its name too"


def test_a_shelf_holding_books_but_no_photos_is_still_occupied():
    """A review finding, pinned. `deepest_occupied_depths` is the ONE way to
    ask, and it asks BOTH halves.

    Captures are the obvious half. Copies are the half a reasonable person
    leaves out — a shelf can hold books with no photograph at all (a MANUAL
    entry, or a photo deleted later), and asking only about captures calls it
    empty, hands it to the DELETE branch, and leaves `copies.shelf_id` naming
    a shelf that no longer exists: invisible to `foreign_key_check`, because
    there is deliberately no foreign key there, and invisible to every screen.
    """
    maps, shelves, books = _world()
    ids = SeqIdGen()
    drawn = draw_bookcase(maps, shelves, LIB, _case(), ids=ids,
                          clock=StubClock(), columns=1, levels=2, depth=1)
    section = drawn.sections[0]
    standing = shelves.list_shelves_in_section(LIB, section.id)
    with_book, bare = standing[0], standing[1]
    _shelve_a_book(books, with_book.id)
    assert shelves.list_captures(LIB, with_book.id) == (), (
        "the point of this test is a shelf with NO photograph"
    )
    assert deepest_occupied_depths(shelves, books, LIB, standing) == {
        with_book.id: 1}

    removal = clear_bookcase_slots(maps, shelves, books, LIB, "bc", journal=_journal())
    assert removal.detached == (with_book.id,)
    assert removal.deleted == (bare.id,)
    assert shelves.get_shelf(LIB, with_book.id) is not None, (
        "the shelf a book stands on was deleted because nobody photographed it"
    )


def test_a_shelf_holding_photos_but_no_books_is_still_occupied():
    """The MIRROR of the case above, and a review found it missing: the
    docstring says "⚠ both halves" and only one half was pinned.

    A shelf photographed but not yet reviewed holds no copies at all — every
    shelf is in that state between the capture and the read settling. Its
    captures are the record a re-read diffs against (§5.6), so deleting it is
    the destructive direction the whole design refuses.
    """
    maps, shelves, books = _world()
    ids = SeqIdGen()
    drawn = draw_bookcase(maps, shelves, LIB, _case(), ids=ids,
                          clock=StubClock(), columns=1, levels=2, depth=1)
    section = drawn.sections[0]
    standing = shelves.list_shelves_in_section(LIB, section.id)
    photographed, bare = standing[0], standing[1]
    shelves.save_capture(LIB, new_capture(photographed, id="cap",
                                          image_id="img"))
    assert books.deepest_copy_depth(LIB) == {}, (
        "the point of this test is a shelf with NO books on it"
    )
    assert deepest_occupied_depths(shelves, books, LIB, standing) == {
        photographed.id: 1}

    removal = clear_bookcase_slots(maps, shelves, books, LIB, "bc", journal=_journal())
    assert removal.detached == (photographed.id,)
    assert removal.deleted == (bare.id,)
    assert shelves.get_shelf(LIB, photographed.id) is not None
    assert shelves.list_captures(LIB, photographed.id) != (), (
        "the photograph a re-read diffs against went with the slot"
    )


def test_the_back_row_counts_as_occupied_at_the_depth_it_stands_at():
    """One question, one answer. `deepest_occupied_depths` is both *is
    anything here?* and *how far back?* — two queries could disagree, and the
    disagreement either deletes a shelf or un-declares a book's depth."""
    maps, shelves, books = _world()
    ids = SeqIdGen()
    drawn = draw_bookcase(maps, shelves, LIB, _case(), ids=ids,
                          clock=StubClock(), columns=1, levels=2, depth=3)
    section = drawn.sections[0]
    standing = shelves.list_shelves_in_section(LIB, section.id)
    by_copy, by_photo = standing[0], standing[1]
    _shelve_a_book(books, by_copy.id, depth=3)
    shelves.save_capture(LIB, new_capture(by_photo, id="cap", depth=2,
                                          image_id="img"))
    assert deepest_occupied_depths(shelves, books, LIB, standing) == {
        by_copy.id: 3, by_photo.id: 2}


def test_occupancy_is_recomputed_at_the_moment_of_the_write():
    """A review measured the window: occupancy answered at T0 and trusted at
    T1, with a book shelved from the phone in between while the map was open
    on a laptop. The shelf was deleted and `copies.shelf_id` was left naming
    it.

    The fix is not a required argument — that stops a caller FORGETTING, not
    the answer going stale — so the destructive functions compute it
    themselves, immediately before the removal. This test stands in for that
    window by shelving the book after the change is computed.
    """
    maps, shelves, books = _world()
    ids = SeqIdGen()
    drawn = draw_bookcase(maps, shelves, LIB, _case(), ids=ids,
                          clock=StubClock(), columns=2, levels=1, depth=1)
    section = drawn.sections[0]
    doomed = shelves.get_shelf_at(LIB, ShelfAddress(section.id, 2, 1))
    change = with_column_count(section, 1)      # computed BEFORE the book

    _shelve_a_book(books, doomed.id)            # …the phone, mid-edit

    removal = apply_slot_change(maps, shelves, books, LIB, change, journal=_journal(), ids=ids,
                                clock=StubClock())
    assert removal.detached == (doomed.id,)
    assert shelves.get_shelf(LIB, doomed.id) is not None, (
        "a book shelved between the request and the write lost its shelf"
    )


def test_a_failed_removal_leaves_the_drawing_untouched_and_heals_on_retry():
    """The write ORDER, which a review showed was inverted for shrinking.

    Section-first wrote the smaller grid, then failed in the removal loop, and
    left a shelf addressed to a slot that no longer existed — permanent,
    because the retry recomputed `dropped` from the already-shrunk section and
    found nothing, and the bookcase then could not be deleted at all.

    Removals-first is self-healing: the drawing is unchanged, so the retry
    computes the same change and finishes it. Here the removal loop is made to
    fail the way it really can — a capture arriving after the occupancy query,
    which `delete_shelf` refuses.
    """
    import app.map_edit as map_edit

    maps, shelves, books = _world()
    ids = SeqIdGen()
    drawn = draw_bookcase(maps, shelves, LIB, _case(), ids=ids,
                          clock=StubClock(), columns=2, levels=1, depth=1)
    section = drawn.sections[0]
    doomed = shelves.get_shelf_at(LIB, ShelfAddress(section.id, 2, 1))
    change = with_column_count(section, 1)

    # ⚠ The failure has to be one `_release` does NOT handle, or the order is
    # unobservable — a mutation check caught the first version of this test
    # passing with the writes swapped, because the only failure it forced
    # (`ShelfNotEmpty`) is caught and turned into a detach. So: the store
    # itself fails mid-removal.
    real_delete = shelves.delete_shelf

    def wedged(library, shelf_id):
        raise RuntimeError("the disk went away")

    shelves.delete_shelf = wedged
    try:
        apply_slot_change(maps, shelves, books, LIB, change, journal=_journal(), ids=ids,
                          clock=StubClock())
    except RuntimeError:
        pass
    else:
        raise AssertionError("the wedge did not fire")
    finally:
        shelves.delete_shelf = real_delete

    assert maps.get_section(LIB, section.id).column_levels == (1, 1), (
        "the grid was written before the removals, so the drawing now says a "
        "slot that a shelf is still addressed to does not exist"
    )
    assert shelves.get_shelf_at(LIB, ShelfAddress(section.id, 2, 1)) is not None

    # …and the retry, computing the SAME change from the unchanged drawing,
    # finishes it. That is what "self-healing" means and what the other order
    # could not do: it recomputed `dropped` from an already-shrunk section,
    # got nothing, and left the case permanently undeletable.
    removal = apply_slot_change(maps, shelves, books, LIB, change, journal=_journal(), ids=ids,
                                clock=StubClock())
    assert removal.deleted == (doomed.id,)
    assert maps.get_section(LIB, section.id).column_levels == (1,)
    assert shelves.list_shelves_in_section(LIB, section.id) != ()
    assert clear_bookcase_slots(maps, shelves, books, LIB, "bc", journal=_journal()).total == 1
    assert maps.delete_bookcase(LIB, "bc") is True


def test_a_bookcase_is_emptied_before_it_can_be_deleted():
    """The store REFUSES while a shelf stands in one of its slots, and the
    emptying is a separate, explicit call. A store method that quietly emptied
    the slots itself is the silent-data-loss path MAP_PLAN §2 predicted for
    exactly this item."""
    maps, shelves, books = _world()
    ids = SeqIdGen()
    drawn = draw_bookcase(maps, shelves, LIB, _case(), ids=ids,
                          clock=StubClock(), columns=1, levels=2, depth=1)
    section = drawn.sections[0]
    keeper = shelves.get_shelf_at(LIB, ShelfAddress(section.id, 1, 1))
    _shelve_a_book(books, keeper.id)

    _raises(NotEmpty, maps.delete_bookcase, LIB, "bc")

    removal = clear_bookcase_slots(maps, shelves, books, LIB, "bc", journal=_journal())
    assert removal.detached == (keeper.id,) and len(removal.deleted) == 1
    assert maps.delete_bookcase(LIB, "bc") is True
    assert maps.get_section(LIB, section.id) is None
    assert shelves.get_shelf(LIB, keeper.id) is not None, (
        "deleting the furniture deleted the shelf its books stand on"
    )


def test_clearing_one_section_leaves_the_other_sections_alone():
    """A bookcase with a base and a hutch has two sections, and *"remove the
    hutch"* implemented by clearing the CASE would detach or delete every
    shelf in the base as well."""
    maps, shelves, books = _world()
    ids = SeqIdGen()
    drawn = draw_bookcase(maps, shelves, LIB, _case(), ids=ids,
                          clock=StubClock(), columns=1, levels=2, depth=1)
    base = drawn.sections[0]
    # Built EMPTY and then grown, because that is how the editor adds a
    # section: `with_column_count` reports the slots that came into being, and
    # a section saved already-shaped reports none — which is how the first
    # version of this test came to assert against zero shelves.
    hutch = Section(id="hutch", library_id=LIB.id, bookcase_id="bc",
                    ordinal=2, column_levels=(), default_levels=2)
    maps.save_section(LIB, hutch)
    apply_slot_change(maps, shelves, books, LIB, with_column_count(hutch, 1),
                      journal=_journal(), ids=ids, clock=StubClock())

    cleared = clear_section_slots(maps, shelves, books, LIB, hutch.id,
                                  journal=_journal())
    assert cleared.total == 2
    assert shelves.list_shelves_in_section(LIB, hutch.id) == ()
    assert len(shelves.list_shelves_in_section(LIB, base.id)) == 2, (
        "clearing the hutch took the base's shelves with it"
    )
    assert maps.delete_section(LIB, hutch.id) is True


def test_applying_a_depth_default_writes_the_clamp_it_reports():
    """§3.3's explicit half, and the clamp a review measured missing.

    The shelf with a book in the BACK row keeps its depth; the empty one goes
    to 1; and the caller is handed the ones it could not move so the screen
    says so instead of silently doing less. Without it a copy is recorded at
    depth 2 of a shelf declaring one row — which `Shelf.check_depth` then
    refuses, and which no foreign key can see.
    """
    maps, shelves, books = _world()
    ids = SeqIdGen()
    drawn = draw_bookcase(maps, shelves, LIB, _case(), ids=ids,
                          clock=StubClock(), columns=1, levels=2, depth=3)
    section = drawn.sections[0]
    deep = shelves.get_shelf_at(LIB, ShelfAddress(section.id, 1, 1))
    shallow = shelves.get_shelf_at(LIB, ShelfAddress(section.id, 1, 2))
    _shelve_a_book(books, deep.id, depth=2)

    section = with_default_depth(section, 1)
    maps.save_section(LIB, section)
    kept = apply_depth_default(shelves, books, LIB, section)
    assert [s.id for s in kept] == [deep.id]
    assert shelves.get_shelf(LIB, deep.id).depth_count == 2, (
        "a book standing in the back row lost the depth it stands at"
    )
    assert shelves.get_shelf(LIB, shallow.id).depth_count == 1
    # …and the location is still declarable, which is the point of the clamp.
    shelves.get_shelf(LIB, deep.id).check_depth(2)


def test_attaching_a_case_to_a_room_moves_it_onto_that_rooms_storey():
    """§3.7, through the port: the two fields change together, in one write,
    so a case attached to the kitchen can never be recorded upstairs."""
    maps, shelves, _ = _world()
    maps.save_floor(LIB, new_floor(id="fl2", library_id=LIB.id, site_id="st",
                                   name="קומה א"))
    maps.save_place(LIB, new_place(id="pl2", library_id=LIB.id,
                                   floor_id="fl2", rect=Rect(0, 0, 6, 6),
                                   name="חדר שינה"))
    maps.save_bookcase(LIB, _case())

    moved = attach_case_to_room(maps, LIB, maps.get_bookcase(LIB, "bc"),
                                maps.get_place(LIB, "pl2"))
    assert (moved.place_id, moved.floor_id) == ("pl2", "fl2")
    stored = maps.get_bookcase(LIB, "bc")
    assert (stored.place_id, stored.floor_id) == ("pl2", "fl2")

    loose = attach_case_to_room(maps, LIB, stored, None)
    assert loose.place_id is None
    assert loose.floor_id == "fl2", (
        "detaching a case moved it off its storey, so it is nowhere"
    )


def test_gapping_a_cell_that_holds_books_is_refused_and_names_what_is_there():
    """The owner's decision, 2026-08-22, and the one place a gap deliberately
    disagrees with every other slot edit.

    Erasing a column DETACHES an occupied shelf: the books keep their shelf,
    the shelf loses its address, and the location is gone. A gap refuses
    instead — *the television goes where the books are not* — so no book
    loses its location to this gesture.

    ⚠ Not the same as costing NOTHING, which is what this docstring used to
    say: what a gapped cell does not keep is its shelf's id, and standing
    decisions are keyed by it. `apply_gaps` states the whole cost.
    """
    from app.domain import SlotsOccupied, with_gaps
    from app.map_edit import apply_gaps

    maps, shelves, books = _world()
    ids, clock = SeqIdGen(), StubClock()
    drawn = draw_bookcase(maps, shelves, LIB, _case(), ids=ids, clock=clock,
                          columns=2, levels=3, depth=1)
    section = drawn.sections[0]
    occupied = shelves.get_shelf_at(LIB, ShelfAddress(section.id, 1, 2))
    _shelve_a_book(books, occupied.id)

    change = with_gaps(section, [(1, 1), (1, 2)], gap=True)
    refusal = _raises(SlotsOccupied, apply_gaps, maps, shelves, books, LIB,
                      change, journal=_journal(), ids=ids, clock=clock)

    assert [s.id for s in refusal.shelves] == [occupied.id], (
        "the refusal did not say which shelf was in the way, so the screen "
        "can only say 'cannot'"
    )
    # Nothing at all happened — not the empty cell either. Half of a delete
    # is worse than none of it: the owner sees one hole appear and reads the
    # refusal as being about the OTHER cell.
    assert maps.get_section(LIB, section.id).gaps == ()
    assert len(shelves.list_shelves_in_section(LIB, section.id)) == 6
    assert shelves.get_shelf(LIB, occupied.id).is_addressed


def test_a_photographed_but_bookless_cell_is_occupied_too():
    """Both halves, exactly as `deepest_occupied_depths` argues: a shelf can
    hold a photograph and no confirmed book — the read is pending, or every
    finding was rejected — and the capture is the record a re-read diffs
    against (§5.6). Asking only about copies calls that cell empty and
    deletes the photograph with it."""
    from app.domain import SlotsOccupied, with_gaps
    from app.map_edit import apply_gaps

    maps, shelves, books = _world()
    ids, clock = SeqIdGen(), StubClock()
    drawn = draw_bookcase(maps, shelves, LIB, _case(), ids=ids, clock=clock,
                          columns=1, levels=2, depth=1)
    section = drawn.sections[0]
    photographed = shelves.get_shelf_at(LIB, ShelfAddress(section.id, 1, 1))
    shelves.save_capture(LIB, new_capture(photographed, id="cap",
                                          image_id="img"))
    assert books.deepest_copy_depth(LIB) == {}, (
        "the point of this test is a cell with NO books on it"
    )

    change = with_gaps(section, [(1, 1)], gap=True)
    _raises(SlotsOccupied, apply_gaps, maps, shelves, books, LIB, change,
            journal=_journal(), ids=ids, clock=clock)
    assert shelves.get_shelf(LIB, photographed.id) is not None
    assert len(shelves.list_captures(LIB, photographed.id)) == 1


def test_gapping_empty_cells_removes_their_shelves_and_leaves_the_rest_standing():
    """The ordinary case: mark the middle of the wall unit, press delete, and
    a television fits. The shelves below keep the addresses they had — which
    is the difference between this and shrinking the column, and the reason
    the owner asked for it."""
    from app.domain import with_gaps
    from app.map_edit import apply_gaps

    maps, shelves, books = _world()
    ids, clock = SeqIdGen(), StubClock()
    drawn = draw_bookcase(maps, shelves, LIB, _case(), ids=ids, clock=clock,
                          columns=2, levels=4, depth=1)
    section = drawn.sections[0]
    below = shelves.get_shelf_at(LIB, ShelfAddress(section.id, 1, 4))

    change = with_gaps(section, [(1, 2), (1, 3)], gap=True)
    removal = apply_gaps(maps, shelves, books, LIB, change, journal=_journal(), ids=ids,
                         clock=clock)

    assert len(removal.deleted) == 2 and removal.detached == ()
    assert maps.get_section(LIB, section.id).gaps == ((1, 2), (1, 3))
    assert len(shelves.list_shelves_in_section(LIB, section.id)) == 6
    still = shelves.get_shelf_at(LIB, ShelfAddress(section.id, 1, 4))
    assert still is not None and still.id == below.id, (
        "the shelf below the hole is a different shelf now, so every address "
        "already printed for a book in that column points somewhere else"
    )


def test_switching_a_gap_back_on_mints_an_empty_shelf_at_that_address():
    """*"User should be able to click on a 'missing' cell and make it a real
    shelf again"* (owner). It is a NEW shelf, with a new id, and says so:
    nothing is kept alive behind a hole. What that costs — the id, and the
    decisions keyed by it — is stated once, in `apply_gaps`."""
    from app.domain import with_gaps
    from app.map_edit import apply_gaps

    maps, shelves, books = _world()
    ids, clock = SeqIdGen(), StubClock()
    drawn = draw_bookcase(maps, shelves, LIB, _case(), ids=ids, clock=clock,
                          columns=1, levels=3, depth=2)
    section = drawn.sections[0]
    holed = with_gaps(section, [(1, 2)], gap=True)
    apply_gaps(maps, shelves, books, LIB, holed, journal=_journal(), ids=ids, clock=clock)
    assert shelves.get_shelf_at(LIB, ShelfAddress(section.id, 1, 2)) is None

    back = with_gaps(maps.get_section(LIB, section.id), [(1, 2)], gap=False)
    apply_gaps(maps, shelves, books, LIB, back, journal=_journal(), ids=ids, clock=clock)

    restored = shelves.get_shelf_at(LIB, ShelfAddress(section.id, 1, 2))
    assert restored is not None and restored.label == ""
    assert restored.depth_count == 2, (
        "the restored shelf did not take the section's default depth (§3.3)"
    )
    assert maps.get_section(LIB, section.id).gaps == ()


def test_gapping_every_cell_leaves_the_bookcase_and_its_section_standing():
    """*"It should not delete the bookcase itself. Only to effect the
    cell(s)"* (owner). Written against the STORES, because the sentence is
    about what survives on disk: the case, the section, and an extent to
    switch back on."""
    from app.domain import with_gaps
    from app.map_edit import apply_gaps

    maps, shelves, books = _world()
    ids, clock = SeqIdGen(), StubClock()
    drawn = draw_bookcase(maps, shelves, LIB, _case(), ids=ids, clock=clock,
                          columns=2, levels=2, depth=1)
    section = drawn.sections[0]

    every = [(col, level) for col in (1, 2) for level in (1, 2)]
    apply_gaps(maps, shelves, books, LIB,
               with_gaps(section, every, gap=True), journal=_journal(), ids=ids, clock=clock)

    assert maps.get_bookcase(LIB, "bc") is not None
    standing = maps.get_section(LIB, section.id)
    assert standing is not None and standing.column_levels == (2, 2)
    assert len(shelves.list_shelves_in_section(LIB, section.id)) == 0


def test_a_named_cell_or_one_with_its_own_depth_refuses_the_gap_too():
    """Measured by a review, against the first draft of this feature, which
    claimed gapping was loss-proof because it only ever removed EMPTY shelves.

    An empty shelf is not an empty thing. The review drove the real routes and
    watched a cell called "מדף הטלוויזיה" at depth 3 come back from a
    gap-and-restore as `''` at the section default — a name and a declaration
    the owner had TYPED, gone, with a 200 on both calls.

    So the refusal covers what the owner declared, not merely what is standing
    there. Both have an obvious remedy — clear the name, reset the depth —
    which is what separates them from a standing decision, which is NOT
    refused because no screen can clear one (see `apply_gaps`).
    """
    from dataclasses import replace

    from app.domain import SlotsOccupied, rename_shelf, with_gaps
    from app.map_edit import apply_gaps

    maps, shelves, books = _world()
    ids, clock = SeqIdGen(), StubClock()
    drawn = draw_bookcase(maps, shelves, LIB, _case(), ids=ids, clock=clock,
                          columns=1, levels=3, depth=1)
    section = drawn.sections[0]
    named = shelves.get_shelf_at(LIB, ShelfAddress(section.id, 1, 1))
    deeper = shelves.get_shelf_at(LIB, ShelfAddress(section.id, 1, 2))
    shelves.save_shelf(LIB, rename_shelf(named, "מדף הטלוויזיה"))
    shelves.save_shelf(LIB, replace(deeper, depth_count=3))

    for cell in ((1, 1), (1, 2)):
        change = with_gaps(section, [cell], gap=True)
        _raises(SlotsOccupied, apply_gaps, maps, shelves, books, LIB, change,
                journal=_journal(), ids=ids, clock=clock)

    # Both survive, with what the owner said about them.
    assert shelves.get_shelf(LIB, named.id).label == "מדף הטלוויזיה"
    assert shelves.get_shelf(LIB, deeper.id).depth_count == 3
    assert maps.get_section(LIB, section.id).gaps == ()

    # …and the third cell, which the owner never said anything about, goes.
    plain = with_gaps(section, [(1, 3)], gap=True)
    removal = apply_gaps(maps, shelves, books, LIB, plain, journal=_journal(), ids=ids, clock=clock)
    assert len(removal.deleted) == 1, (
        "the refusal widened until an ordinary empty cell could not be gapped"
    )


def test_a_cell_at_the_sections_own_default_depth_is_not_a_declaration():
    """The other side of the same rule, and the reason it compares against the
    SECTION rather than against 1: a case whose shelves are all two rows deep
    declared that ONCE, on the section (§3.3), and every shelf in it copied
    the number at creation. Treating that copy as a per-shelf declaration
    would refuse every gap in every deep bookcase — which is most of them."""
    from app.domain import with_gaps
    from app.map_edit import apply_gaps

    maps, shelves, books = _world()
    ids, clock = SeqIdGen(), StubClock()
    drawn = draw_bookcase(maps, shelves, LIB, _case(), ids=ids, clock=clock,
                          columns=1, levels=2, depth=2)
    section = drawn.sections[0]
    assert all(s.depth_count == 2
               for s in shelves.list_shelves_in_section(LIB, section.id))

    change = with_gaps(section, [(1, 1)], gap=True)
    removal = apply_gaps(maps, shelves, books, LIB, change, journal=_journal(), ids=ids,
                         clock=clock)
    assert len(removal.deleted) == 1
    assert maps.get_section(LIB, section.id).gaps == ((1, 1),)


def test_a_name_typed_while_the_gap_is_in_flight_survives_it():
    """Measured by a data-integrity review, in the window the docstring had
    already admitted existed and only half covered.

    `apply_gaps` checks what the owner declared, then `_release` deletes — one
    query apart. `_release` re-read OCCUPANCY and nothing else, so a label
    written in between was destroyed outright, the route answered 200, and
    `removal.detached` was empty, so no screen could even say something was
    lost. Two HTTP requests: the window is milliseconds of wall clock, not
    microseconds — laptop presses *make a space here* while the phone is
    naming that very shelf.

    The protected shelf is DETACHED rather than deleted: the same smaller loss
    an occupied shelf takes, and for the same reason — half-applying the edit
    is worse than either.
    """
    from app.domain import rename_shelf, with_gaps
    from app.map_edit import apply_gaps

    maps, shelves, books = _world()
    ids, clock = SeqIdGen(), StubClock()
    drawn = draw_bookcase(maps, shelves, LIB, _case(), ids=ids, clock=clock,
                          columns=1, levels=2, depth=1)
    section = drawn.sections[0]
    target = shelves.get_shelf_at(LIB, ShelfAddress(section.id, 1, 1))

    # The phone lands its rename between the check and the delete — hooked
    # onto the LAST read `_release` makes before it destroys anything.
    real = books.deepest_copy_depth
    fired = []

    def racing(library):
        if not fired:
            fired.append(True)
            shelves.save_shelf(library, rename_shelf(
                shelves.get_shelf(library, target.id), "מדף הטלוויזיה"))
        return real(library)

    books.deepest_copy_depth = racing
    try:
        removal = apply_gaps(maps, shelves, books, LIB,
                             with_gaps(section, [(1, 1)], gap=True),
                             journal=_journal(), ids=ids, clock=clock)
    finally:
        books.deepest_copy_depth = real

    assert fired, "the race never fired, so this test proves nothing"
    survivor = shelves.get_shelf(LIB, target.id)
    assert survivor is not None, (
        "a shelf named while the gap was in flight was deleted outright"
    )
    assert survivor.label == "מדף הטלוויזיה"
    assert removal.detached == (target.id,) and removal.deleted == (), (
        "the response did not report what happened to it"
    )
    assert survivor.address is None


def test_a_slot_stranded_by_a_concurrent_edit_is_released_by_the_next_one():
    """Measured by a data-integrity review, and pre-existing: `_change` diffs
    the section the HANDLER read, so an address only the other request created
    is missing from `dropped`, nothing releases it, and a `Shelf` is left
    addressed to a cell the section no longer describes.

    It never healed on its own, either — every later `dropped` is computed
    from `addresses`, which no longer contains that cell — so `delete_section`
    and `delete_bookcase` counted the stray forever and the case became
    undeletable. Releasing against the section the change LEAVES BEHIND is the
    destructive mirror of what `_fill` already does creatively.

    P6.3.2 did not cause this; it adds an innocuous-looking way in, because
    restoring a TV cell does not read like a resize.
    """
    from app.domain import with_column_levels, with_gaps
    from app.map_edit import apply_gaps, apply_slot_change

    maps, shelves, books = _world()
    ids, clock = SeqIdGen(), StubClock()
    drawn = draw_bookcase(maps, shelves, LIB, _case(), ids=ids, clock=clock,
                          columns=2, levels=4, depth=1)
    section = drawn.sections[0]
    apply_gaps(maps, shelves, books, LIB,
               with_gaps(section, [(1, 4)], gap=True), journal=_journal(), ids=ids, clock=clock)

    # Two tabs, both computed from the section as it is NOW: one puts the
    # gapped cell back, the other shortens that column past it.
    stale = maps.get_section(LIB, section.id)
    restore = with_gaps(stale, [(1, 4)], gap=False)
    shrink = with_column_levels(stale, 1, 2)

    apply_gaps(maps, shelves, books, LIB, restore, journal=_journal(), ids=ids, clock=clock)
    apply_slot_change(maps, shelves, books, LIB, shrink, journal=_journal(), ids=ids, clock=clock)

    settled = maps.get_section(LIB, section.id)
    standing = {(s.address.col, s.address.level)
                for s in shelves.list_shelves_in_section(LIB, section.id)}
    slots = {(a.col, a.level) for a in settled.addresses}
    assert standing == slots, (
        f"the drawing and the shelves disagree: {standing ^ slots} — a shelf "
        f"addressed to a cell no screen can render, which nothing heals"
    )


def test_a_cell_whose_alias_holds_books_is_occupied_and_cannot_be_gapped():
    """**A shelf other identities resolve to is OCCUPIED** (P6.4a, §3.11) —
    and §3.10a named this exact hole before the alias existed: *"a cell whose
    live shelf is empty while its alias holds books passes this check and is
    gapped, and it does so without a single test going red."*

    Nothing is rewritten when shelves merge, so a copy that arrived with the
    absorbed identity still names IT, and both occupancy queries are keyed by
    the id on the row. The live shelf therefore reads as empty. Switching the
    cell off would then destroy the one identity those books are reachable
    through.
    """
    from app.domain import SlotsOccupied, with_gaps
    from app.domain.alias import ShelfAlias
    from app.map_edit import apply_gaps

    maps, shelves, books = _world()
    drawn = draw_bookcase(maps, shelves, LIB, _case(), ids=SeqIdGen(),
                          clock=StubClock(), columns=2, levels=2, depth=1)
    section = drawn.sections[0]
    survivor = shelves.get_shelf_at(LIB, ShelfAddress(section.id, 2, 2))

    # A photo-born shelf, absorbed by the drawn one — its books still name it.
    shelves.save_shelf(LIB, new_shelf(id="sh-photo", library_id=LIB.id))
    _shelve_a_book(books, "sh-photo")
    shelves.save_alias(LIB, ShelfAlias(
        alias_id="sh-photo", library_id=LIB.id, shelf_id=survivor.id,
        address=None, label="", merged_at=WHEN))
    assert not books.copies_per_shelf(LIB).get(survivor.id), (
        "the survivor holds no books directly — that is the whole point")

    refusal = _raises(
        SlotsOccupied, apply_gaps, maps, shelves, books, LIB,
        with_gaps(maps.get_section(LIB, section.id), [(2, 2)], gap=True),
        journal=_journal(), ids=SeqIdGen(), clock=StubClock())
    assert survivor.id in {s.id for s in refusal.shelves}, (
        "the refusal did not name the shelf the books are reachable through")

    assert shelves.get_shelf_at(LIB, ShelfAddress(section.id, 2, 2)) is not None
    assert shelves.get_shelf(LIB, "sh-photo") is not None


def test_a_survivor_with_an_EMPTY_alias_is_still_protected():
    """The half the depth fold cannot see, and the one that crashed.

    An absorbed identity holding nothing folds zero depth — and after a merge
    its captures are gone anyway — so the survivor read as EMPTY.
    `plan_slot_removal` scheduled it for deletion and `delete_shelf` then
    raised `ShelfHasAliases` out of the middle of the loop. Being a survivor
    IS the occupancy, whatever the aliases hold.
    """
    from app.domain import SlotsOccupied, with_gaps
    from app.domain.alias import ShelfAlias
    from app.map_edit import apply_gaps

    maps, shelves, books = _world()
    drawn = draw_bookcase(maps, shelves, LIB, _case(), ids=SeqIdGen(),
                          clock=StubClock(), columns=2, levels=2, depth=1)
    section = drawn.sections[0]
    survivor = shelves.get_shelf_at(LIB, ShelfAddress(section.id, 2, 2))

    shelves.save_shelf(LIB, new_shelf(id="sh-empty", library_id=LIB.id))
    shelves.save_alias(LIB, ShelfAlias(
        alias_id="sh-empty", library_id=LIB.id, shelf_id=survivor.id,
        address=None, label="", merged_at=WHEN))

    refusal = _raises(
        SlotsOccupied, apply_gaps, maps, shelves, books, LIB,
        with_gaps(maps.get_section(LIB, section.id), [(2, 2)], gap=True),
        journal=_journal(), ids=SeqIdGen(), clock=StubClock())
    assert survivor.id in {s.id for s in refusal.shelves}
    assert shelves.get_shelf(LIB, survivor.id) is not None


def test_clearing_a_bookcase_DETACHES_a_survivor_instead_of_dying_on_it():
    """⚠ The measured cost of letting `ShelfHasAliases` escape the loop:
    three of four labelled shelves destroyed, ZERO journal entries (recording
    happens after the loop returns), and the bookcase left permanently
    undeletable because the survivor stayed in its section.

    Detaching is the planner's own answer for "must not be destroyed", and it
    is the smaller loss — the shelf keeps its books, its aliases and its
    label, and loses only an address the owner has just erased.
    """
    from app.domain.alias import ShelfAlias
    from app.map_edit import clear_bookcase_slots

    maps, shelves, books = _world()
    drawn = draw_bookcase(maps, shelves, LIB, _case(), ids=SeqIdGen(),
                          clock=StubClock(), columns=2, levels=2, depth=1)
    section = drawn.sections[0]
    standing = shelves.list_shelves_in_section(LIB, section.id)
    survivor = standing[-1]

    shelves.save_shelf(LIB, new_shelf(id="sh-empty", library_id=LIB.id))
    shelves.save_alias(LIB, ShelfAlias(
        alias_id="sh-empty", library_id=LIB.id, shelf_id=survivor.id,
        address=None, label="", merged_at=WHEN))

    journal = _journal()
    removal = clear_bookcase_slots(maps, shelves, books, LIB,
                                   drawn.bookcase.id, journal=journal)

    assert survivor.id in removal.detached, (
        "the survivor was destroyed, or the loop died on it")
    assert survivor.id not in removal.deleted
    back = shelves.get_shelf(LIB, survivor.id)
    assert back is not None and back.address is None
    assert shelves.aliases_of(LIB, survivor.id), "its aliases went with it"
    assert len(removal.deleted) == len(standing) - 1, (
        "the loop stopped early instead of finishing the other shelves")
    assert journal.store.recent(LIB, limit=9), (
        "the edit recorded no inverse — the loop never reached `_record`")


def test_an_absorbed_shelf_that_is_still_live_keeps_its_own_occupancy():
    """⚠ `get`, not `pop`. Moving the occupancy off the absorbed shelf is only
    safe once its row is gone, and nothing enforces that — a merge writes the
    alias and removes the row as two steps, and this is the window between.

    Measured with `pop`: the absorbed shelf read as empty, its own cell was
    gapped and silently detached rather than refused, and
    `apply_depth_default` shallowed it under a copy standing at depth 2 — the
    corruption its own docstring says a review already measured once.
    """
    from app.domain.alias import ShelfAlias
    from app.map_edit import deepest_occupied_depths

    maps, shelves, books = _world()
    drawn = draw_bookcase(maps, shelves, LIB, _case(), ids=SeqIdGen(),
                          clock=StubClock(), columns=2, levels=2, depth=2)
    section = drawn.sections[0]
    survivor = shelves.get_shelf_at(LIB, ShelfAddress(section.id, 2, 2))
    absorbed = shelves.get_shelf_at(LIB, ShelfAddress(section.id, 1, 1))
    _shelve_a_book(books, absorbed.id, depth=2)

    shelves.save_alias(LIB, ShelfAlias(
        alias_id=absorbed.id, library_id=LIB.id, shelf_id=survivor.id,
        address=None, label="", merged_at=WHEN))

    deep = deepest_occupied_depths(
        shelves, books, LIB,
        shelves.list_shelves_in_section(LIB, section.id))
    assert deep.get(absorbed.id) == 2, (
        "the absorbed shelf is still standing and still holds a book at "
        "depth 2 — its occupancy was moved away from it")
    assert deep.get(survivor.id, 0) >= 1, "the survivor is occupied too"
