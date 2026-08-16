# -*- coding: utf-8 -*-
"""H4 ring — ``app.map_edit``: a drawing, turned into shelves (P6.1).

The layer above ``app.domain.place``: real ``MemoryMapStore``/
``MemoryShelfStore`` instances, a stub ``Clock``/``IdGen``, and the actual
persisted result. Every case here is one sentence of ``planning/MAP_PLAN.md``
§3 that a later reader could plausibly "fix" — and this is the module where
"fixing" it would silently lose a book's only recorded location, which is why
MAP_PLAN §2 flagged this item as the risky one before any of it was written.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.adapters.memory_store import MemoryMapStore, MemoryShelfStore
from app.domain import (
    LibraryRef,
    NotEmpty,
    Rect,
    ShelfAddress,
    new_bookcase,
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
    is in the moment before a bookcase is drawn."""
    shelves = MemoryShelfStore()
    maps = MemoryMapStore()
    maps.bind_shelves(shelves)
    maps.save_site(LIB, new_site(id="st", library_id=LIB.id, name="הבית"))
    maps.save_floor(LIB, new_floor(id="fl", library_id=LIB.id, site_id="st",
                                   name="קומת קרקע"))
    maps.save_place(LIB, new_place(id="pl", library_id=LIB.id, floor_id="fl",
                                   rect=Rect(0, 0, 12, 9), name="סלון"))
    return maps, shelves


def _case(**kw):
    return new_bookcase(id="bc", library_id=LIB.id, floor_id="fl",
                        rect=Rect(0, 0, 4, 1), place_id="pl", **kw)


def test_drawing_a_bookcase_creates_a_real_empty_shelf_per_slot():
    """MAP_PLAN §3.1, the sentence the whole item turns on: *a drawn slot IS a
    Shelf* — created empty, carrying an address, and not a second concept with
    a mapping table beside it. Draw 2 columns of 5 and ten shelves exist that
    were never photographed."""
    maps, shelves = _world()
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
    maps, shelves = _world()
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
    maps, shelves = _world()
    ids = SeqIdGen()
    drawn = draw_bookcase(maps, shelves, LIB, _case(), ids=ids,
                          clock=StubClock(), columns=1, levels=3, depth=1)
    section = drawn.sections[0]
    change = with_column_count(section, 2)      # the request, computed once

    first = apply_slot_change(maps, shelves, LIB, change, ids=ids,
                              clock=StubClock(), occupied_ids=())
    assert first.total == 0
    assert len(shelves.list_shelves_in_section(LIB, section.id)) == 6

    again = apply_slot_change(maps, shelves, LIB, change, ids=ids,
                              clock=StubClock(), occupied_ids=())
    assert again.total == 0
    assert len(shelves.list_shelves_in_section(LIB, section.id)) == 6, (
        "the retry minted a second shelf for a slot that already had one"
    )


def test_growing_a_section_adds_shelves_and_shrinking_removes_the_empty_ones():
    """The drawing and the shelves move together, in one call — a caller that
    updated the grid and forgot the shelves would leave a bookcase whose
    columns exist on screen and nowhere else."""
    maps, shelves = _world()
    ids = SeqIdGen()
    drawn = draw_bookcase(maps, shelves, LIB, _case(), ids=ids,
                          clock=StubClock(), columns=1, levels=2, depth=1)
    section = drawn.sections[0]
    apply_slot_change(maps, shelves, LIB, with_column_count(section, 3),
                      ids=ids, clock=StubClock(), occupied_ids=())
    assert len(shelves.list_shelves_in_section(LIB, section.id)) == 6
    assert maps.get_section(LIB, section.id).column_levels == (2, 2, 2)

    back = apply_slot_change(maps, shelves, LIB,
                             with_column_count(maps.get_section(LIB, section.id), 1),
                             ids=ids, clock=StubClock(), occupied_ids=())
    assert len(back.deleted) == 4 and back.detached == ()
    assert len(shelves.list_shelves_in_section(LIB, section.id)) == 2


def test_shrinking_a_section_detaches_an_occupied_shelf_instead_of_deleting_it():
    """§3.1 and §5.6 together, and the reason this item is the risky one: the
    shelf holding the photographs SURVIVES, unaddressed. Its books keep their
    shelf; what they lose is a location the owner has just erased from the
    drawing."""
    maps, shelves = _world()
    ids = SeqIdGen()
    drawn = draw_bookcase(maps, shelves, LIB, _case(), ids=ids,
                          clock=StubClock(), columns=2, levels=1, depth=1)
    section = drawn.sections[0]
    photographed = shelves.get_shelf_at(LIB, ShelfAddress(section.id, 2, 1))
    shelves.save_shelf(LIB, new_shelf(id=photographed.id, library_id=LIB.id,
                                      label="מדף עם ספרים", depth_count=1,
                                      address=photographed.address))

    removal = apply_slot_change(maps, shelves, LIB,
                                with_column_count(section, 1), ids=ids,
                                clock=StubClock(),
                                occupied_ids=(photographed.id,))
    assert removal.detached == (photographed.id,)
    assert removal.deleted == ()
    survivor = shelves.get_shelf(LIB, photographed.id)
    assert survivor is not None, "a shelf with books on it was deleted"
    assert survivor.address is None
    assert survivor.label == "מדף עם ספרים", "the survivor lost its name too"


