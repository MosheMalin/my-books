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

    first = apply_slot_change(maps, shelves, books, LIB, change, ids=ids,
                              clock=StubClock())
    assert first.total == 0
    assert len(shelves.list_shelves_in_section(LIB, section.id)) == 6

    again = apply_slot_change(maps, shelves, books, LIB, change, ids=ids,
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
                      ids=ids, clock=StubClock())
    assert len(shelves.list_shelves_in_section(LIB, section.id)) == 6
    assert maps.get_section(LIB, section.id).column_levels == (2, 2, 2)

    back = apply_slot_change(
        maps, shelves, books, LIB,
        with_column_count(maps.get_section(LIB, section.id), 1),
        ids=ids, clock=StubClock())
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
                                with_column_count(section, 1), ids=ids,
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

    removal = clear_bookcase_slots(maps, shelves, books, LIB, "bc")
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

    removal = clear_bookcase_slots(maps, shelves, books, LIB, "bc")
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

    removal = apply_slot_change(maps, shelves, books, LIB, change, ids=ids,
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
        apply_slot_change(maps, shelves, books, LIB, change, ids=ids,
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
    removal = apply_slot_change(maps, shelves, books, LIB, change, ids=ids,
                                clock=StubClock())
    assert removal.deleted == (doomed.id,)
    assert maps.get_section(LIB, section.id).column_levels == (1,)
    assert shelves.list_shelves_in_section(LIB, section.id) != ()
    assert clear_bookcase_slots(maps, shelves, books, LIB, "bc").total == 1
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

    removal = clear_bookcase_slots(maps, shelves, books, LIB, "bc")
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
                      ids=ids, clock=StubClock())

    cleared = clear_section_slots(shelves, books, LIB, hutch.id)
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
