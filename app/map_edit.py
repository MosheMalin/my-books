# -*- coding: utf-8 -*-
"""Editing the map — persistence only, no rules (P6.1, MAP_PLAN §3).

The third module of its kind, and it exists for the reason
``reconcile_apply.py`` gives in its own docstring: this work needs BOTH
``app.domain`` (the rules and their entities) and ``app.ports``
(``MapStore``, ``ShelfStore``, ``IdGen``, ``Clock``), and neither the pure
domain (H1) nor an API router (whose job is HTTP shape, not orchestration
across two ports) is the right home.

**What is orchestrated here, and why none of it can live in one store.**
MAP_PLAN §3.1 says a drawn slot IS a ``Shelf``. So a bookcase is never one
record:

    draw a case with 2 columns of 5 levels
      -> 1 bookcase + 1 section  (MapStore)
      -> 10 real, empty, addressed shelves  (ShelfStore)

and erasing a column is the same sentence backwards, with the clamp that
makes this item the risky one: **an occupied shelf is detached, never
deleted** (``app.domain.place.plan_slot_removal``). Every function below is
"ask the domain what should happen, then write it through the ports".

⚠ It may import ``app.domain`` and ``app.ports``; it must NOT import
``app.adapters``, and it is imported BY ``app.api``, never the reverse —
``tests/test_layering.py`` enforces both.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.domain import (
    Bookcase,
    LibraryRef,
    Place,
    Section,
    Shelf,
    ShelfAddress,
    SlotChange,
    SlotRemoval,
    apply_default_depth,
    attach_bookcase,
    detach_bookcase,
    new_section,
    new_shelf,
    plan_slot_removal,
    unbind_shelf,
)
from app.ports import Clock, IdGen
from app.ports.map import MapStore
from app.ports.store import BookStore, ShelfStore


def occupied_shelf_ids(
    shelves: ShelfStore,
    books: BookStore,
    library: LibraryRef,
    candidates: Iterable[Shelf],
) -> tuple[str, ...]:
    """Which of these shelves are holding something — the ONE way to ask.

    ⚠ Both halves, and the second one is the one a reasonable person leaves
    out. **Captures** are the photographic record a re-read diffs against
    (§5.6), and **copies** are the books themselves — a shelf can hold books
    with no photograph at all (a MANUAL entry, or a photo deleted later), so
    asking only about captures calls an occupied shelf empty and hands it to
    the delete branch of :func:`app.domain.plan_slot_removal`. That is the
    review finding this function exists to make unrepeatable: the answer is
    computed here, once, instead of at each call site.

    Every function below takes ``occupied_ids`` as a REQUIRED keyword for the
    same reason. A default of "nothing is occupied" is a default of "delete
    everything", and it would be silently correct in every test that happens
    to use empty shelves.
    """
    on_a_copy = books.shelf_ids_in_use(library)
    return tuple(
        shelf.id
        for shelf in candidates
        if shelf.id in on_a_copy or shelves.list_captures(library, shelf.id)
    )


@dataclass(frozen=True)
class DrawnCase:
    """What drawing one bookcase created — the numbers a screen reports back.

    ``shelves`` is a count and not a list on purpose: ten new empty shelves
    are not ten things the owner wants listed, they are one bookcase. The
    ids are on the shelves themselves for anyone who needs them.
    """

    bookcase: Bookcase
    sections: tuple[Section, ...]
    shelves: int


def draw_bookcase(
    map_store: MapStore,
    shelves: ShelfStore,
    library: LibraryRef,
    bookcase: Bookcase,
    *,
    ids: IdGen,
    clock: Clock,
    columns: int,
    levels: int,
    depth: int,
) -> DrawnCase:
    """Create a bookcase, its first section, and every shelf that section
    describes.

    The shelves come into existence HERE rather than lazily on first
    photograph, and that is §3.1's whole point: a drawn slot is a real row
    from the moment it is drawn, so "the books on this shelf" has one code
    path for the drawn and the photographed alike.

    Each shelf takes the section's ``default_depth`` **as a copy** (§3.3).
    Nothing reads back through to the section afterwards.
    """
    map_store.save_bookcase(library, bookcase)
    section = new_section(
        id=ids.new_id(),
        library_id=library.id,
        bookcase_id=bookcase.id,
        ordinal=1,
        columns=columns,
        default_levels=levels,
        default_depth=depth,
    )
    map_store.save_section(library, section)
    made = _fill(shelves, library, section, section.addresses,
                 ids=ids, clock=clock)
    return DrawnCase(bookcase=bookcase, sections=(section,), shelves=made)


def apply_slot_change(
    map_store: MapStore,
    shelves: ShelfStore,
    library: LibraryRef,
    change: SlotChange,
    *,
    ids: IdGen,
    clock: Clock,
    occupied_ids: tuple[str, ...],
) -> SlotRemoval:
    """Persist a section edit: the grid, the new shelves, and the lost ones.

    The order matters and is not arbitrary. The **section is written first**,
    so a crash between the two halves leaves slots without shelves — which
    reads as an unphotographed bookcase, a state the model already allows and
    every screen already handles. The other order leaves shelves addressed to
    slots that no longer exist, which is a shelf nothing can render.

    ``occupied_ids`` is REQUIRED, and :func:`occupied_shelf_ids` is how it is
    computed — a default would mean "nothing is occupied", which is "delete
    everything", and it would read as correct in every test using empty
    shelves.
    """
    map_store.save_section(library, change.section)
    _fill(shelves, library, change.section, change.added, ids=ids, clock=clock)
    losing = [
        shelf
        for address in change.dropped
        if (shelf := shelves.get_shelf_at(library, address)) is not None
    ]
    removal = plan_slot_removal(losing, occupied_ids=occupied_ids)
    by_id = {s.id: s for s in losing}
    for shelf_id in removal.detached:
        # It keeps its label, its photos and its books. What it loses is a
        # location the owner has just erased from the drawing — which is a
        # smaller loss than the shelf, and the only one that was asked for.
        shelves.save_shelf(library, unbind_shelf(by_id[shelf_id]))
    for shelf_id in removal.deleted:
        shelves.delete_shelf(library, shelf_id)
    return removal


def clear_bookcase_slots(
    map_store: MapStore,
    shelves: ShelfStore,
    library: LibraryRef,
    bookcase_id: str,
    *,
    occupied_ids: tuple[str, ...],
) -> SlotRemoval:
    """Empty every slot of a bookcase, so the case can then be deleted.

    Split from the delete deliberately: ``MapStore.delete_bookcase`` REFUSES
    while a shelf still stands in one of its sections, and the API calls this
    first, having shown the owner the counts. A store method that quietly
    emptied the slots itself would be the silent data-loss path MAP_PLAN §2
    predicted for this exact item.
    """
    snapshot = map_store.load_map(library)
    mine = [s for s in snapshot.sections if s.bookcase_id == bookcase_id]
    standing: list[Shelf] = []
    for section in mine:
        standing.extend(shelves.list_shelves_in_section(library, section.id))
    removal = plan_slot_removal(standing, occupied_ids=occupied_ids)
    by_id = {s.id: s for s in standing}
    for shelf_id in removal.detached:
        shelves.save_shelf(library, unbind_shelf(by_id[shelf_id]))
    for shelf_id in removal.deleted:
        shelves.delete_shelf(library, shelf_id)
    return removal


def apply_depth_default(
    shelves: ShelfStore,
    library: LibraryRef,
    section: Section,
    *,
    deepest_occupied: dict[str, int] | None = None,
) -> tuple[Shelf, ...]:
    """Push a section's depth default onto its existing shelves.

    The explicit, opt-in half of §3.3 — and the half that needed books to be
    written at all: :func:`app.domain.apply_default_depth` refuses to take a
    shelf below its deepest occupied depth, and returns the ones it left
    deeper so the screen can say so rather than silently doing less than it
    was asked.

    Returns the shelves that were KEPT deeper.
    """
    standing = shelves.list_shelves_in_section(library, section.id)
    result = apply_default_depth(section, standing,
                                 deepest_occupied=deepest_occupied)
    for shelf in result.shelves:
        shelves.save_shelf(library, shelf)
    return result.kept


def attach_case_to_room(
    map_store: MapStore,
    library: LibraryRef,
    bookcase: Bookcase,
    place: Place | None,
) -> Bookcase:
    """Point a case at a room (or at none) and persist it.

    Thin, and here rather than in a router so that the one place a bookcase's
    ``place_id`` and ``floor_id`` change together is a place the layering test
    can see. ``place=None`` is an explicit DETACH — geometry-driven
    reassignment goes through ``app.domain.reattach_bookcase``, which never
    orphans.
    """
    moved = attach_bookcase(bookcase, place) if place else detach_bookcase(bookcase)
    map_store.save_bookcase(library, moved)
    return moved


def _fill(
    shelves: ShelfStore,
    library: LibraryRef,
    section: Section,
    addresses: tuple[ShelfAddress, ...],
    *,
    ids: IdGen,
    clock: Clock,
) -> int:
    """Create one empty shelf per address that has none yet.

    Idempotent by address, which is what makes a retried request safe: the
    slot is the identity, so a second call finds the shelf already standing
    there instead of minting a twin the unique index would then refuse.
    """
    made = 0
    now = clock.now_iso()
    for address in addresses:
        if shelves.get_shelf_at(library, address) is not None:
            continue
        shelves.save_shelf(library, new_shelf(
            id=ids.new_id(),
            library_id=library.id,
            depth_count=section.default_depth,
            created_at=now,
            address=address,
        ))
        made += 1
    return made