def test_a_bookcase_is_emptied_before_it_can_be_deleted():
    """The store REFUSES while a shelf stands in one of its slots, and the
    emptying is a separate, explicit call. A store method that quietly emptied
    the slots itself is the silent-data-loss path MAP_PLAN §2 predicted for
    exactly this item."""
    maps, shelves = _world()
    ids = SeqIdGen()
    drawn = draw_bookcase(maps, shelves, LIB, _case(), ids=ids,
                          clock=StubClock(), columns=1, levels=2, depth=1)
    section = drawn.sections[0]
    keeper = shelves.get_shelf_at(LIB, ShelfAddress(section.id, 1, 1))

    _raises(NotEmpty, maps.delete_bookcase, LIB, "bc")

    removal = clear_bookcase_slots(maps, shelves, LIB, "bc",
                                   occupied_ids=(keeper.id,))
    assert removal.detached == (keeper.id,) and len(removal.deleted) == 1
    assert maps.delete_bookcase(LIB, "bc") is True
    assert maps.get_section(LIB, section.id) is None
    assert shelves.get_shelf(LIB, keeper.id) is not None, (
        "deleting the furniture deleted the shelf its books stand on"
    )


def test_applying_a_depth_default_writes_the_clamp_it_reports():
    """§3.3's explicit half. The shelf with a book at depth 2 keeps 2, the
    empty one goes to 1, and the caller is handed the ones it could not move
    so the screen says so instead of silently doing less."""
    maps, shelves = _world()
    ids = SeqIdGen()
    drawn = draw_bookcase(maps, shelves, LIB, _case(), ids=ids,
                          clock=StubClock(), columns=1, levels=2, depth=3)
    section = drawn.sections[0]
    deep = shelves.get_shelf_at(LIB, ShelfAddress(section.id, 1, 1))
    shallow = shelves.get_shelf_at(LIB, ShelfAddress(section.id, 1, 2))

    section = with_default_depth(section, 1)
    maps.save_section(LIB, section)
    kept = apply_depth_default(shelves, LIB, section,
                               deepest_occupied={deep.id: 2})
    assert [s.id for s in kept] == [deep.id]
    assert shelves.get_shelf(LIB, deep.id).depth_count == 2
    assert shelves.get_shelf(LIB, shallow.id).depth_count == 1


def test_a_shelf_holding_books_but_no_photos_is_still_occupied():
    """The review finding, pinned. `occupied_shelf_ids` is the ONE way to ask,
    and it asks BOTH halves.

    Captures are the obvious half. Copies are the half a reasonable person
    leaves out — a shelf can hold books with no photograph at all (a MANUAL
    entry, or a photo deleted later), and asking only about captures calls it
    empty, hands it to the DELETE branch, and leaves `copies.shelf_id` naming
    a shelf that no longer exists: invisible to `foreign_key_check`, because
    there is deliberately no foreign key there, and invisible to every screen.
    """
    from app.adapters.memory_store import MemoryBookStore
    from app.domain import new_book
    from app.map_edit import occupied_shelf_ids

    maps, shelves = _world()
    books = MemoryBookStore()
    ids = SeqIdGen()
    drawn = draw_bookcase(maps, shelves, LIB, _case(), ids=ids,
                          clock=StubClock(), columns=1, levels=2, depth=1)
    section = drawn.sections[0]
    standing = shelves.list_shelves_in_section(LIB, section.id)
    with_book, bare = standing[0], standing[1]
    books.save(LIB, new_book(id="b1", library_id=LIB.id, title="ספר",
                             author="סופר", copy_id="c1",
                             shelf_id=with_book.id, depth=1))
    assert shelves.list_captures(LIB, with_book.id) == (), (
        "the point of this test is a shelf with NO photograph"
    )

    occupied = occupied_shelf_ids(shelves, books, LIB, standing)
    assert occupied == (with_book.id,)

    removal = clear_bookcase_slots(maps, shelves, LIB, "bc",
                                   occupied_ids=occupied)
    assert removal.detached == (with_book.id,)
    assert removal.deleted == (bare.id,)
    assert shelves.get_shelf(LIB, with_book.id) is not None, (
        "the shelf a book stands on was deleted because nobody photographed it"
    )


def test_attaching_a_case_to_a_room_moves_it_onto_that_rooms_storey():
    """§3.7, through the port: the two fields change together, in one write,
    so a case attached to the kitchen can never be recorded upstairs."""
    maps, shelves = _world()
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
